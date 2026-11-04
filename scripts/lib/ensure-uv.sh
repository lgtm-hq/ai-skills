#!/usr/bin/env bash
# Sourced uv bootstrap; reuse the repository's verified installer and pins.

uv_tooling_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck source=scripts/tool-versions.sh
source "$uv_tooling_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$uv_tooling_root/scripts/lib/fetch-verified.sh"

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  local uv_bootstrap_dir
  uv_bootstrap_dir=$(mktemp -d) || return
  (
    trap 'rm -rf "$uv_bootstrap_dir"' EXIT
    fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$uv_bootstrap_dir/uv-install.sh" &&
      sh "$uv_bootstrap_dir/uv-install.sh"
  ) || return
  export PATH="${HOME}/.local/bin:${PATH}"
}
