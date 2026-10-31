#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
# shellcheck source=scripts/tool-versions.sh
source "$repo_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$repo_root/scripts/lib/fetch-verified.sh"

bash scripts/install-ripgrep.sh

if ! command -v uv >/dev/null 2>&1; then
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT
  fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$tmp_dir/uv-install.sh"
  sh "$tmp_dir/uv-install.sh"
  echo "${HOME}/.local/bin" >>"${GITHUB_PATH:-/dev/null}"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv sync --frozen
