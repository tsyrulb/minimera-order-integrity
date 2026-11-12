import asyncio
import json

import httpx
import pytest

from ntk import model
from ntk.config import DEFAULT_CLOUD_MODEL, ModelSettings
from ntk.contracts import AppError
from ntk.dataset import load_dataset
from ntk.policy import digest, project


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ([], "MODEL_OUTPUT_FAILED"),
        ({"status": "incomplete"}, "MODEL_OUTPUT_INCOMPLETE"),
        ({"status": "completed", "output": []}, "MODEL_OUTPUT_FAILED"),
        ({"status": "completed", "output": None}, "MODEL_OUTPUT_FAILED"),
    ],
)
def test_provider_failures_release_the_generation_lock_and_do_not_expose_credentials(
    tmp_path, payload, code
):
    def respond(request):
        return httpx.Response(200, json=payload)

    config = ModelSettings(
        provider="openai", model=DEFAULT_CLOUD_MODEL, api_key="synthetic-private-api-key"
    )
    client = model.ModelClient(tmp_path, config, transport=httpx.MockTransport(respond))
    projection = project(load_dataset()[0]["cases"][0], "purpose")
    for _ in range(2):
        with pytest.raises(AppError, match=code) as error:
            asyncio.run(client.analyze(projection))
        assert "synthetic-private-api-key" not in error.value.message


@pytest.mark.parametrize("invalid_citation", [False, True])
def test_cloud_requests_are_bounded_and_outputs_are_validated(tmp_path, invalid_citation):
    captured = []
    projection = project(load_dataset()[0]["cases"][0], "purpose")

    async def respond(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["max_output_tokens"] == 512
        assert body["text"]["format"]["strict"] is True
        assert "expected" not in body
        captured.append(body)
        analysis = {
            "action": "gather_evidence",
            "missing_evidence": ["tracking"],
            "citations": ["F99" if invalid_citation else "F11"],
            "rationale": "No tracking record is available.",
            "reply_draft": "Thank you for reporting the issue. We are reviewing our shipment records.",
        }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": json.dumps(analysis)}]}],
                "usage": {"input_tokens": 100, "output_tokens": 60},
            },
        )

    config = ModelSettings(
        provider="openai", model=DEFAULT_CLOUD_MODEL, api_key="synthetic-unit-test-token"
    )
    client = model.ModelClient(tmp_path, config, transport=httpx.MockTransport(respond))
    if invalid_citation:
        with pytest.raises(AppError, match="INVALID_CITATION"):
            asyncio.run(client.analyze(projection))
    else:
        result = asyncio.run(client.analyze(projection))
        assert result["request_sha256"] == digest(captured[0])
        assert result["model"]["digest"] is None
        assert result["memory_after"] is None
        assert "synthetic-unit-test-token" not in json.dumps(result)
