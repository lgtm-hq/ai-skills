#!/usr/bin/env bash
set -euo pipefail
export SPIKE_REQUIRE_BUN=1
requirements="$(uv run --no-project --isolated --python "$SPIKE_PYTHON" \
  research/install-plane-spike/scripts/pins.py --test-dependencies)"
dependency_args=()
while IFS= read -r requirement; do
  dependency_args+=("--with=$requirement")
done <<<"$requirements"
uv run --no-project --isolated --python "$SPIKE_PYTHON" \
  "${dependency_args[@]}" \
  pytest -o addopts='' tests/test_install_plane_spike.py tests/test_install_plane_collector.py
