#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
# shellcheck source=scripts/lib/ensure-uv.sh
source "$repo_root/scripts/lib/ensure-uv.sh"

bash scripts/install-ripgrep.sh

if ! command -v uv >/dev/null 2>&1; then
  ensure_uv
  echo "${HOME}/.local/bin" >>"${GITHUB_PATH:-/dev/null}"
fi

uv sync --frozen
