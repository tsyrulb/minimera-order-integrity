"""Reconstruct a recorded configuration without credentials or model invocation."""

from dataclasses import replace
from pathlib import Path

from .config import ModelSettings
from .contracts import JsonObject
from .dataset import ROOT


def recorded_model(protocol: JsonObject, base: ModelSettings | None = None) -> ModelSettings:
    if protocol.get("provider") != "bedrock":
        raise ValueError("The portable experiment adapter requires a Bedrock recording")
    return replace(
        base if base is not None else ModelSettings(),
        provider="bedrock",
        model=protocol["model"],
        aws_region=protocol["region"],
        prompt_version=protocol["prompt_version"],
        bedrock_max_tokens=protocol["settings"].get("maxTokens", 768),
        bedrock_reasoning_effort=protocol["settings"].get("reasoning_effort"),
    )


def recorded_dataset(protocol: JsonObject, root: Path = ROOT) -> Path:
    filename = protocol.get("dataset_file", "data/cases.json")
    if not isinstance(filename, str):
        raise ValueError("The recorded dataset must name a public data fixture")
    path = (root / filename).resolve()
    if not path.is_relative_to((root / "data").resolve()):
        raise ValueError("A bundled experiment must reference a public data fixture")
    return path
