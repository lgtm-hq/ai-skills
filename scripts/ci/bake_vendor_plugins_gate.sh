#!/usr/bin/env bash
# Bake vendor plugin slices and fail closed on validation/collisions.
# Coverage is printed to stdout and, in GitHub Actions, the job summary.

set -euo pipefail

uv run python scripts/bake_vendor_plugins.py
uv run python scripts/bake_vendor_plugins.py --check

coverage="plugins-baked/COVERAGE.md"
if [[ -f "$coverage" && -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## Vendor plugin bake coverage"
    echo
    cat "$coverage"
  } >>"$GITHUB_STEP_SUMMARY"
fi
