"""Explicit, non-atomic replacement workflow. AI explains; policy authorizes."""

import asyncio
import secrets
import time
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import uuid4

from ..contracts import AppError
from .contracts import (
    Change,
    ChangeRequest,
    Checkout,
    CompleteCheckout,
    NewWorkspace,
    Order,
    Payment,
    Refund,
    Workspace,
)
from .model import Reviewer
from .payments import Gateway, Simulator
from .policy import (
    append_event,
    decide,
    facts,
    fingerprint,
    now,
    payment_binding,
    refund_binding,
    refund_matches_payment,
    seed_items,
    snapshot,
)
from .store import Store


class IntegrityService:
    def __init__(
        self,
        store: Store,
        analyst: Reviewer,
        *,
        sandbox: Gateway | None = None,
        origin: str = "http://127.0.0.1:8766",
        sandbox_limit: int = 8,
    ) -> None:
        self.store = store
        self.analyst = analyst
        self.sandbox = sandbox
        self.simulator = Simulator(store)
        self.origin = origin.rstrip("/")
        self.sandbox_limit = sandbox_limit
        self._locks: dict[str, asyncio.Lock] = {}

    def gateway(self, ws: Workspace) -> Gateway:
        if ws.mode == "sandbox":
            if self.sandbox is None:
                raise AppError(
                    "SANDBOX_DISABLED", "Sandbox writes are disabled for this local server.", 409
                )
            return self.sandbox
        return self.simulator

    def lock(self, workspace_id: str) -> asyncio.Lock:
        if workspace_id not in self._locks and len(self._locks) >= 200:
            raise AppError(
                "WORKSPACE_LIMIT", "Restart the local demo after reviewing its evidence.", 429
            )
        return self._locks.setdefault(workspace_id, asyncio.Lock())

    async def create(self, request: NewWorkspace) -> Workspace:
        if request.mode == "sandbox":
            if self.sandbox is None or request.scenario != "address_change":
                raise AppError(
                    "SANDBOX_DISABLED",
                    "Use simulation for negative scenarios; enable Sandbox explicitly for a real test payment.",
                    409,
                )
            self.store.reserve("sandbox_workspaces", self.sandbox_limit)
        ws = Workspace(
            id=uuid4().hex,
            mode=request.mode,
            scenario=request.scenario,
            order=Order(items=seed_items(request.mode)),
            created_at=now(),
        )
        self.store.create(ws)
        if ws.mode == "simulation":
            payment, _ = await self.simulator.create(
                ws.id + ":seed", ws.order.cents, "home", ws.id + ":original", "", ""
            )
            await self.simulator.approve_simulation(payment.order_id)
            await self.simulator.capture(payment.order_id, ws.id + ":seed:capture")
            ws.order.payment = await self.simulator.read(payment.order_id)
            if ws.scenario == "already_shipped":
                ws.order.fulfillment = "shipped"
        append_event(
            ws,
            "system",
            "workspace_created",
            "Synthetic merchant order created. Payment source: " + ws.mode + ".",
        )
        self.store.save(ws)
        return ws

    async def request_change(self, workspace_id: str, request: ChangeRequest) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            if ws.change is not None:
                raise AppError(
                    "CHANGE_EXISTS",
                    "This demo already has a change request. Start another scenario to try a different request.",
                    409,
                )
            if ws.order.payment:
                ws.order.payment = await self._read_bound(ws, ws.order.payment)
            items = [
                item.model_copy()
                for item in ws.order.items
                if not (request.remove_pouch and item.sku == "POUCH")
            ]
            route, explanation = decide(ws.order, request.destination, items)
            source_facts = facts(ws.order, request.destination, items)
            if route == "replace_order":
                ws.order.fulfillment = "on_hold"
                ws.order.revision += 1
            change = Change(
                id=uuid4().hex,
                destination=request.destination,
                remove_pouch=request.remove_pouch,
                items=items,
                route=route,
                state="review" if route == "replace_order" else "blocked",
                facts=source_facts,
                snapshot_hash="",
                explanation=explanation,
                created_at=now(),
            )
            change.snapshot_hash = snapshot(ws.order, change)
            ws.change = change
            append_event(
                ws,
                "buyer",
                "change_requested",
                "Requested a destination change and/or item removal. No payment mutation authorized.",
            )
            if route == "replace_order":
                append_event(
                    ws,
                    "policy",
                    "fulfillment_held",
                    "The merchant fulfillment simulator is paused while the payment plan is reviewed.",
                )
            self.store.save(ws)
            return ws

    async def analyze(self, workspace_id: str) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            change = self.get_change(ws)
            if change.advice and change.advice.plan is not None:
                return ws
            advice = await self.analyst.review(change)
            change.advice = advice
            append_event(
                ws,
                "analyst",
                "context_reviewed",
                "Minimized context reviewed. Source: "
                + advice.source
                + ". Payment execution remains controlled by deterministic checks.",
            )
            self.store.save(ws)
            return ws

    async def recheck(self, workspace_id: str) -> Workspace:
        """Check the saved review/approval again, without renewing or executing it."""
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            change = self.get_change(ws)
            if change.state == "stale":
                return ws
            if change.state not in ("review", "approved", "awaiting_buyer"):
                raise AppError(
                    "NOT_RECHECKABLE", "Inspect the payment evidence for this workflow state.", 409
                )
            if ws.order.payment:
                ws.order.payment = await self._read_bound(ws, ws.order.payment)
            current = (
                snapshot(ws.order, change) == change.snapshot_hash
                if change.state == "review"
                else self._approval_current(ws)
            )
            if not current:
                return self._stale(ws)
            append_event(
                ws,
                "policy",
                "approval_rechecked",
                "The saved order snapshot still matches. No payment operation was sent and approval expiry was not extended.",
            )
            self.store.save(ws)
            return ws

    async def approve(self, workspace_id: str, supplied_hash: str) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            change = self.get_change(ws)
            if change.state != "review" or change.route != "replace_order":
                raise AppError(
                    "NOT_APPROVABLE", "This request is not awaiting merchant approval.", 409
                )
            if ws.order.payment:
                ws.order.payment = await self._read_bound(ws, ws.order.payment)
            if supplied_hash != change.snapshot_hash or snapshot(ws.order, change) != supplied_hash:
                return self._stale(ws)
            route, _ = decide(ws.order, change.destination, change.items)
            if route != "replace_order" or ws.order.fulfillment != "on_hold":
                return self._stale(ws)
            change.approved_hash = supplied_hash
            change.approval_expires = int(time.time()) + 1800
            change.state = "approved"
            append_event(
                ws,
                "merchant",
                "plan_approved",
                "Approved this exact order version, replacement amount and destination. Valid for 30 minutes; buyer approval is still required.",
            )
            self.store.save(ws)
            return ws

    def _stale(self, ws: Workspace) -> Workspace:
        change = self.get_change(ws)
        change.state = "stale"
        change.explanation = "The order or payment changed after review. This approval is invalid; no new payment operation was sent."
        append_event(ws, "policy", "approval_invalidated", change.explanation)
        self.store.save(ws)
        return ws

    def _approval_current(self, ws: Workspace) -> bool:
        change = self.get_change(ws)
        return (
            change.approved_hash == snapshot(ws.order, change)
            and change.approval_expires is not None
            and change.approval_expires > time.time()
            and ws.order.fulfillment == "on_hold"
        )

    async def checkout(
        self, workspace_id: str, purpose: Literal["original", "replacement"]
    ) -> Checkout:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            for previous in ws.checkouts:
                if previous.purpose == purpose:
                    if not previous.approval_url:
                        raise AppError(
                            "CHECKOUT_UNCONFIRMED",
                            "Checkout creation has an unknown result. Inspect PayPal before creating another order.",
                            409,
                        )
                    return previous
            if purpose == "original":
                if ws.order.payment is not None:
                    raise AppError(
                        "ALREADY_PAID", "The original payment has already been verified.", 409
                    )
                cents, destination = ws.order.cents, ws.order.destination
            else:
                change = self.get_change(ws)
                if change.state != "approved" or ws.order.payment is None:
                    raise AppError(
                        "APPROVAL_REQUIRED", "A current merchant approval is required.", 409
                    )
                ws.order.payment = await self._read_bound(ws, ws.order.payment)
                if not self._approval_current(ws):
                    self._stale(ws)
                    raise AppError(
                        "STALE_APPROVAL",
                        "The approval is no longer current. No replacement order was created.",
                        409,
                    )
                cents, destination = change.cents, change.destination
            checkout = Checkout(
                id=uuid4().hex,
                purpose=purpose,
                order_id="",
                state=secrets.token_urlsafe(24),
                approval_url="",
                custom_id=ws.id + ":" + purpose,
                cents=cents,
                destination=destination,
                merchant_id="",
            )
            ws.checkouts.append(checkout)
            append_event(
                ws, "buyer", "checkout_requested", purpose.title() + " PayPal checkout requested."
            )
            self.store.save(ws)
            if not self.store.claim(ws.id, purpose + ":create"):
                raise AppError(
                    "OPERATION_UNCONFIRMED",
                    "This operation was already dispatched. Check its result before proceeding.",
                    409,
                )
            query = urlencode({"checkout": checkout.id, "state": checkout.state})
            return_url = self.origin + "/return?" + query
            cancel_url = self.origin + "/return?" + query + "&cancelled=1"
            payment, approval = await self.gateway(ws).create(
                ws.id + ":" + purpose + ":create",
                cents,
                destination,
                checkout.custom_id,
                return_url,
                cancel_url,
            )
            checkout.order_id = payment.order_id
            checkout.approval_url = approval
            checkout.merchant_id = payment.merchant_id
            if (
                payment.cents != cents
                or payment.destination != destination
                or payment.custom_id != checkout.custom_id
            ):
                raise AppError(
                    "CHECKOUT_MISMATCH", "The created order differs from the approved plan.", 409
                )
            if ws.change and purpose == "replacement":
                ws.change.replacement = payment
                ws.change.state = "awaiting_buyer"
            self.store.save(ws)
            self.store.finish(ws.id, purpose + ":create")
            return checkout

    async def complete_checkout(self, workspace_id: str, request: CompleteCheckout) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            checkout = next((c for c in ws.checkouts if c.id == request.checkout_id), None)
            if checkout is None or not secrets.compare_digest(checkout.state, request.state):
                raise AppError(
                    "CHECKOUT_REFUSED", "This checkout does not belong to the current order.", 403
                )
            if checkout.completed:
                return ws
            if not checkout.order_id:
                raise AppError(
                    "CHECKOUT_UNCONFIRMED", "Checkout creation has not been confirmed.", 409
                )
            gateway = self.gateway(ws)
            if ws.mode == "simulation":
                await self.simulator.approve_simulation(checkout.order_id)
            payment = await gateway.read(checkout.order_id)
            self._check_checkout(checkout, payment)
            if payment.status != "APPROVED":
                raise AppError(
                    "BUYER_APPROVAL_REQUIRED",
                    "PayPal has not confirmed buyer approval for this order.",
                    409,
                )
            if checkout.purpose == "original":
                ws.order.payment = await self._capture(ws, checkout, payment)
                checkout.completed = True
                append_event(
                    ws,
                    "paypal",
                    "original_payment_verified",
                    "Original capture independently read back and verified.",
                )
                self.store.save(ws)
                return ws
            change = self.get_change(ws)
            if ws.order.payment is None:
                raise AppError(
                    "ORIGINAL_PAYMENT_MISSING", "The original payment is unavailable.", 409
                )
            ws.order.payment = await self._read_bound(ws, ws.order.payment)
            if change.state != "awaiting_buyer" or not self._approval_current(ws):
                return self._stale(ws)
            change.replacement = payment
            change.state = "processing"
            append_event(
                ws,
                "buyer",
                "replacement_approved",
                "Buyer approved the exact replacement order in "
                + ws.mode
                + ". This is approval, not a completed charge.",
            )
            self.store.save(ws)
            return await self._execute(ws, checkout)

    async def _execute(self, ws: Workspace, checkout: Checkout) -> Workspace:
        change = self.get_change(ws)
        gateway = self.gateway(ws)
        original = ws.order.payment
        if original is None or original.capture_id is None:
            raise AppError(
                "ORIGINAL_PAYMENT_MISSING", "A linked original capture is required.", 409
            )
        try:
            if change.refund is None:
                if not self.store.claim(ws.id, change.id + ":refund"):
                    raise AppError(
                        "REFUND_UNCONFIRMED",
                        "A refund was already dispatched. Its result must be reconciled before continuing.",
                        409,
                    )
                refund_id = await gateway.refund(
                    original.capture_id, original.cents, ws.id + ":" + change.id + ":refund"
                )
                # Persist the returned identity before the independent GET.
                change.refund = Refund(
                    refund_id=refund_id,
                    capture_id=original.capture_id,
                    status="UNVERIFIED",
                    cents=original.cents,
                    verified_at=now(),
                    source=original.source,
                )
                self.store.save(ws)
            observed_refund = await gateway.read_refund(change.refund.refund_id)
            if refund_binding(observed_refund) != refund_binding(
                change.refund
            ) or not refund_matches_payment(observed_refund, original):
                raise AppError(
                    "REFUND_MISMATCH",
                    "The observed refund differs from the approved original capture.",
                    409,
                )
            change.refund = observed_refund
            if observed_refund.status != "COMPLETED":
                change.state = "pending"
                change.explanation = "The original refund is not completed. The replacement has not been captured; fulfillment remains paused."
                append_event(
                    ws,
                    "paypal",
                    "refund_pending",
                    "Refund state: " + observed_refund.status + ". Replacement capture withheld.",
                )
                self.store.save(ws)
                return ws
            self.store.finish(ws.id, change.id + ":refund")
            append_event(
                ws,
                "paypal",
                "refund_verified",
                "Original full refund independently read back as COMPLETED.",
            )
            self.store.save(ws)
            payment = await gateway.read(checkout.order_id)
            self._check_checkout(checkout, payment)
            if payment.capture_status != "COMPLETED":
                if not self._approval_current(ws):
                    raise AppError(
                        "APPROVAL_EXPIRED",
                        "The approval expired while payments were pending. The original refund may have completed; the replacement remains held for manual review.",
                        409,
                    )
                payment = await self._capture(ws, checkout, payment)
            self._check_checkout(checkout, payment)
            if payment.capture_status != "COMPLETED":
                raise AppError(
                    "CAPTURE_NOT_COMPLETED",
                    "Replacement capture is not completed. Fulfillment remains paused.",
                    409,
                )
            # A final refund observation prevents success based on two POST responses.
            confirmed_refund = await gateway.read_refund(observed_refund.refund_id)
            if (
                confirmed_refund.status != "COMPLETED"
                or refund_binding(confirmed_refund) != refund_binding(observed_refund)
                or not refund_matches_payment(confirmed_refund, original)
            ):
                raise AppError(
                    "REFUND_CHANGED",
                    "Refund verification changed. Fulfillment remains paused.",
                    409,
                )
            change.refund = confirmed_refund
            change.replacement = payment
            change.state = "complete"
            change.explanation = "Original refund and replacement capture verified separately. The corrected order is ready for merchant fulfillment review."
            checkout.completed = True
            ws.order.payment = await self._read_bound(ws, original)
            ws.order.revision += 1
            ws.order.fulfillment = "replaced"
            ws.fulfillment_order = Order(
                id=ws.order.id + "-R1",
                items=[i.model_copy() for i in change.items],
                destination=change.destination,
                fulfillment="ready",
                payment=payment,
            )
            append_event(
                ws,
                "paypal",
                "replacement_verified",
                "Replacement capture, amount, merchant and destination verified against the approved checkout.",
            )
            append_event(
                ws,
                "policy",
                "ready_for_fulfillment",
                "Payment checks passed. The merchant may release the corrected order in the fulfillment simulator.",
            )
            self.store.save(ws)
            return ws
        except (Exception, asyncio.CancelledError):
            change.state = "indeterminate"
            change.explanation = "The payment sequence did not reach a fully verified outcome. Fulfillment remains paused. Inspect the known payment and refund IDs before retrying."
            append_event(
                ws,
                "policy",
                "execution_paused",
                "No success assumed after an interrupted, failed or unverified payment operation.",
            )
            self.store.save(ws)
            raise

    async def resume(self, workspace_id: str) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            change = self.get_change(ws)
            known_unverified = (
                change.state == "indeterminate"
                and change.refund is not None
                and change.refund.status == "UNVERIFIED"
            )
            if change.refund is None or (change.state != "pending" and not known_unverified):
                raise AppError(
                    "MANUAL_RECONCILIATION",
                    "Only a known pending or unverified refund can be checked. Unknown dispatch outcomes require manual reconciliation.",
                    409,
                )
            if ws.order.fulfillment != "on_hold":
                return self._stale(ws)
            if ws.order.payment is None:
                raise AppError(
                    "ORIGINAL_PAYMENT_MISSING", "The original payment is unavailable.", 409
                )
            # Verify current ownership and resource linkage without replacing
            # the pre-refund snapshot or extending its approval expiry.
            await self._read_bound(ws, ws.order.payment)
            checkout = next(c for c in ws.checkouts if c.purpose == "replacement")
            append_event(
                ws,
                "merchant",
                "refund_check_requested",
                "Requested verification of the known refund ID and continuation of the approved plan. No refund is resent and approval expiry is unchanged.",
            )
            change.state = "processing"
            self.store.save(ws)
            return await self._execute(ws, checkout)

    async def release(self, workspace_id: str) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            change = self.get_change(ws)
            if change.state != "complete" or change.replacement is None or change.refund is None:
                raise AppError(
                    "NOT_READY",
                    "Both payment legs must be verified before fulfillment release.",
                    409,
                )
            if ws.fulfillment_order is None or ws.fulfillment_order.fulfillment != "ready":
                raise AppError("NOT_READY", "The corrected order is not awaiting release.", 409)
            if (
                ws.fulfillment_order.id != ws.order.id + "-R1"
                or ws.fulfillment_order.destination != change.destination
                or ws.fulfillment_order.items != change.items
                or payment_binding(ws.fulfillment_order.payment)
                != payment_binding(change.replacement)
            ):
                raise AppError(
                    "FULFILLMENT_MISMATCH",
                    "The warehouse order differs from the approved correction. Release is blocked.",
                    409,
                )
            gateway = self.gateway(ws)
            latest = await self._read_bound(ws, change.replacement)
            refund = await gateway.read_refund(change.refund.refund_id)
            if (
                latest.capture_status != "COMPLETED"
                or refund.status != "COMPLETED"
                or refund_binding(refund) != refund_binding(change.refund)
            ):
                raise AppError(
                    "PAYMENT_CHANGED",
                    "A payment state changed. Fulfillment release is blocked.",
                    409,
                )
            change.replacement = latest
            change.refund = refund
            ws.fulfillment_order.payment = latest
            ws.fulfillment_order.fulfillment = "released"
            ws.fulfillment_order.revision += 1
            change.explanation = "The corrected destination and items have been released to the synthetic warehouse queue after another payment check. No real goods are shipped by this demo."
            append_event(
                ws,
                "merchant",
                "fulfillment_released",
                "Corrected destination and items released to the synthetic warehouse queue. No real goods are shipped by this demo.",
            )
            self.store.save(ws)
            return ws

    async def advance_warehouse(self, workspace_id: str) -> Workspace:
        async with self.lock(workspace_id):
            ws = self.store.get(workspace_id)
            if ws.mode != "simulation" or ws.scenario != "stale_approval":
                raise AppError(
                    "SCENARIO_ONLY",
                    "This control is available only in the stale-approval simulation.",
                    409,
                )
            ws.order.fulfillment = "shipped"
            ws.order.revision += 1
            append_event(
                ws,
                "warehouse",
                "external_state_changed",
                "Simulated an external warehouse shipment after the review snapshot.",
            )
            self.store.save(ws)
            return ws

    async def _capture(self, ws: Workspace, checkout: Checkout, payment: Payment) -> Payment:
        self._check_checkout(checkout, payment)
        if payment.status != "APPROVED":
            raise AppError("NOT_APPROVED", "The replacement must be approved before capture.", 409)
        operation = checkout.purpose + ":capture"
        if not self.store.claim(ws.id, operation):
            raise AppError(
                "CAPTURE_UNCONFIRMED",
                "Capture was already dispatched. Inspect PayPal before another attempt.",
                409,
            )
        await self.gateway(ws).capture(payment.order_id, ws.id + ":" + operation)
        verified = await self.gateway(ws).read(payment.order_id)
        self._check_checkout(checkout, verified)
        if (
            verified.status != "COMPLETED"
            or verified.capture_status != "COMPLETED"
            or not verified.capture_id
        ):
            raise AppError(
                "CAPTURE_UNCONFIRMED",
                "A completed capture has not been independently verified.",
                409,
            )
        self.store.finish(ws.id, operation)
        return verified

    async def _read_bound(self, ws: Workspace, expected: Payment) -> Payment:
        result = await self.gateway(ws).read(expected.order_id)
        bound = (
            "order_id",
            "cents",
            "currency",
            "destination",
            "custom_id",
            "merchant_id",
            "capture_id",
            "source",
        )
        if any(getattr(result, k) != getattr(expected, k) for k in bound):
            raise AppError(
                "PAYMENT_BINDING_MISMATCH",
                "The observed payment no longer matches this merchant order.",
                409,
            )
        return result

    @staticmethod
    def _check_checkout(checkout: Checkout, payment: Payment) -> None:
        if (
            payment.order_id != checkout.order_id
            or payment.cents != checkout.cents
            or payment.destination != checkout.destination
            or payment.custom_id != checkout.custom_id
            or payment.merchant_id != checkout.merchant_id
        ):
            raise AppError(
                "CHECKOUT_MISMATCH",
                "PayPal state differs from the approved amount, merchant or destination.",
                409,
            )

    @staticmethod
    def get_change(ws: Workspace) -> Change:
        if ws.change is None:
            raise AppError("NO_CHANGE", "Create a customer change request first.", 409)
        return ws.change

    def evidence(self, ws: Workspace) -> dict[str, Any]:
        """Selected, normalized evidence only; no raw provider profiles or buyer tokens."""
        return {
            "schema": "minimera-order-integrity-evidence/1.0.0",
            "mode": ws.mode,
            "merchant_system": "synthetic_oms",
            "hardware_verified": False,
            "workspace": ws.id,
            "order": ws.order.model_dump(),
            "fulfillment_order": ws.fulfillment_order.model_dump()
            if ws.fulfillment_order
            else None,
            "change": ws.change.model_dump() if ws.change else None,
            "events": [e.model_dump() for e in ws.events],
            "event_chain_hash": ws.events[-1].hash if ws.events else fingerprint([]),
            "integrity_scope": "Local hash chain detects accidental edits when compared with an independently retained hash; not an external attestation or immutable ledger.",
            "seller_protection": "PayPal determines eligibility. This workflow does not guarantee coverage.",
        }
