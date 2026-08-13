"""Plan-document validation and runtime error paths of ops.apply."""

import json

import pytest
from PIL import Image

from pixshift.ops.apply import apply_plans, load_plan_document


def _step(**overrides):
    step = {"input": "in.png", "command": "convert", "arguments": {}}
    step.update(overrides)
    return step


def test_load_plan_accepts_a_bare_list():
    steps = load_plan_document(json.dumps([_step()]))
    assert steps[0]["command"] == "convert"


def test_load_plan_accepts_an_optimize_results_payload():
    document = {"results": [{"input": "a.png", "plan": {"command": "compress", "arguments": {}}}]}
    steps = load_plan_document(json.dumps(document))
    assert steps == [{"input": "a.png", "command": "compress", "arguments": {}}]


def test_load_plan_accepts_plans_key_and_single_command():
    assert load_plan_document(json.dumps({"plans": [_step()]}))[0]["input"] == "in.png"
    assert load_plan_document(json.dumps(_step()))[0]["command"] == "convert"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("42", "plan_must_be_object_or_array"),
        (json.dumps({"results": 17}), "invalid_optimize_result"),
        (json.dumps({"plans": 5}), "invalid_plans_list"),
        (json.dumps({"neither": True}), "unrecognized_plan_document"),
        (json.dumps(_step(input=None)), "missing_input"),
        (json.dumps(_step(command=None)), "missing_command"),
        (json.dumps(_step(arguments=[1])), "invalid_arguments"),
    ],
)
def test_load_plan_rejects_malformed_documents(raw, message):
    with pytest.raises(ValueError, match=message):
        load_plan_document(raw)


def test_load_plan_skips_failed_entries_in_a_mixed_optimize_batch():
    # A mixed batch must apply its healthy entries, not reject wholesale:
    # non-dict noise and plan-less failures are skipped, not fatal.
    document = json.dumps(
        {
            "results": [
                17,
                {"input": "failed.png"},
                {"input": "ok.png", "plan": {"command": "convert", "arguments": {"to": "webp"}}},
            ]
        }
    )
    steps = load_plan_document(document)
    assert [step["input"] for step in steps] == ["ok.png"]


def test_load_plan_skips_empty_plan_objects_from_error_entries():
    # Since schema 1.1 a failed optimize entry carries plan: {} — an empty
    # dict, not a missing key. One broken file in a scanned directory must
    # not poison the whole optimize-to-apply pipe (found by the e2e sweep).
    document = json.dumps(
        {
            "results": [
                {"input": "broken.png", "plan": {}, "error": "cannot identify image file"},
                {"input": "ok.png", "plan": {"command": "convert", "arguments": {"to": "webp"}}},
            ]
        }
    )
    steps = load_plan_document(document)
    assert [step["input"] for step in steps] == ["ok.png"]


def test_apply_reports_a_missing_input(tmp_path):
    result = apply_plans([_step(input=str(tmp_path / "gone.png"))])
    assert result.ok is False
    assert result.steps[0].error == "input_not_found"


def test_apply_rejects_an_unsupported_command(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(src, format="PNG")
    result = apply_plans([_step(input=str(src), command="rotate")])
    assert result.ok is False
    assert result.steps[0].error == "unsupported_plan_command"


def test_apply_surfaces_engine_errors(tmp_path):
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not an image")
    result = apply_plans([_step(input=str(fake), arguments={"format": "webp"})])
    assert result.ok is False
    assert result.steps[0].error
