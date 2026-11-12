"""Replay the judge walkthrough against an existing local Docker image."""

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_judge_demo import verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="minimera:demo")
    parser.add_argument("--port", type=int, default=10000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a loopback port between 1024 and 65535.")
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", args.port))
        subprocess.run(["docker", "image", "inspect", args.image], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        parser.error("Build the local image first and choose a free loopback port.")
    os.umask(0o077)
    identity = uuid4().hex[:12]
    name = "minimera-verify-" + identity
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "runtime/container-demo" / (stamp + "-" + identity)
    output.mkdir(mode=0o700, parents=True)
    base = f"http://127.0.0.1:{args.port}"
    opener = build_opener(ProxyHandler({}))
    started = False

    def docker(*arguments: str) -> None:
        subprocess.run(["docker", *arguments], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

    def ready() -> None:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                with opener.open(base + "/api/integrity/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError("The owned container did not become ready; inspect container.log.")

    def restart() -> None:
        docker("restart", "--time", "3", name)
        ready()

    try:
        docker(
            "run",
            "--rm",
            "--detach",
            "--name",
            name,
            "--memory=384m",
            "--cpus=1",
            "--publish",
            f"127.0.0.1:{args.port}:10000",
            args.image,
        )
        started = True
        ready()
        success = verify(base, output, restart)
    finally:
        if started:
            with (output / "container.log").open("w", encoding="utf-8") as log:
                subprocess.run(
                    ["docker", "logs", name], stdout=log, stderr=subprocess.STDOUT, check=False
                )
            subprocess.run(
                ["docker", "stop", "--time", "3", name], check=False, stdout=subprocess.DEVNULL
            )
    print("Container report: " + str(output / "browser-report.json"), flush=True)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
