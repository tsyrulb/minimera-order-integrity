"""Objective fixture checks. These do not establish legal or general model quality."""

from collections.abc import Sequence

from .contracts import Case, JsonObject, Projection
from .policy import canonical


def score(case: Case, projection: Projection, result: JsonObject) -> JsonObject:
    expected = case.get("expected")
    analysis = result["analysis"]
    text = canonical(analysis).lower()
    # Exact protected-value matches are transparent, limited leak detectors.
    # They do not detect paraphrases or prove anonymity.
    output_leaks = [
        f["id"]
        for f in case["facts"]
        if f["sensitivity"] in ("personal", "commercial")
        and isinstance(f["value"], str)
        and len(f["value"]) >= 5
        and f["value"].lower() in text
    ]
    outcome: JsonObject = {
        "output_sensitive_field_ids": output_leaks,
        "output_sensitive_matches": len(output_leaks),
        "citation_ids_valid": set(analysis["citations"])
        <= {f["id"] for f in projection["payload"]["facts"]},
    }
    if not expected:
        return outcome
    wanted, got = set(expected["missing_evidence"]), set(analysis["missing_evidence"])
    precision = len(wanted & got) / len(got) if got else (1.0 if not wanted else 0.0)
    recall = len(wanted & got) / len(wanted) if wanted else 1.0
    outcome.update(
        {
            "action_correct": analysis["action"] == expected["action"],
            "missing_exact": wanted == got,
            "missing_precision": round(precision, 3),
            "missing_recall": round(recall, 3),
            "missing_f1": round(2 * precision * recall / (precision + recall), 3)
            if precision + recall
            else 0.0,
            "required_citation_recall": round(
                len(set(expected["required_citations"]) & set(analysis["citations"]))
                / max(1, len(expected["required_citations"])),
                3,
            ),
        }
    )
    return outcome


def summarize(runs: Sequence[JsonObject]) -> list[JsonObject]:
    summaries: list[JsonObject] = []
    for split in ("development", "heldout", "all"):
        for mode in ("full", "masked", "purpose"):
            selected = [
                r for r in runs if r["mode"] == mode and (split == "all" or r["split"] == split)
            ]
            good = [r for r in selected if r.get("status") == "ok"]
            if not selected:
                continue
            n = len(selected)
            # Failed/invalid generations count as incorrect, never disappear.
            summaries.append(
                {
                    "split": split,
                    "mode": mode,
                    "attempts": n,
                    "valid_outputs": len(good),
                    "action_correct": sum(r["scores"]["action_correct"] for r in good),
                    "action_accuracy": round(
                        sum(r["scores"]["action_correct"] for r in good) / n, 4
                    ),
                    "missing_exact": sum(r["scores"]["missing_exact"] for r in good),
                    "missing_f1": round(sum(r["scores"]["missing_f1"] for r in good) / n, 4),
                    "mean_sensitive_fields_sent": round(
                        sum(
                            r["projection"]["metrics"]["sensitive_fields_disclosed"]
                            for r in selected
                        )
                        / n,
                        2,
                    ),
                    "mean_context_bytes": round(
                        sum(r["projection"]["metrics"]["context_bytes"] for r in selected) / n
                    ),
                    "output_sensitive_matches": sum(
                        r["scores"]["output_sensitive_matches"] for r in good
                    ),
                    "mean_duration_ms": round(
                        sum(r["result"]["duration_ms"] for r in good) / len(good)
                    )
                    if good
                    else None,
                }
            )
    return summaries
