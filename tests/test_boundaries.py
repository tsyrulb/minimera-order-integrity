import asyncio
import fcntl
import json

import httpx
import pytest

from ntk import resources
from ntk.config import ModelSettings
from ntk.contracts import AppError
from ntk.dataset import load_dataset
from ntk.model import ModelClient
from ntk.policy import project


def test_memory_guard_reserves_headroom_before_loading(monkeypatch):
    monkeypatch.setattr(
        resources, "memory_snapshot", lambda: {"available_mib": 3000, "pressure_avg10": 0}
    )
    with pytest.raises(AppError, match="MEMORY_GUARD"):
        resources.ensure_memory(loaded=False, load_budget_mib=2400)
    assert resources.ensure_memory(loaded=True)["available_mib"] == 3000
    monkeypatch.setattr(
        resources, "memory_snapshot", lambda: {"available_mib": 1535, "pressure_avg10": 0}
    )
    with pytest.raises(AppError, match="MEMORY_GUARD"):
        resources.ensure_memory(loaded=True)


def test_memory_pressure_also_stops_inference(monkeypatch):
    monkeypatch.setattr(
        resources, "memory_snapshot", lambda: {"available_mib": 5000, "pressure_avg10": 5}
    )
    with pytest.raises(AppError, match="MEMORY_GUARD"):
        resources.ensure_memory(loaded=True)


def test_an_unknown_large_model_cannot_use_the_small_model_memory_allowance():
    assert resources.model_load_budget("another-8b", 5 * 1024**3) > 8000
    with pytest.raises(AppError, match="MODEL_SIZE_UNKNOWN"):
        resources.model_load_budget("unknown", None)


def test_a_second_generation_is_refused_across_processes(tmp_path):
    model = ModelClient(tmp_path)
    lock = (tmp_path / "model.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(AppError, match="MODEL_BUSY"):
        asyncio.run(model.analyze(project(load_dataset()[0]["cases"][0], "purpose")))
    lock.close()


def test_memory_drop_cancels_the_owned_request_and_unloads_only_its_model(tmp_path, monkeypatch):
    snapshot_count = 0
    cancelled = []
    unloads = []

    def memory():
        nonlocal snapshot_count
        snapshot_count += 1
        return {"available_mib": 3000 if snapshot_count == 1 else 1500, "pressure_avg10": 0}

    async def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:3b", "size": 1900000000}]}
            )
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "synthetic-test"})
        if request.url.path == "/api/chat":
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        if request.url.path == "/api/generate":
            unloads.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})
        pytest.fail("Unexpected model API call")

    monkeypatch.setattr(resources, "memory_snapshot", memory)
    client = ModelClient(tmp_path, ModelSettings(), transport=httpx.MockTransport(respond))

    async def run():
        with pytest.raises(AppError, match="MEMORY_GUARD"):
            await asyncio.wait_for(
                client.analyze(project(load_dataset()[0]["cases"][0], "purpose")), timeout=3
            )

    asyncio.run(run())
    assert cancelled == [True]
    assert unloads == [{"model": "qwen2.5:3b", "keep_alive": 0}]


def test_ui_and_api_do_not_expose_oracle_or_secrets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    response = client.get("/api/cases/NTK-001")
    assert response.status_code == 200
    assert "expected" not in response.json()["case"]
    assert (
        response.json()["projections"]["purpose"]["model_request"]["messages"][1]["role"] == "user"
    )
    assert "PAYPAL_SANDBOX_CLIENT_SECRET" not in response.text
    assert client.get("/assets/../.env").status_code == 404
    assert client.get("/api/cases/not-an-allowed-case").status_code == 404
    assert client.get("/", headers={"Host": "unrelated.onrender.com"}).status_code == 400


def test_no_arbitrary_model_url_prompt_or_payment_action(client):
    assert (
        client.post(
            "/api/analyze",
            json={
                "case_id": "NTK-001",
                "mode": "purpose",
                "provider_url": "http://169.254.169.254",
            },
        ).status_code
        == 422
    )
    assert (
        client.post("/api/analyze", json={"case_id": "../../secret", "mode": "purpose"}).status_code
        == 422
    )
    assert client.post("/api/paypal/refund", json={}).status_code == 404
    assert (
        client.post(
            "/api/analyze",
            json={"case_id": "NTK-001"},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )


def test_oversized_chunked_body_is_rejected_before_model(client):
    response = client.post(
        "/api/analyze",
        content=iter([b"x" * 1500, b"x" * 1500]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_analyze_dispatch_passes_only_a_fixed_case_and_mode(client, monkeypatch):
    calls = []

    async def analyze(case_id, mode, fresh):
        calls.append((case_id, mode, fresh))
        return {"delivery": "recorded", "test": True}

    monkeypatch.setattr(client.app.state.service, "analyze", analyze)
    response = client.post("/api/analyze", json={"case_id": "NTK-002", "mode": "purpose"})
    assert response.status_code == 200
    assert calls == [("NTK-002", "purpose", False)]
