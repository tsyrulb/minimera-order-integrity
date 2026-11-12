import asyncio

import httpx
import pytest

from ntk.config import PayPalSettings
from ntk.contracts import AppError
from ntk.paypal import BASE, PayPalClient, credentials, normalize
from ntk.policy import canonical, project


def records():
    order = {
        "id": "ORDER1",
        "payer": {"email_address": "REAL-PERSON-DO-NOT-FORWARD@example.test"},
        "purchase_units": [
            {
                "reference_id": "need-to-know-sandbox",
                "payments": {
                    "captures": [
                        {
                            "id": "CAPTURE1",
                            "status": "PENDING",
                            "amount": {"value": "1.00", "currency_code": "USD"},
                        }
                    ]
                },
            }
        ],
    }
    dispute = {
        "dispute_id": "DISPUTE1",
        "status": "WAITING_FOR_SELLER_RESPONSE",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "dispute_amount": {"value": "1.00", "currency_code": "USD"},
        "disputed_transactions": [{"seller_transaction_id": "CAPTURE1"}],
        "messages": [{"content": "REAL-PRIVATE-MESSAGE"}],
        "evidences": [{"notes": "REAL-PRIVATE-ATTACHMENT-NOTE"}],
    }
    historical = {
        "order_id": "ORDER1",
        "capture_id": "CAPTURE1",
        "status": "COMPLETED",
        "capture_status": "COMPLETED",
        "amount": "1.00",
        "currency": "USD",
        "payment_verified": True,
    }
    return order, dispute, historical


def test_live_adapter_drops_profiles_and_free_text_without_changing_payment_state():
    order, dispute, old = records()
    current = normalize(order, dispute, "ORDER1", "CAPTURE1", "DISPUTE1", old)
    wire = canonical(current)
    assert "REAL-" not in wire
    values = {f["key"]: f["value"] for f in current["facts"]}
    assert values["payment_status"] == "PENDING"
    assert values["payment_previously_completed"] is True
    assert values["respond_by"] is None
    assert values["deadline_passed"] is None
    assert values["tracking_status"] is None
    assert "Unsigned local observation" in current["source"]["completion_basis"]
    assert project(current, "purpose")["metrics"]["sensitive_fields_disclosed"] == 0


def test_mismatched_capture_cannot_be_used_as_evidence():
    order, dispute, old = records()
    dispute["disputed_transactions"][0]["seller_transaction_id"] = "ANOTHER_CAPTURE"
    with pytest.raises(AppError, match="PAYPAL_LINK_FAILED"):
        normalize(order, dispute, "ORDER1", "CAPTURE1", "DISPUTE1", old)


@pytest.mark.parametrize("change", ["order", "amount", "dispute_amount"])
def test_adapter_refuses_other_orders_and_amounts(change):
    order, dispute, old = records()
    if change == "order":
        order["purchase_units"][0]["reference_id"] = "another-merchant-order"
    if change == "amount":
        order["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"] = "99.00"
    if change == "dispute_amount":
        dispute["dispute_amount"]["currency_code"] = "EUR"
    with pytest.raises(AppError):
        normalize(order, dispute, "ORDER1", "CAPTURE1", "DISPUTE1", old)


def test_an_unrelated_historical_record_does_not_establish_completion():
    order, dispute, old = records()
    old["capture_id"] = "ANOTHER_CAPTURE"
    current = normalize(order, dispute, "ORDER1", "CAPTURE1", "DISPUTE1", old)
    assert (
        next(f["value"] for f in current["facts"] if f["key"] == "payment_previously_completed")
        is None
    )


def test_credentials_file_must_be_owned_private_regular_file(tmp_path, monkeypatch):
    for name in ("PAYPAL_SANDBOX_CLIENT_ID", "PAYPAL_SANDBOX_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    file = tmp_path / "sandbox.env"
    file.write_text("PAYPAL_SANDBOX_CLIENT_ID=fake-id\nPAYPAL_SANDBOX_CLIENT_SECRET=fake-secret\n")
    file.chmod(0o644)
    monkeypatch.setenv("NTK_PAYPAL_ENV_FILE", str(file))
    with pytest.raises(AppError):
        credentials()
    file.chmod(0o600)
    assert credentials() == ("fake-id", "fake-secret")
    alias = tmp_path / "alias.env"
    alias.symlink_to(file)
    monkeypatch.setenv("NTK_PAYPAL_ENV_FILE", str(alias))
    with pytest.raises(AppError):
        credentials()


def test_sandbox_adapter_uses_only_authentication_and_read_endpoints():
    order, dispute, _ = records()
    calls = []

    def respond(request):
        calls.append((request.method, str(request.url)))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "synthetic-access-token"})
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        if request.url.path == "/v2/checkout/orders/ORDER1":
            return httpx.Response(200, json=order)
        if request.url.path == "/v1/customer/disputes/DISPUTE1":
            return httpx.Response(200, json=dispute)
        pytest.fail("Unexpected payment API call")

    config = PayPalSettings(
        client_id="synthetic-id",
        client_secret="synthetic-secret",
        order_id="ORDER1",
        capture_id="CAPTURE1",
        dispute_id="DISPUTE1",
    )
    client = PayPalClient(config, transport=httpx.MockTransport(respond))
    case = asyncio.run(client.read())
    assert calls == [
        ("POST", BASE + "/v1/oauth2/token"),
        ("GET", BASE + "/v2/checkout/orders/ORDER1"),
        ("GET", BASE + "/v1/customer/disputes/DISPUTE1"),
    ]
    assert "REAL-" not in canonical(case)
    assert "synthetic-secret" not in canonical(case)
