#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the ai-skills repo.
#
# Provisions the two toolchains this repo ships with and refreshes both
# dependency trees from their committed lockfiles:
#   * uv  -> Python catalog / validation / generator scripts
#   * bun -> the @lgtm-hq/ai-skills gateway CLI under npm/ai-skills/
#
# Safe to run repeatedly: toolchains are installed only when missing and
# both package managers are driven from frozen lockfiles, so a second run
# is a no-op.
set -euo pipefail

# uv pin mirrors scripts/install-validate-deps.sh so local, CI, and Cloud
# Agent setups resolve the same interpreter and tooling.
UV_VERSION="0.11.26"

# Resolve the repo root so the script is safe to invoke from any working
# directory, not only via the .cursor/environment.json install hook.
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

export PATH="${HOME}/.local/bin:${HOME}/.bun/bin:${PATH}"
# uv hardlink warnings are noisy across the VM's separate filesystems.
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi

if ! command -v bun >/dev/null 2>&1; then
  curl -fsSL https://bun.sh/install | bash
fi

uv sync --frozen

(cd npm/ai-skills && bun install --frozen-lockfile)
