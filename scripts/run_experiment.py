"""Run a separately named Bedrock experiment without rewriting the original benchmark."""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.config import Settings
from ntk.experiments import ExperimentRunner
from ntk.service import create_service


async def main(experiment: str, split: str, cases: str | None) -> None:
    settings = Settings.from_env()
    if settings.model.provider != "bedrock":
        raise SystemExit("Set NTK_PROVIDER=bedrock for this experiment")
    settings = replace(
        settings,
        experiment=experiment,
        model=replace(settings.model, bedrock_fresh_enabled=True),
    )
    runner = ExperimentRunner(create_service(settings))
    result = await runner.run(split=split, case_ids=set(cases.split(",")) if cases else None)
    print(
        json.dumps(
            {
                "experiment": experiment,
                "status": result["status"],
                "runs": len(result["runs"]),
                "report": str(runner.path),
                "summary": result["summary"],
                "workflow_check": result.get("workflow_check", {}).get("passes_fixture_gates"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--split", choices=["development", "heldout", "all"], default="all")
    parser.add_argument(
        "--cases", help="Comma-separated fixed development fixture IDs for a short smoke test"
    )
    args = parser.parse_args()
    asyncio.run(main(args.experiment, args.split, args.cases))
