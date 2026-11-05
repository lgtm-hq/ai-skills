#!/usr/bin/env bash
# Validate a caller repository's ai-skills.yaml with a pinned ai-skills engine.
#
# Called by .github/workflows/ai-skills-validate.yml with these variables:
#   ENGINE_REF     full 40-hex commit the engine checkout must be at
#   ENGINE_DIR     ai-skills engine checkout
#   CALLER_DIR     caller repository checkout
#   MANIFEST_PATH  caller-relative path whose file name is ai-skills.yaml
#   STRICT         true or false
#   TERMINOLOGY    true or false: also lint docs/ against docs/glossary.md
#
# Every input is validated and the script fails closed. When the caller commits
# ai-skills.lock, `lock --fetch` fills the source cache with exactly the locked,
# digest-verified vendor sources; `validate` itself never fetches or executes
# vendor content.
set -euo pipefail

fail() {
  printf 'ai-skills-validate: %s\n' "$1" >&2
  exit 1
}

[[ "${ENGINE_REF:-}" =~ ^[0-9a-f]{40}$ ]] ||
  fail "engine-ref must be a full 40-hex commit SHA"
[[ "${STRICT:-}" == "true" || "${STRICT:-}" == "false" ]] ||
  fail "strict must be true or false"
[[ "${TERMINOLOGY:-}" == "true" || "${TERMINOLOGY:-}" == "false" ]] ||
  fail "terminology must be true or false"
manifest="${MANIFEST_PATH:-}"
[[ "$manifest" =~ ^([A-Za-z0-9_.-]+/)*ai-skills\.yaml$ ]] ||
  fail "manifest-path must be a relative path to an ai-skills.yaml file"
case "/$manifest" in
*/./* | */../*) fail "manifest-path must not contain . or .. segments" ;;
esac
[[ -d "${ENGINE_DIR:-}" && -d "${CALLER_DIR:-}" ]] ||
  fail "ENGINE_DIR and CALLER_DIR must be checked-out directories"

actual="$(git -C "$ENGINE_DIR" rev-parse HEAD)"
[[ "$actual" == "$ENGINE_REF" ]] ||
  fail "engine checkout is at $actual, expected $ENGINE_REF"

root="$(dirname -- "$CALLER_DIR/$manifest")"
[[ -f "$root/ai-skills.yaml" && ! -L "$root/ai-skills.yaml" ]] ||
  fail "$manifest is not a regular file in the caller checkout"

engine=(uv run --project "$ENGINE_DIR" --locked --no-dev ai-skills-engine)
if [[ -f "$root/ai-skills.lock" ]]; then
  "${engine[@]}" lock --fetch --repo-root "$root"
fi
arguments=(validate --repo-root "$root")
if [[ "$STRICT" == "true" ]]; then
  arguments+=(--strict)
fi
if [[ "$TERMINOLOGY" == "true" ]]; then
  arguments+=(--terminology)
fi
"${engine[@]}" "${arguments[@]}"
