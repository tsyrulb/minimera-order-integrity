"""Async Bedrock Converse adapter, signed through the standard AWS credential chain."""

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import ReadOnlyCredentials
from botocore.exceptions import BotoCoreError
from botocore.session import Session
from pydantic import ValidationError

from .config import ModelSettings
from .contracts import AppError, JsonObject, Projection
from .gateway import generation_lock, validate_analysis
from .model_requests import request_body
from .policy import canonical, digest
from .storage import atomic_json, read_json_object

CredentialSource = Callable[[], ReadOnlyCredentials | None]
_MAX_RESPONSE_BYTES = 256_000


class BedrockClient:
    """Run bounded requests without exposing AWS credentials in evidence records."""

    def __init__(
        self,
        runtime: Path,
        config: ModelSettings,
        *,
        credentials: CredentialSource | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if config.provider != "bedrock":
            raise ValueError("BedrockClient requires the bedrock provider")
        self.runtime = runtime
        self.config = config
        self._credentials = credentials if credentials is not None else self._aws_credentials
        self._transport = transport

    @property
    def generation_settings(self) -> JsonObject:
        settings: JsonObject = {
            "temperature": 0,
            "maxTokens": self.config.bedrock_max_tokens,
            "output_format": "json_schema",
        }
        if self.config.bedrock_reasoning_effort is not None:
            settings["reasoning_effort"] = self.config.bedrock_reasoning_effort
        return settings

    def request(self, projection: Projection) -> JsonObject:
        return request_body(projection, self.config)

    def _aws_credentials(self) -> ReadOnlyCredentials | None:
        session = Session(profile=self.config.aws_profile)
        credentials = session.get_credentials()
        return credentials.get_frozen_credentials() if credentials is not None else None

    def _budget(self) -> JsonObject:
        path = self.runtime / "bedrock-usage.json"
        if not path.exists():
            return {"model": self.config.model, "region": self.config.aws_region, "attempts": 0}
        value = read_json_object(path)
        if (
            value.get("model") != self.config.model
            or value.get("region") != self.config.aws_region
            or type(value.get("attempts")) is not int
            or value["attempts"] < 0
        ):
            raise ValueError("Use a separate runtime directory for each Bedrock model and region")
        return value

    def _reserve_attempt(self) -> None:
        try:
            budget = self._budget()
        except (OSError, ValueError):
            raise AppError(
                "BEDROCK_CONFIGURATION",
                "The persistent Bedrock request allowance could not be read. No request was sent.",
            ) from None
        if budget["attempts"] >= self.config.bedrock_call_limit:
            raise AppError(
                "BEDROCK_CALL_LIMIT",
                "This runtime's Bedrock request allowance is exhausted. Recorded results remain available.",
                429,
            )
        budget["attempts"] += 1
        # Reserve before sending. An interrupted or rejected request still uses
        # one allowance; restarting a process cannot silently reset the limit.
        atomic_json(self.runtime / "bedrock-usage.json", budget)

    async def inspect(self) -> JsonObject:
        ready = False
        remaining = 0
        error = None
        try:
            credentials = (
                await asyncio.to_thread(self._credentials)
                if self.config.bedrock_fresh_enabled
                else None
            )
            budget = self._budget()
            remaining = max(0, self.config.bedrock_call_limit - budget["attempts"])
            ready = credentials is not None and remaining > 0
        except (BotoCoreError, OSError, ValueError):
            error = "BEDROCK_CONFIGURATION"
        return {
            "ready": ready,
            "model": self.config.model,
            "digest": None,
            "provider": "Amazon Bedrock",
            "region": self.config.aws_region,
            "location": f"Amazon Bedrock · {self.config.aws_region}",
            "loaded": [],
            "identity_basis": "AWS model identifier and region; no cryptographic weight digest or execution attestation available",
            "readiness_basis": "Local credentials and request allowance; model invocation is checked only when requested",
            "remaining_calls": remaining,
            "fresh_enabled": self.config.bedrock_fresh_enabled,
            "last_error": error,
        }

    async def unload(self) -> None:
        """No model weights are loaded on this machine."""

    async def analyze(self, projection: Projection) -> JsonObject:
        if not self.config.bedrock_fresh_enabled:
            raise AppError(
                "BEDROCK_FRESH_DISABLED",
                "Fresh Bedrock inference is disabled. Enable it on the server to use the AWS credential chain; recorded results remain available.",
            )
        started = time.monotonic()
        evidence: JsonObject | None = None
        with generation_lock(self.runtime):
            try:
                credentials = await asyncio.to_thread(self._credentials)
                if credentials is None:
                    raise AppError(
                        "BEDROCK_NOT_CONFIGURED",
                        "Configure the server's AWS credential chain to run a fresh Bedrock analysis.",
                    )
                envelope = self.request(projection)
                self._reserve_attempt()
                result, request_id = await asyncio.wait_for(
                    self._send(envelope, credentials), timeout=210
                )
                content = "".join(
                    block["text"]
                    for block in result["output"]["message"]["content"]
                    if "text" in block
                )
                usage = result.get("usage", {})
                evidence = {
                    "raw_output": content,
                    "model": {
                        "ready": True,
                        "model": self.config.model,
                        "digest": None,
                        "provider": "Amazon Bedrock",
                        "region": self.config.aws_region,
                        "location": f"Amazon Bedrock · {self.config.aws_region}",
                        "identity_basis": "AWS model identifier and region; no cryptographic weight digest or execution attestation available",
                    },
                    "prompt_version": self.config.prompt_version,
                    "request": envelope,
                    "request_sha256": digest(envelope),
                    "hash_encoding": "SHA-256 of compact UTF-8 JSON of operation, region, modelId and body with recursively sorted keys; authentication headers excluded",
                    "settings": self.generation_settings,
                    "tokens": {
                        "input": usage.get("inputTokens"),
                        "output": usage.get("outputTokens"),
                    },
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "provider_request_id": request_id,
                    "stop_reason": result["stopReason"],
                    "memory_after": None,
                }
                if result.get("stopReason") != "end_turn":
                    raise AppError(
                        "MODEL_OUTPUT_INCOMPLETE",
                        "Bedrock did not finish a complete draft. No draft was accepted.",
                        502,
                    )
                analysis = validate_analysis(content, projection)
                return {**evidence, "analysis": analysis.model_dump()}
            except AppError as error:
                if error.evidence is None:
                    error.evidence = evidence
                raise
            except (BotoCoreError, OSError):
                raise AppError(
                    "BEDROCK_CONFIGURATION",
                    "AWS credentials or the local request allowance could not be read.",
                ) from None
            except (httpx.HTTPError, asyncio.TimeoutError):
                raise AppError(
                    "BEDROCK_UNAVAILABLE",
                    "The Bedrock request could not complete. Recorded results remain available.",
                ) from None
            except ValidationError as error:
                if evidence is not None:
                    evidence["validation_errors"] = error.errors(
                        include_input=False, include_url=False
                    )
                raise AppError(
                    "MODEL_OUTPUT_FAILED",
                    "Bedrock did not return a JSON draft that passes structural and citation checks.",
                    502,
                    evidence=evidence,
                ) from None
            except (ValueError, KeyError, TypeError, AttributeError):
                raise AppError(
                    "MODEL_OUTPUT_FAILED",
                    "Bedrock did not return a JSON draft that passes structural and citation checks.",
                    502,
                    evidence=evidence,
                ) from None

    async def _send(
        self, envelope: JsonObject, credentials: ReadOnlyCredentials
    ) -> tuple[JsonObject, str | None]:
        url = f"https://bedrock-runtime.{self.config.aws_region}.amazonaws.com/model/{quote(self.config.model, safe='')}/converse"
        wire = canonical(envelope["body"]).encode("utf-8")
        signed = AWSRequest(
            method="POST",
            url=url,
            data=wire,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        SigV4Auth(credentials, "bedrock", self.config.aws_region).add_auth(signed)
        headers = dict(signed.headers.items())
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180, connect=10),
            trust_env=False,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            async with client.stream("POST", url, content=wire, headers=headers) as response:
                if response.status_code in (401, 403):
                    raise AppError(
                        "BEDROCK_ACCESS_DENIED",
                        "The AWS identity cannot invoke the configured model. Check its Bedrock InvokeModel permission.",
                        503,
                    )
                if response.status_code == 429:
                    raise AppError(
                        "BEDROCK_THROTTLED", "Bedrock throttled this request. Retry later.", 429
                    )
                if response.status_code == 400:
                    raise AppError(
                        "BEDROCK_REQUEST_REJECTED",
                        "Bedrock rejected the model settings or output schema. No draft was accepted.",
                        503,
                    )
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise AppError(
                            "MODEL_RESPONSE_TOO_LARGE",
                            "Bedrock response exceeded its size limit.",
                            502,
                        )
                    data.extend(chunk)
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError("Bedrock response must be an object")
                return value, response.headers.get("x-amzn-requestid")
