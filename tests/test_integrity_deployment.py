"""Hosted judge mode must preserve callback, session and recording boundaries."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from ntk.config import Settings
from ntk.dataset import ROOT
from ntk.integrity.app import create_integrity_app
from ntk.integrity.deployment import normalize_origin, resolve_origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://demo.example.test",
        "https://user:password@demo.example.test",
        "https://demo.example.test/app",
        "https://demo.example.test?redirect=elsewhere",
        "https://demo.example.test#fragment",
        "https://*.example.test",
        "https://demo.example.test:70000",
        "https://demo.example.test:0",
        "https://demo.example.test\n",
        "https://demo.example.test%2f.other.test",
        "javascript:alert(1)",
    ],
)
def test_callback_origin_refuses_credentials_paths_and_unusable_hosts(origin):
    with pytest.raises(ValueError, match="origin"):
        normalize_origin(origin)


def test_origin_comes_from_operator_config_not_request_like_environment():
    env = {"HTTP_HOST": "attacker.test", "HTTP_X_FORWARDED_HOST": "attacker.test"}
    assert resolve_origin(8766, env) == "http://127.0.0.1:8766"
    env["RENDER_EXTERNAL_HOSTNAME"] = "minimera-example.onrender.com"
    assert resolve_origin(8766, env) == "https://minimera-example.onrender.com"
    env["NTK_PUBLIC_ORIGIN"] = "https://merchant.example.test/"
    assert resolve_origin(8766, env) == "https://merchant.example.test"
    assert resolve_origin(8766, env, "http://localhost:8768") == "http://localhost:8768"


@pytest.mark.parametrize("flags", [{"sandbox_enabled": True}, {"fresh_ai": True}])
def test_public_mode_refuses_live_provider_capabilities_before_startup(tmp_path, flags):
    with pytest.raises(ValueError, match="local operator"):
        create_integrity_app(
            Settings(runtime_dir=tmp_path / "unused"),
            origin="https://judge.example.test",
            **flags,
        )
    assert not (tmp_path / "unused").exists()


def test_hosted_https_session_and_origin_checks_remain_enforced(tmp_path):
    origin = "https://judge.example.test"
    app = create_integrity_app(Settings(runtime_dir=tmp_path), origin=origin)
    with TestClient(app, base_url=origin) as client:
        assert client.get("/api/integrity/status").json()["publication"] == "operator_hosted"
        response = client.post("/api/integrity/workspaces", json={})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        before = response.json()["workspace"]["id"]
        refused = client.post(
            "/api/integrity/workspaces", json={}, headers={"Origin": "https://attacker.test"}
        )
        assert refused.status_code == 403
        assert client.get("/api/integrity/workspace").json()["workspace"]["id"] == before
        assert (
            client.get("/api/integrity/status", headers={"Host": "attacker.test"}).status_code
            == 400
        )


@pytest.mark.parametrize(
    "host",
    [
        "judge.example.test/elsewhere",
        "judge.example.test?path=/api/integrity/status",
        "judge.example.test#fragment",
    ],
)
def test_malformed_trusted_host_cannot_reinterpret_the_requested_path(tmp_path, host):
    origin = "https://judge.example.test"
    app = create_integrity_app(Settings(runtime_dir=tmp_path), origin=origin)
    with TestClient(app, base_url=origin) as client:
        assert client.get("/api/integrity/status", headers={"Host": host}).status_code == 400
        assert client.get("/api/integrity/status").status_code == 200


def test_health_is_not_ready_until_built_assets_are_mounted_and_storage_works(
    tmp_path, monkeypatch
):
    static = tmp_path / "source"
    (static / "web").mkdir(parents=True)
    monkeypatch.setattr("ntk.integrity.app.ROOT", static)
    settings = Settings(runtime_dir=tmp_path / "state")
    app = create_integrity_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/integrity/health").status_code == 503
        assets = static / "ui/dist/integrity-assets"
        assets.mkdir(parents=True)
        (assets.parent / "index.html").write_text("<html></html>")
        (assets / "app.js").write_text("void 0;")
        (assets / "app.css").write_text("body {}")
        assert client.get("/api/integrity/health").status_code == 503
    ready = create_integrity_app(settings)
    with TestClient(ready) as client:
        assert client.get("/api/integrity/health").json()["status"] == "ready"
        ready.state.integrity.store.path.unlink()
        assert client.get("/api/integrity/health").status_code == 503


def test_large_interface_assets_are_compressed_without_changing_their_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "web").mkdir(parents=True)
    assets = source / "ui/dist/integrity-assets"
    assets.mkdir(parents=True)
    body = b"// Synthetic dashboard module for the compression check.\n" * 400
    (assets / "studio.js").write_bytes(body)
    monkeypatch.setattr("ntk.integrity.app.ROOT", source)
    app = create_integrity_app(Settings(runtime_dir=tmp_path / "state"))
    with TestClient(app) as client:
        response = client.get("/integrity-assets/studio.js", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in response.headers["vary"]
        assert int(response.headers["content-length"]) < len(body) // 2
        assert response.content == body
        assert response.headers["x-content-type-options"] == "nosniff"


class Reply:
    def __init__(self):
        self.calls = 0

    async def invoke(self, request):
        self.calls += 1
        plan = '{"route":"replace_order","summary":"Pause fulfillment and obtain both approvals.","steps":["Verify the refund before capturing the replacement."],"fact_ids":["F1","F5"],"customer_message":"The refund and replacement payment are separate."}'
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": plan}]}},
        }, "synthetic-rehearsal-request"


def test_named_rehearsal_uses_separate_recordings_and_preserves_source_evidence(tmp_path):
    baseline = ROOT / "reports/order-integrity-v1/recordings"
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in baseline.glob("*.json")}
    recordings = tmp_path / "named-rehearsal/recordings"
    app = create_integrity_app(
        Settings(runtime_dir=tmp_path / "state"), fresh_ai=True, recordings_dir=recordings
    )
    fake = Reply()
    with TestClient(app) as client:
        app.state.integrity.analyst.client = fake
        sources = []
        for _ in range(2):
            view = client.post("/api/integrity/workspaces", json={}).json()
            buyer = view["buyer_url"].rsplit("/", 1)[-1]
            assert (
                client.post(
                    "/api/integrity/buyer/change",
                    json={"destination": "office", "remove_pouch": True},
                    headers={"X-Minimera-Buyer": buyer},
                ).status_code
                == 200
            )
            analyzed = client.post(
                "/api/integrity/analyze", headers={"X-Minimera-CSRF": view["csrf"]}
            )
            assert analyzed.status_code == 200
            sources.append(analyzed.json()["workspace"]["change"]["advice"]["source"])
        assert sources == ["bedrock", "recorded_bedrock"]
        assert fake.calls == 1
        assert len(list(recordings.glob("*.json"))) == 1
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in baseline.glob("*.json")
    }
