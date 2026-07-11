#!/usr/bin/env bash
# Publish the ai-skills npm package. Default mode verifies the tarball only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/npm/ai-skills"

publish_flags=(--access public --tag "${NPM_DIST_TAG:-latest}")
if [[ "${LIVE:-0}" == "1" ]]; then
  publish_flags+=(--provenance)
else
  publish_flags+=(--dry-run)
  echo "DRY-RUN mode: no package will be published."
fi

(cd "$PACKAGE_DIR" && npm publish "${publish_flags[@]}")
