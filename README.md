# ai-skills

<!-- markdownlint-disable MD033 MD013 -- badges and centered intro -->
<p align="center">
Canonical <a href="https://agentskills.io">Agent Skills</a> library — one <code>skills/</code> tree for Claude Code, Cursor, Codex, and other agents.
</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT"></a>
<a href="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
<a href="https://github.com/lgtm-hq/ai-skills/releases/latest"><img src="https://img.shields.io/github/v/release/lgtm-hq/ai-skills?label=release" alt="Release"></a>
</p>

<!-- markdownlint-enable MD033 MD013 -->

This repository is the **source of truth** for shared skills: each skill lives at
`skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`). There is
**no** per-agent copy of the catalog in-repo; installers symlink into each
agent’s config directory.

## Install (recommended)

Use the [Vercel Labs `skills` CLI](https://github.com/vercel-labs/skills) to
install into detected agents. Prefer **[Bun](https://bun.sh)** and **`bunx`**
(same idea as **`npx`** / **`pnpm dlx`** for other runtimes):

```bash
# Latest from default branch (all skills, all detected agents)
bunx skills add lgtm-hq/ai-skills -g --all

# Pinned to a release tag (example)
bunx skills add lgtm-hq/ai-skills@v0.1.7 -g --all

# Single agent (e.g. Cursor)
bunx skills add lgtm-hq/ai-skills -a cursor -g
```

**npm / pnpm equivalents** (same flags):

```bash
npx skills add lgtm-hq/ai-skills -g --all
pnpm dlx skills add lgtm-hq/ai-skills -g --all
```

### Selective install

Install only the skills you need (names match `skills/<name>/` in this repo; see
**[AGENTS.md](./AGENTS.md)**):

```bash
# List available skills without installing
bunx skills add lgtm-hq/ai-skills -l

# Install specific skills globally
bunx skills add lgtm-hq/ai-skills -g --skill lint commit branch -y

# Pin a subset to a release tag
bunx skills add lgtm-hq/ai-skills@v0.1.7 -g --skill lint test -y
```

### Update installed skills

The CLI updates by **skill name** or **scope**, not by package slug (`update
lgtm-hq/ai-skills` does not match installed skills).

```bash
# Update all globally installed skills from their recorded source
bunx skills update -g

# Update only skills you have installed (by name)
bunx skills update lint commit -g

# npm / pnpm equivalents
npx skills update -g
pnpm dlx skills update -g
```

To move everything to a specific release, reinstall with a tag (replaces symlinks for
that install):

```bash
bunx skills add lgtm-hq/ai-skills@v0.1.7 -g --all
```

List or remove installs with `bunx skills ls -g` and `bunx skills remove <name> -g`.
See the [upstream CLI docs](https://github.com/vercel-labs/skills) for more flags.

## Community

- [Contributing](./CONTRIBUTING.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)

## Skill inventory

See **[AGENTS.md](./AGENTS.md)** for the full list of skills with short
descriptions and paths. Regenerate that index after skill changes (see
`scripts/generate_agents_md.py` in CI).

## Repository layout

```text
skills/<name>/SKILL.md   # Canonical skill definitions (this is the product)
AGENTS.md                # Human- and agent-readable index
scripts/validate.sh       # Frontmatter, naming, AGENTS sync checks
tests/                    # Pytest wraps for validate script
.github/workflows/      # CI + thin callers into org reusable workflows
```

## Architecture

```mermaid
flowchart LR
  subgraph repo [ai-skills]
    SK["skills/**/SKILL.md"]
  end
  subgraph cli [skills CLI]
    add["bunx skills add …"]
  end
  subgraph dirs [Agent config]
    c["~/.claude/skills"]
    u["~/.cursor/skills"]
    x["~/.codex/skills …"]
  end
  SK --> add
  add --> c
  add --> u
  add --> x
```

## Contributing (clone + check)

See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for org policies, skill layout rules, and
full PR expectations. Quick local loop:

```bash
git clone https://github.com/lgtm-hq/ai-skills.git
cd ai-skills
uv sync
uv run lintro fmt
uv run lintro chk
uv run lintro tst
bash scripts/validate.sh
```

Use [Conventional Commits](https://www.conventionalcommits.org/) for PR titles
(squash merge drives release semver). Follow
`.github/PULL_REQUEST_TEMPLATE.md`.

### CI

Pull requests and pushes to `main` run **lintro** (via the published
**py-lintro** container image) and `bash scripts/validate.sh`.

### Releases

Version bumps and **CHANGELOG.md** updates flow through **`lgtm-hq/lgtm-ci`**
[reusable workflows](https://github.com/lgtm-hq/lgtm-ci), called from this repo
with **full SHA pins** on `uses:` (see `.github/workflows/release-version-pr.yml`
and `release-auto-tag.yml`). When upstream release behavior changes, bump those
SHAs to a commit that exists on GitHub (`repos/lgtm-hq/lgtm-ci/commits/<sha>`).

**Baseline note:** [`lgtm-ci#138`](https://github.com/lgtm-hq/lgtm-ci/pull/138)
is merged; the current caller pins match `lgtm-hq/lgtm-ci` **`main`** at
`79444626c1b3afa4d959b5840b4b5310a46a4095` (re-verify when bumping).

## License

MIT — see [LICENSE](./LICENSE).
