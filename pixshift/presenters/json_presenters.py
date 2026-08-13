"""Helpers for stable JSON command output."""

import json
from typing import Any

import click


def emit_json(payload: dict[str, Any]) -> None:
    """Emit JSON payload to stdout as UTF-8 bytes.

    Writing bytes bypasses the console/pipe text encoding, which on Windows
    defaults to a legacy code page (cp1252/GBK) and made any payload with
    non-ASCII text — Chinese recommendation reasons, file names — crash with
    UnicodeEncodeError. JSON is UTF-8 by definition.
    """
    document = {"schema_version": "1.1", **payload}
    click.echo(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def emit_json_and_exit(payload: dict[str, Any], exit_code: int = 0) -> None:
    """Emit JSON payload and terminate process with explicit exit code."""
    emit_json(payload)
    raise SystemExit(exit_code)
