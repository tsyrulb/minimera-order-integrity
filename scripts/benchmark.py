"""Run 30 x 3 real generations sequentially. Resume compatible completed runs."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.contracts import AppError
from ntk.dataset import ROOT
from ntk.evaluation import summarize
from ntk.model import PROMPT_VERSION
from ntk.policy import POLICY_VERSION, project
from ntk.service import create_service
from ntk.storage import atomic_json


async def main(split):
    service = create_service()
    if service.model.config.provider != "ollama" or service.store.experiment is not None:
        raise SystemExit(
            "Use scripts/run_experiment.py for a separately named experiment; the original baseline must be preserved."
        )
    runs = []
    report = {
        "schema_version": "ntk-benchmark/1.0.0",
        "status": "running",
        "model": service.model.config.model,
        "prompt_version": PROMPT_VERSION,
        "policy_version": POLICY_VERSION,
        "dataset_sha256": service.dataset_sha256,
        "settings": service.model.generation_settings,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "30 developer-authored synthetic fixtures with AI assistance; 20 development, 10 fixed heldout. Same model, prompt, options; only context changes. Mode order rotates across cases. Labels are never sent to the model. Failed generations count as incorrect. Not independently blinded; no claims of generalization.",
        "runs": runs,
        "summary": [],
    }
    selected = [c for c in service.document["cases"] if split == "all" or c["split"] == split]
    target = ROOT / "reports/benchmark.json"
    try:
        for i, case in enumerate(selected):
            modes = ["full", "masked", "purpose"]
            modes = modes[i % 3 :] + modes[: i % 3]
            for mode in modes:
                try:
                    result = await service.analyze(case["id"], mode)
                    result.pop("delivery", None)
                    runs.append(result)
                    print(
                        json.dumps(
                            {
                                "case": case["id"],
                                "mode": mode,
                                "status": "ok",
                                "action_correct": result["scores"]["action_correct"],
                                "duration_ms": result["result"]["duration_ms"],
                            }
                        ),
                        flush=True,
                    )
                except AppError as exc:
                    if exc.code in (
                        "MEMORY_GUARD",
                        "MEMORY_UNKNOWN",
                        "OTHER_MODEL_LOADED",
                        "MODEL_BUSY",
                        "MODEL_UNAVAILABLE",
                    ):
                        # Resource problems pause the experiment, rather than
                        # manufacturing model failures or fighting other apps.
                        report["status"] = "paused"
                        report["pause_reason"] = exc.code
                        print(json.dumps({"status": "paused", "reason": exc.code}), flush=True)
                        return
                    runs.append(
                        {
                            "status": "error",
                            "case_id": case["id"],
                            "split": case["split"],
                            "mode": mode,
                            "error": exc.code,
                            "projection": project(case, mode),
                        }
                    )
                    print(
                        json.dumps({"case": case["id"], "mode": mode, "error": exc.code}),
                        flush=True,
                    )
                finally:
                    report["summary"] = summarize(runs)
                    atomic_json(target, report)
        report["status"] = "complete"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        report["summary"] = summarize(runs)
        atomic_json(target, report)
        await service.model.unload()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "heldout", "all"], default="all")
    asyncio.run(main(parser.parse_args().split))
