"""Open a single-use local window; Sandbox credentials stay outside chat and git."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ntk.dataset import ROOT
from ntk.integrity.setup import serve_setup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--open", action="store_true", help="Open the local form in your default browser."
    )
    args = parser.parse_args()
    path = ROOT / "private/paypal-sandbox.env"
    if serve_setup(path, open_browser=args.open):
        print(
            "Sandbox connection verified. Owner-only credentials saved in private/paypal-sandbox.env."
        )
    else:
        print("Setup window expired. No new credentials saved.")


if __name__ == "__main__":
    main()
