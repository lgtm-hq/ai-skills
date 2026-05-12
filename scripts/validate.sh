#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
	cat <<'EOF'
Validate skill repository consistency.

Checks:
  1. SKILL.md filename casing in skills/*/
  2. name + description keys in SKILL.md frontmatter
  3. AGENTS.md entries match skills/ directories (regenerate skills list via:
     uv run python scripts/generate_agents_md.py)
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

for skill_file in skills/*/SKILL.md; do
	[[ -f "$skill_file" ]] || continue
	if ! awk '
		BEGIN { in_fm=0; start=0; has_name=0; has_desc=0; has_end=0 }
		NR==1 && $0=="---" { in_fm=1; start=1; next }
		in_fm && $0=="---" { in_fm=0; has_end=1; exit }
		in_fm && $0 ~ /^name:[[:space:]]*/ { has_name=1 }
		in_fm && $0 ~ /^description:[[:space:]]*/ { has_desc=1 }
		END { if (!(start && has_end && has_name && has_desc)) exit 1 }
	' "$skill_file"; then
		echo "Missing frontmatter name/description in $skill_file"
		errors=$((errors + 1))
	fi
done

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

if [[ "$errors" -gt 0 ]]; then
	echo "Validation failed with $errors error(s)."
	exit 1
fi

echo "Validation passed."
