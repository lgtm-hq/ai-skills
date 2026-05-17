#!/usr/bin/env bash
set -euo pipefail

if command -v rg >/dev/null 2>&1; then
  exit 0
fi

if command -v sudo >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends ripgrep
else
  apt-get update -qq
  apt-get install -y --no-install-recommends ripgrep
fi
