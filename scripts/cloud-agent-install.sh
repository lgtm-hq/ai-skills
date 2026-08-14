#!/usr/bin/env bash
# Cloud Agent install hook: provision the uv + bun toolchains and refresh both
# deliverables' dependencies. Idempotent so it is safe to rerun against cached
# state or a warm snapshot.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

export PATH="${HOME}/.local/bin:${HOME}/.bun/bin:${PATH}"
# uv hardlink warnings are noisy across the VM's separate filesystems.
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v bun >/dev/null 2>&1; then
  curl -fsSL https://bun.sh/install | bash
fi

# Python catalog/validation/generator deliverable.
uv sync --frozen

# JS gateway CLI deliverable.
(cd npm/ai-skills && bun install --frozen-lockfile)
