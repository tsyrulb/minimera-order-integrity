import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from ntk.app import create_app
from ntk.config import ModelSettings, Settings
from ntk.contracts import AppError
from ntk.dataset import ROOT
from ntk.experiments import ExperimentRunner
from ntk.recorded import recorded_dataset, recorded_model
from ntk.service import create_service
from scripts.serve_demo import DEFAULT_EXPERIMENT, demo_settings


def test_recorded_demo_runs_without_aws_and_uses_the_frozen_model_configuration(tmp_path):
    settings = demo_settings(DEFAULT_EXPERIMENT, base=Settings(runtime_dir=tmp_path))
    service = create_service(settings)

    def forbidden():
        pytest.fail("Recorded demo attempted to resolve AWS credentials")

    service.model._credentials = forbidden
    assert service.model.config.model == "openai.gpt-oss-120b-1:0"
    assert service.model.config.bedrock_max_tokens == 4096
    assert service.model.config.bedrock_reasoning_effort == "low"
    with TestClient(create_app(settings, service=service)) as client:
        assert client.get("/api/health").json()["model"]["ready"] is False
        for case_id, mode in [
            ("NTK-003", "full"),
            ("NTK-003", "masked"),
            ("NTK-003", "purpose"),
            ("paypal-sandbox", "purpose"),
        ]:
            response = client.post("/api/analyze", json={"case_id": case_id, "mode": mode})
            assert response.status_code == 200
            assert response.json()["delivery"] == "recorded"
        evaluation = client.get("/api/evaluation").json()
        assert evaluation["workflow_check"]["passes_fixture_gates"] is True
    assert not list(tmp_path.rglob("bedrock-usage.json"))


def test_recorded_dataset_cannot_escape_the_public_data_directory(tmp_path):
    with pytest.raises(ValueError, match="public data"):
        recorded_dataset({"dataset_file": "../private.json"}, tmp_path)
    assert recorded_dataset({}, tmp_path) == tmp_path / "data/cases.json"


def test_recorded_configuration_preserves_operator_credentials_without_resolving_them():
    protocol = json.loads(
        (ROOT / "reports/experiments" / DEFAULT_EXPERIMENT / "protocol.json").read_text()
    )
    base = ModelSettings(aws_profile="synthetic-profile", bedrock_call_limit=17)
    settings = recorded_model(protocol, base)
    assert settings.aws_profile == "synthetic-profile" and settings.bedrock_call_limit == 17
    assert settings.provider == "bedrock" and settings.prompt_version == protocol["prompt_version"]


def test_completed_bedrock_experiment_resume_cannot_invoke_or_rewrite(tmp_path):
    settings = demo_settings(DEFAULT_EXPERIMENT, base=Settings(runtime_dir=tmp_path))
    service = create_service(settings)
    runner = ExperimentRunner(service)
    before = runner.path.read_bytes()
    # The model is disabled and there are no cached runtime runs. A complete
    # experiment must validate and return its frozen observations without calls.
    assert asyncio.run(runner.run())["status"] == "complete"
    assert runner.path.read_bytes() == before
    assert not list(tmp_path.rglob("bedrock-usage.json"))


def test_recorded_failure_never_retries_the_provider_without_an_explicit_fresh_request(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    settings = demo_settings(DEFAULT_EXPERIMENT, fresh=True, base=Settings(runtime_dir=tmp_path))
    service = create_service(settings)
    provider = AsyncMock(side_effect=AppError("EXPECTED_FRESH_CALL", "Synthetic provider called"))
    monkeypatch.setattr(service.model, "analyze", provider)
    with pytest.raises(AppError, match="RECORDED_MODEL_OUTPUT_FAILED"):
        asyncio.run(service.analyze("NTK-039", "full"))
    provider.assert_not_awaited()
    with pytest.raises(AppError, match="EXPECTED_FRESH_CALL"):
        asyncio.run(service.analyze("NTK-039", "full", fresh=True))
    provider.assert_awaited_once()
