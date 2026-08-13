"""Tests for the shared bounded-parallel batch executor."""

import json

import pytest
from click.testing import CliRunner
from PIL import Image

from pixshift.cli import cli
from pixshift.commands.common import run_batch_tasks


def _echo_worker(input_path, output_path):
    return (input_path, output_path)


def test_results_preserve_task_order_in_the_pool_path():
    tasks = [(f"in_{index}", f"out_{index}") for index in range(12)]
    ticks = []
    results = run_batch_tasks(tasks, _echo_worker, on_result=lambda: ticks.append(1))
    assert results == tasks
    assert len(ticks) == len(tasks)


def test_small_batches_stay_serial():
    tasks = [("a", "b"), ("c", "d")]
    assert run_batch_tasks(tasks, _echo_worker) == tasks
    assert run_batch_tasks([], _echo_worker) == []


def test_pool_child_import_graph_can_decode_heic(tmp_path):
    """A worker that imports only its own ops module must still open HEIC.

    Under spawn/forkserver start methods (the Linux default since Python
    3.14) pool children do not inherit the parent's imports; before the
    package-level plugin registration, a compress/strip child failed with
    "cannot identify image file" on HEIC while convert children worked.
    """
    import subprocess
    import sys

    pytest.importorskip("pillow_heif")
    import pillow_heif

    pillow_heif.register_heif_opener()
    photo = tmp_path / "phone.heic"
    Image.new("RGB", (40, 30), "teal").save(str(photo), format="HEIF", quality=70)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "import pixshift.ops.compress; "
            "from PIL import Image; "
            f"Image.open({str(photo)!r}).load(); "
            "print('ok')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "ok"


def test_parallel_compress_batch_keeps_json_order(tmp_path):
    src = tmp_path / "photos"
    src.mkdir()
    names = [f"img_{index:02d}.jpg" for index in range(8)]
    for index, name in enumerate(names):
        Image.new("RGB", (64, 64), (index * 20 % 255, 80, 90)).save(
            str(src / name), format="JPEG", quality=90
        )
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["compress", str(src), "-o", str(out), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] == len(names)
    produced = sorted(p.name for p in out.rglob("*.jpg"))
    assert produced == sorted(f"img_{index:02d}_compressed.jpg" for index in range(8))
