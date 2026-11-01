#!/usr/bin/env bash
set -euo pipefail
build/spike/py/runtime/bin/python3 -E -s -B \
  research/install-plane-spike/scripts/measure.py \
  --build build/spike --results build/spike/results --offline-only
