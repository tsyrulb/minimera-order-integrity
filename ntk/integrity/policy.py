"""Pure order-change policy and the deliberately small model projection."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    Change,
    Destination,
    Fact,
    Item,
    Mode,
    Order,
    Payment,
    Refund,
    Route,
    Workspace,
)

POLICY_VERSION = "order-integrity/1.0.0"
DESTINATIONS: dict[str, dict[str, str]] = {
    "home": {
        "address_line_1": "123 Test Street",
        "admin_area_2": "New York",
        "admin_area_1": "NY",
        "postal_code": "10001",
        "country_code": "US",
    },
    "office": {
        "address_line_1": "456 Demo Avenue",
        "admin_area_2": "Boston",
        "admin_area_1": "MA",
        "postal_code": "02108",
        "country_code": "US",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def price(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def seed_items(mode: Mode) -> list[Item]:
    return [
        Item(sku="TOTE", name="Weekender tote", cents=70 if mode == "sandbox" else 8400),
        Item(sku="POUCH", name="Travel pouch", cents=30 if mode == "sandbox" else 3600),
    ]


def payment_binding(payment: Payment | None) -> dict[str, Any] | None:
    if payment is None:
        return None
    return payment.model_dump(exclude={"verified_at"})


def refund_binding(refund: Refund) -> dict[str, Any]:
    """Resource identity and financial scope; status is checked separately."""
    return refund.model_dump(exclude={"status", "verified_at"})


def refund_matches_payment(refund: Refund, original: Payment) -> bool:
    return (
        refund.capture_id == original.capture_id
        and refund.cents == original.cents
        and refund.currency == original.currency
        and refund.source == original.source
    )


def snapshot(order: Order, change: Change) -> str:
    """Bind approval to business state, not observation timestamps or AI wording."""
    return fingerprint(
        {
            "policy": POLICY_VERSION,
            "revision": order.revision,
            "items": [item.model_dump() for item in order.items],
            "destination": order.destination,
            "fulfillment": order.fulfillment,
            "payment": payment_binding(order.payment),
            "change_id": change.id,
            "new_destination": change.destination,
            "new_items": [item.model_dump() for item in change.items],
        }
    )


def decide(order: Order, destination: Destination, items: list[Item]) -> tuple[Route, str]:
    if order.fulfillment in ("shipped", "released"):
        return (
            "manual_review",
            "The warehouse has already shipped this order. Automatic changes are blocked.",
        )
    if order.payment is None or order.payment.capture_status != "COMPLETED":
        return (
            "manual_review",
            "A completed, verified original payment is required before a paid-order change.",
        )
    if destination == order.destination and items == order.items:
        return (
            "no_change",
            "The request leaves the paid order unchanged. No payment operation is needed.",
        )
    return "replace_order", (
        "A completed PayPal order cannot be edited. Pause fulfillment, obtain merchant and buyer approval, "
        "refund the original payment, then capture and verify a replacement order."
    )


def facts(order: Order, destination: Destination, items: list[Item]) -> list[Fact]:
    source = order.payment.source if order.payment else "merchant"
    return [
        Fact(
            id="F1",
            label="Original payment",
            value=order.payment.capture_status or "unknown" if order.payment else "not_paid",
            source=source,
        ),
        Fact(id="F2", label="Fulfillment", value=order.fulfillment, source="merchant"),
        Fact(
            id="F3",
            label="Shipping destination changed",
            value=str(destination != order.destination).lower(),
            source="merchant",
        ),
        Fact(
            id="F4",
            label="Order total changed",
            value=str(sum(i.cents * i.quantity for i in items) != order.cents).lower(),
            source="merchant",
        ),
        Fact(
            id="F5",
            label="Completed order is editable",
            value="false",
            source="paypal_documentation",
        ),
        Fact(
            id="F6",
            label="Refund and replacement are atomic",
            value="false",
            source="paypal_documentation",
        ),
        Fact(
            id="F7",
            label="Seller Protection",
            value="Shipping conditions apply; PayPal determines eligibility",
            source="paypal_documentation",
        ),
    ]


def model_context(change: Change) -> dict[str, Any]:
    """No names, addresses, messages, payment IDs, approval tokens or other orders."""
    return {
        "task": "review_paid_order_change",
        "policy_version": POLICY_VERSION,
        "facts": [f.model_dump() for f in change.facts],
    }


def append_event(ws: Workspace, actor: str, action: str, detail: str) -> None:
    from .contracts import Event

    record = {
        "sequence": len(ws.events) + 1,
        "at": now(),
        "actor": actor,
        "action": action,
        "detail": detail,
        "previous_hash": ws.events[-1].hash if ws.events else "0" * 64,
    }
    ws.events.append(Event.model_validate({**record, "hash": fingerprint(record)}))
