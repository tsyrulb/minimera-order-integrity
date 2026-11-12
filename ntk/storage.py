"""Filesystem evidence persistence; independent of HTTP and model providers."""

import copy
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from .contracts import Case, JsonObject
from .dataset import ROOT


def atomic_json(path: Path, value: object) -> None:
    """Replace a JSON file atomically using a unique, owner-only temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temp = Path(target.name)
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.flush()
            os.fsync(target.fileno())
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def read_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(JsonObject, value)


class EvidenceStore:
    """Own runtime paths and lazily index compatible, bundled recorded runs."""

    def __init__(self, runtime: Path, root: Path = ROOT, *, experiment: str | None = None) -> None:
        self.runtime = runtime
        self.root = root
        self.experiment = experiment
        if experiment is not None and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", experiment) is None:
            raise ValueError("Invalid experiment identifier")
        self.recordings = (
            root / "reports" / "experiments" / experiment if experiment else root / "reports"
        )
        self.benchmark_path = self.recordings / "benchmark.json"
        self.live_path = runtime / "paypal-observation.json"
        self._recorded: dict[str, JsonObject] | None = None
        self._recorded_dataset: str | None = None
        self._failed: dict[str, JsonObject] = {}

    def observation(self) -> Case | None:
        path = next(
            (
                candidate
                for candidate in (
                    self.live_path,
                    self.recordings / "paypal-observation.json",
                    self.root / "reports/paypal-observation.json",
                )
                if candidate.exists()
            ),
            None,
        )
        if path is None:
            return None
        live = read_json_object(path)
        if path != self.live_path:
            live["label"] = "Recorded PayPal sandbox observation"
            live["source"]["label"] = "PayPal sandbox · recorded observation"
        return cast(Case, live)

    def cached(self, key: str, dataset_sha256: str) -> JsonObject | None:
        path = self._run_path(key)
        if path.exists():
            return read_json_object(path)
        if self._recorded is None or self._recorded_dataset != dataset_sha256:
            self._index_recordings(dataset_sha256)
        saved = self._recorded.get(key) if self._recorded is not None else None
        # A caller may add delivery/review metadata without mutating the stored
        # evidence that another request will receive.
        return copy.deepcopy(saved)

    def save_run(self, report: JsonObject) -> None:
        atomic_json(self._run_path(report["cache_key"]), report)

    def failed(self, request_sha256: str, dataset_sha256: str) -> JsonObject | None:
        if self._recorded is None or self._recorded_dataset != dataset_sha256:
            self._index_recordings(dataset_sha256)
        return copy.deepcopy(self._failed.get(request_sha256))

    def save_observation(self, case: Case) -> None:
        atomic_json(self.live_path, case)

    def _run_path(self, key: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{64}", key) is None:
            raise ValueError("Evidence keys must be SHA-256 hex digests")
        return self.runtime / "runs" / f"{key}.json"

    def _index_recordings(self, dataset_sha256: str) -> None:
        recorded: dict[str, JsonObject] = {}
        failed: dict[str, JsonObject] = {}
        benchmark = self.benchmark_path
        if benchmark.exists():
            report = read_json_object(benchmark)
            if report.get("dataset_sha256") == dataset_sha256:
                recorded.update(
                    {r["cache_key"]: r for r in report.get("runs", []) if r.get("status") == "ok"}
                )
                failed.update(
                    {
                        r["result"]["request_sha256"]: r
                        for r in report.get("runs", [])
                        if r.get("status") == "error" and r.get("result", {}).get("request_sha256")
                    }
                )
        extras = self.recordings / "paypal-model-run.json"
        if extras.exists():
            for run in json.loads(extras.read_text(encoding="utf-8")):
                if run.get("status") == "ok":
                    recorded.setdefault(run["cache_key"], run)
        self._recorded = recorded
        self._failed = failed
        self._recorded_dataset = dataset_sha256
