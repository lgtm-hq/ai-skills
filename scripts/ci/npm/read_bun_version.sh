#!/usr/bin/env bash
# Expose the canonical tool pin to setup-bun without duplicating the version.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tool-versions.sh
source "$SCRIPT_DIR/../../tool-versions.sh"
echo "bun-version=$BUN_VERSION" >>"$GITHUB_OUTPUT"
