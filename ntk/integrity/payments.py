"""Fixed-origin Sandbox writes and an explicitly separate durable simulator."""

import re
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx

from ..config import PayPalSettings
from ..contracts import AppError
from ..paypal import credentials
from .contracts import Destination, Payment, Refund
from .policy import DESTINATIONS, now, price
from .store import Store

BASE = "https://api-m.sandbox.paypal.com"
REFERENCE = "minimera-order-integrity-v1"


def request_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"minimera:order-integrity:{value}"))


class Gateway(Protocol):
    async def create(
        self,
        key: str,
        cents: int,
        destination: Destination,
        custom_id: str,
        return_url: str,
        cancel_url: str,
    ) -> tuple[Payment, str]: ...
    async def read(self, order_id: str) -> Payment: ...
    async def capture(self, order_id: str, key: str) -> None: ...
    async def refund(self, capture_id: str, cents: int, key: str) -> str: ...
    async def read_refund(self, refund_id: str) -> Refund: ...


class Simulator:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def create(
        self,
        key: str,
        cents: int,
        destination: Destination,
        custom_id: str,
        return_url: str,
        cancel_url: str,
    ) -> tuple[Payment, str]:
        order_id = "SIM-" + request_id(key)[:18].upper()
        payment = Payment(
            order_id=order_id,
            status="CREATED",
            cents=cents,
            destination=destination,
            custom_id=custom_id,
            merchant_id="SIM-MERCHANT",
            verified_at=now(),
            source="simulator",
        )
        self.store.provider_put(order_id, payment.model_dump_json())
        return payment, return_url

    async def read(self, order_id: str) -> Payment:
        return Payment.model_validate_json(self.store.provider_get(order_id)).model_copy(
            update={"verified_at": now()}
        )

    async def approve_simulation(self, order_id: str) -> None:
        payment = await self.read(order_id)
        if payment.status == "CREATED":
            payment.status = "APPROVED"
            self.store.provider_put(order_id, payment.model_dump_json())

    async def capture(self, order_id: str, key: str) -> None:
        payment = await self.read(order_id)
        if payment.status != "APPROVED":
            raise AppError("NOT_APPROVED", "The buyer must approve this payment first.", 409)
        payment.status = "COMPLETED"
        payment.capture_status = "COMPLETED"
        payment.capture_id = "SIM-CAP-" + request_id(key)[:14].upper()
        payment.protection_status = "SIMULATED_NOT_ELIGIBILITY"
        self.store.provider_put(order_id, payment.model_dump_json())
        self.store.provider_put(payment.capture_id, order_id)

    async def refund(self, capture_id: str, cents: int, key: str) -> str:
        order_id = self.store.provider_get(capture_id)
        payment = await self.read(order_id)
        if payment.capture_status != "COMPLETED" or payment.cents != cents:
            raise AppError("REFUND_REFUSED", "This capture cannot be fully refunded.", 409)
        refund_id = "SIM-REF-" + request_id(key)[:14].upper()
        result = Refund(
            refund_id=refund_id,
            capture_id=capture_id,
            status="COMPLETED",
            cents=cents,
            verified_at=now(),
            source="simulator",
        )
        self.store.provider_put(refund_id, result.model_dump_json())
        payment.capture_status = "REFUNDED"
        self.store.provider_put(order_id, payment.model_dump_json())
        return refund_id

    async def read_refund(self, refund_id: str) -> Refund:
        return Refund.model_validate_json(self.store.provider_get(refund_id))


def _cents(amount: dict[str, Any]) -> int:
    value = str(amount.get("value", ""))
    if amount.get("currency_code") != "USD" or not re.fullmatch(r"\d+\.\d{2}", value):
        raise ValueError("Unexpected payment amount")
    dollars, fractional = value.split(".")
    return int(dollars) * 100 + int(fractional)


def _destination(address: dict[str, Any]) -> Destination:
    for destination, expected in DESTINATIONS.items():
        if all(
            str(address.get(k, "")).strip().casefold() == v.casefold() for k, v in expected.items()
        ):
            return cast(Destination, destination)
    raise ValueError("Unexpected shipping destination")


def normalize_order(value: dict[str, Any]) -> Payment:
    units = value["purchase_units"]
    if len(units) != 1 or units[0]["reference_id"] != REFERENCE:
        raise ValueError("Unexpected purchase unit")
    unit = units[0]
    captures = unit.get("payments", {}).get("captures", [])
    if len(captures) > 1:
        raise ValueError("Unexpected capture count")
    capture = captures[0] if captures else {}
    if capture and _cents(capture["amount"]) != _cents(unit["amount"]):
        raise ValueError("Capture amount differs")
    return Payment(
        order_id=value["id"],
        status=value["status"],
        cents=_cents(unit["amount"]),
        destination=_destination(unit["shipping"]["address"]),
        custom_id=unit["custom_id"],
        merchant_id=unit["payee"]["merchant_id"],
        capture_id=capture.get("id"),
        capture_status=capture.get("status"),
        protection_status=capture.get("seller_protection", {}).get("status"),
        verified_at=now(),
        source="paypal_sandbox",
    )


class Sandbox:
    """No caller-supplied hosts, credential forwarding, redirects, or live endpoints."""

    def __init__(
        self,
        settings: PayPalSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        maximum_cents: int = 200,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.maximum_cents = maximum_cents

    async def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None, key: str | None = None
    ) -> dict[str, Any]:
        try:
            client_id, secret = credentials(self.settings)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(35, connect=10),
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                token_response = await client.post(
                    BASE + "/v1/oauth2/token",
                    auth=(client_id, secret),
                    data={"grant_type": "client_credentials"},
                )
                token_response.raise_for_status()
                token = token_response.json()["access_token"]
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Prefer": "return=representation",
                }
                if key:
                    headers["PayPal-Request-Id"] = request_id(key)
                response = await client.request(method, BASE + path, json=body, headers=headers)
                response.raise_for_status()
                if len(response.content) > 256_000:
                    raise ValueError("Response too large")
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Invalid provider response")
                return cast(dict[str, Any], result)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AppError(
                "PAYPAL_UNCONFIRMED",
                "PayPal did not confirm this operation. Fulfillment remains on hold; check the payment before retrying.",
                502,
            ) from None

    async def create(
        self,
        key: str,
        cents: int,
        destination: Destination,
        custom_id: str,
        return_url: str,
        cancel_url: str,
    ) -> tuple[Payment, str]:
        if not 0 < cents <= self.maximum_cents:
            raise AppError(
                "SANDBOX_AMOUNT_LIMIT",
                "The Sandbox transaction exceeds the demo amount limit.",
                422,
            )
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": REFERENCE,
                    "custom_id": custom_id,
                    "amount": {"currency_code": "USD", "value": price(cents)},
                    "shipping": {
                        "name": {"full_name": "Minimera Test Buyer"},
                        "address": DESTINATIONS[destination],
                    },
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "Minimera Sandbox",
                        "shipping_preference": "SET_PROVIDED_ADDRESS",
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        result = await self._request("POST", "/v2/checkout/orders", body=body, key=key)
        try:
            order_id = str(result["id"])
            approval = next(
                str(link["href"])
                for link in result["links"]
                if link["rel"] in ("payer-action", "approve")
            )
            parsed = urlsplit(approval)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.sandbox.paypal.com"
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Unexpected approval origin")
            return await self.read(order_id), approval
        except (ValueError, KeyError, StopIteration, TypeError):
            raise AppError(
                "PAYPAL_RESPONSE_INVALID", "The PayPal approval link could not be verified.", 502
            ) from None

    async def read(self, order_id: str) -> Payment:
        self._identifier(order_id)
        try:
            observation = normalize_order(
                await self._request("GET", f"/v2/checkout/orders/{order_id}")
            )
            if observation.order_id != order_id:
                raise ValueError("Wrong order")
            if observation.capture_id:
                self._identifier(observation.capture_id)
                capture = await self._request(
                    "GET", f"/v2/payments/captures/{observation.capture_id}"
                )
                if (
                    capture["id"] != observation.capture_id
                    or _cents(capture["amount"]) != observation.cents
                    or capture["supplementary_data"]["related_ids"]["order_id"] != order_id
                ):
                    raise ValueError("Capture linkage differs")
                observation.capture_status = capture["status"]
            return observation
        except (KeyError, ValueError, TypeError, IndexError):
            raise AppError(
                "PAYPAL_READBACK_MISMATCH",
                "PayPal returned unexpected order, capture, or shipping details. Automatic execution is blocked.",
                409,
            ) from None

    async def capture(self, order_id: str, key: str) -> None:
        self._identifier(order_id)
        await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", body={}, key=key)

    async def refund(self, capture_id: str, cents: int, key: str) -> str:
        self._identifier(capture_id)
        if not 0 < cents <= self.maximum_cents:
            raise AppError("SANDBOX_AMOUNT_LIMIT", "The refund exceeds the demo amount limit.", 422)
        result = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            body={"amount": {"currency_code": "USD", "value": price(cents)}},
            key=key,
        )
        return str(result["id"])

    async def read_refund(self, refund_id: str) -> Refund:
        self._identifier(refund_id)
        try:
            result = await self._request("GET", f"/v2/payments/refunds/{refund_id}")
            capture_urls = [link["href"] for link in result["links"] if link["rel"] == "up"]
            if result["id"] != refund_id or len(capture_urls) != 1:
                raise ValueError("Unexpected refund parent")
            # Sandbox HATEOAS links also use api.sandbox.paypal.com. Parse the
            # identity only; authenticated requests still use the fixed BASE.
            parent = urlsplit(capture_urls[0])
            capture_path = re.fullmatch(r"/v2/payments/captures/([A-Z0-9]{8,40})", parent.path)
            if (
                parent.scheme != "https"
                or parent.netloc not in {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
                or parent.query
                or parent.fragment
                or capture_path is None
            ):
                raise ValueError("Unexpected refund parent")
            capture_id = capture_path.group(1)
            return Refund(
                refund_id=refund_id,
                capture_id=capture_id,
                status=result["status"],
                cents=_cents(result["amount"]),
                verified_at=now(),
                source="paypal_sandbox",
            )
        except (KeyError, ValueError, TypeError):
            raise AppError(
                "REFUND_READBACK_MISMATCH", "The refund could not be independently verified.", 409
            ) from None

    @staticmethod
    def _identifier(value: str) -> None:
        if not re.fullmatch(r"[A-Z0-9]{8,40}", value):
            raise AppError("INVALID_PAYMENT_ID", "The payment identifier is invalid.", 422)
