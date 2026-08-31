#!/usr/bin/env bash
# Re-pin one vendor and open (or update) a review-only PR. Never auto-merges.

set -euo pipefail

vendor="${1:?vendor id required}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
cd "$repo_root"

summary="$(mktemp)"
trap 'rm -f "$summary"' EXIT

status=0
uv run python scripts/repin_vendor.py --id "$vendor" --summary-path "$summary" ||
  status=$?

paths=(
  vendors.yaml
  vendor-indexes
  npm/ai-skills/data
  NOTICE.md
  npm/ai-skills/NOTICE.md
)

if [[ -z "$(git status --porcelain -- "${paths[@]}")" ]]; then
  if [[ "$status" -ne 0 ]]; then
    exit "$status"
  fi
  echo "No pin change for ${vendor}."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

branch="chore/vendor-repin-${vendor}"
git checkout -B "$branch"
git add -- "${paths[@]}"
git commit -m "chore(vendors): re-pin ${vendor}"
git push --force-with-lease -u origin "$branch"

existing="$(
  gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty'
)"
if [[ -n "$existing" ]]; then
  gh pr edit "$existing" --body-file "$summary"
else
  gh pr create \
    --title "chore(vendors): re-pin ${vendor}" \
    --body-file "$summary" \
    --label "new-vendor" \
    --label "automation"
fi

# Collisions fail the re-pin command but still land as a human-review PR.
exit 0
