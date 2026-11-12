"""Regression tests for money/state boundaries, not just the happy-path UI."""

import asyncio
import json
import time
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from ntk.config import PayPalSettings, Settings
from ntk.contracts import AppError
from ntk.integrity.app import create_integrity_app
from ntk.integrity.auth import Sessions
from ntk.integrity.contracts import (
    ChangeRequest,
    CompleteCheckout,
    NewWorkspace,
    Plan,
)
from ntk.integrity.model import Analyst
from ntk.integrity.payments import Sandbox, normalize_order
from ntk.integrity.policy import DESTINATIONS, fingerprint, model_context
from ntk.integrity.service import IntegrityService
from ntk.integrity.store import Store


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def integrity(tmp_path):
    store = Store(tmp_path / "state")
    return IntegrityService(store, Analyst(store, tmp_path / "recordings"))


def requested(integrity, scenario="address_change"):
    ws = run(integrity.create(NewWorkspace(scenario=scenario)))
    return run(integrity.request_change(ws.id, ChangeRequest()))


def approved(integrity):
    ws = requested(integrity)
    return run(integrity.approve(ws.id, ws.change.snapshot_hash))


def checkout_request(checkout):
    return CompleteCheckout(checkout_id=checkout.id, state=checkout.state)


def test_full_change_requires_both_roles_then_verifies_two_legs(integrity):
    ws = requested(integrity)
    assert ws.order.fulfillment == "on_hold"
    assert ws.change.cents == 8400
    with pytest.raises(AppError, match="APPROVAL_REQUIRED"):
        run(integrity.checkout(ws.id, "replacement"))
    ws = run(integrity.approve(ws.id, ws.change.snapshot_hash))
    assert ws.change.refund is None
    checkout = run(integrity.checkout(ws.id, "replacement"))
    assert integrity.store.get(ws.id).change.replacement.capture_id is None
    ws = run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    assert ws.change.state == "complete"
    assert ws.change.refund.status == "COMPLETED"
    assert ws.change.refund.cents == 12000
    assert ws.change.replacement.capture_status == "COMPLETED"
    assert ws.change.replacement.cents == 8400
    assert ws.change.replacement.destination == "office"
    assert ws.order.fulfillment == "replaced"
    assert ws.order.payment.capture_status == "REFUNDED"
    assert ws.fulfillment_order.fulfillment == "ready"
    assert ws.fulfillment_order.destination == "office"
    assert [i.sku for i in ws.fulfillment_order.items] == ["TOTE"]
    released = run(integrity.release(ws.id))
    assert released.fulfillment_order.fulfillment == "released"
    assert "released to the synthetic warehouse" in released.change.explanation


def test_shipped_order_cannot_be_approved_or_refunded(integrity):
    ws = requested(integrity, "already_shipped")
    assert ws.change.route == "manual_review"
    assert ws.change.state == "blocked"
    assert ws.order.fulfillment == "shipped"
    with pytest.raises(AppError, match="NOT_APPROVABLE"):
        run(integrity.approve(ws.id, ws.change.snapshot_hash))
    assert ws.change.refund is None


def test_state_change_invalidates_an_approval_before_checkout(integrity):
    ws = requested(integrity, "stale_approval")
    ws = run(integrity.approve(ws.id, ws.change.snapshot_hash))
    run(integrity.advance_warehouse(ws.id))
    with pytest.raises(AppError, match="STALE_APPROVAL"):
        run(integrity.checkout(ws.id, "replacement"))
    saved = integrity.store.get(ws.id)
    assert saved.change.state == "stale"
    assert saved.checkouts == []


@pytest.mark.parametrize("merchant_approved", [False, True])
def test_recheck_detects_changed_warehouse_without_dispatch(integrity, merchant_approved):
    ws = requested(integrity, "stale_approval")
    if merchant_approved:
        ws = run(integrity.approve(ws.id, ws.change.snapshot_hash))
    saved_hash = ws.change.approved_hash
    run(integrity.advance_warehouse(ws.id))
    checked = run(integrity.recheck(ws.id))
    assert checked.change.state == "stale"
    assert checked.order.fulfillment == "shipped"
    assert checked.change.approved_hash == saved_hash
    assert checked.change.refund is None
    assert checked.change.replacement is None
    assert checked.checkouts == []
    with integrity.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


def test_recheck_never_renews_approval_or_executes_payments(integrity):
    ws = approved(integrity)
    expires = ws.change.approval_expires
    saved_hash = ws.change.approved_hash
    checked = run(integrity.recheck(ws.id))
    assert checked.change.state == "approved"
    assert checked.change.approval_expires == expires
    assert checked.change.approved_hash == saved_hash
    assert checked.change.refund is None
    assert checked.change.replacement is None
    assert checked.events[-1].action == "approval_rechecked"
    checked.change.approval_expires = int(time.time()) - 1
    integrity.store.save(checked)
    expired = run(integrity.recheck(ws.id))
    assert expired.change.state == "stale"
    assert expired.change.approval_expires == checked.change.approval_expires
    assert expired.change.refund is None
    assert expired.checkouts == []


def test_changed_payment_status_invalidates_review_snapshot(integrity):
    ws = requested(integrity)
    remote = run(integrity.simulator.read(ws.order.payment.order_id))
    remote.capture_status = "REFUNDED"
    integrity.store.provider_put(remote.order_id, remote.model_dump_json())
    result = run(integrity.approve(ws.id, ws.change.snapshot_hash))
    assert result.change.state == "stale"


def test_amount_destination_merchant_binding_is_independent_of_status(integrity):
    ws = requested(integrity)
    remote = run(integrity.simulator.read(ws.order.payment.order_id))
    remote.merchant_id = "OTHER-MERCHANT"
    integrity.store.provider_put(remote.order_id, remote.model_dump_json())
    with pytest.raises(AppError, match="PAYMENT_BINDING_MISMATCH"):
        run(integrity.approve(ws.id, ws.change.snapshot_hash))


def test_expired_approval_sends_no_replacement_payment(integrity):
    ws = approved(integrity)
    ws.change.approval_expires = int(time.time()) - 1
    integrity.store.save(ws)
    with pytest.raises(AppError, match="STALE_APPROVAL"):
        run(integrity.checkout(ws.id, "replacement"))
    assert integrity.store.get(ws.id).change.refund is None


def test_duplicate_checkout_completion_does_not_duplicate_money(integrity):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))

    async def two_returns():
        return await asyncio.gather(
            *[integrity.complete_checkout(ws.id, checkout_request(checkout)) for _ in range(2)]
        )

    first, second = run(two_returns())
    assert first.change.refund.refund_id == second.change.refund.refund_id
    assert first.change.replacement.capture_id == second.change.replacement.capture_id
    with integrity.store.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM operations WHERE operation LIKE '%refund'").fetchone()[
                0
            ]
            == 1
        )


def test_pending_refund_withholds_capture_and_can_be_checked_without_resending(
    integrity, monkeypatch
):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))
    read_refund = integrity.simulator.read_refund
    calls = []
    refund = integrity.simulator.refund

    async def counted_refund(*args):
        calls.append(args)
        return await refund(*args)

    async def pending(refund_id):
        result = await read_refund(refund_id)
        result.status = "PENDING"
        return result

    monkeypatch.setattr(integrity.simulator, "refund", counted_refund)
    monkeypatch.setattr(integrity.simulator, "read_refund", pending)
    result = run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    assert result.change.state == "pending"
    assert result.order.fulfillment == "on_hold"
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None
    monkeypatch.setattr(integrity.simulator, "read_refund", read_refund)
    assert run(integrity.resume(ws.id)).change.state == "complete"
    assert len(calls) == 1


def test_timeout_after_refund_dispatch_is_not_automatically_retried(integrity, monkeypatch):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))
    calls = []

    async def unknown(*args):
        calls.append(args)
        raise AppError("PAYPAL_UNCONFIRMED", "Synthetic timeout", 502)

    monkeypatch.setattr(integrity.simulator, "refund", unknown)
    with pytest.raises(AppError, match="PAYPAL_UNCONFIRMED"):
        run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    assert integrity.store.get(ws.id).change.state == "indeterminate"
    with pytest.raises(AppError, match="MANUAL_RECONCILIATION"):
        run(integrity.resume(ws.id))
    assert len(calls) == 1
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None


def pause_after_known_refund(integrity, monkeypatch):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))

    async def unreadable(refund_id):
        raise AppError("REFUND_READBACK_MISMATCH", "Synthetic invalid readback", 409)

    with monkeypatch.context() as patch:
        patch.setattr(integrity.simulator, "read_refund", unreadable)
        with pytest.raises(AppError, match="REFUND_READBACK_MISMATCH"):
            run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    paused = integrity.store.get(ws.id)
    assert paused.change.state == "indeterminate"
    assert paused.change.refund.status == "UNVERIFIED"
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None
    return paused, checkout


def test_known_refund_readback_recovery_never_resends_refund_or_renews_approval(
    integrity, monkeypatch
):
    ws, checkout = pause_after_known_refund(integrity, monkeypatch)
    capture = integrity.simulator.capture
    captures = []

    async def forbidden_refund(*args):
        raise AssertionError("A known refund must never be resent")

    async def counted_capture(*args):
        captures.append(args)
        await capture(*args)

    monkeypatch.setattr(integrity.simulator, "refund", forbidden_refund)
    monkeypatch.setattr(integrity.simulator, "capture", counted_capture)
    resumed = run(integrity.resume(ws.id))
    assert resumed.change.state == "complete"
    assert resumed.change.refund.refund_id == ws.change.refund.refund_id
    assert resumed.change.replacement.order_id == checkout.order_id
    assert resumed.change.approval_expires == ws.change.approval_expires
    assert resumed.change.approved_hash == ws.change.approved_hash
    assert len(captures) == 1
    actions = [event.action for event in resumed.events]
    assert actions.index("execution_paused") < actions.index("refund_check_requested")
    assert actions.index("refund_verified") < actions.index("replacement_verified")
    with pytest.raises(AppError, match="MANUAL_RECONCILIATION"):
        run(integrity.resume(ws.id))
    assert len(captures) == 1
    with integrity.store.connection() as db:
        operations = db.execute(
            "SELECT operation, status FROM operations WHERE workspace=?", (ws.id,)
        ).fetchall()
    assert dict(operations) == {
        "replacement:create": "verified",
        ws.change.id + ":refund": "verified",
        "replacement:capture": "verified",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_id", "OTHER-CAPTURE"),
        ("cents", 1),
        ("refund_id", "OTHER-REFUND"),
        ("source", "paypal_sandbox"),
    ],
)
def test_known_refund_recovery_still_requires_exact_resource_binding(
    integrity, monkeypatch, field, value
):
    ws, checkout = pause_after_known_refund(integrity, monkeypatch)
    read = integrity.simulator.read_refund

    async def mismatch(refund_id):
        result = await read(refund_id)
        setattr(result, field, value)
        return result

    monkeypatch.setattr(integrity.simulator, "read_refund", mismatch)
    with pytest.raises(AppError, match="REFUND_MISMATCH"):
        run(integrity.resume(ws.id))
    assert integrity.store.get(ws.id).order.fulfillment == "on_hold"
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None


def test_known_refund_recovery_with_expired_approval_withholds_capture(integrity, monkeypatch):
    ws, checkout = pause_after_known_refund(integrity, monkeypatch)
    ws.change.approval_expires = int(time.time()) - 1
    integrity.store.save(ws)
    with pytest.raises(AppError, match="APPROVAL_EXPIRED"):
        run(integrity.resume(ws.id))
    saved = integrity.store.get(ws.id)
    assert saved.change.refund.status == "COMPLETED"
    assert saved.change.approval_expires == ws.change.approval_expires
    assert saved.order.fulfillment == "on_hold"
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None
    with pytest.raises(AppError, match="MANUAL_RECONCILIATION"):
        run(integrity.resume(ws.id))


def test_cancelled_capture_leaves_an_explicit_indeterminate_state(integrity, monkeypatch):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))

    async def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(integrity.simulator, "capture", cancelled)
    with pytest.raises(asyncio.CancelledError):
        run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    saved = integrity.store.get(ws.id)
    assert saved.change.state == "indeterminate"
    assert saved.change.refund.status == "COMPLETED"
    assert saved.order.fulfillment == "on_hold"
    with pytest.raises(AppError, match="MANUAL_RECONCILIATION"):
        run(integrity.resume(ws.id))


def test_storage_failure_before_operation_claim_sends_no_refund(integrity, monkeypatch):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))
    calls = []

    def broken_claim(*args):
        raise OSError("Synthetic disk failure")

    async def forbidden(*args):
        calls.append(args)
        raise AssertionError("No dispatch is permitted")

    monkeypatch.setattr(integrity.store, "claim", broken_claim)
    monkeypatch.setattr(integrity.simulator, "refund", forbidden)
    with pytest.raises(OSError):
        run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    assert calls == []


def test_wrong_refund_parent_never_unlocks_capture(integrity, monkeypatch):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))
    read = integrity.simulator.read_refund

    async def mismatch(refund_id):
        result = await read(refund_id)
        result.capture_id = "OTHER-CAPTURE"
        return result

    monkeypatch.setattr(integrity.simulator, "read_refund", mismatch)
    with pytest.raises(AppError, match="REFUND_MISMATCH"):
        run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    assert run(integrity.simulator.read(checkout.order_id)).capture_id is None


def test_persistence_survives_restart_and_cas_rejects_lost_updates(integrity):
    ws = requested(integrity)
    stale_copy = integrity.store.get(ws.id)
    run(integrity.approve(ws.id, ws.change.snapshot_hash))
    with pytest.raises(AppError, match="STATE_CHANGED"):
        integrity.store.save(stale_copy)
    second = Store(integrity.store.path.parent)
    assert second.get(ws.id).change.state == "approved"
    assert second.claim(ws.id, "test-dispatch")
    assert not Store(integrity.store.path.parent).claim(ws.id, "test-dispatch")


def test_model_projection_excludes_identity_addresses_ids_and_oracle(integrity):
    ws = requested(integrity)
    serialized = json.dumps(model_context(ws.change))
    for excluded in (
        ws.id,
        ws.order.payment.order_id,
        "Test Street",
        "Boston",
        "customer_message",
        "expected",
        "route",
        "snapshot_hash",
    ):
        assert excluded not in serialized
    assert len(model_context(ws.change)["facts"]) == 7
    assert run(integrity.analyze(ws.id)).change.advice.source == "unavailable"


class ModelReply:
    def __init__(self, route="replace_order", citation="F3"):
        self.calls = 0
        self.route = route
        self.citation = citation

    async def invoke(self, request):
        self.calls += 1
        plan = Plan(
            route=self.route,
            summary="Review the order change.",
            steps=["Pause fulfillment and review the exact replacement."],
            fact_ids=[self.citation],
            customer_message="The refund and new payment are separate. Bank availability can lag.",
        )
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": plan.model_dump_json()}]}},
        }, "synthetic-request"


def test_ai_recording_replay_is_bound_to_exact_request_and_not_authority(integrity, tmp_path):
    ws = requested(integrity)
    client = ModelReply(route="manual_review")
    analyst = Analyst(integrity.store, tmp_path / "recordings", fresh=True, client=client)
    first = run(analyst.review(ws.change))
    assert first.policy_agrees is False
    assert client.calls == 1
    analyst.fresh = False
    second = run(analyst.review(ws.change))
    assert second.source == "recorded_bedrock"
    assert client.calls == 1
    assert run(integrity.approve(ws.id, ws.change.snapshot_hash)).change.route == "replace_order"
    path = analyst.recordings / (first.request_hash + ".json")
    value = json.loads(path.read_text())
    value["request"]["modelId"] = "different-model"
    path.write_text(json.dumps(value))
    with pytest.raises(AppError, match="AI_RECORDING_INVALID"):
        run(analyst.review(ws.change))


def test_unknown_ai_citations_are_rejected_and_attempts_persist(integrity, tmp_path):
    ws = requested(integrity)
    analyst = Analyst(
        integrity.store,
        tmp_path / "recordings",
        fresh=True,
        client=ModelReply(citation="F999"),
    )
    with pytest.raises(AppError, match="AI_UNAVAILABLE"):
        run(analyst.review(ws.change))
    with integrity.store.connection() as db:
        assert db.execute("SELECT attempts FROM allowances").fetchone()[0] == 1
    assert not list((tmp_path / "recordings").glob("*.json"))


def test_buyer_capability_cannot_be_used_for_merchant_or_another_workspace(integrity, tmp_path):
    app = create_integrity_app(Settings(runtime_dir=tmp_path), integrity=integrity)
    with TestClient(app) as merchant:
        one = merchant.post("/api/integrity/workspaces", json={}).json()
        token = one["buyer_url"].split("/")[-1]
        buyer_headers = {"X-Minimera-Buyer": token}
        assert (
            merchant.post("/api/integrity/buyer/change", headers=buyer_headers, json={}).status_code
            == 200
        )
        assert (
            merchant.post(
                "/api/integrity/approve", headers=buyer_headers, json={"snapshot_hash": "0" * 64}
            ).status_code
            == 403
        )
        assert merchant.post("/api/integrity/analyze").status_code == 403
        assert merchant.post("/api/integrity/resume").status_code == 403
        assert merchant.post("/api/integrity/resume", headers=buyer_headers).status_code == 403
        assert (
            merchant.post(
                "/api/integrity/analyze", headers={"X-Minimera-CSRF": one["csrf"]}
            ).status_code
            == 200
        )
        two = merchant.post("/api/integrity/workspaces", json={}).json()
        assert one["workspace"]["id"] != two["workspace"]["id"]
        assert (
            merchant.get("/api/integrity/buyer", headers=buyer_headers).json()["change"] is not None
        )
        assert merchant.get("/api/integrity/workspace").json()["workspace"]["change"] is None
        assert merchant.get("/api/integrity/evidence", headers=buyer_headers).status_code == 403


def test_recheck_requires_merchant_csrf_and_assistant_reports_current_state(integrity, tmp_path):
    app = create_integrity_app(Settings(runtime_dir=tmp_path), integrity=integrity)
    with TestClient(app) as client:
        created = client.post(
            "/api/integrity/workspaces", json={"scenario": "stale_approval"}
        ).json()
        workspace_id = created["workspace"]["id"]
        buyer_headers = {"X-Minimera-Buyer": created["buyer_url"].split("/")[-1]}
        merchant_headers = {"X-Minimera-CSRF": created["csrf"]}
        client.post("/api/integrity/buyer/change", headers=buyer_headers, json={})
        ws = integrity.store.get(workspace_id)
        run(integrity.approve(ws.id, ws.change.snapshot_hash))
        run(integrity.advance_warehouse(ws.id))
        assert client.post("/api/integrity/recheck", headers=buyer_headers).status_code == 403
        assert client.post("/api/integrity/recheck").status_code == 403
        checked = client.post("/api/integrity/recheck", headers=merchant_headers)
        assert checked.status_code == 200
        assert checked.json()["workspace"]["change"]["state"] == "stale"
        reply = client.post(
            "/api/integrity/assistant", headers=merchant_headers, json={"question": "explain"}
        )
        assert reply.status_code == 200
        assert reply.json()["source"] == "deterministic_workflow_state"
        assert reply.json()["answer"] == checked.json()["workspace"]["change"]["explanation"]


@pytest.mark.parametrize("question", ["explain", "next_step"])
def test_assistant_does_not_request_release_again_after_fulfillment(integrity, tmp_path, question):
    app = create_integrity_app(Settings(runtime_dir=tmp_path), integrity=integrity)
    with TestClient(app) as client:
        created = client.post("/api/integrity/workspaces", json={}).json()
        ws = run(integrity.request_change(created["workspace"]["id"], ChangeRequest()))
        run(integrity.approve(ws.id, ws.change.snapshot_hash))
        checkout = run(integrity.checkout(ws.id, "replacement"))
        run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
        run(integrity.release(ws.id))
        reply = client.post(
            "/api/integrity/assistant",
            headers={"X-Minimera-CSRF": created["csrf"]},
            json={"question": question},
        )
        assert reply.status_code == 200
        assert reply.json()["source"] == "deterministic_workflow_state"
        assert "released to the synthetic warehouse" in reply.json()["answer"]
        assert "Review and release" not in reply.json()["answer"]


def test_checkout_state_is_bound_to_owner_and_errors_do_not_reflect_input(integrity, tmp_path):
    app = create_integrity_app(Settings(runtime_dir=tmp_path), integrity=integrity)
    with TestClient(app) as client:
        created = client.post("/api/integrity/workspaces", json={}).json()
        token = created["buyer_url"].split("/")[-1]
        response = client.post(
            "/api/integrity/buyer/change",
            headers={"X-Minimera-Buyer": token},
            json={"destination": "PASTED-SECRET"},
        )
        assert response.status_code == 422
        assert "PASTED-SECRET" not in response.text
        assert (
            client.post(
                "/api/integrity/workspaces", headers={"Origin": "https://other.invalid"}, json={}
            ).status_code
            == 403
        )
        assert client.post("/api/integrity/workspaces", content=b"x" * 4097).status_code == 413
        assert client.get("/api/integrity/workspace").headers["cache-control"] == "no-store"
    other = run(integrity.create(NewWorkspace()))
    with pytest.raises(AppError, match="CHECKOUT_REFUSED"):
        run(
            integrity.complete_checkout(
                other.id, CompleteCheckout(checkout_id="unowned", state="x" * 24)
            )
        )


def test_signed_sessions_expire_reject_wrong_role_and_are_owner_private(tmp_path, monkeypatch):
    auth = Sessions(tmp_path)
    token = auth.token("a" * 32, "buyer")
    assert auth.verify(token, "buyer") == "a" * 32
    with pytest.raises(AppError, match="SESSION_REQUIRED"):
        auth.verify(token, "merchant")
    with pytest.raises(AppError):
        auth.verify(token + "changed", "buyer")
    monkeypatch.setattr("ntk.integrity.auth.time.time", lambda: 9999999999)
    with pytest.raises(AppError):
        auth.verify(token, "buyer")
    assert (tmp_path / "session.key").stat().st_mode & 0o077 == 0


def paypal_order():
    return {
        "id": "ORDER00000001",
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": "minimera-order-integrity-v1",
                "custom_id": "opaque-version",
                "amount": {"currency_code": "USD", "value": "1.00"},
                "payee": {"merchant_id": "MERCHANT00001"},
                "shipping": {"address": DESTINATIONS["home"]},
                "payments": {
                    "captures": [
                        {
                            "id": "CAPTURE000001",
                            "status": "COMPLETED",
                            "amount": {"currency_code": "USD", "value": "1.00"},
                            "seller_protection": {"status": "ELIGIBLE"},
                        }
                    ]
                },
            }
        ],
    }


def test_sandbox_read_independently_checks_capture_parent_and_amount():
    def transport(request):
        assert request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "SYNTHETIC-TOKEN"})
        if request.url.path.startswith("/v2/checkout/orders/"):
            return httpx.Response(200, json=paypal_order())
        return httpx.Response(
            200,
            json={
                "id": "CAPTURE000001",
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "1.00"},
                "supplementary_data": {"related_ids": {"order_id": "DIFFERENTORDER"}},
            },
        )

    gateway = Sandbox(
        PayPalSettings(client_id="synthetic-id", client_secret="synthetic-secret"),
        transport=httpx.MockTransport(transport),
    )
    with pytest.raises(AppError, match="PAYPAL_READBACK_MISMATCH"):
        run(gateway.read("ORDER00000001"))
    with pytest.raises(AppError, match="INVALID_PAYMENT_ID"):
        run(gateway.read("https://other.invalid/steal"))


@pytest.mark.parametrize(
    "parent,accepted",
    [
        ("https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001", True),
        ("https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE000001", True),
        ("https://api.paypal.com/v2/payments/captures/CAPTURE000001", False),
        ("https://api.sandbox.paypal.com.evil.invalid/v2/payments/captures/CAPTURE000001", False),
        ("https://api.sandbox.paypal.com@evil.invalid/v2/payments/captures/CAPTURE000001", False),
        ("https://evil.invalid@api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001", False),
        ("http://api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001", False),
        ("https://api.sandbox.paypal.com:443/v2/payments/captures/CAPTURE000001", False),
        ("https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001?extra=1", False),
        ("https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001#extra", False),
        ("https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE000001/refund", False),
        ("https://api.sandbox.paypal.com/v2/payments/captures/%43APTURE000001", False),
    ],
)
def test_refund_parent_supports_observed_sandbox_alias_without_following_links(parent, accepted):
    requests = []

    def transport(request):
        requests.append((request.method, str(request.url)))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "SYNTHETIC-TOKEN"})
        return httpx.Response(
            200,
            json={
                "id": "REFUND000001",
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "1.00"},
                "links": [{"rel": "up", "href": parent}],
            },
        )

    gateway = Sandbox(
        PayPalSettings(client_id="synthetic-id", client_secret="synthetic-secret"),
        transport=httpx.MockTransport(transport),
    )
    if accepted:
        result = run(gateway.read_refund("REFUND000001"))
        assert result.capture_id == "CAPTURE000001"
        assert result.cents == 100
        assert result.status == "COMPLETED"
    else:
        with pytest.raises(AppError, match="REFUND_READBACK_MISMATCH"):
            run(gateway.read_refund("REFUND000001"))
    assert requests == [
        ("POST", "https://api-m.sandbox.paypal.com/v1/oauth2/token"),
        ("GET", "https://api-m.sandbox.paypal.com/v2/payments/refunds/REFUND000001"),
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda order: order["purchase_units"][0].update(reference_id="legacy-dispute-order"),
        lambda order: order["purchase_units"][0]["amount"].update(currency_code="EUR"),
        lambda order: order["purchase_units"][0]["shipping"]["address"].update(postal_code="OTHER"),
        lambda order: order["purchase_units"][0]["payments"]["captures"].append(
            deepcopy(order["purchase_units"][0]["payments"]["captures"][0])
        ),
    ],
)
def test_sandbox_normalization_rejects_wrong_resources(mutate):
    order = deepcopy(paypal_order())
    mutate(order)
    with pytest.raises(ValueError):
        normalize_order(order)


def test_event_evidence_chain_is_recomputable_and_contains_no_buyer_token(integrity):
    ws = requested(integrity)
    evidence = integrity.evidence(ws)
    previous = "0" * 64
    for event in evidence["events"]:
        body = {k: v for k, v in event.items() if k != "hash"}
        assert body["previous_hash"] == previous
        assert fingerprint(body) == event["hash"]
        previous = event["hash"]
    assert evidence["hardware_verified"] is False
    assert "checkouts" not in evidence
    assert "buyer_url" not in json.dumps(evidence)


def test_warehouse_manifest_tampering_blocks_release(integrity):
    ws = approved(integrity)
    checkout = run(integrity.checkout(ws.id, "replacement"))
    ws = run(integrity.complete_checkout(ws.id, checkout_request(checkout)))
    ws.fulfillment_order.destination = "home"
    integrity.store.save(ws)
    with pytest.raises(AppError, match="FULFILLMENT_MISMATCH"):
        run(integrity.release(ws.id))
    assert integrity.store.get(ws.id).fulfillment_order.fulfillment == "ready"


def test_sandbox_adapter_contract_flow_uses_fixed_origin_and_distinct_write_keys(tmp_path):
    """A mocked HTTP contract test, explicitly not evidence of a live Sandbox run."""
    orders = {}
    refunds = {}
    captures = {}
    writes = []

    def transport(request):
        assert request.url.host == "api-m.sandbox.paypal.com"
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "SYNTHETIC-TOKEN"})
        assert request.headers["authorization"] == "Bearer SYNTHETIC-TOKEN"
        if request.method == "POST":
            writes.append((path, request.headers["paypal-request-id"]))
        if path == "/v2/checkout/orders":
            value = json.loads(request.content)
            assert value["intent"] == "CAPTURE"
            assert (
                value["payment_source"]["paypal"]["experience_context"]["shipping_preference"]
                == "SET_PROVIDED_ADDRESS"
            )
            order_id = f"ORDER{len(orders) + 1:012d}"
            value.update(id=order_id, status="CREATED")
            value["purchase_units"][0]["payee"] = {"merchant_id": "TESTMERCHANT"}
            value["links"] = [
                {
                    "rel": "payer-action",
                    "href": "https://www.sandbox.paypal.com/checkoutnow?token=" + order_id,
                }
            ]
            orders[order_id] = value
            return httpx.Response(201, json=value)
        if path.startswith("/v2/checkout/orders/"):
            order_id = path.split("/")[4]
            value = orders[order_id]
            if path.endswith("/capture"):
                assert value["status"] == "APPROVED"
                capture_id = f"CAPTURE{len(captures) + 1:010d}"
                capture = {
                    "id": capture_id,
                    "status": "COMPLETED",
                    "amount": deepcopy(value["purchase_units"][0]["amount"]),
                    "supplementary_data": {"related_ids": {"order_id": order_id}},
                }
                value["status"] = "COMPLETED"
                value["purchase_units"][0]["payments"] = {"captures": [capture]}
                captures[capture_id] = capture
            return httpx.Response(200, json=value)
        if path.startswith("/v2/payments/captures/"):
            capture_id = path.split("/")[4]
            if path.endswith("/refund"):
                assert captures[capture_id]["status"] == "COMPLETED"
                result = {
                    "id": "REFUND00000000001",
                    "status": "COMPLETED",
                    "amount": json.loads(request.content)["amount"],
                    "links": [
                        {
                            "rel": "up",
                            "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/"
                            + capture_id,
                        }
                    ],
                }
                refunds[result["id"]] = result
                captures[capture_id]["status"] = "REFUNDED"
                return httpx.Response(201, json=result)
            return httpx.Response(200, json=captures[capture_id])
        if path.startswith("/v2/payments/refunds/"):
            return httpx.Response(200, json=refunds[path.split("/")[-1]])
        raise AssertionError("Unexpected provider endpoint")

    store = Store(tmp_path / "contract")
    gateway = Sandbox(
        PayPalSettings(client_id="synthetic-id", client_secret="synthetic-secret"),
        transport=httpx.MockTransport(transport),
    )
    service = IntegrityService(store, Analyst(store, tmp_path / "recordings"), sandbox=gateway)
    ws = run(service.create(NewWorkspace(mode="sandbox")))
    original = run(service.checkout(ws.id, "original"))
    with pytest.raises(AppError, match="BUYER_APPROVAL_REQUIRED"):
        run(service.complete_checkout(ws.id, checkout_request(original)))
    orders[original.order_id]["status"] = "APPROVED"
    ws = run(service.complete_checkout(ws.id, checkout_request(original)))
    ws = run(service.request_change(ws.id, ChangeRequest()))
    ws = run(service.approve(ws.id, ws.change.snapshot_hash))
    replacement = run(service.checkout(ws.id, "replacement"))
    orders[replacement.order_id]["status"] = "APPROVED"
    ws = run(service.complete_checkout(ws.id, checkout_request(replacement)))
    assert ws.change.state == "complete"
    assert ws.change.replacement.source == "paypal_sandbox"
    assert ws.change.replacement.cents == 70
    assert ws.change.refund.cents == 100
    assert run(service.release(ws.id)).fulfillment_order.destination == "office"
    assert len(writes) == 5  # Two creates, two captures, one refund.
    assert len({key for _, key in writes}) == 5


def test_checked_in_bedrock_records_match_their_exact_requests():
    from ntk.dataset import ROOT
    from ntk.integrity.contracts import Advice

    directory = ROOT / "reports/order-integrity-v1"
    summary = json.loads((directory / "model-fixtures.json").read_text())
    assert summary["independent_evaluation"] is False
    for fixture in summary["fixtures"]:
        path = directory / "recordings" / (fixture["request_hash"] + ".json")
        value = json.loads(path.read_text())
        assert fingerprint(value["request"]) == fixture["request_hash"]
        advice = Advice.model_validate(value["advice"])
        assert advice.source == "bedrock"
        assert advice.plan.route == fixture["expected_route"]
        assert set(advice.plan.fact_ids) <= {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
        assert "reasoningContent" not in json.dumps(value)


def test_setup_rejects_field_injection_and_saves_owner_private_values(tmp_path):
    from ntk.integrity.setup import credential_values, save_credentials
    from ntk.paypal import KEYS
    from ntk.secrets import read_private_env

    for body in (
        b"client_id=VALID1234&client_secret=VALID1234%0AINJECTED%3Dyes",
        b"client_id=VALID1234&client_secret=VALID1234&extra=value",
        b"client_id=VALID1234&client_id=SECOND123&client_secret=VALID1234",
    ):
        with pytest.raises(ValueError):
            credential_values(body)
    values = credential_values(b"client_id=TESTCLIENT123&client_secret=TESTSECRET123")
    path = tmp_path / "private/paypal-sandbox.env"
    save_credentials(path, *values)
    assert read_private_env(path, frozenset(KEYS)) == dict(zip(KEYS, values, strict=True))
    assert path.stat().st_mode & 0o077 == 0
    assert not list(path.parent.glob(".*"))


def test_session_key_rejects_pipes_and_oversized_files_before_reading(tmp_path):
    import os

    key = tmp_path / "session.key"
    os.mkfifo(key, 0o600)
    with pytest.raises(ValueError, match="owner-only regular file"):
        Sessions(tmp_path)
    key.unlink()
    key.write_bytes(b"x" * 1024)
    key.chmod(0o600)
    with pytest.raises(ValueError, match="owner-only regular file"):
        Sessions(tmp_path)
