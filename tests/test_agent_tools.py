"""Tests for the agent-facing tools/apply/prep/manifest/hash commands."""

import hashlib
import json

from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.core.tool_catalog import TOOL_CATALOG


def _payload(result):
    return json.loads(result.output.strip())


def test_tools_catalog_lists_annotations():
    runner = CliRunner()
    result = runner.invoke(cli, ["tools", "--json"])
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["command"] == "tools"
    assert payload["ok"] is True
    assert payload["total"] == len(TOOL_CATALOG)
    names = {tool["name"] for tool in payload["tools"]}
    assert {"convert", "apply", "prep", "manifest", "hash", "tools"} <= names
    for tool in payload["tools"]:
        annotations = tool["annotations"]
        assert annotations["openWorldHint"] is False
        assert isinstance(annotations["readOnlyHint"], bool)
        assert isinstance(annotations["destructiveHint"], bool)
        assert isinstance(annotations["idempotentHint"], bool)
    dedup = next(tool for tool in payload["tools"] if tool["name"] == "dedup")
    assert dedup["annotations"]["destructiveHint"] is True


def test_optimize_plan_apply_end_to_end(tmp_path):
    src = tmp_path / "photo.png"
    Image.new("RGB", (64, 48), (200, 40, 40)).save(src, format="PNG")

    runner = CliRunner()
    optimize_result = runner.invoke(cli, ["optimize", str(src), "--json"])
    assert optimize_result.exit_code == 0
    optimize_payload = _payload(optimize_result)
    plan_document = json.dumps(optimize_payload)

    out_dir = tmp_path / "out"
    apply_result = runner.invoke(
        cli,
        ["apply", "--plan", "-", "--output", str(out_dir), "--json"],
        input=plan_document,
    )
    assert apply_result.exit_code == 0
    apply_payload = _payload(apply_result)
    assert apply_payload["command"] == "apply"
    assert apply_payload["ok"] is True
    assert apply_payload["total"] == 1
    step = apply_payload["steps"][0]
    assert step["ok"] is True
    assert step["output"]

    verify = runner.invoke(cli, ["hash", str(out_dir), "-r", "--json"])
    assert verify.exit_code == 0
    verify_payload = _payload(verify)
    assert verify_payload["total"] >= 1
    assert all(item["digest"] for item in verify_payload["files"])


def test_apply_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (32, 32), (10, 60, 90)).save(src, format="PNG")
    plan = {"input": str(src), "command": "convert", "arguments": {"to": "webp"}}
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["apply", "--plan", "-", "--output", str(out_dir), "--dry-run", "--json"],
        input=json.dumps(plan),
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["dry_run"] is True
    assert payload["ok"] is True
    assert not out_dir.exists() or not any(out_dir.iterdir())


def test_apply_compress_without_output_uses_derivative_name(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGB", (32, 32), (200, 200, 10)).save(src, format="PNG")
    plan = {
        "input": str(src),
        "command": "compress",
        "arguments": {"preset": "lossless"},
    }

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input=json.dumps(plan))
    assert result.exit_code == 0
    payload = _payload(result)
    step = payload["steps"][0]
    assert step["ok"] is True
    assert step["skipped"] is False
    assert step["output"].endswith("img_compressed.png")
    assert (tmp_path / "img_compressed.png").is_file()


def test_apply_rejects_invalid_plan():
    runner = CliRunner()
    result = runner.invoke(cli, ["apply", "--plan", "-", "--json"], input="{}")
    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["ok"] is False
    assert payload["error"] == "unrecognized_plan_document"


def test_prep_produces_manifest_and_is_idempotent(tmp_path):
    src_dir = tmp_path / "raw"
    src_dir.mkdir()
    Image.new("RGB", (640, 480), (12, 90, 160)).save(src_dir / "a.png", format="PNG")
    Image.new("RGB", (320, 240), (160, 90, 12)).save(src_dir / "b.jpg", format="JPEG")
    out_dir = tmp_path / "dist"

    runner = CliRunner()
    first = runner.invoke(
        cli,
        ["prep", str(src_dir), "-o", str(out_dir), "--max-size", "256", "--json"],
    )
    assert first.exit_code == 0
    payload = _payload(first)
    assert payload["command"] == "prep"
    assert payload["ok"] is True
    assert payload["success"] == 2
    for item in payload["items"]:
        assert item["ok"] is True
        assert item["sha256"]
        assert item["output"].endswith(".webp")
        assert item["width"] is not None and item["width"] <= 256
        assert item["height"] is not None and item["height"] <= 256

    second = runner.invoke(
        cli,
        ["prep", str(src_dir), "-o", str(out_dir), "--max-size", "256", "--json"],
    )
    assert second.exit_code == 0
    second_payload = _payload(second)
    assert second_payload["skipped"] == 2
    assert second_payload["success"] == 0


def test_manifest_reports_hash_and_properties(tmp_path):
    src = tmp_path / "img.png"
    Image.new("RGBA", (30, 20), (0, 100, 200, 128)).save(src, format="PNG")

    runner = CliRunner()
    result = runner.invoke(cli, ["manifest", str(src), "--json"])
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["command"] == "manifest"
    entry = payload["files"][0]
    assert entry["format"] == "PNG"
    assert entry["width"] == 30
    assert entry["height"] == 20
    assert entry["has_alpha"] is True
    expected = hashlib.sha256(src.read_bytes()).hexdigest()
    assert entry["sha256"] == expected


def test_hash_matches_hashlib(tmp_path):
    src = tmp_path / "img.jpg"
    Image.new("RGB", (16, 16), (5, 5, 5)).save(src, format="JPEG")

    runner = CliRunner()
    result = runner.invoke(cli, ["hash", str(src), "--json"])
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["algorithm"] == "sha256"
    entry = payload["files"][0]
    assert entry["digest"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert entry["size_bytes"] == src.stat().st_size


def test_hash_all_files_includes_non_media(tmp_path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    runner = CliRunner()
    media_only = runner.invoke(cli, ["hash", str(tmp_path), "-r", "--json"])
    assert _payload(media_only)["total"] == 0
    everything = runner.invoke(cli, ["hash", str(tmp_path), "-r", "--all-files", "--json"])
    payload = _payload(everything)
    assert payload["total"] == 1
    assert payload["files"][0]["path"].endswith("notes.txt")
