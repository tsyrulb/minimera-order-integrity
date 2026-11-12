"""Narrow, deterministic draft checks. This is not a semantic truth verifier."""

import re

from .contracts import Case, JsonObject

VERSION = "inr-draft-checks/1.0.2"


def check_draft(case: Case, analysis: JsonObject) -> JsonObject:
    values = {f["key"]: f["value"] for f in case["facts"] if f["sensitivity"] == "task"}
    reply = analysis["reply_draft"].lower()
    flags = []
    if values.get("case_status") in ("RESOLVED", "CLOSED") and analysis["action"] != "no_action":
        flags.append("The case is already resolved; the model proposes a new seller task.")
    if (
        values.get("case_status") in ("WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW")
        and analysis["action"] != "await_review"
    ):
        flags.append(
            "The case is waiting for another party or review; the model proposes a new seller task."
        )
    if re.search(
        r"(?:provide|send|share|submit)[^.\n]{0,100}(?:tracking|proof of delivery|shipment evidence)",
        reply,
    ):
        flags.append("The draft asks the buyer for shipment evidence the seller should gather.")
    if re.search(
        r"paypal.?s (?:guidelines|polic)|seller protection|guarantee.{0,30}(?:refund|win)", reply
    ):
        flags.append(
            "The draft refers to a policy or outcome not established by the supplied facts."
        )
    if re.search(r"(?:within the next|within \d+ (?:day|hour)|by tomorrow)", reply):
        flags.append("The draft introduces a response timeframe not grounded in a cited deadline.")
    if values.get("refund_status") != "COMPLETED" and re.search(
        r"(?:refund has been|we have refunded|refund is (?:completed|processed)|refund was (?:completed|processed))",
        reply,
    ):
        flags.append("Refund wording needs review: the case has no verified completed refund.")
    if analysis["action"] == "prepare_delivery_evidence" and not (
        values.get("tracking_status") == "DELIVERED"
        and values.get("tracking_source") == "carrier"
        and values.get("destination_match") is True
        and values.get("proof_of_delivery_available") is True
    ):
        flags.append("The recommendation lacks the workflow's required carrier delivery facts.")
    if (
        analysis["action"] == "await_review"
        and values.get("case_status") == "WAITING_FOR_SELLER_RESPONSE"
    ):
        flags.append(
            "PayPal is waiting for the seller; the recommendation incorrectly waits for another party."
        )
    return {
        "version": VERSION,
        "flags": flags,
        "draft_status": "needs_review" if flags else "unapproved",
        "human_review_required": True,
        "scope": "Pattern and explicit precondition checks only; passing is not a guarantee of factual correctness.",
    }
