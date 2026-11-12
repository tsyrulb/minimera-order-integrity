from ntk.dataset import load_dataset
from ntk.review import check_draft


def test_buyer_is_not_asked_for_seller_owned_tracking():
    case = load_dataset()[0]["cases"][0]
    review = check_draft(
        case,
        {
            "action": "gather_evidence",
            "reply_draft": "Please provide any available tracking information.",
        },
    )
    assert review["draft_status"] == "needs_review"
    assert any("buyer" in flag for flag in review["flags"])


def test_unverified_delivery_recommendation_is_flagged():
    case = load_dataset()[0]["cases"][0]
    review = check_draft(
        case,
        {
            "action": "prepare_delivery_evidence",
            "reply_draft": "We are reviewing your report and our shipment records.",
        },
    )
    assert any("carrier" in flag for flag in review["flags"])


def test_a_passing_draft_still_requires_human_approval():
    case = load_dataset()[0]["cases"][0]
    review = check_draft(
        case,
        {
            "action": "gather_evidence",
            "reply_draft": "Thank you for reporting that your item has not arrived. We are reviewing our shipment records.",
        },
    )
    assert review["flags"] == []
    assert review["draft_status"] == "unapproved"
    assert review["human_review_required"] is True


def test_observed_regression_closed_case_must_not_request_new_shipment_evidence():
    case = load_dataset()[0]["cases"][8]
    review = check_draft(
        case, {"action": "gather_evidence", "reply_draft": "We are reviewing our shipment records."}
    )
    assert any("already resolved" in flag for flag in review["flags"])


def test_a_conservative_refund_pattern_does_not_claim_to_prove_a_false_statement():
    case = load_dataset()[0]["cases"][7]
    review = check_draft(
        case,
        {
            "action": "check_refund",
            "reply_draft": "A refund has been claimed for this transaction. We are checking its status.",
        },
    )
    assert review["version"] == "inr-draft-checks/1.0.2"
    assert review["flags"] == [
        "Refund wording needs review: the case has no verified completed refund."
    ]
    assert review["human_review_required"] is True
