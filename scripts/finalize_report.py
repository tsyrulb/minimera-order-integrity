"""Verify recorded requests and add deterministic review metadata; never edit model outputs."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.dataset import ROOT, load_dataset
from ntk.evaluation import score, summarize
from ntk.policy import canonical, digest, project
from ntk.review import check_draft
from ntk.storage import atomic_json


def main():
    path = ROOT / "reports/benchmark.json"
    report = json.loads(path.read_text())
    data, data_hash = load_dataset()
    if not (report["dataset_sha256"] == data_hash):
        raise ValueError("Report dataset hash does not match the fixtures")
    if not (report["status"] == "complete" and len(report["runs"]) == 90):
        raise ValueError("Report must contain all 90 completed attempts")
    successful = [r for r in report["runs"] if r["status"] == "ok"]
    if not (len({r["result"]["model"]["digest"] for r in successful}) == 1):
        raise ValueError("Model digests differ across successful runs")
    if not (all(r["result"]["model"]["model"] == report["model"] for r in successful)):
        raise ValueError("Model identities differ across runs")
    if not (all(r["result"]["prompt_version"] == report["prompt_version"] for r in successful)):
        raise ValueError("Prompt versions differ across runs")
    if not (all(r["result"]["settings"] == report["settings"] for r in successful)):
        raise ValueError("Generation settings differ across runs")
    cases = {c["id"]: c for c in data["cases"]}
    if not (len({(r["case_id"], r["mode"]) for r in report["runs"]}) == 90):
        raise ValueError("Every case and mode must occur once")
    for run in report["runs"]:
        current = cases[run["case_id"]]
        projection = project(current, run["mode"])
        if not (projection == run["projection"]):
            raise ValueError("Recorded projection does not match its policy")
        if run["status"] == "ok":
            if not (digest(run["result"]["request"]) == run["result"]["request_sha256"]):
                raise ValueError("Recorded request hash does not match its body")
            messages = run["result"]["request"].get(
                "messages", run["result"]["request"].get("input")
            )
            if not (messages[1]["content"] == canonical(projection["payload"])):
                raise ValueError("Recorded request does not contain the projected context")
            if not (score(current, projection, run["result"]) == run["scores"]):
                raise ValueError("Recorded scores do not match the measured output")
            run["result"]["hash_encoding"] = (
                "SHA-256 of compact UTF-8 JSON with recursively sorted object keys; headers excluded"
            )
            run["result"]["model"]["identity_basis"] = (
                "Ollama installed model manifest digest; not an attested execution measurement"
            )
            run["review"] = check_draft(current, run["result"]["analysis"])
    report["summary"] = summarize(report["runs"])
    protocol = json.loads((ROOT / "data/PROTOCOL.json").read_text())
    if not (protocol["model"] == report["model"] and protocol["settings"] == report["settings"]):
        raise ValueError("Report model and settings differ from the declared protocol")
    if not (
        protocol["prompt_version"] == report["prompt_version"]
        and protocol["policy_version"] == report["policy_version"]
    ):
        raise ValueError("Report prompt and policy differ from the declared protocol")
    if not (
        protocol["recorded_at"]
        < min(
            r["created_at"]
            for r in report["runs"]
            if r["split"] == "heldout" and r["status"] == "ok"
        )
    ):
        raise ValueError("The reporting protocol must predate its held-out runs")
    selected = {s["mode"]: s for s in report["summary"] if s["split"] == "heldout"}
    baseline, candidate = selected["full"], selected["purpose"]
    checks = {
        "baseline_action_floor": baseline["action_accuracy"]
        >= protocol["gates"]["minimum_action_accuracy"],
        "candidate_action_floor": candidate["action_accuracy"]
        >= protocol["gates"]["minimum_action_accuracy"],
        "candidate_missing_evidence_floor": candidate["missing_f1"]
        >= protocol["gates"]["minimum_missing_f1"],
        "candidate_valid_outputs": candidate["valid_outputs"] == candidate["attempts"],
        "candidate_no_unrelated_fields": candidate["mean_sensitive_fields_sent"] == 0,
        "no_action_accuracy_regression": candidate["action_correct"] >= baseline["action_correct"],
    }
    report["workflow_check"] = {
        "protocol": protocol,
        "checks": checks,
        "passes_fixture_gates": all(checks.values()),
        "interpretation": "Passes these fixed fixture gates only; does not establish generalization or compliance."
        if all(checks.values())
        else "The fixed fixture gates are not met. Do not infer that this model and policy are ready for operational use.",
        "scope": "Local project thresholds, not regulatory standards or independent certification.",
    }
    report["verified_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(path, report)
    rows = [
        "# Recorded evaluation",
        "",
        report["methodology"],
        "",
        f"Model: `{report['model']}`. Dataset SHA-256: `{data_hash}`.",
        "",
        "| Split | Context | Action accuracy | Missing evidence F1 | Unrelated fields sent | Valid outputs |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for s in report["summary"]:
        rows.append(
            f"| {s['split']} | {s['mode']} | {s['action_correct']}/{s['attempts']} | {s['missing_f1']:.3f} | {s['mean_sensitive_fields_sent']:.1f} | {s['valid_outputs']}/{s['attempts']} |"
        )
    rows += [
        "",
        report["workflow_check"]["interpretation"],
        "",
        "Raw outputs, citation coverage, exact-value checks, all failures, settings and exact requests are included in benchmark.json. Review patterns were applied after generation; no model response was rewritten.",
        "",
    ]
    (ROOT / "reports/RESULTS.md").write_text("\n".join(rows))
    print(
        json.dumps(
            {
                "verified_runs": len(report["runs"]),
                "workflow_check": report["workflow_check"]["passes_fixture_gates"],
                "heldout": list(selected.values()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
