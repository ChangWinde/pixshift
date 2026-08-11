"""Minimal MCP stdio server mapping the tool catalog onto the CLI.

The CLI JSON contract stays authoritative (ADR-0003). This adapter only
translates JSON-RPC tool calls into ``python -m pixshift ... --json``
invocations and returns the emitted document verbatim.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from .. import __version__
from ..core.tool_catalog import TOOL_CATALOG, ToolEntry

PROTOCOL_VERSION = "2025-06-18"
_JSON_UNSUPPORTED: frozenset[str] = frozenset()


def _mcp_tool_name(catalog_name: str) -> str:
    """MCP tool names must match ``[a-zA-Z0-9_-]``; map dots to underscores."""
    return catalog_name.replace(".", "_")


def _catalog_command(catalog_name: str) -> list[str]:
    """Translate a catalog name into CLI tokens."""
    return catalog_name.split(".")


def list_tools() -> list[dict[str, Any]]:
    """Return MCP tool descriptors derived from the stable catalog."""
    tools: list[dict[str, Any]] = []
    for entry in TOOL_CATALOG:
        tools.append(
            {
                "name": _mcp_tool_name(entry["name"]),
                "description": f"{entry['description']} {entry['when_to_use']}",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "CLI arguments after the command name. "
                                f"Summary: {entry['input_summary']}. "
                                "--json is appended automatically."
                            ),
                        }
                    },
                    "additionalProperties": False,
                },
                "annotations": dict(entry["annotations"]),
            }
        )
    return tools


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Execute one catalog tool through the CLI and wrap the JSON document."""
    entry = _find_entry(name)
    if entry is None:
        return _tool_error(f"unknown_tool:{name}")
    args_value = (arguments or {}).get("args", [])
    if not isinstance(args_value, list) or not all(isinstance(item, str) for item in args_value):
        return _tool_error("invalid_arguments:args_must_be_string_array")

    cli_args = _catalog_command(entry["name"]) + list(args_value)
    if "--json" not in cli_args and entry["name"] not in _JSON_UNSUPPORTED:
        cli_args.append("--json")
    completed = subprocess.run(
        [sys.executable, "-m", "pixshift", *cli_args],
        capture_output=True,
        text=True,
        check=False,
    )
    # Import-time warnings from optional codecs may precede the JSON document;
    # the CLI contract emits exactly one JSON line, so keep the last one.
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    text = stdout_lines[-1] if stdout_lines else completed.stderr.strip()
    return {
        "content": [{"type": "text", "text": text}],
        "isError": completed.returncode != 0,
    }


def _find_entry(name: str) -> ToolEntry | None:
    for entry in TOOL_CATALOG:
        if _mcp_tool_name(entry["name"]) == name:
            return entry
    return None


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request; notifications return None."""
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pixshift", "version": __version__},
            "instructions": (
                "Local-first image/PDF toolkit. Call tools with an args string "
                "array mirroring the CLI; every result is the stable PixShift "
                "JSON document (schema_version 1.0)."
            ),
        }
        return _jsonrpc_result(request_id, result)
    if method == "ping":
        return _jsonrpc_result(request_id, {})
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": list_tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "arguments must be an object")
        return _jsonrpc_result(request_id, call_tool(name, arguments))
    return _jsonrpc_error(request_id, -32601, f"method not found: {method}")


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve() -> None:
    """Run the newline-delimited JSON-RPC loop over stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        else:
            response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
