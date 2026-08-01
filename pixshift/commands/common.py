"""Shared command-boundary validation and error mapping."""

from collections.abc import Sequence

import click

from ..core.errors import OperationPolicyError
from ..core.files import validate_filename_affix, validate_unique_output_paths
from ..presenters.json_presenters import emit_json_and_exit


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
    payload = {"command": command, "ok": False, "error": error.code, "detail": str(error)}
    if as_json:
        emit_json_and_exit(payload, 1)
    raise click.ClickException(str(error))
