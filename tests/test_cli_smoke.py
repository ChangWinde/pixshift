"""CLI smoke tests for command registration."""

from click.testing import CliRunner

from pixshift.cli import cli


def test_root_help_contains_core_commands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "convert" in result.output
    assert "compress" in result.output
    assert "strip" in result.output
    assert "dedup" in result.output
    assert "pdf" in result.output


def test_convert_help_available():
    runner = CliRunner()
    result = runner.invoke(cli, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--resize" in result.output
    assert "--bg-color" in result.output


def test_pdf_group_help_available():
    runner = CliRunner()
    result = runner.invoke(cli, ["pdf", "--help"])
    assert result.exit_code == 0
    assert "merge" in result.output
    assert "extract" in result.output
    assert "compress" in result.output
    assert "concat" in result.output
    assert "info" in result.output


def test_advanced_commands_help_available():
    runner = CliRunner()
    root = runner.invoke(cli, ["--help"])
    assert root.exit_code == 0
    assert "compare" in root.output
    assert "crop" in root.output
    assert "watermark" in root.output
    assert "montage" in root.output
    assert "optimize" in root.output
    assert "watch" in root.output

    for args in [
        ["compare", "--help"],
        ["crop", "--help"],
        ["watermark", "--help"],
        ["watermark", "text", "--help"],
        ["watermark", "image", "--help"],
        ["montage", "--help"],
        ["optimize", "--help"],
        ["watch", "--help"],
    ]:
        result = runner.invoke(cli, args)
        assert result.exit_code == 0

