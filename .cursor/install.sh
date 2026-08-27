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

export PATH="${HOME}/.local/bin:${HOME}/.bun/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi

if ! command -v bun >/dev/null 2>&1; then
  curl -fsSL https://bun.sh/install | bash
fi

uv sync --frozen

(cd npm/ai-skills && bun install)
