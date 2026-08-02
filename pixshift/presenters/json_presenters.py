"""Helpers for stable JSON command output."""

import json
from typing import Any

import click


def emit_json(payload: dict[str, Any]) -> None:
    """Emit JSON payload to stdout with UTF-8 characters preserved."""
    document = {"schema_version": "1.0", **payload}
    click.echo(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


def emit_json_and_exit(payload: dict[str, Any], exit_code: int = 0) -> None:
    """Emit JSON payload and terminate process with explicit exit code."""
    emit_json(payload)
    raise SystemExit(exit_code)
