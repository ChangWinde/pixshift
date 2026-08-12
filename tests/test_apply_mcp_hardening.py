"""Regression tests for apply/prep/MCP/core hardening (A5/A6/A7/B2)."""

import io
import json

import pytest
from PIL import Image

from pixshift.core.errors import OutputCollisionError
from pixshift.ops import apply as apply_ops
from pixshift.ops import prep as prep_ops


def _img(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (30, 30, 30)).save(path)
    return path


def test_prep_rejects_colliding_outputs(tmp_path):
    # a.png and a.jpg both prepare to a.webp -> must fail, not silently clobber.
    _img(tmp_path / "src" / "a.png")
    _img(tmp_path / "src" / "a.jpg")
    with pytest.raises(OutputCollisionError):
        prep_ops.prep_files(
            [str(tmp_path / "src")],
            output_dir=str(tmp_path / "out"),
            output_format="webp",
        )


def test_apply_flags_second_colliding_step(tmp_path):
    _img(tmp_path / "a.png")
    _img(tmp_path / "a.jpg")
    steps = [
        {"input": str(tmp_path / "a.png"), "command": "convert", "arguments": {"to": "webp"}},
        {"input": str(tmp_path / "a.jpg"), "command": "convert", "arguments": {"to": "webp"}},
    ]
    result = apply_ops.apply_plans(steps, output_dir=str(tmp_path / "out"))
    assert result.steps[0].success
    assert result.steps[1].error == "output_collision"


def test_load_plan_skips_failed_optimize_entries():
    document = json.dumps(
        {
            "results": [
                {"input": "ok.png", "plan": {"command": "convert", "arguments": {"to": "webp"}}},
                {"input": "failed.xyz", "ok": False},
            ]
        }
    )
    steps = apply_ops.load_plan_document(document)
    assert len(steps) == 1
    assert steps[0]["input"] == "ok.png"


@pytest.mark.parametrize("raw", ['{"plans": 5}', "[1]", "42"])
def test_load_plan_raises_valueerror_not_typeerror(raw):
    with pytest.raises(ValueError):
        apply_ops.load_plan_document(raw)


def test_mcp_call_tool_isolates_stdin_and_bounds_time(monkeypatch):
    import pixshift.mcp.server as server

    captured: dict = {}

    class _Done:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _Done()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    server.call_tool("tools", {"args": []})

    assert captured["stdin"] is server.subprocess.DEVNULL
    assert captured["timeout"] == server._TOOL_TIMEOUT


def test_mcp_call_tool_reports_timeout(monkeypatch):
    import subprocess

    import pixshift.mcp.server as server

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    out = server.call_tool("tools", {"args": []})
    assert out["isError"] is True
    assert "tool_timeout" in out["content"][0]["text"]


def test_mcp_serve_rejects_non_object_message(monkeypatch, capsys):
    import pixshift.mcp.server as server

    monkeypatch.setattr("sys.stdin", io.StringIO("[1]\n"))
    server.serve()
    response = json.loads(capsys.readouterr().out.strip())
    assert response["error"]["code"] == -32600
