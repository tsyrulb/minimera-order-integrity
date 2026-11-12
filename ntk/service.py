"""Application workflows composed from a model, sandbox reader and evidence store."""

import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .bedrock import BedrockClient
from .config import Settings
from .contracts import AppError, Case, JsonObject, Mode
from .dataset import load_dataset
from .evaluation import score
from .model import ModelClient, ModelGateway
from .paypal import PayPalClient, SandboxReader
from .policy import POLICY_VERSION, digest, project
from .review import check_draft
from .storage import EvidenceStore


class Service:
    """Coordinate use cases; dependencies and mutable state belong to this instance."""

    def __init__(
        self,
        model: ModelGateway,
        store: EvidenceStore,
        sandbox: SandboxReader,
        *,
        clock: Callable[[], float] = time.monotonic,
        dataset_file: Path | None = None,
    ) -> None:
        self.model = model
        self.store = store
        self.sandbox = sandbox
        self._clock = clock
        self.dataset_file = (
            dataset_file if dataset_file is not None else store.root / "data/cases.json"
        )
        self.document, self.dataset_sha256 = load_dataset(self.dataset_file)
        self.cases = {c["id"]: c for c in self.document["cases"]}
        observation = store.observation()
        if observation is not None:
            self.cases["paypal-sandbox"] = observation
        self.refresh_error: str | None = None
        self._last_refresh = float("-inf")

    def get_case(self, case_id: str) -> Case:
        if case_id not in self.cases:
            raise AppError("CASE_NOT_FOUND", "Choose one of the available demo cases.", 404)
        return self.cases[case_id]

    def key(self, case: Case, mode: Mode) -> str:
        projection = project(case, mode)
        return digest(
            {
                "request": self.model.request(projection),
                "policy": POLICY_VERSION,
                "dataset": self.dataset_sha256
                if case["source"]["kind"] == "synthetic"
                else case["source"].get("resource_fingerprint"),
            }
        )

    def cached(self, case: Case, mode: Mode) -> JsonObject | None:
        return self.store.cached(self.key(case, mode), self.dataset_sha256)

    async def refresh_paypal(self) -> Case:
        now = self._clock()
        if now - self._last_refresh < 30:
            raise AppError(
                "REFRESH_COOLDOWN", "Wait 30 seconds before refreshing PayPal again.", 429
            )
        self._last_refresh = now
        try:
            case = await self.sandbox.read()
            self.store.save_observation(case)
            self.cases[case["id"]] = case
            self.refresh_error = None
            return case
        except AppError as exc:
            self.refresh_error = exc.code
            raise
        except OSError:
            self.refresh_error = "PAYPAL_STORE_FAILED"
            raise AppError(
                "PAYPAL_STORE_FAILED",
                "The sandbox observation could not be saved. The previous observation remains available.",
            ) from None

    async def analyze(self, case_id: str, mode: Mode, fresh: bool = False) -> JsonObject:
        case = self.get_case(case_id)
        if mode != "purpose" and case["source"]["kind"] != "synthetic":
            raise AppError("SYNTHETIC_ONLY", "Baseline comparisons use synthetic cases only.", 400)
        if not fresh:
            saved = self.cached(case, mode)
            if saved:
                return {
                    **saved,
                    "review": check_draft(case, saved["result"]["analysis"]),
                    "delivery": "recorded",
                }
        projection = project(case, mode)
        if not fresh:
            request = self.model.request(projection)
            failure = self.store.failed(digest(request), self.dataset_sha256)
            if (
                failure
                and failure["projection"] == projection
                and failure["result"]["request"] == request
            ):
                raise AppError(
                    "RECORDED_MODEL_OUTPUT_FAILED",
                    "This recorded generation failed validation. Its original response is in the exported benchmark; no new generation was requested.",
                    502,
                )
        result = await self.model.analyze(projection)
        report: JsonObject = {
            "schema_version": "ntk-evidence/1.0.0",
            "status": "ok",
            "report_id": digest(
                {"request": result["request_sha256"], "at": datetime.now(timezone.utc).isoformat()}
            ),
            "cache_key": self.key(case, mode),
            "case_id": case_id,
            "case_label": case["label"],
            "split": case["split"],
            "mode": mode,
            "source": case["source"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_sha256": self.dataset_sha256,
            "projection": projection,
            "result": result,
            "scores": score(case, projection, result),
            "review": check_draft(case, result["analysis"]),
            "limitations": [
                "Hashes identify these payloads; they are not signatures or proof of provider behavior.",
                "Expected labels are developer-authored synthetic fixture labels, not PayPal or legal decisions.",
                "Exact string checks and citation checks do not prove absence of semantic leakage or hallucinations.",
                "The policy covers structured fields in this one workflow. Attachments and arbitrary text are excluded.",
                "All responses are drafts requiring human review; this app cannot submit evidence or move money.",
            ],
        }
        if "expected" in case:
            report["reference_label"] = case["expected"]
        self.store.save_run(report)
        return {**report, "delivery": "fresh"}


def create_service(settings: Settings | None = None) -> Service:
    """Composition root used by the web lifespan and command-line benchmark."""
    settings = settings if settings is not None else Settings.from_env()
    runtime = (
        settings.runtime_dir / "experiments" / settings.experiment
        if settings.experiment
        else settings.runtime_dir
    )
    return Service(
        model=BedrockClient(runtime, settings.model)
        if settings.model.provider == "bedrock"
        else ModelClient(runtime, settings.model),
        store=EvidenceStore(runtime, experiment=settings.experiment),
        sandbox=PayPalClient(settings.paypal),
        dataset_file=settings.dataset_file,
    )
