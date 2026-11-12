"""Immutable operator configuration, read explicitly when an app is created."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from .contracts import Provider
from .dataset import ROOT
from .prompts import EXAMPLES_PROMPT_VERSION, LEGACY_PROMPT_VERSION, ROUTING_PROMPT_VERSION

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_CLOUD_MODEL = "gpt-4.1-mini-2025-04-14"
DEFAULT_BEDROCK_MODEL = "qwen.qwen3-next-80b-a3b"


@dataclass(frozen=True)
class ModelSettings:
    provider: Provider = "ollama"
    model: str = DEFAULT_MODEL
    ollama_url: str = "http://127.0.0.1:11434"
    api_key: str = field(default="", repr=False)
    env_file: Path | None = None
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    bedrock_call_limit: int = 100
    bedrock_fresh_enabled: bool = False
    prompt_version: str = LEGACY_PROMPT_VERSION
    bedrock_max_tokens: int = 768
    bedrock_reasoning_effort: Literal["low", "medium", "high"] | None = None

    def __post_init__(self) -> None:
        if self.provider not in ("ollama", "openai", "bedrock"):
            raise ValueError("NTK_PROVIDER must be ollama, openai or bedrock")
        if not self.model or any(c.isspace() for c in self.model):
            raise ValueError("NTK_MODEL must be a nonempty model identifier")
        if self.prompt_version not in (
            LEGACY_PROMPT_VERSION,
            ROUTING_PROMPT_VERSION,
            EXAMPLES_PROMPT_VERSION,
        ):
            raise ValueError("Unsupported NTK_PROMPT_VERSION")
        if self.provider == "bedrock":
            if re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", self.aws_region) is None:
                raise ValueError("NTK_AWS_REGION must be an AWS region identifier")
            if not 1 <= self.bedrock_call_limit <= 1000:
                raise ValueError("NTK_BEDROCK_CALL_LIMIT must be between 1 and 1000")
            if not 128 <= self.bedrock_max_tokens <= 4096:
                raise ValueError("NTK_BEDROCK_MAX_TOKENS must be between 128 and 4096")
            if self.bedrock_reasoning_effort is not None and (
                self.bedrock_reasoning_effort not in ("low", "medium", "high")
                or not self.model.startswith("openai.gpt-oss-")
            ):
                raise ValueError("NTK_BEDROCK_REASONING_EFFORT is supported only for GPT-OSS")
        if self.provider != "ollama":
            return
        parsed = urlsplit(self.ollama_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ValueError("NTK_OLLAMA_URL must be an origin configured by the server operator")
        # Accessing port also validates malformed and out-of-range ports.
        _ = parsed.port
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1") and parsed.scheme != "https":
            raise ValueError("A remote model server requires HTTPS")

    @property
    def local(self) -> bool:
        return self.provider == "ollama" and urlsplit(self.ollama_url).hostname in (
            "localhost",
            "127.0.0.1",
            "::1",
        )


@dataclass(frozen=True)
class PayPalSettings:
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)
    env_file: Path | None = None
    order_id: str = ""
    capture_id: str = ""
    dispute_id: str = ""
    completion_record: Path | None = None

    @property
    def configured(self) -> bool:
        return bool(
            (self.env_file or (self.client_id and self.client_secret))
            and self.order_id
            and self.capture_id
            and self.dispute_id
        )


@dataclass(frozen=True)
class Settings:
    runtime_dir: Path = ROOT / "runtime"
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    model: ModelSettings = field(default_factory=ModelSettings)
    paypal: PayPalSettings = field(default_factory=PayPalSettings)
    experiment: str | None = None
    dataset_file: Path | None = None

    def __post_init__(self) -> None:
        if (
            self.experiment is not None
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", self.experiment) is None
        ):
            raise ValueError("NTK_EXPERIMENT must be a short lowercase experiment identifier")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        provider = env.get("NTK_PROVIDER", "ollama")
        if provider not in ("ollama", "openai", "bedrock"):
            raise ValueError("NTK_PROVIDER must be ollama, openai or bedrock")
        default_model = {
            "ollama": DEFAULT_MODEL,
            "openai": DEFAULT_CLOUD_MODEL,
            "bedrock": DEFAULT_BEDROCK_MODEL,
        }[provider]
        hosts = tuple(
            h.strip()
            for h in env.get("NTK_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
            if h.strip()
        )
        if env.get("RENDER_EXTERNAL_HOSTNAME"):
            hosts += (env["RENDER_EXTERNAL_HOSTNAME"],)
        if not hosts:
            raise ValueError("NTK_ALLOWED_HOSTS must name at least one host")
        return cls(
            runtime_dir=Path(env.get("NTK_RUNTIME_DIR", str(ROOT / "runtime"))),
            allowed_hosts=hosts,
            model=ModelSettings(
                provider=cast(Provider, provider),
                model=env.get("NTK_MODEL", default_model),
                ollama_url=env.get("NTK_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
                api_key=env.get("NTK_OPENAI_API_KEY", ""),
                env_file=_optional_path(env.get("NTK_MODEL_ENV_FILE")),
                aws_region=env.get(
                    "NTK_AWS_REGION",
                    env.get("AWS_REGION", env.get("AWS_DEFAULT_REGION", "us-east-1")),
                ),
                aws_profile=env.get("NTK_AWS_PROFILE", env.get("AWS_PROFILE")) or None,
                bedrock_call_limit=int(env.get("NTK_BEDROCK_CALL_LIMIT", "100")),
                bedrock_fresh_enabled=env.get("NTK_ENABLE_BEDROCK_FRESH", "false").lower()
                == "true",
                prompt_version=env.get("NTK_PROMPT_VERSION", LEGACY_PROMPT_VERSION),
                bedrock_max_tokens=int(env.get("NTK_BEDROCK_MAX_TOKENS", "768")),
                bedrock_reasoning_effort=cast(
                    Literal["low", "medium", "high"] | None,
                    env.get("NTK_BEDROCK_REASONING_EFFORT") or None,
                ),
            ),
            paypal=PayPalSettings(
                client_id=env.get("PAYPAL_SANDBOX_CLIENT_ID", ""),
                client_secret=env.get("PAYPAL_SANDBOX_CLIENT_SECRET", ""),
                env_file=_optional_path(env.get("NTK_PAYPAL_ENV_FILE")),
                order_id=env.get("NTK_PAYPAL_ORDER_ID", ""),
                capture_id=env.get("NTK_PAYPAL_CAPTURE_ID", ""),
                dispute_id=env.get("NTK_PAYPAL_DISPUTE_ID", ""),
                completion_record=_optional_path(env.get("NTK_COMPLETION_RECORD")),
            ),
            experiment=env.get("NTK_EXPERIMENT") or None,
            dataset_file=_optional_path(env.get("NTK_DATASET_FILE")),
        )


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None
