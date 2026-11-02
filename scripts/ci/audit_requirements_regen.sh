#!/usr/bin/env bash
# Run from the trusted PR base; read only the two lock inputs from the PR head.
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
if [[ ! ${PR_HEAD_SHA:-} =~ ^[0-9a-f]{40}$ ]]; then
  echo 'PR_HEAD_SHA must be a full commit SHA' >&2
  exit 2
fi
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

audit_work=$(mktemp -d)
trap 'rm -rf "$audit_work"' EXIT
git fetch --no-tags --depth=1 origin "$PR_HEAD_SHA"
for audit_input in pyproject.toml uv.lock requirements-audit.txt; do
  git show "$PR_HEAD_SHA:$audit_input" >"$audit_work/$audit_input"
done
# Neither a PR script nor a PR interpreter is executed. uv export reads TOML/lock
# data offline without syncing or building the project or its dependencies.
cp "$audit_work/pyproject.toml" pyproject.toml
cp "$audit_work/uv.lock" uv.lock
bash scripts/export-audit-requirements.sh
bash scripts/export-audit-requirements.sh --check

if cmp -s "$audit_work/requirements-audit.txt" requirements-audit.txt; then
  echo 'changed=false' >>"$GITHUB_OUTPUT"
else
  echo 'changed=true' >>"$GITHUB_OUTPUT"
fi
