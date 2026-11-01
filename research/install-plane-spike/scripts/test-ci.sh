#!/usr/bin/env bash
set -euo pipefail
export SPIKE_REQUIRE_BUN=1
uv run --no-project --python "$SPIKE_PYTHON" \
  --with pytest==9.0.3 --with assertpy==1.1 \
  pytest -o addopts='' tests/test_install_plane_spike.py tests/test_install_plane_collector.py
