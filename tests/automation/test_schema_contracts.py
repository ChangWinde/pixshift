"""Validate live JSON outputs against the published schema contracts."""

import json
from pathlib import Path

import jsonschema
import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validate(payload: dict, schema_name: str) -> None:
    jsonschema.validate(
        payload,
        _schema(schema_name),
        format_checker=jsonschema.FormatChecker(),
    )


def _run(args, input_text=None):
    runner = CliRunner()
    result = runner.invoke(cli, args, input=input_text)
    assert result.exit_code == 0, result.output
    return json.loads(result.output.strip())


def test_all_schema_files_are_valid_json_schema():
    validator = jsonschema.Draft202012Validator
    for schema_path in sorted(SCHEMA_DIR.glob("*.json")):
        validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))


def test_tools_payload_matches_schema():
    payload = _run(["tools", "--json"])
    _validate(payload, "tools.json")
    _validate(payload, "envelope.json")


def test_optimize_and_apply_payloads_match_schema(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (48, 48), (90, 90, 20)).save(src, format="PNG")

    optimize_payload = _run(["optimize", str(src), "--json"])
    _validate(optimize_payload, "optimize.json")
    _validate(optimize_payload, "envelope.json")

    apply_payload = _run(
        ["apply", "--plan", "-", "--output", str(tmp_path / "out"), "--json"],
        input_text=json.dumps(optimize_payload),
    )
    _validate(apply_payload, "apply.json")
    _validate(apply_payload, "envelope.json")


def test_prep_manifest_hash_payloads_match_schema(tmp_path):
    src = tmp_path / "img.jpg"
    Image.new("RGB", (120, 80), (10, 10, 120)).save(src, format="JPEG")

    prep_payload = _run(["prep", str(src), "-o", str(tmp_path / "dist"), "--json"])
    _validate(prep_payload, "prep.json")
    _validate(prep_payload, "envelope.json")

    manifest_payload = _run(["manifest", str(src), "--json"])
    _validate(manifest_payload, "manifest.json")
    _validate(manifest_payload, "envelope.json")

    hash_payload = _run(["hash", str(src), "--json"])
    _validate(hash_payload, "hash.json")
    _validate(hash_payload, "envelope.json")


def test_verify_payload_matches_schema(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    image = Image.new("RGB", (24, 18), (10, 80, 160))
    image.save(source)
    image.save(candidate)

    payload = _run(["verify", str(source), str(candidate), "--json"])
    _validate(payload, "verify.json")
    _validate(payload, "envelope.json")


@pytest.mark.parametrize(
    "args",
    [
        ["formats", "--json"],
        ["doctor", "--json"],
    ],
)
def test_system_payloads_match_envelope(args):
    payload = _run(args)
    _validate(payload, "envelope.json")
