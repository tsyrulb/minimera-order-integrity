"""Versioned, resumable experiments that preserve earlier model observations."""

import json
from datetime import datetime, timezone

from .contracts import AppError, JsonObject, Mode
from .evaluation import score, summarize
from .policy import POLICY_VERSION, digest, project
from .prompts import EXAMPLES_PROMPT_VERSION, LEGACY_PROMPT_VERSION
from .service import Service
from .storage import atomic_json, read_json_object

_MODES: tuple[Mode, ...] = ("full", "masked", "purpose")
_PAUSE_CODES = frozenset(
    {
        "MODEL_BUSY",
        "MODEL_UNAVAILABLE",
        "BEDROCK_NOT_CONFIGURED",
        "BEDROCK_FRESH_DISABLED",
        "BEDROCK_CONFIGURATION",
        "BEDROCK_CALL_LIMIT",
        "BEDROCK_ACCESS_DENIED",
        "BEDROCK_THROTTLED",
        "BEDROCK_UNAVAILABLE",
        "BEDROCK_REQUEST_REJECTED",
    }
)


class ExperimentRunner:
    """Fix the protocol before generation and persist each observed attempt."""

    def __init__(self, service: Service) -> None:
        if service.store.experiment is None:
            raise ValueError(
                "An experiment identifier is required; the original report is immutable"
            )
        self.service = service
        self.path = service.store.benchmark_path
        self.protocol_path = service.store.recordings / "protocol.json"
        self.protocol = self._prepare_protocol()
        self.report = (
            read_json_object(self.path)
            if self.path.exists()
            else {
                "schema_version": "ntk-benchmark/1.0.0",
                "experiment_id": service.store.experiment,
                "status": "partial",
                "model": service.model.config.model,
                "provider": service.model.config.provider,
                "region": service.model.config.aws_region,
                "prompt_version": service.model.config.prompt_version,
                "policy_version": POLICY_VERSION,
                "dataset_sha256": service.dataset_sha256,
                "settings": service.model.generation_settings,
                "started_at": self.protocol["recorded_at"],
                "protocol_sha256": digest(self.protocol),
                "methodology": service.document.get("evaluation", {}).get(
                    "methodology",
                    "30 developer-authored synthetic fixtures with AI assistance: 20 development and 10 fixed reporting cases reused from the earlier experiment. Same model, prompt, settings and output schema within this experiment; only context changes. Mode order rotates. Reference labels are never sent to the model. Invalid generations count as failures. This reused reporting set is not a new unseen or independently blinded test set; no claims of generalization or compliance.",
                ),
                "runs": [],
                "summary": [],
            }
        )
        if self.report.get("protocol_sha256") != digest(self.protocol):
            raise ValueError("Existing results belong to a different protocol")

    def _prepare_protocol(self) -> JsonObject:
        service = self.service
        original = read_json_object(service.store.root / "data/PROTOCOL.json")
        planned = {
            f"{case['id']}/{mode}": digest(service.model.request(project(case, mode)))
            for case in service.document["cases"]
            for mode in _MODES
        }
        protocol: JsonObject = {
            "schema_version": "ntk-experiment-protocol/1.0.0",
            "experiment_id": service.store.experiment,
            "provider": service.model.config.provider,
            "model": service.model.config.model,
            "region": service.model.config.aws_region,
            "dataset_sha256": service.dataset_sha256,
            "prompt_version": service.model.config.prompt_version,
            "policy_version": POLICY_VERSION,
            "settings": service.model.generation_settings,
            "gates": original["gates"],
            "planned_request_sha256": planned,
            "partition": {"development": 20, "heldout": 10, "reporting_set_reused": True},
        }
        if (
            service.model.config.prompt_version != LEGACY_PROMPT_VERSION
            or service.dataset_file != service.store.root / "data/cases.json"
        ):
            protocol["dataset_file"] = str(
                service.dataset_file.resolve().relative_to(service.store.root.resolve())
            )
            protocol["dataset_version"] = service.document["version"]
            protocol["partition"]["reporting_set_reused"] = service.document.get(
                "evaluation", {}
            ).get("reporting_set_reused", True)
        if service.model.config.prompt_version == EXAMPLES_PROMPT_VERSION:
            protocol["prompt_development"] = {
                "worked_examples_from_development": [
                    "NTK-002",
                    "NTK-004",
                    "NTK-006",
                    "NTK-012",
                    "NTK-016",
                    "NTK-017",
                ],
                "input_encoding": "Selected facts unchanged; provenance metadata key source renamed record_origin",
                "reporting_outputs_used_for_selection": False,
            }
        if self.protocol_path.exists():
            saved = read_json_object(self.protocol_path)
            if {k: v for k, v in saved.items() if k != "recorded_at"} != protocol:
                raise ValueError("Protocol changed; create a separately named experiment")
            return saved
        protocol["recorded_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.protocol_path, protocol)
        return protocol

    async def run(self, split: str = "all", case_ids: set[str] | None = None) -> JsonObject:
        if split not in ("all", "development", "heldout"):
            raise ValueError("Unknown experiment partition")
        if case_ids is not None and not case_ids <= {
            c["id"] for c in self.service.document["cases"]
        }:
            raise ValueError("Only fixed synthetic fixture IDs are allowed in this experiment")
        if self.report.get("status") == "complete":
            self._validate_observations()
            if summarize(self.report["runs"]) != self.report["summary"]:
                raise ValueError("Completed report summary does not match its observations")
            # A successful resume must not rewrite earlier timestamps, outputs,
            # selection records or measured results.
            return self.report
        observed = {(r["case_id"], r["mode"]) for r in self.report["runs"]}
        self.report["status"] = "running"
        self.report.pop("pause_reason", None)
        self._save()
        for index, case in enumerate(self.service.document["cases"]):
            if (
                split != "all"
                and case["split"] != split
                or case_ids is not None
                and case["id"] not in case_ids
            ):
                continue
            modes = _MODES[index % 3 :] + _MODES[: index % 3]
            for mode in modes:
                if (case["id"], mode) in observed:
                    continue
                try:
                    run = await self.service.analyze(case["id"], mode)
                    run.pop("delivery", None)
                    if (
                        run["result"]["request_sha256"]
                        != self.protocol["planned_request_sha256"][f"{case['id']}/{mode}"]
                    ):
                        raise ValueError("Observed request does not match the fixed protocol")
                except AppError as exc:
                    if exc.code in _PAUSE_CODES:
                        self.report["status"] = "paused"
                        self.report["pause_reason"] = exc.code
                        self._save()
                        print(json.dumps({"status": "paused", "reason": exc.code}), flush=True)
                        return self.report
                    run = {
                        "status": "error",
                        "case_id": case["id"],
                        "split": case["split"],
                        "mode": mode,
                        "error": exc.code,
                        "projection": project(case, mode),
                    }
                    if exc.evidence is not None:
                        run["result"] = exc.evidence
                self.report["runs"].append(run)
                observed.add((case["id"], mode))
                self._save()
                print(
                    json.dumps(
                        {
                            "case": case["id"],
                            "mode": mode,
                            "status": run["status"],
                            "action_correct": run.get("scores", {}).get("action_correct"),
                            "error": run.get("error"),
                        }
                    ),
                    flush=True,
                )
        self.report["status"] = "complete" if len(observed) == 90 else "partial"
        if self.report["status"] == "complete":
            self._verify()
        self._save()
        return self.report

    def _validate_observations(self) -> None:
        service = self.service
        observed = [(run["case_id"], run["mode"]) for run in self.report["runs"]]
        expected = {(case["id"], mode) for case in service.document["cases"] for mode in _MODES}
        if len(observed) != len(expected) or set(observed) != expected:
            raise ValueError("A complete report requires each planned observation exactly once")
        for run in self.report["runs"]:
            case = service.get_case(run["case_id"])
            projection = project(case, run["mode"])
            if run["projection"] != projection:
                raise ValueError("Recorded projection does not match the policy")
            if "result" in run:
                result = run["result"]
                if (
                    result["request"] != service.model.request(projection)
                    or digest(result["request"]) != result["request_sha256"]
                ):
                    raise ValueError("Recorded request does not match the observation")
            if run["status"] == "ok" and (
                score(case, projection, run["result"]) != run["scores"]
                or run["cache_key"] != service.key(case, run["mode"])
            ):
                raise ValueError("Recorded scores or cache key do not match the observation")

    def _verify(self) -> None:
        self._validate_observations()
        summaries = summarize(self.report["runs"])
        selected = {s["mode"]: s for s in summaries if s["split"] == "heldout"}
        baseline, candidate = selected["full"], selected["purpose"]
        gates = self.protocol["gates"]
        checks = {
            "baseline_action_floor": baseline["action_accuracy"]
            >= gates["minimum_action_accuracy"],
            "candidate_action_floor": candidate["action_accuracy"]
            >= gates["minimum_action_accuracy"],
            "candidate_missing_evidence_floor": candidate["missing_f1"]
            >= gates["minimum_missing_f1"],
            "candidate_valid_outputs": candidate["valid_outputs"] == candidate["attempts"],
            "candidate_no_unrelated_fields": candidate["mean_sensitive_fields_sent"] == 0,
            "no_action_accuracy_regression": candidate["action_correct"]
            >= baseline["action_correct"],
        }
        passed = all(checks.values())
        reused = self.protocol["partition"]["reporting_set_reused"]
        self.report["workflow_check"] = {
            "protocol": self.protocol,
            "checks": checks,
            "passes_fixture_gates": passed,
            "interpretation": "Passes these synthetic fixture gates only; does not establish generalization or compliance."
            if passed
            else "The fixed fixture gates are not met. Do not infer operational readiness.",
            "scope": f"Local project thresholds on {'reused' if reused else 'new developer-authored'} reporting fixtures, not independent certification.",
        }
        self.report["verified_at"] = datetime.now(timezone.utc).isoformat()
        self.report["completed_at"] = self.report["verified_at"]

    def _save(self) -> None:
        self.report["summary"] = summarize(self.report["runs"])
        if any(r["status"] == "error" and "result" not in r for r in self.report["runs"]):
            self.report["observability_note"] = (
                "Raw model replies are unavailable for some early validation failures recorded before failure capture was enabled. These failed attempts remain in every relevant metric; a separate diagnostic retry does not replace them."
            )
        atomic_json(self.path, self.report)
