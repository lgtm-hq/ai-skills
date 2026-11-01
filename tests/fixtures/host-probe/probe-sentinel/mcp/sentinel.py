"""Serve a dependency-free, read-only MCP sentinel over stdio."""

import json
import sys

result: dict[str, object]

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "PROBE-7f3a-integration", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "probe_integration",
                    "description": "Return the integration sentinel",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ],
        }
    elif method == "tools/call":
        result = {
            "content": [{"type": "text", "text": "PROBE-7f3a-integration"}],
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))
    sys.stdout.flush()
