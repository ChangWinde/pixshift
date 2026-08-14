"""Minimal MCP stdio server mapping the tool catalog onto the CLI.

The CLI JSON contract stays authoritative (ADR-0003). This adapter only
translates JSON-RPC tool calls into ``python -m pixshift ... --json``
invocations and returns the emitted document verbatim.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

from .. import __version__
from ..core.tool_catalog import TOOL_CATALOG, ToolEntry

PROTOCOL_VERSION = "2025-06-18"
_JSON_UNSUPPORTED: frozenset[str] = frozenset()
# A wedged CLI subprocess must not hang the whole MCP session; bound it.
_DEFAULT_TOOL_TIMEOUT = 120.0


def _tool_timeout() -> float:
    """Return a finite positive timeout even when configuration is malformed."""
    try:
        value = float(os.environ.get("PIXSHIFT_MCP_TIMEOUT", str(_DEFAULT_TOOL_TIMEOUT)))
    except ValueError:
        return _DEFAULT_TOOL_TIMEOUT
    return value if math.isfinite(value) and value > 0 else _DEFAULT_TOOL_TIMEOUT


_TOOL_TIMEOUT = _tool_timeout()


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
    validation_error = _tool_arguments_error(arguments)
    if validation_error is not None:
        return _tool_error(validation_error)
    args_value = (arguments or {}).get("args", [])

    cli_args = _catalog_command(entry["name"]) + list(args_value)
    if entry["name"] not in _JSON_UNSUPPORTED:
        # Always append the flag. A previous ``--json`` token may have been
        # consumed as another option's value; a duplicate boolean flag is safe.
        cli_args.append("--json")
    try:
        completed = _run_cli(
            cli_args,
        )
    except subprocess.TimeoutExpired:
        return _tool_error(f"tool_timeout_after_{_TOOL_TIMEOUT:g}s:{entry['name']}")
    except (OSError, ValueError):
        return _tool_error(f"tool_process_failed:{entry['name']}")
    # Import-time warnings from optional codecs may precede the JSON document;
    # the CLI contract emits exactly one JSON line, so keep the last one.
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return _tool_error(f"tool_emitted_no_json:{entry['name']}")
    text = stdout_lines[-1]
    try:
        document = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        return _tool_error(f"tool_emitted_invalid_json:{entry['name']}")
    if not isinstance(document, dict):
        return _tool_error(f"tool_emitted_invalid_json:{entry['name']}")
    return {
        "content": [{"type": "text", "text": text}],
        "isError": completed.returncode != 0 or document.get("ok") is False,
    }


def _run_cli(cli_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one CLI call in a group that can be terminated as a whole."""
    command = [sys.executable, "-I", "-m", "pixshift", *cli_args]
    creationflags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    # Isolated mode removes the working directory from sys.path. Without it,
    # an untrusted workspace-level ``pixshift.py`` executes before the CLI.
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # The CLI's JSON channel is UTF-8; platform code pages would mangle it.
        encoding="utf-8",
        errors="replace",
        # Never inherit the MCP stream: ``apply --plan -`` would consume it.
        stdin=subprocess.DEVNULL,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=_TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate the isolated CLI process group, including ffmpeg/workers."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        with contextlib.suppress(OSError):
            process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
        return

    kill_process_group = getattr(os, "killpg", None)
    if kill_process_group is None:  # pragma: no cover - defensive non-POSIX fallback
        with contextlib.suppress(OSError):
            process.kill()
        return
    with contextlib.suppress(ProcessLookupError):
        kill_process_group(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1)
    # The direct Python child can exit before a descendant that ignored
    # SIGTERM. Kill the still-existing group even when ``wait`` returned.
    with contextlib.suppress(ProcessLookupError):
        kill_process_group(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def _find_entry(name: str) -> ToolEntry | None:
    for entry in TOOL_CATALOG:
        if _mcp_tool_name(entry["name"]) == name:
            return entry
    return None


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _tool_arguments_error(arguments: object) -> str | None:
    """Validate the advertised ``{"args": string[]}`` tool input schema."""
    if arguments is None:
        return None
    if not isinstance(arguments, dict) or set(arguments) - {"args"}:
        return "invalid_arguments:expected_args_object"
    args_value = arguments.get("args", [])
    if not isinstance(args_value, list) or not all(isinstance(item, str) for item in args_value):
        return "invalid_arguments:args_must_be_string_array"
    if any("\x00" in item for item in args_value):
        return "invalid_arguments:nul_byte"
    if "--help" in args_value:
        return "invalid_arguments:help_not_available"
    return None


def _valid_request_id(value: object) -> bool:
    """MCP request IDs are non-null strings or integers (never booleans)."""
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def _initialize_params_error(params: object) -> str | None:
    if not isinstance(params, dict):
        return "initialize params must be an object"
    if not isinstance(params.get("protocolVersion"), str):
        return "initialize protocolVersion must be a string"
    if not isinstance(params.get("capabilities"), dict):
        return "initialize capabilities must be an object"
    client_info = params.get("clientInfo")
    if not isinstance(client_info, dict):
        return "initialize clientInfo must be an object"
    if not isinstance(client_info.get("name"), str) or not isinstance(
        client_info.get("version"), str
    ):
        return "initialize clientInfo name and version must be strings"
    return None


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request; notifications return None."""
    method = message.get("method")
    has_id = "id" in message
    request_id = message.get("id")
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _jsonrpc_error(
            request_id if _valid_request_id(request_id) else None, -32600, "invalid request"
        )
    if not has_id:
        return None
    if not _valid_request_id(request_id):
        return _jsonrpc_error(None, -32600, "invalid request")

    if method == "initialize":
        params_error = _initialize_params_error(message.get("params"))
        if params_error is not None:
            return _jsonrpc_error(request_id, -32602, params_error)
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pixshift", "version": __version__},
            "instructions": (
                "Local-first image/PDF/video toolkit. Call tools with an args string "
                "array mirroring the CLI; every result is the stable PixShift "
                "JSON document (schema_version 1.1)."
            ),
        }
        return _jsonrpc_result(request_id, result)
    if method == "ping":
        return _jsonrpc_result(request_id, {})
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": list_tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _jsonrpc_error(request_id, -32602, "params must be an object")
        name = params.get("name")
        if not isinstance(name, str) or _find_entry(name) is None:
            return _jsonrpc_error(request_id, -32602, "unknown or invalid tool name")
        arguments = params.get("arguments")
        arguments_error = _tool_arguments_error(arguments)
        if arguments_error is not None:
            return _jsonrpc_error(request_id, -32602, arguments_error)
        return _jsonrpc_result(request_id, call_tool(name, arguments))
    return _jsonrpc_error(request_id, -32601, f"method not found: {method}")


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _reject_json_constant(value: str) -> None:
    """Reject Python's non-standard NaN/Infinity JSON extensions."""
    raise ValueError(f"non-standard JSON constant: {value}")


def _input_lines() -> Iterator[str | None]:
    """Yield UTF-8 request lines; ``None`` represents an invalid byte sequence."""
    binary = getattr(sys.stdin, "buffer", None)
    if binary is None:
        yield from sys.stdin
        return
    for raw_line in binary:
        try:
            yield raw_line.decode("utf-8")
        except UnicodeDecodeError:
            yield None


def serve() -> None:
    """Run the newline-delimited JSON-RPC loop over stdio."""
    for line in _input_lines():
        if line is None:
            _write_response(_jsonrpc_error(None, -32700, "parse error"))
            continue
        line = line.strip()
        if not line:
            continue
        response: dict[str, Any] | None
        try:
            message = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            response = _jsonrpc_error(None, -32700, "parse error")
        else:
            if isinstance(message, dict):
                response = handle_request(message)
            else:
                # A valid-JSON but non-object payload (e.g. ``[1]``) must not
                # crash the loop on the later ``.get`` calls.
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "invalid request"},
                }
        if response is not None:
            _write_response(response)


def _write_response(response: dict[str, Any]) -> None:
    """Write one strict-JSON UTF-8 response on the stdio transport."""
    payload = json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n"
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:
        sys.stdout.write(payload)
    else:
        binary.write(payload.encode("utf-8"))
    sys.stdout.flush()
