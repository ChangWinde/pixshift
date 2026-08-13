"""Contract tests: exit codes and the object shape of ``errors`` arrays.

The documented contract (docs/JSON_OUTPUT.md): exit 0 success, exit 1
operational failure (work attempted, at least one item failed), exit 2 usage
rejection (invocation refused before any output is written). Batch commands
report failures as ``{"input", "output", "error"}`` objects.
"""

import json

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def still(tmp_path):
    source = tmp_path / "img.png"
    Image.new("RGB", (20, 20), "teal").save(str(source))
    return source


@pytest.fixture
def corrupt(tmp_path):
    source = tmp_path / "broken.png"
    source.write_bytes(b"definitely not a png")
    return source


USAGE_CASES = [
    (["convert", "{src}", "-t", "jpg", "--resize", "bogus"], "invalid_resize"),
    (
        ["convert", "{src}", "-t", "jpg", "--resize", "50%", "--max-size", "100"],
        "conflicting_options",
    ),
    (["convert", "{src}", "-t", "jpg", "--bg-color", "1,2"], "invalid_bg_color"),
    (["convert", "{src}", "-t", "jpg", "--prefix", "a/b"], "invalid_filename_component"),
    (["compress", "{src}", "--quality", "80", "--target-size", "1MB"], "conflicting_options"),
    (["resize", "{src}", "--percent", "50", "--max-size", "100"], "conflicting_options"),
    (["resize", "{src}", "--size", "bogus"], "invalid_size"),
    (["rotate", "{src}"], "nothing_to_do"),
]


@pytest.mark.parametrize("argv,code", USAGE_CASES)
def test_usage_rejections_exit_2_in_json(runner, still, argv, code):
    args = [part.format(src=still) for part in argv] + ["--json"]
    result = runner.invoke(cli, args)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == code
    # A usage rejection must not have produced any derivative next to the source.
    assert list(still.parent.glob("*")) == [still]


@pytest.mark.parametrize("argv,code", USAGE_CASES)
def test_usage_rejections_exit_2_in_human_mode(runner, still, argv, code):
    args = [part.format(src=still) for part in argv]
    result = runner.invoke(cli, args)
    assert result.exit_code == 2, result.output


FAILURE_COMMANDS = [
    ["convert", "{src}", "-t", "webp"],
    ["resize", "{src}", "--percent", "50"],
    ["rotate", "{src}", "--degrees", "90"],
    ["compress", "{src}"],
    ["strip", "{src}"],
    ["crop", "{src}", "--crop", "1,1,10,10"],
]


@pytest.mark.parametrize("argv", FAILURE_COMMANDS, ids=lambda argv: argv[0])
def test_operational_failures_exit_1_with_object_errors(runner, corrupt, argv):
    args = [part.format(src=corrupt) for part in argv] + ["--json"]
    result = runner.invoke(cli, args)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["failed"] == 1
    entry = payload["errors"][0]
    assert set(entry) == {"input", "output", "error"}
    assert entry["input"] == str(corrupt)
    assert entry["error"]


def test_watermark_failures_use_object_errors(runner, corrupt):
    result = runner.invoke(cli, ["watermark", "text", str(corrupt), "--text", "pix", "--json"])
    assert result.exit_code == 1
    entry = json.loads(result.output)["errors"][0]
    assert set(entry) == {"input", "output", "error"}
    assert entry["input"] == str(corrupt)
