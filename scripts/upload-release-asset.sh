#!/usr/bin/env bash
# Upload an asset file to an existing GitHub Release.
#
# Required environment variables:
#   TAG      Release tag to attach the asset to (e.g. v0.1.10)
#   ASSET    Path of the asset file to upload
#   GH_TOKEN Token used by the gh CLI
set -euo pipefail

if [[ -z "${TAG:-}" ]]; then
  echo "TAG is required (release tag, e.g. v0.1.10)." >&2
  exit 1
fi
if [[ -z "${ASSET:-}" || ! -f "${ASSET}" ]]; then
  echo "ASSET is required and must be an existing file (got: '${ASSET:-}')." >&2
  exit 1
fi

echo "Uploading ${ASSET} to release ${TAG}..."
gh release upload "${TAG}" "${ASSET}" --clobber
echo "Uploaded ${ASSET} to ${TAG}."
