#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Validate skill repository consistency.

Checks:
  1. SKILL.md filename casing in skills/*/
  2. SKILL.md frontmatter values (YAML mapping; non-empty name/description
     strings; description <= 1024 chars; name matches directory; optional
     'upstream' provenance block is well-formed and the upstream-drift
     tracking workflow exists) via:
     uv run python scripts/validate_skills.py
  3. AGENTS.md entries match skills/ directories (regenerate skills list via:
     uv run python scripts/generate_agents_md.py)
  4. bundles.yaml covers all skills and marketplace.json is in sync (regenerate via:
     uv run python scripts/generate_marketplace.py)
  5. skills-manifest generator is deterministic (two runs produce identical
     output; see scripts/generate_skills_manifest.py)
EOF
  exit 0
fi

if [[ ! -d "skills" ]]; then
  echo "No skills/ directory in this branch. Skipping validation."
  exit 0
fi

errors=0

for dir in skills/*; do
  [[ -d "$dir" ]] || continue
  if [[ ! -f "$dir/SKILL.md" ]]; then
    echo "Missing SKILL.md in $dir"
    errors=$((errors + 1))
  fi
  for entry in "$dir"/*; do
    entry_name=$(basename "$entry")
    entry_lower=$(printf '%s' "$entry_name" | tr '[:upper:]' '[:lower:]')
    if [[ "$entry_name" != "SKILL.md" && "$entry_lower" == "skill.md" ]]; then
      echo "Invalid skill filename casing: $entry"
      errors=$((errors + 1))
    fi
  done
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to validate SKILL.md frontmatter; please install it."
  errors=$((errors + 1))
elif ! uv run python "$script_dir/validate_skills.py" skills; then
  errors=$((errors + 1))
fi

if [[ -f "AGENTS.md" ]]; then
  if ! command -v rg >/dev/null 2>&1; then
    echo "ripgrep (rg) is required to validate AGENTS.md; please install it."
    exit 1
  fi
  for dir in skills/*; do
    [[ -d "$dir" ]] || continue
    skill_name=$(basename "$dir")
    escaped_skill_name=$(printf '%s' "$skill_name" | sed -E 's/[][(){}.^$*+?|\\]/\\&/g')
    if ! rg --quiet -- "^[[:space:]]*[-*+][[:space:]]+\`$escaped_skill_name\`([[:space:]:]|$)" AGENTS.md; then
      echo "AGENTS.md missing skill entry for: $skill_name"
      errors=$((errors + 1))
    fi
  done

  while IFS= read -r skill_name; do
    if [[ -z "$skill_name" || "$skill_name" == "." || "$skill_name" == ".." || "$skill_name" == */* ]]; then
      echo "AGENTS.md contains invalid skill name: $skill_name"
      errors=$((errors + 1))
      continue
    fi
    if [[ ! -d "skills/$skill_name" ]]; then
      echo "AGENTS.md references missing skill directory: $skill_name"
      errors=$((errors + 1))
    fi
  done < <(rg --no-filename "^[[:space:]]*[-*+][[:space:]]+\`[^\`]+\`" AGENTS.md | sed -E "s/^[[:space:]]*[-*+][[:space:]]+\`([^\`]+)\`.*/\1/")
else
  echo "AGENTS.md not found. Skipping AGENTS consistency checks."
fi

if [[ -f "bundles.yaml" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to validate bundles/marketplace; please install it."
    errors=$((errors + 1))
  elif ! uv run python scripts/generate_marketplace.py --check; then
    errors=$((errors + 1))
  fi
else
  echo "bundles.yaml not found. Skipping marketplace consistency checks."
fi

if [[ ! -f "scripts/generate_skills_manifest.py" ]]; then
  echo "scripts/generate_skills_manifest.py not found. Skipping manifest checks."
elif command -v python3 >/dev/null 2>&1; then
  manifest_tmp_dir=$(mktemp -d)
  trap 'rm -rf "$manifest_tmp_dir"' EXIT
  if python3 scripts/generate_skills_manifest.py \
    --output "$manifest_tmp_dir/first.json" >/dev/null &&
    python3 scripts/generate_skills_manifest.py \
      --output "$manifest_tmp_dir/second.json" >/dev/null; then
    if ! diff -u "$manifest_tmp_dir/first.json" "$manifest_tmp_dir/second.json"; then
      echo "skills-manifest generator output is not deterministic."
      errors=$((errors + 1))
    fi
  else
    echo "skills-manifest generator failed to run."
    errors=$((errors + 1))
  fi
else
  echo "python3 is required to validate the skills-manifest generator."
  errors=$((errors + 1))
fi

if [[ "$errors" -gt 0 ]]; then
  echo "Validation failed with $errors error(s)."
  exit 1
fi

echo "Validation passed."
