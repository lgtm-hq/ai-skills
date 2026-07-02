#!/usr/bin/env bash
set -euo pipefail

bash scripts/install-ripgrep.sh

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/0.11.26/install.sh | sh
  echo "${HOME}/.local/bin" >>"${GITHUB_PATH:-/dev/null}"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv sync --frozen
