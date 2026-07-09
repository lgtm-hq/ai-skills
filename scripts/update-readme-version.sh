#!/usr/bin/env bash
# Rewrite release-tag pins in README.md to a new version.
#
# Runs as the repo-specific version-update-script in the release version-PR
# workflow (after the ecosystem updater bumps pyproject.toml), keeping the
# README install examples pinned to the release being cut. Mirrors the pin
# patterns in scripts/generate_readme.py.
#
# Required environment variables:
#   NEXT_VERSION Semver to pin, without the v prefix (e.g. 0.1.23)
#
# Optional arguments:
#   $1 Path to the README to rewrite (default: README.md in the repo root)
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readme_path="${1:-${repo_root}/README.md}"

if [[ -z "${NEXT_VERSION:-}" ]]; then
  echo "NEXT_VERSION is required (semver, e.g. 0.1.23)." >&2
  exit 1
fi
# lgtm-ci emits a bare X.Y.Z; tolerate a v prefix in case that ever changes.
next_version="${NEXT_VERSION#v}"
if [[ ! "${next_version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "NEXT_VERSION must be X.Y.Z or vX.Y.Z (got: '${NEXT_VERSION}')." >&2
  exit 1
fi
if [[ ! -f "${readme_path}" ]]; then
  echo "README not found: ${readme_path}" >&2
  exit 1
fi

# -i.bak keeps BSD (macOS) and GNU sed compatible.
sed -E -i.bak \
  -e "s|(lgtm-hq/ai-skills@v)[0-9]+\.[0-9]+\.[0-9]+|\1${next_version}|g" \
  -e "s|(gh release download v)[0-9]+\.[0-9]+\.[0-9]+|\1${next_version}|g" \
  "${readme_path}"
rm -f "${readme_path}.bak"
echo "Pinned README install examples to v${next_version}."
