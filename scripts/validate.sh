#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Validate skill repository consistency.

Checks:
  1. SKILL.md filename casing in skills/*/
  2. SKILL.md frontmatter values (YAML mapping; non-empty name/description
     strings; description <= 1024 chars; name matches directory) via:
     uv run python scripts/validate_skills.py
  3. AGENTS.md entries match skills/ directories (regenerate skills list via:
     uv run python scripts/generate_agents_md.py)
  4. bundles.yaml covers all skills and marketplace.json is in sync (regenerate via:
     uv run python scripts/generate_marketplace.py)
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

if [[ "$errors" -gt 0 ]]; then
  echo "Validation failed with $errors error(s)."
  exit 1
fi

echo "Validation passed."
