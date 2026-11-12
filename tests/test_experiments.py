import asyncio
import copy
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from ntk.config import ModelSettings, PayPalSettings
from ntk.contracts import AppError
from ntk.dataset import ROOT
from ntk.experiments import ExperimentRunner
from ntk.model_requests import OPTIONS, request_body
from ntk.paypal import PayPalClient
from ntk.policy import digest
from ntk.service import Service
from ntk.storage import EvidenceStore


class RecordedGateway:
    """Test double replaying fixtures; never starts a model or uses a network."""

    def __init__(self):
        self.config = ModelSettings()
        self.calls = 0
        report = json.loads((ROOT / "reports/benchmark.json").read_text())
        self.results = {r["result"]["request_sha256"]: r["result"] for r in report["runs"]}

    @property
    def generation_settings(self):
        return OPTIONS.copy()

    def request(self, projection):
        return request_body(projection, self.config)

    async def analyze(self, projection):
        self.calls += 1
        return copy.deepcopy(self.results[digest(self.request(projection))])

    async def inspect(self):
        return {"ready": True}

    async def unload(self):
        pass


@pytest.fixture
def experiment_service(tmp_path):
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    for name in ("cases.json", "PROTOCOL.json"):
        (root / "data" / name).write_bytes((ROOT / "data" / name).read_bytes())
    return Service(
        RecordedGateway(),
        EvidenceStore(tmp_path / "runtime", root=root, experiment="unit-experiment"),
        PayPalClient(PayPalSettings()),
    )


def test_protocol_is_fixed_before_generation_and_resume_does_not_repeat_calls(experiment_service):
    service = experiment_service
    runner = ExperimentRunner(service)
    protocol = runner.protocol_path.read_bytes()
    assert service.model.calls == 0
    assert len(runner.protocol["planned_request_sha256"]) == 90
    development = asyncio.run(runner.run(split="development"))
    assert development["status"] == "partial"
    assert len(development["runs"]) == 60
    assert all(r["split"] == "development" for r in development["runs"])
    completed = asyncio.run(ExperimentRunner(service).run(split="heldout"))
    assert completed["status"] == "complete"
    assert len(completed["runs"]) == service.model.calls == 90
    assert completed["verified_at"]
    assert runner.protocol_path.read_bytes() == protocol
    completed_bytes = runner.path.read_bytes()
    assert asyncio.run(ExperimentRunner(service).run())["status"] == "complete"
    assert service.model.calls == 90
    assert runner.path.read_bytes() == completed_bytes


def test_completed_report_with_duplicate_observation_is_rejected_without_rewriting_it(
    experiment_service,
):
    runner = ExperimentRunner(experiment_service)
    result = asyncio.run(runner.run())
    result["runs"][-1] = copy.deepcopy(result["runs"][0])
    raw = json.dumps(result).encode()
    runner.path.write_bytes(raw)
    with pytest.raises(ValueError, match="exactly once"):
        asyncio.run(ExperimentRunner(experiment_service).run())
    assert runner.path.read_bytes() == raw
    assert experiment_service.model.calls == 90


def test_changed_model_cannot_resume_under_the_same_protocol(experiment_service):
    runner = ExperimentRunner(experiment_service)
    original = runner.protocol_path.read_bytes()
    experiment_service.model.config = replace(
        experiment_service.model.config, model="different-model"
    )
    with pytest.raises(ValueError, match="Protocol changed"):
        ExperimentRunner(experiment_service)
    assert runner.protocol_path.read_bytes() == original
    assert experiment_service.model.calls == 0


def test_configuration_failure_pauses_instead_of_manufacturing_model_errors(
    experiment_service, monkeypatch
):
    fail = AsyncMock(side_effect=AppError("BEDROCK_ACCESS_DENIED", "Permission missing"))
    monkeypatch.setattr(experiment_service.model, "analyze", fail)
    runner = ExperimentRunner(experiment_service)
    result = asyncio.run(runner.run(case_ids={"NTK-001"}))
    assert result["status"] == "paused"
    assert result["pause_reason"] == "BEDROCK_ACCESS_DENIED"
    assert result["runs"] == []
    fail.assert_awaited_once()


def test_invalid_output_keeps_failure_evidence_and_counts_in_the_metrics(
    experiment_service, monkeypatch
):
    evidence = {"raw_output": "synthetic invalid response", "request_sha256": "synthetic-request"}
    monkeypatch.setattr(
        experiment_service.model,
        "analyze",
        AsyncMock(side_effect=AppError("MODEL_OUTPUT_FAILED", "Invalid reply", evidence=evidence)),
    )
    runner = ExperimentRunner(experiment_service)
    result = asyncio.run(runner.run(case_ids={"NTK-001"}))
    assert len(result["runs"]) == 3
    assert all(r["status"] == "error" and r["result"] == evidence for r in result["runs"])
    assert all(
        row["action_accuracy"] == 0 and row["valid_outputs"] == 0 for row in result["summary"]
    )


def test_original_baseline_cannot_be_an_experiment_output(service):
    with pytest.raises(ValueError, match="original report is immutable"):
        ExperimentRunner(service)


def test_evaluation_endpoint_uses_the_selected_experiment(client, tmp_path):
    path = tmp_path / "selected-benchmark.json"
    path.write_text(json.dumps({"model": "synthetic-selected-experiment", "runs": []}))
    client.app.state.service.store.benchmark_path = path
    response = client.get("/api/evaluation")
    assert response.json()["model"] == "synthetic-selected-experiment"
    assert client.get("/api/evaluation/download").json()["model"] == "synthetic-selected-experiment"
