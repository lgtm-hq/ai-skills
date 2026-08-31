#!/usr/bin/env bash
# Emit a JSON vendor-id matrix for the vendor re-pin workflow.

set -euo pipefail

vendor="${1:-all}"
if [[ "$vendor" == "all" || -z "$vendor" ]]; then
  json="$(uv run python scripts/repin_vendor.py --list-json)"
else
  json="$(uv run python scripts/repin_vendor.py --list-json --id "$vendor")"
fi
echo "vendors=${json}" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
