#!/usr/bin/env bash
set -euo pipefail

bash scripts/install-ripgrep.sh

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv sync --frozen
