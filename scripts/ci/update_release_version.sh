#!/usr/bin/env bash
# Run after the ecosystem updater bumps pyproject.toml and uv.lock.
# The reusable workflow carries these tracked edits into the same version PR.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"
bash scripts/update-readme-version.sh

# shellcheck source=scripts/lib/ensure-uv.sh
source "$repo_root/scripts/lib/ensure-uv.sh"
ensure_uv
# Install the bumped project so tar indexes record its real builder identity,
# then regenerate ai-skills.lock. Existing pins never move; missing sources are
# fetched into the source cache.
uv sync --locked
uv run --locked ai-skills-engine lock
