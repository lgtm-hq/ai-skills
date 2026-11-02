#!/usr/bin/env bash
# Acquire nested compiler/type dependencies before Lintro's root-level discovery.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

for project in npm/ai-skills research/install-plane-spike/ts; do
  (
    cd "$REPO_ROOT/$project"
    bun install --frozen-lockfile --ignore-scripts
  )
done
