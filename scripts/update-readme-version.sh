#!/usr/bin/env bash
# Rewrite release-tag pins in README.md and plugin versions in
# .claude-plugin/marketplace.json and .cursor-plugin/marketplace.json.
#
# Runs as the repo-specific version-update-script in the release version-PR
# workflow (after the ecosystem updater bumps pyproject.toml), keeping the
# README install examples and generated marketplace stamps pinned to the
# release being cut. README patterns mirror scripts/generate_readme.py
# (git-tag, @lgtm-hq/ai-skills@, gh, and the prose npm↔tag pair).
#
# Required environment variables:
#   NEXT_VERSION Semver to pin, without the v prefix (e.g. 0.1.23)
#
# Optional arguments:
#   $1 Path to the README to rewrite (default: README.md in the repo root).
#      Marketplace.json files are rewritten when they sit next to that README.
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
# Patterns mirror scripts/generate_readme.py (_VERSION_PIN_PATTERNS +
# _PROSE_VERSION_PAIR_PATTERN): git-tag pins, scoped npm package pins,
# gh release download pins, and the prose npm↔tag pair.
sed -E -i.bak \
  -e "s|(lgtm-hq/ai-skills@v)[0-9]+\.[0-9]+\.[0-9]+|\1${next_version}|g" \
  -e "s|(@lgtm-hq/ai-skills@)[0-9]+\.[0-9]+\.[0-9]+|\1${next_version}|g" \
  -e "s|(gh release download v)[0-9]+\.[0-9]+\.[0-9]+|\1${next_version}|g" \
  -e "s|\`@[0-9]+\.[0-9]+\.[0-9]+\` ↔ \`v[0-9]+\.[0-9]+\.[0-9]+\`|\`@${next_version}\` ↔ \`v${next_version}\`|g" \
  "${readme_path}"
rm -f "${readme_path}.bak"
echo "Pinned README install examples to v${next_version}."

# Marketplace plugin versions are stamped at generation from the repo
# version. Restamp them here so the release version PR stays drift-clean
# without needing uv/python in the updater environment. A missing sibling
# marketplace.json is skipped so README-only invocations still succeed.
readme_dir=$(cd -- "$(dirname -- "${readme_path}")" && pwd)
for marketplace_path in \
  "${readme_dir}/.claude-plugin/marketplace.json" \
  "${readme_dir}/.cursor-plugin/marketplace.json"; do
  if [[ -f "${marketplace_path}" ]]; then
    sed -E -i.bak \
      -e "s|(\"version\": \")[0-9]+\.[0-9]+\.[0-9]+(\")|\1${next_version}\2|g" \
      "${marketplace_path}"
    rm -f "${marketplace_path}.bak"
    if ! grep -Fq "\"version\": \"${next_version}\"" "${marketplace_path}"; then
      echo "Failed to restamp plugin versions in ${marketplace_path} to ${next_version}." >&2
      exit 1
    fi
    echo "Pinned marketplace plugin versions to ${next_version}."
  fi
done
