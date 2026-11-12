"""Run Order Integrity locally, or serve the hosted judge simulation."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from ntk.config import Settings
from ntk.integrity.app import create_integrity_app
from ntk.integrity.deployment import is_local_origin, resolve_origin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default="127.0.0.1", choices=("127.0.0.1", "localhost", "::1", "0.0.0.0")
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--origin",
        help="Canonical HTTPS demo origin; defaults to NTK_PUBLIC_ORIGIN, Render hostname, or local loopback.",
    )
    parser.add_argument(
        "--recordings-dir",
        type=Path,
        help="Separate recording directory for a named local rehearsal; existing source recordings stay intact.",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Allow bounded synthetic PayPal Sandbox orders/refunds (never live payments).",
    )
    parser.add_argument(
        "--fresh-ai",
        action="store_true",
        help="Allow at most 30 persisted Bedrock attempts for this experiment.",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Use a port between 1 and 65535.")
    try:
        origin = resolve_origin(args.port, os.environ, args.origin)
    except ValueError as error:
        parser.error(str(error))
    if (args.sandbox or args.fresh_ai) and (args.host == "0.0.0.0" or not is_local_origin(origin)):
        parser.error("Sandbox and fresh Bedrock calls require a loopback-only operator preview.")
    app = create_integrity_app(
        Settings.from_env(),
        sandbox_enabled=args.sandbox,
        fresh_ai=args.fresh_ai,
        origin=origin,
        recordings_dir=args.recordings_dir,
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
