"""Freeze new reporting fixtures before any model evaluation on them.

The creator knows these synthetic cases. This is a model-unqueried reporting
set, not independent or blinded human data. Original fixtures are never changed.
"""

import copy
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.dataset import ROOT, load_dataset
from ntk.reference import reference_label

SCENARIOS = [
    (
        "Closed case takes precedence",
        "Closed despite unrelated shipment and payment problems.",
        {
            "case_status": "CLOSED",
            "verified_capture_link": False,
            "deadline_passed": True,
            "refund_status": "PENDING",
        },
    ),
    (
        "Waiting on buyer takes precedence",
        "A buyer-response state overrides a delivery mismatch and pending refund.",
        {
            "case_status": "WAITING_FOR_BUYER_RESPONSE",
            "destination_match": False,
            "refund_status": "PENDING",
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
        },
    ),
    (
        "Unknown payment link",
        "A pending refund cannot override an unknown case-to-capture association.",
        {"verified_capture_link": None, "refund_status": "PENDING"},
    ),
    (
        "Unknown deadline with delivery",
        "Complete delivery facts do not resolve an unknown response window.",
        {
            "deadline_passed": None,
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
            "destination_match": True,
        },
    ),
    (
        "Conflicting delivery and refund",
        "Contradictory delivery evidence takes precedence over a pending refund.",
        {
            "destination_match": False,
            "conflicting_tracking": True,
            "refund_status": "PENDING",
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
        },
    ),
    (
        "Claimed refund with delivery",
        "A merchant's unverified refund claim needs reconciliation before shipment triage.",
        {
            "refund_status": "MERCHANT_CLAIMED",
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
            "destination_match": True,
        },
    ),
    (
        "Completed partial refund",
        "A completed partial refund is not evidence of full repayment.",
        {
            "refund_status": "COMPLETED",
            "refund_amount": "12.25",
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
            "destination_match": True,
        },
    ),
    (
        "Complete carrier evidence",
        "A carrier record, matching destination and delivery document are available.",
        {
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
            "destination_match": True,
        },
    ),
    (
        "Destination still unknown",
        "A delivery document does not establish that its destination matches this order.",
        {
            "tracking_status": "DELIVERED",
            "tracking_source": "carrier",
            "tracking_number_available": True,
            "proof_of_delivery_available": True,
            "destination_match": None,
        },
    ),
    (
        "Shipment still in transit",
        "An independent in-transit event is not confirmed delivery.",
        {
            "tracking_status": "IN_TRANSIT",
            "tracking_source": "carrier",
            "tracking_number_available": True,
        },
    ),
]


def main() -> None:
    target = ROOT / "data/cases-v2.json"
    if target.exists():
        raise SystemExit("The validation fixture snapshot already exists; never overwrite it")
    original, original_hash = load_dataset()
    development = [copy.deepcopy(c) for c in original["cases"] if c["split"] == "development"]
    audit = []
    for case in development:
        calculated = reference_label(case)
        expected = case["expected"]
        matches = calculated["action"] == expected["action"] and set(
            calculated["missing_evidence"]
        ) == set(expected["missing_evidence"])
        audit.append(
            {
                "case_id": case["id"],
                "action_and_missing_evidence_match": matches,
                "calculated": calculated,
                "original": expected,
            }
        )
    if not all(row["action_and_missing_evidence_match"] for row in audit):
        raise SystemExit("Original development labels disagree with the explicit rubric")

    reporting = []
    for number, (title, story, changes) in enumerate(SCENARIOS, 31):
        case = copy.deepcopy(original["cases"][0])
        case.update(id=f"NTK-{number:03d}", label=title, story=story, split="heldout")
        case["source"] = {
            "kind": "synthetic",
            "label": "New reporting fixture v2; developer authored",
        }
        currency = ("USD", "EUR", "GBP")[number % 3]
        values = {
            "amount": f"{80 + number}.90",
            "currency": currency,
            "refund_amount": f"{80 + number}.90" if changes.get("refund_status") else None,
            "refund_currency": currency if changes.get("refund_status") else None,
            "respond_by": "2026-11-10T12:00:00Z",
            "dispute_opened_date": "2026-11-03T10:00:00Z",
            "tracking_delivery_date": "2026-11-02T10:00:00Z"
            if changes.get("tracking_status") == "DELIVERED"
            else None,
            "customer_name": f"Synthetic Customer {number}",
            "customer_email": f"buyer{number}@minimera-validation.example",
            "customer_phone": f"+1-202-555-01{number:02d}",
            "loyalty_id": f"VALIDATION-LOYALTY-{number}",
        }
        values.update(changes)
        if not values.keys() <= {fact["key"] for fact in case["facts"]}:
            raise ValueError("A reporting variant references an unknown fact key")
        for fact in case["facts"]:
            if fact["key"] in values:
                fact["value"] = values[fact["key"]]
        # New field IDs and order prevent reliance on the old fixed F-number map.
        rng = random.Random(2026110500 + number)
        ids = list(range(1, len(case["facts"]) + 1))
        rng.shuffle(ids)
        for fact, identifier in zip(case["facts"], ids, strict=True):
            fact["id"] = f"F{identifier:02d}"
        rng.shuffle(case["facts"])
        case["expected"] = reference_label(case)
        reporting.append(case)

    recorded_at = datetime.now(timezone.utc).isoformat()
    document = {
        "version": "ntk-fixtures/2.0.0",
        "authorship": "Developer-authored synthetic cases with AI assistance. References are calculated from the explicit project rubric, not independent human adjudication.",
        "as_of": "2026-11-05",
        "evaluation": {
            "recorded_at": recorded_at,
            "reporting_set_reused": False,
            "development_set_reused": True,
            "original_dataset_sha256": original_hash,
            "reporting_case_ids": [c["id"] for c in reporting],
            "methodology": "20 original development fixtures and 10 newly constructed reporting variants, frozen before model calls on the new variants. Only development outputs may guide prompt selection. Reporting variants permute field IDs/order and vary amounts, currencies and rule precedence. Developer/AI authored and known to their creator, not independently adjudicated or blinded; previous model has not been queried on the new reporting variants. Reference routing is evaluated separately and never substituted for model output. No generalization or compliance claim.",
        },
        "cases": development + reporting,
    }
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    loaded, sha = load_dataset(target)
    report = {
        "recorded_at": recorded_at,
        "scope": "20 original development cases only",
        "review_basis": "Programmatic consistency with explicit project rubric; not independent human adjudication",
        "all_labels_match": True,
        "cases": audit,
        "new_dataset_sha256": sha,
        "new_reporting_case_count": len(reporting),
    }
    audit_path = ROOT / "reports/development-label-audit-20261105.json"
    with audit_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
    print(
        json.dumps(
            {
                "dataset": str(target),
                "sha256": sha,
                "cases": len(loaded["cases"]),
                "development_labels_matching": len(audit),
            }
        )
    )


if __name__ == "__main__":
    main()
