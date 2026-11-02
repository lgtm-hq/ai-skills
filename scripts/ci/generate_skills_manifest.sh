#!/usr/bin/env bash
# Install only the author engine and runtime dependencies for release generation.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"
# shellcheck source=scripts/tool-versions.sh
source "$repo_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$repo_root/scripts/lib/fetch-verified.sh"

if ! command -v uv >/dev/null 2>&1; then
  manifest_tmp=$(mktemp -d)
  trap 'rm -rf "$manifest_tmp"' EXIT
  fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$manifest_tmp/uv-install.sh"
  sh "$manifest_tmp/uv-install.sh"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv run --locked --no-dev python scripts/generate_skills_manifest.py "$@"
