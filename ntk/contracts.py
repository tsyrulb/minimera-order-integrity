"""Wire contracts shared by the policy, adapters and application service."""

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

Mode = Literal["full", "masked", "purpose"]
Action = Literal[
    "gather_evidence",
    "prepare_delivery_evidence",
    "check_refund",
    "manual_review",
    "await_review",
    "no_action",
]
Evidence = Literal[
    "tracking",
    "delivery_confirmation",
    "destination_match",
    "refund_confirmation",
    "payment_link",
    "deadline",
    "resolve_conflict",
]
Provider = Literal["ollama", "openai", "bedrock"]
FactValue: TypeAlias = str | int | float | bool | None
# Provider envelopes and versioned evidence reports have heterogeneous JSON
# fields. Keep that flexibility explicit; policy inputs use the contracts below.
JsonObject: TypeAlias = dict[str, Any]


class Fact(TypedDict):
    id: str
    key: str
    label: str
    value: FactValue
    source: str
    sensitivity: Literal["task", "personal", "commercial", "untrusted"]


class CaseSource(TypedDict):
    kind: Literal["synthetic", "paypal-sandbox"]
    label: str
    observed_at: NotRequired[str]
    capture_link_verified: NotRequired[bool]
    resource_fingerprint: NotRequired[str]
    completion_basis: NotRequired[str]
    scope: NotRequired[str]


class ReferenceLabel(TypedDict):
    action: Action
    missing_evidence: list[Evidence]
    required_citations: list[str]
    rationale: str


class Case(TypedDict):
    id: str
    label: str
    split: Literal["development", "heldout", "live"]
    story: str
    source: CaseSource
    facts: list[Fact]
    expected: NotRequired[ReferenceLabel]


class DatasetDocument(TypedDict):
    version: str
    authorship: str
    as_of: str
    cases: list[Case]
    evaluation: NotRequired[JsonObject]


class OutgoingFact(TypedDict):
    id: str
    key: str
    value: FactValue
    source: str


class ContextPayload(TypedDict):
    purpose: str
    facts: list[OutgoingFact]


class FieldDecision(TypedDict):
    id: str
    key: str
    decision: Literal["retain", "mask", "exclude"]
    reason: str


class ProjectionMetrics(TypedDict):
    source_fields: int
    sent_fields: int
    excluded_fields: int
    masked_fields: int
    sensitive_fields_disclosed: int
    sensitive_field_ids: list[str]
    sensitive_fields_total: int
    personal_value_matches_in_input: list[str]
    task_fields_retained: int
    task_fields_total: int
    context_bytes: int


class Projection(TypedDict):
    mode: Mode
    policy_version: str
    payload: ContextPayload
    context_sha256: str
    ledger: list[FieldDecision]
    metrics: ProjectionMetrics


class Analysis(BaseModel):
    """Model output, checked before it can become a draft. Never executes actions."""

    model_config = ConfigDict(extra="forbid")
    action: Action
    missing_evidence: list[Evidence] = Field(max_length=7)
    citations: list[str] = Field(min_length=1, max_length=4)
    rationale: str = Field(min_length=10, max_length=700)
    reply_draft: str = Field(min_length=10, max_length=900)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^(NTK-\d{3}|paypal-sandbox)$")
    mode: Mode = "purpose"
    fresh: bool = False


class AppError(Exception):
    """A safe application failure whose message may be returned to a caller."""

    def __init__(
        self, code: str, message: str, status: int = 503, *, evidence: JsonObject | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.evidence = evidence
        super().__init__(code)
