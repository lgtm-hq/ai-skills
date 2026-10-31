#!/usr/bin/env bash
# Verify both pins even when installed tools would skip the bootstrap download.
# Downloaded installers are never executed by this check.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck source=scripts/tool-versions.sh
source "$repo_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$repo_root/scripts/lib/fetch-verified.sh"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$tmp_dir/uv-install.sh"
echo "Verified uv ${UV_VERSION} installer: ${UV_INSTALLER_SHA256}"
fetch_verified "$BUN_INSTALLER_URL" "$BUN_INSTALLER_SHA256" "$tmp_dir/bun-install.sh"
echo "Verified bun ${BUN_VERSION} installer: ${BUN_INSTALLER_SHA256}"
