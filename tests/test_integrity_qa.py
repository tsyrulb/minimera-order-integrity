"""QA regressions for concurrent reviews and the final fulfillment boundary."""

import asyncio
import json

import pytest

from ntk.contracts import AppError
from ntk.integrity.contracts import ChangeRequest, CompleteCheckout, NewWorkspace, Plan
from ntk.integrity.model import Analyst
from ntk.integrity.service import IntegrityService
from ntk.integrity.store import Store


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / "state")
    return IntegrityService(store, Analyst(store, tmp_path / "recordings"))


async def requested(service):
    ws = await service.create(NewWorkspace())
    return await service.request_change(ws.id, ChangeRequest())


async def completed(service):
    ws = await requested(service)
    await service.approve(ws.id, ws.change.snapshot_hash)
    checkout = await service.checkout(ws.id, "replacement")
    return await service.complete_checkout(
        ws.id, CompleteCheckout(checkout_id=checkout.id, state=checkout.state)
    )


class DelayedReply:
    def __init__(self):
        self.calls = 0

    async def invoke(self, request):
        self.calls += 1
        identity = self.calls
        await asyncio.sleep(0.01)
        plan = Plan(
            route="replace_order",
            summary=f"Synthetic explanation {identity}.",
            steps=["Review the exact order before either payment operation."],
            fact_ids=["F1", "F3"],
            customer_message="A separate refund and payment require approval.",
        )
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": plan.model_dump_json()}]}},
        }, f"synthetic-request-{identity}"


def test_concurrent_identical_contexts_consume_only_one_model_attempt(service, tmp_path):
    async def scenario():
        ws = await requested(service)
        client = DelayedReply()
        analyst = Analyst(service.store, tmp_path / "fresh", fresh=True, client=client)
        first, second = await asyncio.gather(
            analyst.review(ws.change), analyst.review(ws.change.model_copy(deep=True))
        )
        assert client.calls == 1
        assert {first.source, second.source} == {"bedrock", "recorded_bedrock"}
        assert first.provider_request_id == second.provider_request_id
        assert first.plan == second.plan
        with service.store.connection() as db:
            assert db.execute("SELECT SUM(attempts) FROM allowances").fetchone()[0] == 1
        assert len(list((service.store.path.parent / "model-attempts").glob("*.json"))) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("request_hash", "0" * 64),
        ("model", "unrelated-model"),
        ("prompt_version", "unrelated-prompt"),
        ("source", "unavailable"),
        ("policy_agrees", False),
    ],
)
def test_replay_rejects_inconsistent_advice_provenance(service, tmp_path, field, replacement):
    async def scenario():
        ws = await requested(service)
        analyst = Analyst(service.store, tmp_path / "fresh", fresh=True, client=DelayedReply())
        advice = await analyst.review(ws.change)
        path = analyst.recordings / (advice.request_hash + ".json")
        record = json.loads(path.read_text())
        record["advice"][field] = replacement
        path.write_text(json.dumps(record))
        with pytest.raises(AppError, match="AI_RECORDING_INVALID"):
            await analyst.review(ws.change)

    asyncio.run(scenario())


@pytest.mark.parametrize("output", [None, {"message": None}])
def test_malformed_model_envelope_returns_a_safe_error(service, tmp_path, output):
    class MalformedReply:
        async def invoke(self, request):
            return {"stopReason": "end_turn", "output": output}, "synthetic-malformed"

    async def scenario():
        ws = await requested(service)
        analyst = Analyst(service.store, tmp_path / "fresh", fresh=True, client=MalformedReply())
        with pytest.raises(AppError, match="AI_UNAVAILABLE"):
            await analyst.review(ws.change)
        with service.store.connection() as db:
            assert db.execute("SELECT SUM(attempts) FROM allowances").fetchone()[0] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "value"), [("refund_id", "UNRELATED"), ("source", "paypal_sandbox")]
)
def test_final_release_rejects_a_different_refund_observation(service, monkeypatch, field, value):
    async def scenario():
        ws = await completed(service)
        read_refund = service.simulator.read_refund

        async def mismatch(refund_id):
            observed = await read_refund(refund_id)
            return observed.model_copy(update={field: value})

        monkeypatch.setattr(service.simulator, "read_refund", mismatch)
        with pytest.raises(AppError, match="PAYMENT_CHANGED"):
            await service.release(ws.id)
        saved = service.store.get(ws.id)
        assert saved.fulfillment_order.fulfillment == "ready"
        assert not any(e.action == "fulfillment_released" for e in saved.events)

    asyncio.run(scenario())


def test_final_release_binds_the_warehouse_payment_to_the_verified_replacement(service):
    async def scenario():
        ws = await completed(service)
        # An OMS mapping error must not attach the refunded original payment
        # to the corrected warehouse order, even if its items/address match.
        ws.fulfillment_order.payment = ws.order.payment.model_copy(deep=True)
        service.store.save(ws)
        with pytest.raises(AppError, match="FULFILLMENT_MISMATCH"):
            await service.release(ws.id)
        assert service.store.get(ws.id).fulfillment_order.fulfillment == "ready"

    asyncio.run(scenario())


def test_original_payment_keeps_the_independently_verified_capture(service, monkeypatch):
    async def scenario():
        service.sandbox = service.simulator
        ws = await service.create(NewWorkspace(mode="sandbox"))
        checkout = await service.checkout(ws.id, "original")
        await service.simulator.approve_simulation(checkout.order_id)
        read = service.simulator.read
        completed_reads = 0

        async def conflicting_later_read(order_id):
            nonlocal completed_reads
            payment = await read(order_id)
            if payment.capture_status == "COMPLETED":
                completed_reads += 1
                if completed_reads > 1:
                    return payment.model_copy(update={"cents": payment.cents + 1})
            return payment

        monkeypatch.setattr(service.simulator, "read", conflicting_later_read)
        result = await service.complete_checkout(
            ws.id, CompleteCheckout(checkout_id=checkout.id, state=checkout.state)
        )
        assert result.order.payment.cents == checkout.cents == 100
        assert result.order.payment.capture_status == "COMPLETED"

    asyncio.run(scenario())
