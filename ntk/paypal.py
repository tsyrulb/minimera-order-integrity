"""Read-only sandbox adapter. Raw PayPal response bodies never reach a model or disk."""

import base64
import json
import re
from datetime import datetime, timezone
from typing import Protocol

import httpx

from .config import PayPalSettings, Settings
from .contracts import AppError, Case, FactValue, JsonObject
from .policy import digest
from .secrets import read_private_env

BASE = "https://api-m.sandbox.paypal.com"
KEYS = ("PAYPAL_SANDBOX_CLIENT_ID", "PAYPAL_SANDBOX_CLIENT_SECRET")


def credentials(settings: PayPalSettings | None = None) -> tuple[str, str]:
    settings = settings if settings is not None else Settings.from_env().paypal
    values = {KEYS[0]: settings.client_id, KEYS[1]: settings.client_secret}
    if settings.env_file:
        try:
            values.update(read_private_env(settings.env_file, frozenset(KEYS)))
        except (OSError, ValueError):
            raise AppError(
                "PAYPAL_CONFIG", "Sandbox credential file must be an owner-only regular file."
            ) from None
    if not all(values.values()) or any(re.search(r"\s", v) for v in values.values()):
        raise AppError(
            "PAYPAL_NOT_CONFIGURED",
            "The merchant has not configured the PayPal sandbox connection.",
        )
    return values[KEYS[0]], values[KEYS[1]]


class SandboxReader(Protocol):
    @property
    def configured(self) -> bool: ...

    async def read(self) -> Case: ...


def safe_enum(value: object) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value) else None
    )


def safe_date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 35:
        return None
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
        )
    except ValueError:
        return None


def normalize(
    order: JsonObject,
    dispute: JsonObject,
    order_id: str,
    capture_id: str,
    dispute_id: str,
    historical: JsonObject | None = None,
) -> Case:
    if order.get("id") != order_id or dispute.get("dispute_id") != dispute_id:
        raise AppError(
            "PAYPAL_LINK_FAILED", "PayPal resource IDs did not match the configured demo."
        )
    units = order.get("purchase_units", [])
    if len(units) != 1 or units[0].get("reference_id") != "need-to-know-sandbox":
        raise AppError(
            "PAYPAL_DEMO_ONLY",
            "Only the configured synthetic sandbox order is available in this demo.",
        )
    captures = [
        c for c in units[0].get("payments", {}).get("captures", []) if c.get("id") == capture_id
    ]
    transactions = [
        t
        for t in dispute.get("disputed_transactions", [])
        if t.get("seller_transaction_id") == capture_id
    ]
    if len(captures) != 1 or len(transactions) != 1:
        raise AppError(
            "PAYPAL_LINK_FAILED", "The dispute could not be linked to the configured capture."
        )
    capture = captures[0]
    amount = capture.get("amount", {})
    if amount.get("value") != "1.00" or amount.get("currency_code") != "USD":
        raise AppError(
            "PAYPAL_DEMO_ONLY", "This demo accepts only its synthetic USD 1.00 sandbox payment."
        )
    dispute_amount = dispute.get("dispute_amount", {})
    if dispute_amount.get("value") != "1.00" or dispute_amount.get("currency_code") != "USD":
        raise AppError(
            "PAYPAL_AMOUNT_MISMATCH", "Dispute amount does not match the configured demo payment."
        )
    previous = bool(
        historical
        and all(
            historical.get(k) == v
            for k, v in {
                "order_id": order_id,
                "capture_id": capture_id,
                "status": "COMPLETED",
                "capture_status": "COMPLETED",
                "amount": "1.00",
                "currency": "USD",
                "payment_verified": True,
            }.items()
        )
    )
    due = safe_date(dispute.get("seller_response_due_date"))
    values: list[tuple[str, str, FactValue, str]] = [
        ("case_status", "Case status", safe_enum(dispute.get("status")), "paypal"),
        ("reason", "Reason", safe_enum(dispute.get("reason")), "paypal"),
        ("stage", "Stage", safe_enum(dispute.get("dispute_life_cycle_stage")), "paypal"),
        ("amount", "Disputed amount", "1.00", "paypal"),
        ("currency", "Currency", "USD", "paypal"),
        ("payment_status", "Current capture status", safe_enum(capture.get("status")), "paypal"),
        (
            "payment_previously_completed",
            "Completion observed before dispute",
            True if previous else None,
            "merchant",
        ),
        ("verified_capture_link", "Capture linked to dispute", True, "paypal"),
        ("refund_status", "Confirmed refund status", None, "paypal"),
        ("tracking_status", "Carrier tracking status", None, "carrier"),
        ("tracking_source", "Tracking source", "none", "merchant"),
        ("tracking_number_available", "Tracking available", None, "merchant"),
        ("proof_of_delivery_available", "Delivery proof available", None, "merchant"),
        ("destination_match", "Delivery destination matches", None, "merchant"),
        ("goods_type", "Goods type", "PHYSICAL", "merchant"),
        ("respond_by", "Seller response deadline", due, "paypal"),
        (
            "deadline_passed",
            "Response deadline passed",
            datetime.fromisoformat(due) < datetime.now(timezone.utc) if due else None,
            "merchant",
        ),
    ]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "paypal-sandbox",
        "label": "Live PayPal sandbox dispute",
        "split": "live",
        "story": "A real read of our synthetic USD 1.00 sandbox dispute. No goods were shipped. Carrier facts are unavailable, not assumed false.",
        "source": {
            "kind": "paypal-sandbox",
            "label": "PayPal sandbox · live read",
            "observed_at": now,
            "capture_link_verified": True,
            "resource_fingerprint": digest([order_id, capture_id, dispute_id])[:16],
            "completion_basis": "Unsigned local observation from before the dispute"
            if previous
            else "Not established by a prior record",
            "scope": "PayPal business fields only; no buyer profiles, messages or attachments forwarded.",
        },
        "facts": [
            {
                "id": f"F{i:02d}",
                "key": key,
                "label": label,
                "value": value,
                "source": source,
                "sensitivity": "task",
            }
            for i, (key, label, value, source) in enumerate(values, 1)
        ],
    }


def _bounded_object(response: httpx.Response) -> JsonObject:
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise AppError("PAYPAL_RESPONSE_LIMIT", "PayPal response exceeded the size limit.")
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("PayPal response must be an object")
    return value


class PayPalClient:
    """Read the one configured sandbox workflow through a fixed API origin."""

    def __init__(
        self, settings: PayPalSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self._settings.configured

    async def read(self) -> Case:
        client_id, secret = credentials(self._settings)
        order_id = self._settings.order_id
        capture_id = self._settings.capture_id
        dispute_id = self._settings.dispute_id
        if not all(
            re.fullmatch(r"[A-Z0-9-]{1,80}", value) for value in (order_id, capture_id, dispute_id)
        ):
            raise AppError(
                "PAYPAL_CONFIG", "The merchant must configure the three sandbox resource IDs."
            )
        historical = self._historical_observation()
        try:
            async with httpx.AsyncClient(
                timeout=20, trust_env=False, follow_redirects=False, transport=self._transport
            ) as client:
                token = _bounded_object(
                    await client.post(
                        BASE + "/v1/oauth2/token",
                        data={"grant_type": "client_credentials"},
                        headers={
                            "Authorization": "Basic "
                            + base64.b64encode(f"{client_id}:{secret}".encode()).decode()
                        },
                    )
                )
                access = token.get("access_token")
                if not isinstance(access, str) or not access or re.search(r"\s", access):
                    raise AppError(
                        "PAYPAL_AUTH", "Sandbox authentication did not return a valid token."
                    )
                headers = {"Authorization": "Bearer " + access}
                # Deliberately sequential, read-only calls to a fixed sandbox origin.
                order = _bounded_object(
                    await client.get(BASE + "/v2/checkout/orders/" + order_id, headers=headers)
                )
                dispute = _bounded_object(
                    await client.get(BASE + "/v1/customer/disputes/" + dispute_id, headers=headers)
                )
                return normalize(order, dispute, order_id, capture_id, dispute_id, historical)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise AppError(
                "PAYPAL_READ_FAILED",
                "PayPal sandbox could not be read. The last verified observation remains labelled with its timestamp.",
            ) from None

    def _historical_observation(self) -> JsonObject | None:
        path = self._settings.completion_record
        if path is None:
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Expected a prior observation object")
            return value
        except (ValueError, OSError):
            raise AppError("PAYPAL_CONFIG", "Prior observation could not be read.") from None
