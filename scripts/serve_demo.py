"""Run the recorded judge demo without an account; --fresh explicitly enables AWS calls."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.app import create_app
from ntk.config import Settings
from ntk.dataset import ROOT
from ntk.recorded import recorded_dataset, recorded_model
from ntk.storage import read_json_object

DEFAULT_EXPERIMENT = "gpt-oss120b-routing-v21-20261105"


def demo_settings(
    experiment: str, fresh: bool = False, *, base: Settings | None = None
) -> Settings:
    settings = replace(base if base is not None else Settings.from_env(), experiment=experiment)
    folder = ROOT / "reports/experiments" / experiment
    protocol = read_json_object(folder / "protocol.json")
    benchmark = read_json_object(folder / "benchmark.json")
    if benchmark.get("status") != "complete" or not benchmark.get("verified_at"):
        raise ValueError("Select a complete, verified experiment for the judge demo")
    return replace(
        settings,
        model=replace(recorded_model(protocol, settings.model), bedrock_fresh_enabled=fresh),
        dataset_file=recorded_dataset(protocol),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment", help="Recorded experiment; defaults to the configured or current demo"
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Enable fresh calls using the server's AWS credential chain",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    base = Settings.from_env()
    experiment = args.experiment or base.experiment or DEFAULT_EXPERIMENT
    uvicorn.run(
        create_app(demo_settings(experiment, args.fresh, base=base)),
        host=args.host,
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
