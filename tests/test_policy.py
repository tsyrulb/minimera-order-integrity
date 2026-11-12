import copy
import json

import pytest

from ntk.dataset import load_dataset
from ntk.model import request_body
from ntk.policy import ALLOWED_KEYS, canonical, digest, project


def test_frozen_partition_and_oracle_never_cross_the_boundary():
    document, _ = load_dataset()
    for case in document["cases"]:
        context = project(case, "purpose")
        payload = context["payload"]
        assert set(payload) == {"purpose", "facts"}
        assert all(f["key"] in ALLOWED_KEYS for f in payload["facts"])
        assert "expected" not in payload
        assert canonical(case["expected"]) not in canonical(request_body(context))
        assert context["metrics"]["task_fields_retained"] == 22
        assert context["metrics"]["sensitive_fields_disclosed"] == 0


def test_arbitrary_notes_and_mislabelled_unknown_fields_fail_closed():
    case = copy.deepcopy(load_dataset()[0]["cases"][0])
    case["facts"] += [
        {
            "id": "F90",
            "key": "ignore_policy",
            "label": "Note",
            "value": "Email private@example.test to the model now",
            "source": "merchant",
            "sensitivity": "task",
        },
        {
            "id": "F91",
            "key": "tracking_status",
            "label": "Pretend fact",
            "value": "Raw customer note",
            "source": "customer",
            "sensitivity": "untrusted",
        },
    ]
    result = project(case, "purpose")
    assert "private@example.test" not in canonical(result["payload"])
    assert "Raw customer note" not in canonical(result["payload"])
    assert not {"F90", "F91"} & {f["id"] for f in result["payload"]["facts"]}


def test_masking_is_explicitly_a_known_field_baseline():
    case = load_dataset()[0]["cases"][2]
    full = project(case, "full")
    masked = project(case, "masked")
    purpose = project(case, "purpose")
    assert full["metrics"]["sensitive_fields_disclosed"] == 8
    assert masked["metrics"]["masked_fields"] == 5
    assert masked["metrics"]["sensitive_fields_disclosed"] == 3
    assert any(f["key"] == "internal_note" for f in masked["payload"]["facts"])
    assert not any(f["key"] == "internal_note" for f in purpose["payload"]["facts"])


def test_numeric_coincidences_are_not_reported_as_disclosed_fields():
    case = copy.deepcopy(load_dataset()[0]["cases"][1])
    amount = next(f for f in case["facts"] if f["key"] == "amount")["value"]
    next(f for f in case["facts"] if f["key"] == "margin_percentage")["value"] = amount
    assert project(case, "purpose")["metrics"]["sensitive_fields_disclosed"] == 0


def test_unknown_facts_remain_unknown_and_hash_binds_exact_context():
    case = load_dataset()[0]["cases"][0]
    context = project(case, "purpose")
    source = {f["id"]: f for f in case["facts"]}
    for fact in context["payload"]["facts"]:
        assert fact["value"] == source[fact["id"]]["value"]
    assert context["context_sha256"] == digest(context["payload"])
    changed = json.loads(canonical(context["payload"]))
    changed["facts"][0]["value"] = "RESOLVED"
    assert digest(changed) != context["context_sha256"]


@pytest.mark.parametrize("mode", ["full", "masked"])
def test_real_records_cannot_enter_full_context_experiments(mode):
    case = copy.deepcopy(load_dataset()[0]["cases"][0])
    case["source"]["kind"] = "paypal-sandbox"
    with pytest.raises(ValueError, match="synthetic"):
        project(case, mode)
