#!/usr/bin/env bash
# Re-pin one vendor and open (or update) a review-only PR. Never auto-merges.

set -euo pipefail

vendor="${1:?vendor id required}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
cd "$repo_root"

summary="$(mktemp)"
trap 'rm -f "$summary"' EXIT

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

base_sha="$(git rev-parse HEAD)"
branch="chore/vendor-repin-${vendor}"

# Preserve commits already on this vendor's re-pin PR (for example a
# human ``renameSkills`` recovery) instead of discarding them with
# ``checkout -B`` from main. Merge the job's base SHA onto the existing
# branch, then re-pin. Merge conflicts fail the job.
#
# Fetch here also seeds ``origin/${branch}`` for ``--force-with-lease``.
# Do not fetch again immediately before the push: that would refresh the
# lease to the current remote tip and skip the remote-has-moved check.
if git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"; then
  git checkout -B "$branch" "origin/$branch"
  git merge --no-edit "$base_sha"
else
  git checkout -B "$branch" "$base_sha"
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is dirty before vendor re-pin" >&2
  exit 1
fi

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

git add -- "${paths[@]}"
git commit -m "chore(vendors): re-pin ${vendor}"

if git rev-parse --verify "origin/${branch}" >/dev/null 2>&1; then
  git push --force-with-lease -u origin "$branch"
else
  git push -u origin "$branch"
fi

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
