import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ntk.config import ModelSettings
from ntk.contracts import AppError
from ntk.model import ModelClient
from ntk.service import Service


def test_fresh_run_uses_projected_facts_then_replays_without_calling_model(service, monkeypatch):
    recorded = service.cached(service.get_case("NTK-001"), "purpose")
    generate = AsyncMock(return_value=copy.deepcopy(recorded["result"]))
    monkeypatch.setattr(service.model, "analyze", generate)
    fresh = asyncio.run(service.analyze("NTK-001", "purpose", fresh=True))
    sent = generate.call_args.args[0]
    assert "expected" not in sent["payload"]
    assert sent["metrics"]["sensitive_fields_disclosed"] == 0
    assert all(f["key"] != "customer_email" for f in sent["payload"]["facts"])
    assert fresh["delivery"] == "fresh"
    replayed = asyncio.run(service.analyze("NTK-001", "purpose"))
    assert replayed["delivery"] == "recorded"
    assert replayed["report_id"] == fresh["report_id"]
    assert replayed["result"] == fresh["result"]
    generate.assert_awaited_once()


def test_a_different_model_cannot_replay_an_old_models_answer(service, tmp_path):
    other = Service(
        ModelClient(tmp_path, ModelSettings(model="another-model")), service.store, service.sandbox
    )
    case = service.get_case("NTK-001")
    assert service.cached(case, "purpose") is not None
    assert other.key(case, "purpose") != service.key(case, "purpose")
    assert other.cached(case, "purpose") is None


def test_refresh_failure_keeps_old_observation_and_cooldown_then_recovers(service):
    old = copy.deepcopy(service.get_case("paypal-sandbox"))
    new = copy.deepcopy(old)
    new["label"] = "New normalized observation"
    now = [100.0]
    reader = SimpleNamespace(
        configured=True,
        read=AsyncMock(side_effect=[AppError("PAYPAL_READ_FAILED", "Unavailable"), new]),
    )
    current = Service(service.model, service.store, reader, clock=lambda: now[0])
    with pytest.raises(AppError, match="PAYPAL_READ_FAILED"):
        asyncio.run(current.refresh_paypal())
    assert current.get_case("paypal-sandbox") == old
    assert current.refresh_error == "PAYPAL_READ_FAILED"
    with pytest.raises(AppError, match="REFRESH_COOLDOWN"):
        asyncio.run(current.refresh_paypal())
    assert reader.read.await_count == 1
    now[0] += 31
    assert asyncio.run(current.refresh_paypal()) == new
    assert current.store.observation() == new
    assert current.refresh_error is None


def test_failed_observation_write_does_not_replace_the_visible_case(service, monkeypatch):
    old = copy.deepcopy(service.get_case("paypal-sandbox"))
    new = copy.deepcopy(old)
    new["label"] = "An observation that could not be persisted"
    reader = SimpleNamespace(configured=True, read=AsyncMock(return_value=new))
    current = Service(service.model, service.store, reader)

    def unavailable(case):
        raise PermissionError("synthetic write failure")

    monkeypatch.setattr(service.store, "save_observation", unavailable)
    with pytest.raises(AppError, match="PAYPAL_STORE_FAILED"):
        asyncio.run(current.refresh_paypal())
    assert current.get_case("paypal-sandbox") == old


def test_real_cases_remain_restricted_to_the_purpose_view(service):
    for mode in ("full", "masked"):
        with pytest.raises(AppError, match="SYNTHETIC_ONLY"):
            asyncio.run(service.analyze("paypal-sandbox", mode))
