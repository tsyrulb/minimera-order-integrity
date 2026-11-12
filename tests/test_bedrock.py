import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from botocore.credentials import ReadOnlyCredentials

from ntk.bedrock import BedrockClient
from ntk.config import DEFAULT_BEDROCK_MODEL, ModelSettings, Settings
from ntk.contracts import Analysis, AppError
from ntk.dataset import load_dataset
from ntk.model_requests import bedrock_schema, request_body
from ntk.policy import canonical, digest, project
from ntk.service import create_service


def config(**changes):
    return replace(
        ModelSettings(provider="bedrock", model=DEFAULT_BEDROCK_MODEL, bedrock_fresh_enabled=True),
        **changes,
    )


def credentials():
    return ReadOnlyCredentials(
        "SYNTHETICACCESSKEY", "synthetic-secret-key", "synthetic-session-token"
    )


def projection():
    return project(load_dataset()[0]["cases"][0], "purpose")


def reply(**changes):
    value = {
        "action": "gather_evidence",
        "missing_evidence": ["tracking"],
        "citations": ["F11"],
        "rationale": "The supplied facts do not contain a tracking record.",
        "reply_draft": "Thank you for reporting that the item has not arrived. We are reviewing our shipment records.",
    }
    value.update(changes)
    return {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": json.dumps(value)}]}},
        "usage": {"inputTokens": 1234, "outputTokens": 150},
    }


def test_bedrock_configuration_and_factory_are_explicit(tmp_path):
    settings = Settings.from_env(
        {
            "NTK_PROVIDER": "bedrock",
            "AWS_REGION": "us-east-1",
            "AWS_PROFILE": "synthetic-profile",
            "NTK_RUNTIME_DIR": str(tmp_path),
            "NTK_EXPERIMENT": "unit-experiment",
        }
    )
    service = create_service(settings)
    assert isinstance(service.model, BedrockClient)
    assert service.model.config.model == DEFAULT_BEDROCK_MODEL
    assert service.model.config.aws_profile == "synthetic-profile"
    assert (
        service.model.runtime == service.store.runtime == tmp_path / "experiments/unit-experiment"
    )
    assert service.store.benchmark_path.parts[-3:] == (
        "experiments",
        "unit-experiment",
        "benchmark.json",
    )
    assert not tmp_path.joinpath("model.lock").exists()


def test_schema_adaptation_keeps_local_validation_and_original_contract():
    adapted = bedrock_schema()
    assert "maxLength" not in adapted["properties"]["reply_draft"]
    assert "maxItems" not in adapted["properties"]["citations"]
    assert Analysis.model_json_schema()["properties"]["reply_draft"]["maxLength"] == 900
    assert adapted["additionalProperties"] is False


def test_signed_request_contains_only_projected_data_and_exports_no_authentication(tmp_path):
    requests = []

    def respond(request):
        requests.append(request)
        assert (
            str(request.url)
            == f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{DEFAULT_BEDROCK_MODEL}/converse"
        )
        assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
        assert "/us-east-1/bedrock/aws4_request" in request.headers["Authorization"]
        assert request.headers["X-Amz-Security-Token"] == "synthetic-session-token"
        assert request.content == canonical(request_body(projection(), config())["body"]).encode()
        return httpx.Response(
            200, json=reply(), headers={"x-amzn-requestid": "synthetic-request-id"}
        )

    client = BedrockClient(
        tmp_path, config(), credentials=credentials, transport=httpx.MockTransport(respond)
    )
    result = asyncio.run(client.analyze(projection()))
    assert result["request_sha256"] == digest(result["request"])
    assert result["tokens"] == {"input": 1234, "output": 150}
    assert result["provider_request_id"] == "synthetic-request-id"
    assert result["memory_after"] is None
    assert result["model"]["digest"] is None
    exported = canonical(result)
    for value in credentials():
        if isinstance(value, str):
            assert value not in exported
    user = json.loads(result["request"]["body"]["messages"][0]["content"][0]["text"])
    assert user == projection()["payload"]
    assert "expected" not in user
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"citations": ["F99"]}, "INVALID_CITATION"),
        ({"reply_draft": "x" * 901}, "MODEL_OUTPUT_FAILED"),
        ({"action": "refund_money"}, "MODEL_OUTPUT_FAILED"),
    ],
)
def test_model_output_is_checked_after_provider_schema(tmp_path, changes, code):
    client = BedrockClient(
        tmp_path,
        config(),
        credentials=credentials,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply(**changes))),
    )
    with pytest.raises(AppError, match=code) as error:
        asyncio.run(client.analyze(projection()))
    assert error.value.evidence["raw_output"]
    assert "synthetic-secret-key" not in canonical(error.value.evidence)


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "BEDROCK_REQUEST_REJECTED"), (403, "BEDROCK_ACCESS_DENIED"), (429, "BEDROCK_THROTTLED")],
)
def test_provider_errors_are_sanitized_and_release_the_lock(tmp_path, status, code):
    client = BedrockClient(
        tmp_path,
        config(),
        credentials=credentials,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"message": "synthetic-secret-key"})
        ),
    )
    for _ in range(2):
        with pytest.raises(AppError, match=code) as error:
            asyncio.run(client.analyze(projection()))
        assert "synthetic-secret" not in error.value.message


def test_allowance_persists_across_client_instances_and_stops_before_network(tmp_path):
    calls = []

    def respond(request):
        calls.append(True)
        return httpx.Response(200, json=reply())

    for expected in [None, "BEDROCK_CALL_LIMIT"]:
        client = BedrockClient(
            tmp_path,
            config(bedrock_call_limit=1),
            credentials=credentials,
            transport=httpx.MockTransport(respond),
        )
        if expected:
            with pytest.raises(AppError, match=expected):
                asyncio.run(client.analyze(projection()))
        else:
            asyncio.run(client.analyze(projection()))
    assert len(calls) == 1


def test_missing_credentials_never_send_a_request_or_consume_allowance(tmp_path):
    def unexpected(request):
        pytest.fail("A request was sent without AWS credentials")

    client = BedrockClient(
        tmp_path, config(), credentials=lambda: None, transport=httpx.MockTransport(unexpected)
    )
    with pytest.raises(AppError, match="BEDROCK_NOT_CONFIGURED"):
        asyncio.run(client.analyze(projection()))
    assert not (tmp_path / "bedrock-usage.json").exists()


def test_unreadable_allowance_fails_closed_as_configuration_error(tmp_path):
    def unexpected(request):
        pytest.fail("A request was sent despite an invalid persistent allowance")

    (tmp_path / "bedrock-usage.json").write_text("{broken JSON")
    client = BedrockClient(
        tmp_path, config(), credentials=credentials, transport=httpx.MockTransport(unexpected)
    )
    with pytest.raises(AppError, match="BEDROCK_CONFIGURATION"):
        asyncio.run(client.analyze(projection()))
    assert (tmp_path / "bedrock-usage.json").read_text() == "{broken JSON"


def test_incomplete_or_oversized_response_is_not_accepted(tmp_path):
    incomplete = reply()
    incomplete["stopReason"] = "max_tokens"
    for response, code in [
        (httpx.Response(200, json=incomplete), "MODEL_OUTPUT_INCOMPLETE"),
        (httpx.Response(200, content=b"x" * 260_000), "MODEL_RESPONSE_TOO_LARGE"),
    ]:
        client = BedrockClient(
            tmp_path,
            config(),
            credentials=credentials,
            transport=httpx.MockTransport(lambda request, response=response: response),
        )
        with pytest.raises(AppError, match=code):
            asyncio.run(client.analyze(projection()))


def test_cancellation_closes_the_owned_request_and_releases_the_lock(tmp_path):
    async def run():
        entered = asyncio.Event()
        cancelled = []

        async def slow(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        client = BedrockClient(
            tmp_path, config(), credentials=credentials, transport=httpx.MockTransport(slow)
        )
        task = asyncio.create_task(client.analyze(projection()))
        await asyncio.wait_for(entered.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        other = BedrockClient(
            tmp_path,
            config(),
            credentials=credentials,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply())),
        )
        assert (await other.analyze(projection()))["analysis"]["action"] == "gather_evidence"
        assert cancelled == [True]

    asyncio.run(run())


def test_replay_mode_neither_resolves_credentials_nor_sends_requests(tmp_path):
    def unexpected():
        pytest.fail("Replay mode resolved AWS credentials")

    client = BedrockClient(tmp_path, config(bedrock_fresh_enabled=False), credentials=unexpected)
    assert asyncio.run(client.inspect())["ready"] is False
    with pytest.raises(AppError, match="BEDROCK_FRESH_DISABLED"):
        asyncio.run(client.analyze(projection()))
    assert not (tmp_path / "bedrock-usage.json").exists()


def test_reasoning_settings_are_recorded_and_only_final_text_is_accepted(tmp_path):
    settings = config(
        model="openai.gpt-oss-120b-1:0", bedrock_max_tokens=4096, bedrock_reasoning_effort="low"
    )
    value = reply()
    value["output"]["message"]["content"].insert(
        0,
        {
            "reasoningContent": {
                "reasoningText": {
                    "text": "synthetic private reasoning, never exported",
                    "signature": "synthetic-signature",
                }
            }
        },
    )
    client = BedrockClient(
        tmp_path,
        settings,
        credentials=credentials,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value)),
    )
    result = asyncio.run(client.analyze(projection()))
    assert result["request"]["body"]["inferenceConfig"]["maxTokens"] == 4096
    assert result["request"]["body"]["additionalModelRequestFields"] == {"reasoning_effort": "low"}
    assert result["settings"]["reasoning_effort"] == "low"
    assert "synthetic private reasoning" not in canonical(result)
    assert "synthetic-signature" not in canonical(result)
