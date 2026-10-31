#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the ai-skills repo.
#
# Provisions the two toolchains this repo ships with and refreshes both
# dependency trees from their committed lockfiles:
#   * uv  -> Python catalog / validation / generator scripts
#   * bun -> the @lgtm-hq/ai-skills gateway CLI under npm/ai-skills/
#
# Safe to run repeatedly: toolchains are installed only when missing or
# off-pin, and both package managers are driven from frozen lockfiles, so
# a second run is a no-op.
#
# Both installers are fetched from version-pinned URLs, written to a temp
# file, and SHA-256 verified before execution (never piped to a shell), so
# a compromised endpoint or delivery path fails the bootstrap closed.
set -euo pipefail

# Resolve the repo root so the script is safe to invoke from any working
# directory, not only via the .cursor/environment.json install hook.
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

# shellcheck source=scripts/tool-versions.sh
source "$repo_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$repo_root/scripts/lib/fetch-verified.sh"

export PATH="${HOME}/.local/bin:${HOME}/.bun/bin:${PATH}"
# uv hardlink warnings are noisy across the VM's separate filesystems.
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

# Enforce the pins even when a tool is preinstalled: an off-pin version on
# PATH is reinstalled rather than silently used.
uv_installed=$(command -v uv >/dev/null 2>&1 && uv --version 2>/dev/null | awk '{print $2}' || true)
bun_installed=$(command -v bun >/dev/null 2>&1 && bun --version 2>/dev/null || true)

if [[ "$uv_installed" != "$UV_VERSION" ]]; then
  fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$tmp_dir/uv-install.sh"
  sh "$tmp_dir/uv-install.sh"
fi

if [[ "$bun_installed" != "$BUN_VERSION" ]]; then
  fetch_verified "$BUN_INSTALLER_URL" "$BUN_INSTALLER_SHA256" "$tmp_dir/bun-install.sh"
  bash "$tmp_dir/bun-install.sh" "bun-v${BUN_VERSION}"
fi

# Drop bash's cached command paths so the probes above cannot pin an off-pin
# executable found before the installers ran, then assert the pins actually
# resolve before any dependency work uses them.
hash -r
uv_final=$(uv --version | awk '{print $2}')
bun_final=$(bun --version)
if [[ "$uv_final" != "$UV_VERSION" || "$bun_final" != "$BUN_VERSION" ]]; then
  echo "Toolchain pin not resolved: uv=${uv_final} (want ${UV_VERSION}), bun=${bun_final} (want ${BUN_VERSION})" >&2
  exit 1
fi

# scripts/validate.sh needs ripgrep on PATH; the helper no-ops when present.
bash scripts/install-ripgrep.sh

uv sync --frozen

(cd npm/ai-skills && bun install --frozen-lockfile)
