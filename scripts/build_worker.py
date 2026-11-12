"""Embed the canonical UI, fixtures and real runs in a small dependency-free Worker."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.config import ModelSettings, Settings
from ntk.contracts import Analysis
from ntk.dataset import ROOT, load_dataset
from ntk.model import request_body
from ntk.policy import ALLOWED_KEYS, MODES, POLICY_VERSION, PURPOSE, project
from ntk.recorded import recorded_dataset, recorded_model


def main(allow_partial=False, experiment=None):
    Settings(experiment=experiment)
    recordings = ROOT / "reports" / "experiments" / experiment if experiment else ROOT / "reports"
    benchmark = json.loads((recordings / "benchmark.json").read_text())
    model_config = ModelSettings()
    dataset_file = ROOT / "data/cases.json"
    if experiment:
        protocol = json.loads((recordings / "protocol.json").read_text())
        model_config = recorded_model(protocol)
        dataset_file = recorded_dataset(protocol)
    document, dataset_hash = load_dataset(dataset_file)
    if benchmark["dataset_sha256"] != dataset_hash:
        raise SystemExit("Dataset changed since evaluation; refusing to bundle mismatched runs")
    if not allow_partial and (
        benchmark["status"] != "complete"
        or len(benchmark["runs"]) != 90
        or not benchmark.get("verified_at")
    ):
        raise SystemExit(
            "Complete all 90 model runs before publication. Use --allow-partial for local development only."
        )
    observation_path = recordings / "paypal-observation.json"
    if not observation_path.exists():
        observation_path = ROOT / "reports/paypal-observation.json"
    observation = json.loads(observation_path.read_text()) if observation_path.exists() else None
    if observation:
        if not (
            all(
                f["sensitivity"] == "task" and f["key"] in ALLOWED_KEYS
                for f in observation["facts"]
            )
        ):
            raise ValueError("Only normalized, allowlisted sandbox facts may be bundled")
    assets = {
        "/": {"body": (ROOT / "web/index.html").read_text(), "type": "text/html; charset=utf-8"}
    }
    for name, mime in [
        ("app.js", "text/javascript"),
        ("style.css", "text/css"),
        ("mark.svg", "image/svg+xml"),
    ]:
        assets["/assets/" + name] = {
            "body": (ROOT / "web" / name).read_text(),
            "type": mime + "; charset=utf-8",
        }
    values = {
        "ASSETS": assets,
        "DATASET": document,
        "DATASET_HASH": dataset_hash,
        "BENCHMARK": benchmark,
        "SEED": observation,
        "MODES": MODES,
        "PURPOSE": PURPOSE,
        "POLICY_VERSION": POLICY_VERSION,
        "ALLOWED_KEYS": sorted(ALLOWED_KEYS),
        "PROMPT_VERSION": benchmark["prompt_version"],
        "OPTIONS": benchmark["settings"],
        "ANALYSIS_SCHEMA": Analysis.model_json_schema(),
        "REQUEST_TEMPLATE": request_body(project(document["cases"][0], "purpose"), model_config),
        "METHODOLOGY": (ROOT / "data/DATASET.md").read_text(),
    }
    source = "// Generated from the canonical source by scripts/build_worker.py. No credentials.\n"
    source += "\n".join(
        f"const {key} = {json.dumps(value, ensure_ascii=False, separators=(',', ':'))};"
        for key, value in values.items()
    )
    extras = (
        json.loads((recordings / "paypal-model-run.json").read_text())
        if (recordings / "paypal-model-run.json").exists()
        else []
    )
    source += (
        "\nconst EXTRA_RUNS = "
        + json.dumps(extras, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    source += "\n" + (ROOT / "hosting/worker-runtime.mjs").read_text()
    (ROOT / "site/worker").mkdir(parents=True, exist_ok=True)
    (ROOT / "site/worker/index.js").write_text(source)
    print(
        json.dumps(
            {
                "worker_bytes": len(source.encode()),
                "real_runs": len(benchmark["runs"]),
                "benchmark_status": benchmark["status"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--experiment")
    args = parser.parse_args()
    main(args.allow_partial, args.experiment)
