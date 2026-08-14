"""Tests for the thin MCP stdio adapter."""

import json
import re
import subprocess
import sys
import time

import pytest

from pixshift.mcp import server


def _initialize_request(request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": server.PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }


def test_initialize_reports_capabilities():
    response = server.handle_request(_initialize_request())
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == server.PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "pixshift"


def test_notifications_get_no_response():
    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_returns_error():
    response = server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "nope"})
    assert response is not None
    assert response["error"]["code"] == -32601


def test_tools_list_names_and_annotations_are_mcp_safe():
    response = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    tools = response["result"]["tools"]
    assert tools
    for tool in tools:
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool["name"])
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["openWorldHint"] is False
    names = {tool["name"] for tool in tools}
    assert "pdf_merge" in names
    assert "tools" in names


def test_tools_call_executes_cli_and_returns_json_document():
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tools", "arguments": {"args": []}},
        }
    )
    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    document = json.loads(result["content"][0]["text"])
    assert document["schema_version"] == "1.1"
    assert document["command"] == "tools"


def test_tools_call_unknown_tool_is_error():
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "missing", "arguments": {}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "message",
    [
        {"id": 1, "method": "ping"},
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": None, "method": "ping"},
        {"jsonrpc": "2.0", "id": True, "method": "ping"},
        {"jsonrpc": "2.0", "id": 1, "method": 7},
    ],
)
def test_invalid_jsonrpc_envelopes_are_rejected(message):
    response = server.handle_request(message)
    assert response is not None
    assert response["error"]["code"] == -32600


def test_initialize_requires_protocol_parameters():
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert response is not None
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "params",
    [
        [1],
        {"name": "tools", "arguments": {"args": ["\x00"]}},
        {"name": "tools", "arguments": {"args": "not-an-array"}},
    ],
)
def test_tools_call_rejects_protocol_invalid_params(params):
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    )
    assert response is not None
    assert response["error"]["code"] == -32602


def test_tool_child_cannot_import_a_workspace_shadow_module(tmp_path, monkeypatch):
    marker = tmp_path / "imported"
    (tmp_path / "pixshift.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('owned')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = server.call_tool("tools", {"args": []})

    assert result["isError"] is False
    assert not marker.exists()
    assert json.loads(result["content"][0]["text"])["command"] == "tools"


def test_stdio_round_trip_through_a_real_subprocess(tmp_path):
    """Drive the adapter over its actual transport, not just handle_request."""
    from PIL import Image

    photo = tmp_path / "photo.png"
    Image.new("RGB", (32, 32), "teal").save(str(photo))
    requests = "\n".join(
        [
            json.dumps(_initialize_request()),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "optimize", "arguments": {"args": [str(photo)]}},
                }
            ),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pixshift.mcp"],
        input=requests + "\n",
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 3, completed.stderr
    replies = {json.loads(line)["id"]: json.loads(line) for line in lines}
    assert "capabilities" in replies[1]["result"]
    listed = {tool["name"] for tool in replies[2]["result"]["tools"]}
    assert "optimize" in listed
    call = replies[3]["result"]
    assert call["isError"] is False
    document = json.loads(call["content"][0]["text"])
    assert document["command"] == "optimize"
    assert document["results"][0]["plan"]["command"] in ("convert", "compress", "strip", "keep")


def test_slow_tool_does_not_block_ping(monkeypatch, capsys):
    import io

    def slow_call(name, arguments, *, request_id=None):
        time.sleep(0.15)
        return {"content": [{"type": "text", "text": "{}"}], "isError": False}

    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "tools", "arguments": {"args": []}},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    monkeypatch.setattr(server, "call_tool", slow_call)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(map(json.dumps, messages)) + "\n"))

    server.serve()

    responses = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [response["id"] for response in responses] == [2, 1]


def test_cancel_notification_terminates_registered_process(monkeypatch):
    terminated = []

    class Process:
        pass

    process = Process()
    server._ACTIVE_PROCESSES[77] = process  # type: ignore[assignment]
    monkeypatch.setattr(server, "_terminate_process_tree", terminated.append)
    try:
        server._cancel_request(77)
        assert terminated == [process]
        assert 77 in server._CANCELLED_REQUESTS
    finally:
        server._ACTIVE_PROCESSES.clear()
        server._CANCELLED_REQUESTS.clear()


def test_unknown_cancellations_are_not_retained():
    server._ACTIVE_PROCESSES.clear()
    server._OUTSTANDING_REQUESTS.clear()
    server._CANCELLED_REQUESTS.clear()

    for request_id in range(5000):
        server._cancel_request(request_id)

    assert not server._CANCELLED_REQUESTS


def test_mcp_input_frames_are_bounded_and_stream_recovers(monkeypatch):
    import io

    monkeypatch.setattr(server, "_MAX_MESSAGE_BYTES", 16)
    stream = io.TextIOWrapper(io.BytesIO(b"x" * 32 + b"\n{}\n"), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", stream)

    assert list(server._input_lines()) == [None, "{}\n"]


def test_mcp_tool_output_limit_returns_stable_error(monkeypatch):
    class Process:
        returncode = 0
        pid = 123

        def communicate(self, timeout=None):
            return "x" * 17, ""

    monkeypatch.setattr(server, "_MAX_TOOL_OUTPUT_BYTES", 16)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *args, **kwargs: Process())

    result = server.call_tool("tools", {"args": []})

    assert result["isError"] is True
    assert "tool_output_too_large:tools" in result["content"][0]["text"]


def test_mcp_serve_bounds_outstanding_tool_calls(monkeypatch, capsys):
    import io

    def slow_handle(message):
        time.sleep(0.1)
        return {"jsonrpc": "2.0", "id": message["id"], "result": {}}

    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "tools", "arguments": {"args": []}},
        }
        for request_id in range(1, 9)
    ]
    server._OUTSTANDING_REQUESTS.clear()
    monkeypatch.setattr(server, "handle_request", slow_handle)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(map(json.dumps, messages)) + "\n"))

    server.serve()

    responses = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    busy = [
        response
        for response in responses
        if response.get("error", {}).get("message") == "server busy"
    ]
    assert len(busy) == len(messages) - server._MAX_IN_FLIGHT_TOOLS
    assert not server._OUTSTANDING_REQUESTS
