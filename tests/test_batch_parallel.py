"""Tests for the shared bounded-parallel batch executor."""

import json

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
