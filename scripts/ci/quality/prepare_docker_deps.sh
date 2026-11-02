#!/usr/bin/env bash
# Use the same image, mount, and user as the full quality check.
set -euo pipefail

: "${LINTRO_IMAGE:?Pinned LINTRO_IMAGE is required}"

docker pull "$LINTRO_IMAGE"
docker run --rm --user "$(id -u):$(id -g)" --entrypoint /bin/bash \
  -e HOME=/tmp -e BUN_INSTALL=/tmp/.bun \
  -v "$PWD:/code" -w /code \
  "$LINTRO_IMAGE" scripts/ci/quality/prepare_node_deps.sh
