#!/usr/bin/env bash
set -euo pipefail
source scripts/tool-versions.sh
{
  echo "bun=$BUN_VERSION"
  echo "uv=$UV_VERSION"
  python3 research/install-plane-spike/scripts/pins.py
} >>"$GITHUB_OUTPUT"
