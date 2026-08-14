"""Shared command-boundary validation and error mapping.

Exit-code contract (documented in docs/JSON_OUTPUT.md): ``0`` success,
``1`` operational failure (work was attempted and at least one item
failed), ``2`` usage rejection (the invocation was refused before any
output was written — argument parsing, argument semantics, and batch
plan validation).
"""

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NoReturn

import click

from ..compress_engine import parse_target_size
from ..core.errors import OperationPolicyError
from ..core.files import (
    SelectionFilters,
    validate_aggregate_output_path,
    validate_filename_affix,
    validate_unique_output_paths,
)
from ..core.parallel import run_batch_tasks
from ..presenters.json_presenters import emit_json_and_exit

__all__ = [
    "failure_entry",
    "failure_lines",
    "run_batch_tasks",
    "selection_filters_or_exit",
    "selection_options",
    "usage_error_or_exit",
    "validate_affixes_or_exit",
    "validate_aggregate_output_or_exit",
    "validate_tasks_or_exit",
]


def selection_options(function: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the shared batch-narrowing options to a command.

    Every batch command accepts the same three, so they are declared once:
    a user who learns them on ``compress`` can use them on ``convert``.
    """
    for option in reversed(
        (
            click.option(
                "--include",
                "include_globs",
                multiple=True,
                help="仅处理匹配该通配符的文件，可重复，如 --include '*.jpg'",
            ),
            click.option(
                "--exclude",
                "exclude_globs",
                multiple=True,
                help="跳过匹配该通配符的文件，可重复，如 --exclude '*/thumbs/*'",
            ),
            click.option(
                "--min-file-size",
                "min_file_size",
                default=None,
                type=str,
                help="仅处理不小于该体积的文件，如 1MB",
            ),
        )
    ):
        function = option(function)
    return function


def selection_filters_or_exit(
    *,
    command: str,
    as_json: bool,
    include_globs: Sequence[str] = (),
    exclude_globs: Sequence[str] = (),
    min_file_size: str | None = None,
) -> SelectionFilters:
    """Build the selection filters, rejecting a malformed size before any work."""
    min_bytes = 0
    if min_file_size is not None:
        try:
            min_bytes = parse_target_size(min_file_size)
        except ValueError:
            usage_error_or_exit(
                command=command,
                as_json=as_json,
                error="invalid_min_file_size",
                detail="--min-file-size expects a size like 500KB or 2MB",
                human_message="--min-file-size 需要 500KB / 2MB 这样的大小格式",
            )
        if min_bytes < 0:
            usage_error_or_exit(
                command=command,
                as_json=as_json,
                error="invalid_min_file_size",
                detail="--min-file-size must not be negative",
                human_message="--min-file-size 不能为负数",
            )
    return SelectionFilters(
        include=tuple(include_globs),
        exclude=tuple(exclude_globs),
        min_bytes=min_bytes,
    )


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


def validate_aggregate_output_or_exit(
    *, command: str, as_json: bool, inputs: Sequence[str], output: str
) -> None:
    """Reject aggregate output/input aliases before any source is filtered or read."""
    try:
        validate_aggregate_output_path(inputs, output)
    except OperationPolicyError as error:
        _exit_policy_error(command=command, as_json=as_json, error=error)


def _exit_policy_error(*, command: str, as_json: bool, error: OperationPolicyError) -> None:
    # Policy rejections fire before the first output is written, so they are
    # usage errors under the exit-code contract.
    usage_error_or_exit(command=command, as_json=as_json, error=error.code, detail=str(error))
