# ai-skills

<!-- markdownlint-disable MD033 MD013 -- badges and centered intro -->
<p align="center">
Canonical <a href="https://agentskills.io">Agent Skills</a> library — one <code>skills/</code> tree for Claude Code, Cursor, Codex, and other agents.
</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT"></a>
<a href="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
<a href="https://github.com/lgtm-hq/ai-skills/releases/latest"><img src="https://img.shields.io/github/v/release/lgtm-hq/ai-skills?label=release" alt="Release"></a>
<a href="https://skills.sh/lgtm-hq/ai-skills"><img src="https://skills.sh/b/lgtm-hq/ai-skills" alt="skills.sh"></a>
</p>

<!-- markdownlint-enable MD033 MD013 -->

Validated, semver-pinned **Agent Skills** for real engineering workflows — commit,
review, PR, and language standards. Install into Cursor, Claude Code, Codex, and
other agents from one catalog.

## Quickstart

Use the [Vercel Labs `skills` CLI](https://github.com/vercel-labs/skills). Prefer
**[Bun](https://bun.sh)** and **`bunx`** (same idea as **`npx`** / **`pnpm dlx`**).

**Install pinned to a release tag** (recommended — reproducible, reviewable):

```bash
bunx skills add lgtm-hq/ai-skills@v0.1.10 -g
```

Replace `v0.1.10` with the newest tag from the
[releases page](https://github.com/lgtm-hq/ai-skills/releases/latest).

The installer shows a **grouped checkbox picker** — pick workflow bundles, toggle
individual skills, then choose which agents to install into (Cursor, Claude, Codex,
and others).

**npm / pnpm equivalents:**

```bash
npx skills add lgtm-hq/ai-skills@v0.1.10 -g
pnpm dlx skills add lgtm-hq/ai-skills@v0.1.10 -g
```

### Track latest (unpinned)

```bash
bunx skills add lgtm-hq/ai-skills -g
```

**Caveat:** without a tag, this installs whatever is on the moving `main` branch
at install time, and later updates pull unreviewed-by-you changes. Skills are
instructions your agents execute, so prefer the tag-pinned install above and bump
tags deliberately.

### Verify a release (integrity manifest)

Every release ships a `skills-manifest.json` asset mapping each skill name to
the sha256 of its `SKILL.md`, attested with GitHub build provenance:

```bash
gh release download v0.1.10 -R lgtm-hq/ai-skills -p skills-manifest.json
gh attestation verify skills-manifest.json -R lgtm-hq/ai-skills
shasum -a 256 <install-dir>/<name>/SKILL.md  # compare against the manifest
```

Use your agent's install directory for `<install-dir>` — for example
`~/.claude/skills` for Claude Code, or the equivalent skills directory for
Cursor, Codex, or other agents.

### Bundles

| Bundle | Skills | When to install |
| --- | --- | --- |
| **Git & PR Workflow** | branch, commit, rebase, pr, reconcile, issue | Starting branches, commits, and PRs |
| **Pre-Push Review** | lint, test, greptile, coderabbit | Before pushing or opening a PR |
| **Standards** | stand-general, stand-py, stand-ts, stand-rust, stand-ci | Writing or reviewing code |
| **Raycast** | raycast, pr-raycast | Raycast extension development |
| **Analysis** | analyze-code, analyze-project, analyze-tests | Manual pre-review checks |
| **Agents** | babysit-pr, which-pr | Autonomous PR babysitting |
| **Testing** | test-api, test-ui, test-shell | Writing Playwright/BATS tests |
| **Other** | design, jira, lintro-*, turbo-*, scorecard, … | Optional / project-specific |

See **[AGENTS.md](./AGENTS.md)** for the full skill index with descriptions.

## Advanced install

Power users and CI can skip the interactive picker:

```bash
# All skills, all detected agents, pinned to a release tag
bunx skills add lgtm-hq/ai-skills@v0.1.10 -g --all

# Specific skills only
bunx skills add lgtm-hq/ai-skills -g --skill lint commit greptile -y

# Single agent (e.g. Cursor)
bunx skills add lgtm-hq/ai-skills -a cursor -g --skill lint commit -y

# List available skills without installing
bunx skills add lgtm-hq/ai-skills -l
```

### Update installed skills

The CLI updates by **skill name** or **scope**, not by package slug (`update
lgtm-hq/ai-skills` does not match installed skills).

```bash
bunx skills update -g
bunx skills update lint commit -g
```

To move everything to a specific release, reinstall with a tag:

```bash
bunx skills add lgtm-hq/ai-skills@v0.1.10 -g --all
```

List or remove installs with `bunx skills ls -g` and `bunx skills remove <name> -g`.
See the [upstream CLI docs](https://github.com/vercel-labs/skills) for more flags.

## Community

- [Contributing](./CONTRIBUTING.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)

## Repository layout

```text
skills/<name>/SKILL.md          # Canonical skill definitions
bundles.yaml                    # Installer group source of truth
.claude-plugin/marketplace.json # Generated grouped picker manifest
AGENTS.md                       # Human- and agent-readable skill index
scripts/validate.sh             # Frontmatter, AGENTS, bundles, and marketplace checks
tests/                          # Pytest wraps for scripts
.github/workflows/              # CI + org reusable workflows
```

Architecture diagrams, CI details, and release mechanics live in
**[CONTRIBUTING.md](./CONTRIBUTING.md)**.

## License

MIT — see [LICENSE](./LICENSE).
