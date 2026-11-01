"""Serve a dependency-free, read-only MCP sentinel over stdio."""

import json
import math
import sys
from typing import Any, Never

TOOL_NAME = "probe_integration"


def reject_constant(value: str) -> Never:
    """Reject non-JSON numeric constants accepted by Python's decoder."""
    raise ValueError(f"Invalid JSON constant: {value}")


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC error without an integration sentinel."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def respond(line: str) -> dict[str, Any] | None:
    """Validate one MCP message; notifications produce no response."""
    try:
        request = json.loads(line, parse_constant=reject_constant)
    except ValueError:
        return error(request_id=None, code=-32700, message="Parse error")
    if (
        not isinstance(request, dict)
        or request.get("jsonrpc") != "2.0"
        or not isinstance(request.get("method"), str)
        or type(request.get("id")) not in (str, int, float, type(None))
        or ("id" in request and request["id"] is None)
        or (isinstance(request.get("id"), float) and not math.isfinite(request["id"]))
    ):
        return error(request_id=None, code=-32600, message="Invalid Request")
    if "id" not in request:
        return None
    request_id = request["id"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return error(request_id=request_id, code=-32602, message="Invalid params")
    method = request["method"]
    result: dict[str, Any]
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "probe-sentinel", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Return the integration sentinel",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            ],
        }
    elif method == "tools/call":
        arguments = params.get("arguments", {})
        if (
            params.get("name") != TOOL_NAME
            or not isinstance(arguments, dict)
            or arguments
        ):
            return error(request_id=request_id, code=-32602, message="Invalid params")
        result = {
            "content": [{"type": "text", "text": "PROBE-7f3a-integration"}],
        }
    else:
        return error(request_id=request_id, code=-32601, message="Method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    """Read newline-delimited messages and keep serving after invalid input."""
    for line in sys.stdin:
        response = respond(line)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
