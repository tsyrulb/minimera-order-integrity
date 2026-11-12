import copy
import hashlib
import json
import subprocess
import sys

import pytest

from ntk.dataset import ROOT, load_dataset
from ntk.evaluation import score, summarize
from ntk.model import request_body
from ntk.policy import digest, project


def test_refactor_preserves_every_recorded_request_projection_score_and_cache_key(service):
    report = json.loads((ROOT / "reports/benchmark.json").read_text())
    assert len(report["runs"]) == 90
    assert report["dataset_sha256"] == service.dataset_sha256
    for run in report["runs"]:
        case = service.get_case(run["case_id"])
        projection = project(case, run["mode"])
        assert projection == run["projection"]
        assert request_body(projection) == run["result"]["request"]
        assert digest(request_body(projection)) == run["result"]["request_sha256"]
        assert service.key(case, run["mode"]) == run["cache_key"]
        assert score(case, projection, run["result"]) == run["scores"]
    assert summarize(report["runs"]) == report["summary"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("data/cases.json", "46129d3912881acf7da16685b6094d3d5541a33af1f1e26a28c334e8f8732b98"),
        ("data/PROTOCOL.json", "def0821f00b3e5df6687ebe173b54fb79314be0ae8e5d792931461ff02370cd1"),
        (
            "reports/benchmark.json",
            "aba068eb7642b48526521ab8591990fcf4c19a6d46dbb81cc3b993e0966339e1",
        ),
        (
            "reports/paypal-model-run.json",
            "c2c93cb45ed72caf9196f371da92095347c7a09af40c1a6a01b61c89db838356",
        ),
        (
            "reports/paypal-observation.json",
            "851f740709e7ed549ac0c41da12a217d216e791a759c78d43b43fe1366a9cade",
        ),
        (
            "reports/experiments/qwen3-next-bedrock-20261104/benchmark.json",
            "421a6c1e938f4fcb0df1a6f2b1558232d9fb9b359a9813a22f6ce238414160d7",
        ),
        (
            "reports/experiments/qwen3-next-bedrock-20261104/protocol.json",
            "225dc9087c29aaa96c4e567864ab64f685fab60aeb085b057e5887b4966f8363",
        ),
    ],
)
def test_original_experimental_artifacts_are_unchanged(path, expected):
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("fault", ["duplicate_case", "partition", "citation", "task_key", "source"])
def test_invalid_fixture_invariants_raise_explicit_errors(tmp_path, fault):
    data = copy.deepcopy(load_dataset()[0])
    case = data["cases"][0]
    if fault == "duplicate_case":
        case["id"] = data["cases"][1]["id"]
    elif fault == "partition":
        case["split"] = "heldout"
    elif fault == "citation":
        case["expected"]["required_citations"] = ["F99"]
    elif fault == "task_key":
        case["facts"][0]["key"] = "unknown_task_key"
    else:
        case["source"]["kind"] = "paypal-sandbox"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_dataset(path)


def test_dataset_validation_remains_active_under_python_optimization(tmp_path):
    data = copy.deepcopy(load_dataset()[0])
    data["cases"] = []
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    program = """from pathlib import Path
import sys
from ntk.dataset import load_dataset
try:
    load_dataset(Path(sys.argv[1]))
except ValueError:
    sys.exit(0)
sys.exit('Invalid fixture was accepted under -O')
"""
    subprocess.run(
        [sys.executable, "-O", "-c", program, str(path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=15,
    )


@pytest.mark.parametrize("fault", ["dataset_hash", "request_hash"])
def test_finalizer_refuses_invalid_evidence_under_optimization_without_rewriting_it(
    tmp_path, fault
):
    report = json.loads((ROOT / "reports/benchmark.json").read_text())
    if fault == "dataset_hash":
        report["dataset_sha256"] = "incorrect"
    else:
        report["runs"][0]["result"]["request_sha256"] = "incorrect"
    path = tmp_path / "reports/benchmark.json"
    path.parent.mkdir()
    original = json.dumps(report).encode()
    path.write_bytes(original)
    program = """import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location('finalizer', 'scripts/finalize_report.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path(sys.argv[1])
try:
    module.main()
except ValueError:
    sys.exit(0)
sys.exit('Invalid evidence was accepted under -O')
"""
    subprocess.run(
        [sys.executable, "-O", "-c", program, str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert path.read_bytes() == original
