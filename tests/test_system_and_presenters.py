"""Tests for system commands, CLI entry paths, and presenter helpers."""

from io import StringIO

import pytest
from click.testing import CliRunner
from rich.console import Console

from pixshift import cli as cli_module
from pixshift.cli import cli
from pixshift.commands.system_commands import _check_heif
from pixshift.presenters.cli_presenters import (
    print_failures,
    show_dry_run_table,
    size_ratio_text,
)


def test_cli_no_args_shows_quick_start_panel():
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "快速开始" in result.output
    assert "pixshift convert" in result.output


def test_cli_main_calls_click_group(monkeypatch):
    called = {"ok": False}

    def fake_cli():
        called["ok"] = True

    monkeypatch.setattr(cli_module, "cli", fake_cli)
    cli_module.main()
    assert called["ok"] is True


def test_info_command_renders_exif_when_requested(tmp_path, monkeypatch):
    sample = tmp_path / "sample.jpg"
    sample.write_bytes(b"placeholder")

    def fake_info(_filepath):
        return {
            "format": "JPEG",
            "format_ext": "jpg",
            "size_human": "1.0 KB",
            "width": 100,
            "height": 60,
            "mode": "RGB",
            "has_alpha": False,
            "exif": {"Camera": "UnitTestCam"},
        }

    monkeypatch.setattr(
        "pixshift.commands.system_commands.PixShiftConverter.get_image_info",
        fake_info,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["info", str(sample), "--exif"])
    assert result.exit_code == 0
    assert "EXIF" in result.output
    assert "UnitTestCam" in result.output


def test_formats_command_displays_tables():
    runner = CliRunner()
    result = runner.invoke(cli, ["formats"])
    assert result.exit_code == 0
    assert "运行时能力探测" in result.output
    assert "质量预设" in result.output


def test_doctor_command_displays_runtime_checks():
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "环境检查" in result.output
    assert "Python" in result.output


def test_check_heif_handles_import_error(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pillow_heif":
            raise ImportError("mock missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _check_heif() is False


def test_size_ratio_text_saved_and_expanded():
    to_human = lambda n: f"{n}B"
    text_saved = size_ratio_text(1000, 600, to_human)
    text_expanded = size_ratio_text(1000, 1200, to_human)
    text_empty = size_ratio_text(0, 10, to_human)

    assert "节省 400B" in text_saved
    assert "增加 200B" in text_expanded
    assert text_empty == ""


def test_print_failures_truncates_to_top_ten():
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None)
    errors = [f"err-{i}" for i in range(12)]

    print_failures(console, errors)
    rendered = output.getvalue()
    assert "❌ 失败文件" in rendered
    assert "err-0" in rendered
    assert "err-9" in rendered
    assert "还有 2 个失败" in rendered


def test_show_dry_run_table_limits_rows_to_fifty():
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None)
    tasks = [(f"/tmp/in_{i}.jpg", f"/tmp/out_{i}.webp") for i in range(55)]

    show_dry_run_table(
        console=console,
        tasks=tasks,
        target_label="WebP",
        quality_label="high",
    )
    rendered = output.getvalue()
    assert "预览模式" in rendered
    assert "还有 5 个文件" in rendered
    assert "WebP" in rendered

