"""Exercise the revised MCP oracle in real offline Python subprocesses."""

import json
import shutil
import subprocess  # nosec B404 - local Python fixture only, no shell or host CLI
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

INVALID_ARGUMENTS: tuple[Any, ...] = (None, [], "", 1, False, {"unexpected": True})


@pytest.fixture
def mcp_process(tmp_path: Path) -> Callable[[list[str]], list[dict[str, Any]]]:
    """Run only a copied fixture with an empty environment and isolated Python."""
    source = (
        Path(__file__).resolve().parent
        / "fixtures/host-probe/probe-sentinel/mcp/sentinel.py"
    )
    script = shutil.copy2(src=source, dst=tmp_path / "sentinel.py")

    def run(lines: list[str]) -> list[dict[str, Any]]:
        """Send lines through stdin and collect JSON-RPC replies through EOF."""
        result = (
            subprocess.run(  # nosec B603 - current Python, copied fixture, no shell
                [sys.executable, "-I", str(script)],
                input="\n".join(lines) + "\n",
                text=True,
                capture_output=True,
                cwd=tmp_path,
                env={},
                timeout=5,
                check=False,
            )
        )
        assert_that(result.returncode).is_zero()
        assert_that(result.stderr).is_empty()
        return [json.loads(line) for line in result.stdout.splitlines()]

    return run


def test_initialize_list_and_call(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
) -> None:
    """Only calling the advertised tool returns the integration sentinel."""
    messages = [
        {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "offline-test", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 0, "method": "tools/list"},
    ]
    replies = mcp_process([json.dumps(message) for message in messages])
    assert_that([reply["id"] for reply in replies]).is_equal_to(["init", 0])
    assert_that(replies[0]["result"]["protocolVersion"]).is_equal_to("2024-11-05")
    assert_that(replies[0]["result"]["capabilities"]).contains_key("tools")
    tool = replies[1]["result"]["tools"][0]
    assert_that(tool["inputSchema"]).is_equal_to(
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    assert_that(json.dumps(replies)).does_not_contain("PROBE-7f3a-integration")
    messages.append(
        {
            "jsonrpc": "2.0",
            "id": "call",
            "method": "tools/call",
            "params": {"name": tool["name"], "arguments": {}},
        },
    )
    replies = mcp_process([json.dumps(message) for message in messages])
    assert_that(replies[-1]).is_equal_to(
        {
            "jsonrpc": "2.0",
            "id": "call",
            "result": {
                "content": [{"type": "text", "text": "PROBE-7f3a-integration"}],
            },
        },
    )


@pytest.mark.parametrize("request_id", [0, "request"])
def test_call_without_optional_arguments(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
    request_id: int | str,
) -> None:
    """MCP permits omitted arguments for an empty object schema; IDs survive."""
    replies = mcp_process(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {"name": "probe_integration"},
                },
            ),
        ],
    )
    assert_that(replies[0]["id"]).is_equal_to(request_id)
    assert_that(replies[0]["result"]["content"][0]["text"]).is_equal_to(
        "PROBE-7f3a-integration",
    )


@pytest.mark.parametrize("request_id", [0, 7, "ping-request"])
@pytest.mark.parametrize("fields", [{}, {"params": {}}])
def test_ping_preserves_id_without_sentinel(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
    request_id: int | str,
    fields: dict[str, Any],
) -> None:
    """A health check returns an empty result and leaves notifications silent."""
    messages = [
        {"jsonrpc": "2.0", "id": request_id, "method": "ping", **fields},
        {"jsonrpc": "2.0", "method": "ping", **fields},
        {"jsonrpc": "2.0", "id": "next", "method": "tools/list"},
    ]
    replies = mcp_process([json.dumps(message) for message in messages])
    assert_that(replies).is_length(2)
    assert_that(replies[0]).is_equal_to(
        {"jsonrpc": "2.0", "id": request_id, "result": {}},
    )
    assert_that(replies[1]["id"]).is_equal_to("next")
    assert_that(replies[1]).contains_key("result")
    assert_that(json.dumps(replies)).does_not_contain("PROBE-7f3a-integration")


@pytest.mark.parametrize(
    "method",
    ["initialize", "ping", "tools/list", "tools/call", "unknown"],
)
def test_null_ids_are_invalid(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
    method: str,
) -> None:
    """An explicit null ID is invalid in MCP, including for an otherwise valid call."""
    replies = mcp_process(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "method": method,
                    "params": {"name": "probe_integration"},
                },
            ),
            '{"jsonrpc":"2.0","id":"next","method":"tools/list"}',
        ],
    )
    assert_that(replies).is_length(2)
    assert_that(replies[0]).is_equal_to(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        },
    )
    assert_that(replies[1]["id"]).is_equal_to("next")
    assert_that(replies[1]).contains_key("result")
    assert_that(json.dumps(replies)).does_not_contain("PROBE-7f3a-integration")


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"params": None},
        {"params": []},
        {"params": "probe_integration"},
        {"params": {}},
        {"params": {"name": "missing_tool", "arguments": {}}},
        {"params": {"name": "PROBE_INTEGRATION"}},
        {"params": {"name": None}},
        {"params": {"name": ["probe_integration"]}},
        *(
            {"params": {"name": "probe_integration", "arguments": arguments}}
            for arguments in INVALID_ARGUMENTS
        ),
    ],
)
def test_invalid_tool_calls_never_return_sentinel(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
    fields: dict[str, Any],
) -> None:
    """Missing or wrong names and malformed params/arguments cannot certify wiring."""
    request = {"jsonrpc": "2.0", "id": "bad-call", "method": "tools/call", **fields}
    replies = mcp_process([json.dumps(request)])
    assert_that(replies).is_length(1)
    assert_that(replies[0]["id"]).is_equal_to("bad-call")
    assert_that(replies[0]["error"]["code"]).is_equal_to(-32602)
    assert_that(replies[0]).does_not_contain_key("result")
    assert_that(json.dumps(replies)).does_not_contain("PROBE-7f3a-integration")


@pytest.mark.parametrize(
    ("line", "code", "request_id"),
    [
        ("{", -32700, None),
        ('{"jsonrpc":"2.0","id":NaN,"method":"tools/call"}', -32700, None),
        ('{"jsonrpc":"2.0","id":1e999,"method":"tools/call"}', -32600, None),
        ("null", -32600, None),
        ("[]", -32600, None),
        ('{"jsonrpc":"2.0","id":1}', -32600, 1),
        ('{"jsonrpc":"1.0","id":1,"method":"tools/call"}', -32600, 1),
        ('{"jsonrpc":"2.0","id":[],"method":"tools/call"}', -32600, None),
        ('{"jsonrpc":"2.0","id":true,"method":"tools/call"}', -32600, None),
        ('{"jsonrpc":"2.0","id":1,"method":42}', -32600, 1),
        ('{"jsonrpc":"2.0","id":0,"method":"unknown"}', -32601, 0),
        ('{"jsonrpc":"2.0","id":"x","method":"unknown"}', -32601, "x"),
        ('{"jsonrpc":"2.0","id":"x","method":"initialize","params":[]}', -32602, "x"),
    ],
)
def test_protocol_errors_preserve_stream(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
    line: str,
    code: int,
    request_id: int | str | None,
) -> None:
    """Bad input returns errors and does not stop the next request."""
    replies = mcp_process(
        [line, '{"jsonrpc":"2.0","id":"next","method":"tools/list"}'],
    )
    assert_that(replies).is_length(2)
    assert_that(replies[0]["id"]).is_equal_to(request_id)
    assert_that(replies[0]["error"]["code"]).is_equal_to(code)
    assert_that(replies[1]["id"]).is_equal_to("next")
    assert_that(replies[1]).contains_key("result")
    assert_that(json.dumps(replies)).does_not_contain("PROBE-7f3a-integration")


def test_notifications_are_silent(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
) -> None:
    """Neither valid nor invalid tool-call notifications emit replies or tokens."""
    messages = [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "unknown"},
        {"jsonrpc": "2.0", "method": "tools/call"},
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "probe_integration", "arguments": {}},
        },
    ]
    assert_that(mcp_process([json.dumps(message) for message in messages])).is_empty()


def test_blank_lines_are_ignored_between_requests(
    mcp_process: Callable[[list[str]], list[dict[str, Any]]],
) -> None:
    """Transport whitespace is silent and does not corrupt the next request ID."""
    replies = mcp_process(["", "  ", '{"jsonrpc":"2.0","id":"ok","method":"ping"}'])
    assert_that(replies).is_equal_to([{"jsonrpc": "2.0", "id": "ok", "result": {}}])
