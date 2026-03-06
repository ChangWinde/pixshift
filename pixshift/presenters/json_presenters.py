"""Helpers for stable JSON command output."""

import json
from typing import Any, Dict

import click


def emit_json(payload: Dict[str, Any]) -> None:
    """Emit JSON payload to stdout with UTF-8 characters preserved."""
    click.echo(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def emit_json_and_exit(payload: Dict[str, Any], exit_code: int = 0) -> None:
    """Emit JSON payload and terminate process with explicit exit code."""
    emit_json(payload)
    raise SystemExit(exit_code)

