#!/usr/bin/env bash
set -euo pipefail
source scripts/tool-versions.sh
{
  echo "bun=$BUN_VERSION"
  echo "uv=$UV_VERSION"
  # actions runners provide Python here; avoid Git Bash's python3 Store alias.
  "${pythonLocation:+$pythonLocation/}python" research/install-plane-spike/scripts/pins.py
} >>"$GITHUB_OUTPUT"
