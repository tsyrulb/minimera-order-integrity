import asyncio
import time
from contextlib import suppress
from pathlib import Path

import httpx
from pydantic import ValidationError

from .config import ModelSettings, Settings
from .contracts import Analysis, AppError, JsonObject, Projection, Provider
from .gateway import ModelGateway as ModelGateway
from .gateway import generation_lock, validate_analysis
from .model_requests import OPTIONS as OPTIONS
from .model_requests import PROMPT_VERSION as PROMPT_VERSION
from .model_requests import request_body as request_body
from .policy import digest
from .resources import ensure_memory, memory_snapshot, model_load_budget
from .secrets import read_private_env


def cloud_key(config: ModelSettings) -> str:
    value = config.api_key
    if config.env_file:
        try:
            value = read_private_env(config.env_file, frozenset({"NTK_OPENAI_API_KEY"})).get(
                "NTK_OPENAI_API_KEY", ""
            )
        except (OSError, ValueError):
            return ""
    return value if value and not any(c.isspace() for c in value) else ""


def _parse_analysis(
    result: JsonObject, provider: Provider, projection: Projection
) -> tuple[Analysis, JsonObject]:
    complete = (
        result.get("status") == "completed"
        if provider == "openai"
        else result.get("done") and result.get("done_reason") != "length"
    )
    if not complete:
        raise AppError(
            "MODEL_OUTPUT_INCOMPLETE",
            "The model reached its output budget. No draft was accepted.",
            502,
        )
    if provider == "openai":
        content = "".join(
            c.get("text", "")
            for item in result.get("output", [])
            for c in item.get("content", [])
            if c.get("type") == "output_text"
        )
        tokens = {
            "input": result.get("usage", {}).get("input_tokens"),
            "output": result.get("usage", {}).get("output_tokens"),
        }
    else:
        content = result["message"]["content"]
        tokens = {"input": result.get("prompt_eval_count"), "output": result.get("eval_count")}
    analysis = validate_analysis(content, projection)
    return analysis, tokens


class ModelClient:
    def __init__(
        self,
        runtime: Path,
        config: ModelSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config if config is not None else Settings.from_env().model
        if self.config.provider == "bedrock":
            raise ValueError("Bedrock uses BedrockClient; select it through create_service")
        self.base = self.config.ollama_url
        self.local = self.config.local
        self._transport = transport

    @property
    def generation_settings(self) -> JsonObject:
        return (
            {"temperature": 0, "max_output_tokens": 512, "store": False}
            if self.config.provider == "openai"
            else OPTIONS.copy()
        )

    def request(self, projection: Projection) -> JsonObject:
        return request_body(projection, self.config)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout, trust_env=False, follow_redirects=False, transport=self._transport
        )

    async def inspect(self) -> JsonObject:
        if self.config.provider == "openai":
            return {
                "ready": bool(cloud_key(self.config)),
                "model": self.config.model,
                "digest": None,
                "loaded": [],
                "location": "OpenAI API",
                "identity_basis": "Provider model snapshot ID; no cryptographic model digest available",
            }
        try:
            async with self._client(timeout=4) as client:
                tags, ps, version = await asyncio.gather(
                    *[
                        client.get(self.base + "/api/" + route)
                        for route in ("tags", "ps", "version")
                    ]
                )
                for response in (tags, ps, version):
                    response.raise_for_status()
                installed = next(
                    (
                        m
                        for m in tags.json().get("models", [])
                        if m.get("name") == self.config.model
                    ),
                    None,
                )
                loaded = [m.get("name") for m in ps.json().get("models", [])]
                return {
                    "ready": installed is not None,
                    "model": self.config.model,
                    "digest": installed.get("digest") if installed else None,
                    "identity_basis": "Ollama installed model manifest digest; not an attested execution measurement",
                    "size_bytes": installed.get("size") if installed else None,
                    "ollama_version": version.json().get("version"),
                    "loaded": loaded,
                    "location": "local" if self.local else "operator-configured server",
                }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return {
                "ready": False,
                "model": self.config.model,
                "digest": None,
                "loaded": [],
                "location": "local" if self.local else "operator-configured server",
            }

    async def unload(self) -> None:
        if self.config.provider != "ollama":
            return
        with suppress(httpx.HTTPError):
            async with self._client(timeout=5) as client:
                await client.post(
                    self.base + "/api/generate", json={"model": self.config.model, "keep_alive": 0}
                )

    async def _generate(self, body: JsonObject) -> httpx.Response:
        async with self._client(timeout=120) as client:
            if self.config.provider == "openai":
                task = asyncio.create_task(
                    client.post(
                        "https://api.openai.com/v1/responses",
                        json=body,
                        headers={"Authorization": "Bearer " + cloud_key(self.config)},
                    )
                )
            else:
                task = asyncio.create_task(client.post(self.base + "/api/chat", json=body))
            try:
                while not task.done():
                    await asyncio.sleep(0.5)
                    if self.local:
                        ensure_memory(loaded=True)
                return await task
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError, httpx.HTTPError):
                        await task

    async def analyze(self, projection: Projection) -> JsonObject:
        # Cross-process lock also prevents the benchmark CLI and web server from
        # running two generations together. No unbounded inference queue.
        with generation_lock(self.runtime):
            return await self._analyze_locked(projection)

    async def _analyze_locked(self, projection: Projection) -> JsonObject:
        started = time.monotonic()
        generation_started = False
        aborted = False
        try:
            info = await self.inspect()
            if not info["ready"]:
                message = (
                    "Configure the operator's model API key to run fresh cloud analyses."
                    if self.config.provider == "openai"
                    else f"Start Ollama and install {self.config.model} to run a fresh analysis."
                )
                raise AppError("MODEL_UNAVAILABLE", message)
            if self.local:
                if any(name != self.config.model for name in info["loaded"]):
                    raise AppError(
                        "OTHER_MODEL_LOADED",
                        "Another local model is loaded. Inference paused to protect memory.",
                    )
                budget = model_load_budget(self.config.model, info.get("size_bytes"))
                ensure_memory(loaded=self.config.model in info["loaded"], load_budget_mib=budget)
            body = self.request(projection)
            generation_started = True
            response = await self._generate(body)
            response.raise_for_status()
            if len(response.content) > 256_000:
                raise AppError(
                    "MODEL_RESPONSE_TOO_LARGE", "Model response exceeded the response limit."
                )
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Model response must be an object")
            analysis, tokens = _parse_analysis(result, self.config.provider, projection)
            return {
                "analysis": analysis.model_dump(),
                "model": {k: v for k, v in info.items() if k != "loaded"},
                "prompt_version": self.config.prompt_version,
                "request_sha256": digest(body),
                "hash_encoding": "SHA-256 of compact UTF-8 JSON with recursively sorted object keys; headers excluded",
                "request": body,
                "settings": self.generation_settings,
                "tokens": tokens,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "memory_after": memory_snapshot() if self.local else None,
            }
        except asyncio.CancelledError:
            aborted = True
            raise
        except AppError:
            aborted = True
            raise
        except (httpx.HTTPError, ValidationError, KeyError, ValueError, TypeError, AttributeError):
            aborted = True
            raise AppError(
                "MODEL_OUTPUT_FAILED",
                "The model did not return a JSON draft that passes structural checks. Retry or inspect the evaluation report.",
                502,
            ) from None
        finally:
            if aborted and self.local and generation_started:
                await self.unload()
