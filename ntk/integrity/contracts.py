"""Validated workflow records. Amounts are integer USD cents, never floats."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["simulation", "sandbox"]
Scenario = Literal["address_change", "already_shipped", "stale_approval"]
Destination = Literal["home", "office"]
Route = Literal["replace_order", "manual_review", "no_change"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(Record):
    sku: str
    name: str
    cents: int = Field(gt=0, le=100_000)
    quantity: int = Field(default=1, ge=1, le=10)


class Payment(Record):
    order_id: str
    status: str
    cents: int
    currency: Literal["USD"] = "USD"
    destination: Destination
    custom_id: str
    merchant_id: str
    capture_id: str | None = None
    capture_status: str | None = None
    protection_status: str | None = None
    verified_at: str
    source: Literal["simulator", "paypal_sandbox"]


class Refund(Record):
    refund_id: str
    capture_id: str
    status: str
    cents: int
    currency: Literal["USD"] = "USD"
    verified_at: str
    source: Literal["simulator", "paypal_sandbox"]


class Order(Record):
    id: str = "NL-1042"
    revision: int = 1
    items: list[Item]
    destination: Destination = "home"
    fulfillment: Literal["unfulfilled", "on_hold", "shipped", "ready", "released", "replaced"] = (
        "unfulfilled"
    )
    payment: Payment | None = None

    @property
    def cents(self) -> int:
        return sum(item.cents * item.quantity for item in self.items)


class Fact(Record):
    id: str
    label: str
    value: str
    source: Literal["merchant", "paypal_sandbox", "simulator", "paypal_documentation"]


class Plan(Record):
    route: Route
    summary: str = Field(min_length=1, max_length=600)
    steps: list[str] = Field(min_length=1, max_length=6)
    fact_ids: list[str] = Field(min_length=1, max_length=8)
    customer_message: str = Field(min_length=1, max_length=700)


class Advice(Record):
    plan: Plan | None = None
    source: Literal["bedrock", "recorded_bedrock", "unavailable"] = "unavailable"
    model: str | None = None
    prompt_version: str = "order-change-plan/1.2.0"
    request_hash: str
    provider_request_id: str | None = None
    policy_agrees: bool | None = None


class Change(Record):
    id: str
    destination: Destination
    remove_pouch: bool
    items: list[Item]
    route: Route
    state: Literal[
        "review",
        "blocked",
        "approved",
        "awaiting_buyer",
        "processing",
        "pending",
        "complete",
        "stale",
        "indeterminate",
    ]
    facts: list[Fact]
    advice: Advice | None = None
    snapshot_hash: str
    approved_hash: str | None = None
    approval_expires: int | None = None
    replacement: Payment | None = None
    refund: Refund | None = None
    explanation: str
    created_at: str

    @property
    def cents(self) -> int:
        return sum(item.cents * item.quantity for item in self.items)


class Checkout(Record):
    id: str
    purpose: Literal["original", "replacement"]
    order_id: str
    state: str
    approval_url: str
    custom_id: str
    cents: int
    destination: Destination
    merchant_id: str
    completed: bool = False


class Event(Record):
    sequence: int
    at: str
    actor: str
    action: str
    detail: str
    previous_hash: str
    hash: str


class Workspace(Record):
    id: str
    revision: int = 0
    mode: Mode
    scenario: Scenario
    order: Order
    fulfillment_order: Order | None = None
    change: Change | None = None
    checkouts: list[Checkout] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    created_at: str


class NewWorkspace(Record):
    mode: Mode = "simulation"
    scenario: Scenario = "address_change"


class ChangeRequest(Record):
    destination: Destination = "office"
    remove_pouch: bool = True


class ApprovalRequest(Record):
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompleteCheckout(Record):
    checkout_id: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=16, max_length=128)


class AskRequest(Record):
    question: Literal["explain", "privacy", "next_step"] = "explain"
