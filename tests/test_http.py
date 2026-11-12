import asyncio

import pytest
from fastapi.testclient import TestClient

from ntk.app import create_app
from ntk.config import Settings
from ntk.security import BoundaryMiddleware


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        ("http://testserver", 200),
        ("https://testserver", 403),
        ("https://unrelated.example", 403),
        ("http://[invalid", 403),
        ("null", 403),
    ],
)
def test_post_origin_must_match_scheme_and_host(client, origin, status):
    response = client.post("/api/analyze", json={"case_id": "NTK-001"}, headers={"Origin": origin})
    assert response.status_code == status


@pytest.mark.parametrize("failure", ["origin", "size", "validation", "rate"])
def test_early_rejections_have_security_headers_and_do_not_reflect_input(client, failure):
    marker = "synthetic-private-value-that-must-not-be-reflected"
    if failure == "origin":
        response = client.post(
            "/api/analyze", json={"case_id": "NTK-001"}, headers={"Origin": "null"}
        )
    elif failure == "size":
        response = client.post("/api/analyze", content=marker * 100)
    elif failure == "validation":
        response = client.post("/api/analyze", json={"case_id": marker, "api_key": marker})
    else:
        for _ in range(9):
            response = client.post("/api/analyze", json={"case_id": marker})
    assert response.status_code in (403, 413, 422, 429)
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert marker not in response.text
    assert "error" in response.json()


def test_two_application_instances_do_not_share_rate_limits_or_cases(tmp_path):
    first = create_app(Settings(runtime_dir=tmp_path / "first"))
    second = create_app(Settings(runtime_dir=tmp_path / "second"))
    with TestClient(first) as a, TestClient(second) as b:
        for _ in range(8):
            assert a.post("/api/analyze", json={"case_id": "NTK-999"}).status_code == 404
        assert a.post("/api/analyze", json={"case_id": "NTK-001"}).status_code == 429
        assert b.post("/api/analyze", json={"case_id": "NTK-001"}).status_code == 200
        assert first.state.service is not second.state.service
        first.state.service.cases.pop("NTK-002")
        assert b.get("/api/cases/NTK-002").status_code == 200


def test_fragmented_asgi_body_is_limited_before_application_dispatch():
    messages = iter(
        [
            {"type": "http.request", "body": b"a" * 1500, "more_body": True},
            {"type": "http.request", "body": b"b" * 1500, "more_body": False},
        ]
    )
    sent = []
    dispatched = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def application(scope, receive, send):
        dispatched.append(True)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/analyze",
        "scheme": "http",
        "headers": [],
        "client": ("test", 1),
    }
    asyncio.run(BoundaryMiddleware(application)(scope, receive, send))
    assert not dispatched
    assert sent[0]["status"] == 413
    assert (b"cache-control", b"no-store") in sent[0]["headers"]
