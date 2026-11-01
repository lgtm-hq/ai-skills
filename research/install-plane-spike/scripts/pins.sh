#!/usr/bin/env bash
set -euo pipefail
source scripts/tool-versions.sh
{
  echo "bun=$BUN_VERSION"
  echo "uv=$UV_VERSION"
  sed -n 's/^  "python": "\([^"]*\)",$/python=\1/p' \
    research/install-plane-spike/settings.json
} >>"$GITHUB_OUTPUT"
