#!/usr/bin/env bash
# Publish the ai-skills npm package. Default mode verifies the tarball only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/npm/ai-skills"

package_name="$(cd "$PACKAGE_DIR" && node -p "require('./package.json').name")"
package_version="$(cd "$PACKAGE_DIR" && node -p "require('./package.json').version")"

# Always validate package contents locally before any registry publish path.
# npm publish --dry-run fails when the version already exists, so packing is
# the reliable dry-run content check.
(cd "$PACKAGE_DIR" && npm pack --dry-run)

publish_flags=(--access public --tag "${NPM_DIST_TAG:-latest}")
if [[ "${LIVE:-0}" == "1" ]]; then
  publish_flags+=(--provenance)
else
  publish_flags+=(--dry-run)
  echo "DRY-RUN mode: no package will be published."
  # npm publish --dry-run still errors when the version already exists on the
  # registry. After pack validation above, treat that as a successful no-op.
  if npm view "${package_name}@${package_version}" version >/dev/null 2>&1; then
    echo "Already published: ${package_name}@${package_version} — nothing to do."
    exit 0
  fi
fi

(cd "$PACKAGE_DIR" && npm publish "${publish_flags[@]}")
