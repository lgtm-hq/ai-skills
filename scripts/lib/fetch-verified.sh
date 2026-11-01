#!/usr/bin/env bash
# Sourced helpers: no downloads or shell option changes at load time.

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# fetch_verified <url> <sha256> <dest>: download, then verify before use.
# Explicit returns also fail closed when the caller tests the function status.
fetch_verified() {
  local url="$1" expected="$2" dest="$3" actual
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Invalid SHA-256 pin: expected exactly 64 lowercase hex characters" >&2
    return 1
  fi
  curl --proto '=https' --proto-redir '=https' -LsSf "$url" -o "$dest" || return
  actual=$(sha256_of "$dest") || return
  if [[ "$actual" != "$expected" ]]; then
    echo "Checksum mismatch for ${url}: expected ${expected}, got ${actual}" >&2
    return 1
  fi
}
