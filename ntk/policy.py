"""Local, deterministic field projection. No model sees data to decide what to hide."""

import copy
import hashlib
import json
from typing import Literal

from .contracts import Case, ContextPayload, FieldDecision, Mode, OutgoingFact, Projection

POLICY_VERSION = "inr-context/1.0.1"
PURPOSE = "Review an item-not-received dispute and draft a seller response for human approval."
ALLOWED_KEYS = frozenset(
    {
        "case_status",
        "reason",
        "stage",
        "amount",
        "currency",
        "payment_status",
        "payment_previously_completed",
        "refund_status",
        "refund_amount",
        "refund_currency",
        "tracking_status",
        "tracking_source",
        "tracking_delivery_date",
        "dispute_opened_date",
        "destination_match",
        "proof_of_delivery_available",
        "tracking_number_available",
        "respond_by",
        "deadline_passed",
        "goods_type",
        "verified_capture_link",
        "conflicting_tracking",
    }
)
MODES = {
    "full": {
        "label": "Full context",
        "description": "All synthetic fields, including customer and internal data.",
    },
    "masked": {
        "label": "PII masking",
        "description": "Known personal fields masked; commercial data and notes remain.",
    },
    "purpose": {
        "label": "Minimera",
        "description": "Only allowlisted facts for this dispute workflow.",
    },
}


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def project(case: Case, mode: Mode) -> Projection:
    if mode not in MODES:
        raise ValueError("Unknown context mode")
    # Public/live source records are already normalized on the merchant server.
    # The full-context experiment is allowed only for our synthetic fixtures.
    if mode != "purpose" and case["source"]["kind"] != "synthetic":
        raise ValueError("Full and masked modes are restricted to synthetic cases")
    outgoing: list[OutgoingFact] = []
    ledger: list[FieldDecision] = []
    for original in case["facts"]:
        fact = copy.deepcopy(original)
        allowed = fact["key"] in ALLOWED_KEYS and fact["sensitivity"] == "task"
        decision: Literal["retain", "mask", "exclude"] = "retain"
        reason = "Included in this experimental baseline."
        if mode == "purpose" and not allowed:
            decision, reason = "exclude", "Outside the declared item-not-received purpose."
        elif mode == "masked" and fact["sensitivity"] == "personal":
            fact["value"] = "[MASKED]"
            decision, reason = "mask", "Known personal field; value replaced locally."
        elif mode == "purpose":
            reason = "Allowlisted business fact needed to review the dispute."
        if decision != "exclude":
            # Only public provenance labels and fact IDs travel with values.
            outgoing.append(
                {
                    "id": fact["id"],
                    "key": fact["key"],
                    "value": fact["value"],
                    "source": fact["source"],
                }
            )
        ledger.append(
            {"id": fact["id"], "key": fact["key"], "decision": decision, "reason": reason}
        )
    payload: ContextPayload = {"purpose": PURPOSE, "facts": outgoing}
    sensitive = [
        f for f in case["facts"] if f["sensitivity"] in ("personal", "commercial", "untrusted")
    ]
    wire = canonical(payload)
    # Count actual field decisions, not coincidental short-number matches.
    # A margin of 18 can equal an unrelated task amount without crossing over.
    retained_values = {d["id"] for d in ledger if d["decision"] == "retain"}
    disclosed = [f["id"] for f in sensitive if f["id"] in retained_values]
    personal_matches = [
        f["id"]
        for f in sensitive
        if f["sensitivity"] == "personal"
        and isinstance(f["value"], str)
        and len(f["value"]) >= 6
        and f["value"] in wire
    ]
    task_ids = {f["id"] for f in case["facts"] if f["sensitivity"] == "task"}
    retained_ids = {f["id"] for f in outgoing}
    return {
        "mode": mode,
        "policy_version": POLICY_VERSION,
        "payload": payload,
        "context_sha256": digest(payload),
        "ledger": ledger,
        "metrics": {
            "source_fields": len(case["facts"]),
            "sent_fields": len(outgoing),
            "excluded_fields": sum(x["decision"] == "exclude" for x in ledger),
            "masked_fields": sum(x["decision"] == "mask" for x in ledger),
            "sensitive_fields_disclosed": len(disclosed),
            "sensitive_field_ids": disclosed,
            "sensitive_fields_total": len(sensitive),
            "personal_value_matches_in_input": personal_matches,
            "task_fields_retained": len(task_ids & retained_ids),
            "task_fields_total": len(task_ids),
            "context_bytes": len(wire.encode()),
        },
    }
