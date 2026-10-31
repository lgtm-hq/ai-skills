#!/usr/bin/env bash
# Refresh Renovate's selected pins and summarize them against the PR base.

set -euo pipefail

: "${SUMMARY_PATH:?SUMMARY_PATH is required}"
rm -f "$SUMMARY_PATH"
refresh_status=0
uv run python scripts/manage_vendors.py refresh || refresh_status=$?

status=0
uv run python scripts/repin_vendor.py \
  --all --keep-sha \
  --baseline-ref "${BASE_SHA:?BASE_SHA is required}" \
  --summary-path "${SUMMARY_PATH:?SUMMARY_PATH is required}" || status=$?

# A collision produces a reviewable summary; a hard failure does not.
if [[ ! -s "$SUMMARY_PATH" ]]; then
  exit 1
fi
if [[ "$status" -eq 0 ]]; then
  status=$refresh_status
fi
echo "summary-status=${status}" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
