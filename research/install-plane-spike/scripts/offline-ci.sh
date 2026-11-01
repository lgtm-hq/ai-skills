#!/usr/bin/env bash
set -euo pipefail
export PATH="$PWD/build/spike/tooling:$PATH"
collector_python="$PWD/build/spike/py/runtime/bin/python3"
if [[ ! -x "$collector_python" ]]; then
  # The missing bundled interpreter is measured as unavailable, using only the
  # runner's existing Python to export collection failure without any fetch.
  collector_python="$(command -v python3)"
fi
"$collector_python" -E -s -B \
  research/install-plane-spike/scripts/measure.py \
  --build build/spike --results build/spike/results --offline-only
