"""Tests for the thin MCP stdio adapter."""

import json
import re

from pixshift.mcp import server


def test_initialize_reports_capabilities():
    response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
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
    assert response["result"]["isError"] is True


def test_stdio_round_trip_through_a_real_subprocess(tmp_path):
    """Drive the adapter over its actual transport, not just handle_request."""
    import subprocess
    import sys

    from PIL import Image

    photo = tmp_path / "photo.png"
    Image.new("RGB", (32, 32), "teal").save(str(photo))
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
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
        text=True,
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
