"""Validate the fixed synthetic fixtures before they enter a service instance."""

import json
from pathlib import Path
from typing import cast

from pydantic import TypeAdapter, ValidationError

from .contracts import Case, DatasetDocument, JsonObject
from .policy import ALLOWED_KEYS, digest

ROOT = Path(__file__).resolve().parent.parent
_DATASET_ADAPTER = TypeAdapter(DatasetDocument)


def load_dataset(path: Path = ROOT / "data/cases.json") -> tuple[DatasetDocument, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        _DATASET_ADAPTER.validate_python(raw, strict=True)
    except (ValueError, ValidationError) as exc:
        raise ValueError("Synthetic dataset does not match its declared structure") from exc
    document = cast(DatasetDocument, raw)
    cases = document["cases"]
    if len(cases) != 30 or len({c["id"] for c in cases}) != 30:
        raise ValueError("Synthetic dataset must contain 30 distinct cases")
    if (
        sum(c["split"] == "development" for c in cases) != 20
        or sum(c["split"] == "heldout" for c in cases) != 10
    ):
        raise ValueError("Synthetic dataset must retain its 20/10 partition")
    for case in cases:
        facts = case["facts"]
        ids = {f["id"] for f in facts}
        if len(ids) != len(facts):
            raise ValueError("Fixture fact IDs must be unique")
        if "expected" not in case or not set(case["expected"]["required_citations"]) <= ids:
            raise ValueError("Fixture reference citations must point to supplied facts")
        if any(f["key"] not in ALLOWED_KEYS for f in facts if f["sensitivity"] == "task"):
            raise ValueError("Task facts must use the policy allowlist")
        if case["source"]["kind"] != "synthetic":
            raise ValueError("The comparison dataset must contain synthetic cases only")
    return document, digest(document)


def public_case(case: Case) -> JsonObject:
    return {k: v for k, v in case.items() if k != "expected"}
