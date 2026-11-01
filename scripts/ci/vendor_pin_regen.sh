#!/usr/bin/env bash
# Summarize selected pins against the merge base, then refresh without credentials.
set -euo pipefail

: "${SUMMARY_PATH:?SUMMARY_PATH is required}"
: "${ARTIFACT_DIR:?ARTIFACT_DIR is required}"
mkdir -p "$ARTIFACT_DIR"
rm -f "$SUMMARY_PATH" "$ARTIFACT_DIR/publication.json"
baseline=$(git merge-base "${BASE_SHA:?BASE_SHA is required}" HEAD)
status=0
uv run python scripts/repin_vendor.py \
  --all --keep-sha \
  --baseline-ref "$baseline" \
  --summary-path "$SUMMARY_PATH" || status=$?

# Only collisions produce both a nonzero status and a complete summary.
# Publish their report without committing any generated data.
if [[ ! -s "$SUMMARY_PATH" ]]; then
  exit 1
fi
if [[ "$status" -eq 0 ]]; then
  # Never package partial refresh output, even when a summary already exists.
  uv run python scripts/manage_vendors.py refresh
fi
SUMMARY_STATUS="$status" uv run python scripts/ci/vendor_pin_artifact.py
