import json
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from ntk.storage import EvidenceStore, atomic_json


def test_failed_serialization_preserves_previous_report_and_removes_temporary_file(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"status": "original"})
    with pytest.raises(TypeError):
        atomic_json(path, {"invalid": object()})
    assert json.loads(path.read_text()) == {"status": "original"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_concurrent_writers_produce_a_complete_report(tmp_path):
    path = tmp_path / "report.json"

    def write(value):
        for _ in range(10):
            atomic_json(path, {"writer": value, "items": [value] * 100})

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(write, ["first", "second"]))
    report = json.loads(path.read_text())
    assert report["items"] == [report["writer"]] * 100
    assert list(tmp_path.iterdir()) == [path]


def test_a_replayed_result_cannot_mutate_the_recording_seen_by_another_request(service):
    case = service.get_case("NTK-001")
    first = service.cached(case, "purpose")
    original = first["result"]["analysis"]["reply_draft"]
    first["result"]["analysis"]["reply_draft"] = "Caller changed the result"
    second = service.cached(case, "purpose")
    assert second["result"]["analysis"]["reply_draft"] == original


def test_store_refuses_path_traversal_keys(tmp_path):
    store = EvidenceStore(tmp_path)
    with pytest.raises(ValueError):
        store.cached("../../outside", "unused")
    assert not (tmp_path / "runs").exists()


def test_selected_experiment_observation_is_used_before_original_and_runtime_wins(tmp_path):
    root = tmp_path / "project"
    selected = root / "reports/experiments/selected/paypal-observation.json"
    original = root / "reports/paypal-observation.json"
    runtime = tmp_path / "runtime"
    atomic_json(original, {"label": "original", "source": {"label": "original"}})
    atomic_json(selected, {"label": "selected", "source": {"label": "selected"}, "id": "selected"})
    store = EvidenceStore(runtime, root=root, experiment="selected")
    assert store.observation()["id"] == "selected"
    assert store.observation()["label"] == "Recorded PayPal sandbox observation"
    assert json.loads(selected.read_text())["label"] == "selected"
    atomic_json(runtime / "paypal-observation.json", {"id": "runtime", "source": {}})
    assert store.observation()["id"] == "runtime"
