import json
from dataclasses import replace

from ntk.config import DEFAULT_BEDROCK_MODEL, ModelSettings, Settings
from ntk.dataset import ROOT, load_dataset, public_case
from ntk.model_requests import PROMPT_VERSION, request_body
from ntk.policy import digest, project
from ntk.prompts import EXAMPLES_PROMPT_VERSION, ROUTING_PROMPT_VERSION
from ntk.reference import reference_label
from ntk.service import create_service


def test_prompt_selection_changes_exact_request_and_cache_without_changing_context(tmp_path):
    case = load_dataset()[0]["cases"][0]
    old = ModelSettings(provider="bedrock", model=DEFAULT_BEDROCK_MODEL)
    new = replace(old, prompt_version=ROUTING_PROMPT_VERSION)
    projection = project(case, "purpose")
    before, after = request_body(projection, old), request_body(projection, new)
    assert before["body"]["messages"] == after["body"]["messages"]
    assert before["body"]["outputConfig"] == after["body"]["outputConfig"]
    assert before["body"]["inferenceConfig"] == after["body"]["inferenceConfig"]
    assert digest(before) != digest(after)
    a = create_service(Settings(runtime_dir=tmp_path, model=old))
    b = create_service(Settings(runtime_dir=tmp_path, model=new))
    assert a.key(case, "purpose") != b.key(case, "purpose")
    assert old.prompt_version == PROMPT_VERSION


def test_new_dataset_preserves_development_cases_and_excludes_reference_labels_from_requests():
    original, old_hash = load_dataset()
    updated, new_hash = load_dataset(ROOT / "data/cases-v2.json")
    assert new_hash != old_hash
    assert [c for c in updated["cases"] if c["split"] == "development"] == [
        c for c in original["cases"] if c["split"] == "development"
    ]
    reporting = [c for c in updated["cases"] if c["split"] == "heldout"]
    assert {c["id"] for c in reporting}.isdisjoint(c["id"] for c in original["cases"])
    assert updated["evaluation"]["reporting_set_reused"] is False
    config = ModelSettings(
        provider="bedrock", model=DEFAULT_BEDROCK_MODEL, prompt_version=ROUTING_PROMPT_VERSION
    )
    for case in reporting:
        assert case["expected"] == reference_label(case)
        assert "expected" not in public_case(case)
        for mode in ("full", "masked", "purpose"):
            body = request_body(project(case, mode), config)
            user = json.loads(body["body"]["messages"][0]["content"][0]["text"])
            assert set(user) == {"purpose", "facts"}
            assert all(set(fact) == {"id", "key", "value", "source"} for fact in user["facts"])


def test_evaluation_oracle_agrees_with_original_development_action_and_missing_labels():
    for case in load_dataset()[0]["cases"]:
        if case["split"] == "development":
            reference = reference_label(case)
            assert reference["action"] == case["expected"]["action"], case["id"]
            assert set(reference["missing_evidence"]) == set(
                case["expected"]["missing_evidence"]
            ), case["id"]


def test_dataset_and_prompt_configuration_reaches_the_service_without_aws_lookup(tmp_path):
    settings = Settings.from_env(
        {
            "NTK_PROVIDER": "bedrock",
            "NTK_PROMPT_VERSION": ROUTING_PROMPT_VERSION,
            "NTK_DATASET_FILE": str(ROOT / "data/cases-v2.json"),
            "NTK_RUNTIME_DIR": str(tmp_path),
            "NTK_EXPERIMENT": "new-dataset-test",
        }
    )
    service = create_service(settings)
    assert service.document["version"] == "ntk-fixtures/2.0.0"
    assert service.model.config.prompt_version == ROUTING_PROMPT_VERSION
    assert service.get_case("NTK-031")["split"] == "heldout"
    assert not tmp_path.joinpath("experiments").exists()


def test_example_prompt_only_renames_provenance_without_losing_facts_or_changing_projection():
    case = load_dataset()[0]["cases"][3]
    config = ModelSettings(
        provider="bedrock", model=DEFAULT_BEDROCK_MODEL, prompt_version=EXAMPLES_PROMPT_VERSION
    )
    for mode in ("full", "masked", "purpose"):
        projection = project(case, mode)
        before = json.dumps(projection, sort_keys=True)
        request = request_body(projection, config)
        outgoing = json.loads(request["body"]["messages"][0]["content"][0]["text"])
        assert len(outgoing["facts"]) == len(projection["payload"]["facts"])
        restored = {
            "purpose": outgoing["purpose"],
            "facts": [
                {"id": f["id"], "key": f["key"], "value": f["value"], "source": f["record_origin"]}
                for f in outgoing["facts"]
            ],
        }
        assert restored == projection["payload"]
        assert json.dumps(projection, sort_keys=True) == before
