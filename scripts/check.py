"""Run the repository's local quality checks sequentially, without inference."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    env = dict(
        os.environ,
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONDONTWRITEBYTECODE="1",
        NTK_TEST_PYTHON=sys.executable,
    )
    python = sys.executable
    commands = [
        [python, "-m", "ruff", "check", "ntk", "scripts", "tests"],
        [python, "-m", "ruff", "format", "--check", "ntk", "scripts", "tests"],
        [python, "-m", "mypy"],
        [python, "-m", "pytest", "-q"],
        ["node", "--check", "web/app.js"],
        [python, "scripts/build_worker.py"],
        ["node", "tests/check_worker.mjs"],
    ]
    for path in sorted((ROOT / "reports/experiments").glob("*/benchmark.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") == "complete":
            commands.extend(
                [
                    [python, "scripts/build_worker.py", "--experiment", path.parent.name],
                    ["node", "tests/check_worker.mjs", path.parent.name],
                ]
            )
    for command in commands:
        print("\n" + shlex.join(command), flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        except FileNotFoundError:
            raise SystemExit(
                "Install the development requirements and Node.js 22+ before running all checks."
            ) from None
        if result.returncode:
            raise SystemExit(result.returncode)
    print("\nAll quality checks passed. No model was loaded or external API called.", flush=True)


if __name__ == "__main__":
    main()
