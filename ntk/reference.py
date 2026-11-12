"""Evaluation-only routing oracle. Never imported by inference or context projection.

This implements the project's explicit synthetic rubric, not PayPal policy or
independent adjudication. Model outputs are compared with it, never replaced by it.
"""

from decimal import Decimal, InvalidOperation

from .contracts import Action, Case, Evidence, ReferenceLabel


def reference_label(case: Case) -> ReferenceLabel:
    facts = {fact["key"]: fact for fact in case["facts"]}

    def value(key: str) -> object:
        return facts[key]["value"] if key in facts else None

    def label(action: Action, missing: list[Evidence], keys: list[str], why: str) -> ReferenceLabel:
        return {
            "action": action,
            "missing_evidence": missing,
            "required_citations": [facts[key]["id"] for key in keys if key in facts][:3],
            "rationale": why,
        }

    if value("case_status") in ("CLOSED", "RESOLVED"):
        return label("no_action", [], ["case_status"], "The recorded case is closed or resolved.")
    if value("case_status") in ("UNDER_REVIEW", "WAITING_FOR_BUYER_RESPONSE"):
        return label("await_review", [], ["case_status"], "The case is waiting on another party.")

    missing: list[Evidence] = []
    decisive: list[str] = []
    if value("verified_capture_link") is not True:
        missing.append("payment_link")
        decisive.append("verified_capture_link")
    if value("deadline_passed") is not False:
        missing.append("deadline")
        decisive.append("deadline_passed")
    if value("conflicting_tracking") is True or value("destination_match") is False:
        missing.append("resolve_conflict")
        decisive.append(
            "conflicting_tracking" if value("conflicting_tracking") is True else "destination_match"
        )
    unsupported = value("goods_type") != "PHYSICAL"
    if unsupported:
        decisive.append("goods_type")
    if missing or unsupported:
        return label("manual_review", missing, decisive, "A blocker requires human review.")

    refund = value("refund_status")
    incomplete_refund = refund in ("PENDING", "MERCHANT_CLAIMED", "CLAIMED", "PARTIAL")
    if refund == "COMPLETED":
        try:
            returned = Decimal(str(value("refund_amount")))
            disputed = Decimal(str(value("amount")))
            incomplete_refund = (
                not returned.is_finite() or not disputed.is_finite() or returned < disputed
            )
        except (InvalidOperation, ValueError):
            incomplete_refund = True
        incomplete_refund |= value("refund_currency") != value("currency")
    if incomplete_refund:
        return label(
            "check_refund",
            ["refund_confirmation"],
            ["refund_status", "refund_amount", "amount"],
            "The refund needs confirmation or reconciliation before relying on it.",
        )

    delivered = value("tracking_status") == "DELIVERED"
    independent = value("tracking_source") == "carrier"
    proof = value("proof_of_delivery_available") is True
    if delivered and independent and proof and value("destination_match") is True:
        return label(
            "prepare_delivery_evidence",
            [],
            ["tracking_status", "destination_match", "proof_of_delivery_available"],
            "The supplied carrier delivery, destination and document facts support preparation.",
        )
    if value("tracking_number_available") is not True or value("tracking_status") in (
        None,
        "NOT_PROVIDED",
    ):
        return label(
            "gather_evidence",
            ["tracking"],
            ["tracking_status", "tracking_number_available"],
            "The merchant must locate its shipment or tracking record.",
        )
    if not delivered or not independent or not proof:
        return label(
            "gather_evidence",
            ["delivery_confirmation"],
            ["tracking_status", "tracking_source", "proof_of_delivery_available"],
            "Independent delivery confirmation is missing.",
        )
    return label(
        "gather_evidence",
        ["destination_match"],
        ["tracking_status", "destination_match"],
        "The delivery destination has not been verified.",
    )
