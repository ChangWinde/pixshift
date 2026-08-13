"""Shared command-boundary validation and error mapping.

Exit-code contract (documented in docs/JSON_OUTPUT.md): ``0`` success,
``1`` operational failure (work was attempted and at least one item
failed), ``2`` usage rejection (the invocation was refused before any
output was written — argument parsing, argument semantics, and batch
plan validation).
"""

import multiprocessing
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, NoReturn

import click

from ..core.errors import OperationPolicyError
from ..core.files import validate_filename_affix, validate_unique_output_paths
from ..presenters.json_presenters import emit_json_and_exit

# Image decoders are memory-heavy; an unbounded CPU-count pool can make large
# batches slower through memory pressure. Same bound the convert path uses.
MAX_BATCH_WORKERS = 8
# Below this task count process startup costs more than it saves.
MIN_PARALLEL_TASKS = 4


def run_batch_tasks(
    tasks: Sequence[tuple[str, str]],
    worker: Callable[[str, str], Any],
    *,
    on_result: Callable[[], None] | None = None,
) -> list[Any]:
    """Run ``worker(input, output)`` over a batch, in parallel when it pays.

    Results preserve task order regardless of completion order, so JSON
    payloads and failure lists stay deterministic. ``worker`` must be
    picklable (a module-level function or ``functools.partial`` over one).
    ``on_result`` fires once per completed item, for progress ticks.
    """
    if not tasks:
        return []
    jobs = max(1, min(multiprocessing.cpu_count(), len(tasks), MAX_BATCH_WORKERS))
    if jobs <= 1 or len(tasks) < MIN_PARALLEL_TASKS:
        results = []
        for input_path, output_path in tasks:
            results.append(worker(input_path, output_path))
            if on_result is not None:
                on_result()
        return results
    ordered: list[Any] = [None] * len(tasks)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(worker, input_path, output_path): index
            for index, (input_path, output_path) in enumerate(tasks)
        }
        for future in as_completed(futures):
            ordered[futures[future]] = future.result()
            if on_result is not None:
                on_result()
    return ordered


def usage_error_or_exit(
    *,
    command: str,
    as_json: bool,
    error: str,
    detail: str,
    human_message: str | None = None,
) -> NoReturn:
    """Reject an invocation before any work starts (exit 2 on both channels)."""
    if as_json:
        emit_json_and_exit({"command": command, "ok": False, "error": error, "detail": detail}, 2)
    raise click.UsageError(human_message or detail)


def failure_entry(input_path: str, error: str, output_path: str = "") -> dict[str, str]:
    """One failed item for a command's ``errors`` array (stable object shape)."""
    return {"input": input_path, "output": output_path, "error": error}


def failure_lines(errors: Sequence[Mapping[str, str]]) -> list[str]:
    """Human-channel rendering of object-shaped failure entries."""
    return [f"{os.path.basename(entry['input'])}: {entry['error']}" for entry in errors]


def validate_affixes_or_exit(
    *, command: str, as_json: bool, values: Sequence[tuple[str, str]]
) -> None:
    """Validate filename fragments and map failures to the command contract."""
    try:
        for label, value in values:
            validate_filename_affix(value, label)
    except OperationPolicyError as error:
        _exit_policy_error(command=command, as_json=as_json, error=error)


def validate_tasks_or_exit(
    *,
    command: str,
    as_json: bool,
    tasks: Sequence[tuple[str, str]],
) -> None:
    """Validate the entire batch before the first output is written."""
    try:
        validate_unique_output_paths(tasks)
    except OperationPolicyError as error:
        _exit_policy_error(command=command, as_json=as_json, error=error)


def _exit_policy_error(*, command: str, as_json: bool, error: OperationPolicyError) -> None:
    # Policy rejections fire before the first output is written, so they are
    # usage errors under the exit-code contract.
    usage_error_or_exit(command=command, as_json=as_json, error=error.code, detail=str(error))
