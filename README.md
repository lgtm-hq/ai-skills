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
other agents from one catalog. Third-party vendor catalogs ship as-is via the
gateway (SHA-pinned); curated skills stay first-party only.

## Quickstart

Install the **gateway** package globally (recommended). It exposes two
first-class binaries, `skill` and `sk` (aliases for the same CLI):

```bash
bun add -g @lgtm-hq/ai-skills@0.14.2
skill          # or: sk
```

Prefer a pinned, install-free run? Because the package ships two binaries,
`bunx` needs an explicit `--package` plus the binary name — the npm version
matches the git tag, `@0.14.2` ↔ `v0.14.2`:

```bash
bunx --package=@lgtm-hq/ai-skills@0.14.2 skill
# or: bunx --package=@lgtm-hq/ai-skills@0.14.2 sk
```

Interactive install uses a Clack home/cart wizard. Happy path:

1. Browse one or more catalogs (first-party `@ v…`, vendors `@ latest` / `@ v…`)
2. Toggle skills (first-party bundles and nested vendor folders are grouped at
   runtime from paths; flat vendor layouts stay a single list); return to home
   to browse another catalog or **Proceed**
3. Choose agents (Claude Code, Cursor, and Codex are selected by default)
4. Keep **global** scope (default)

Cancel from home exits with no install. Mixed catalogs install once per source.

Symlink installs are the default; copy-into-agent and conflict jargon stay behind
advanced / unattended flags. Use `--project` for a repo-local install. With the
gateway installed globally, invoke the CLI as `skill` (or `sk`):

```bash
skill install …
skill vendors   # offline: baked vendors + SHAs
skill list
skill update …
skill remove …
skill adopt -y --project   # import skills-lock installs
```

Unattended installs require an explicit scope and agent. Upstream `skills` has no
conflict policy — omit `--on-conflict`, or pass `overwrite`. `keep` / `skip` fail
closed. For a pinned, install-free run, front the command with
`bunx --package=@lgtm-hq/ai-skills@0.14.2 skill`:

```bash
bunx --package=@lgtm-hq/ai-skills@0.14.2 skill install -y --global \
  -a claude-code -a cursor -a codex \
  --bundle pre-push
```

<!-- markdownlint-disable MD033 -- collapsible install variants -->
<details>
<summary><strong>Escape hatch: upstream <code>skills</code> CLI</strong></summary>

The gateway shells out to the [Vercel Labs `skills` CLI](https://github.com/vercel-labs/skills).
You can call it directly when you want the stock installer only:

```bash
bunx skills add lgtm-hq/ai-skills@v0.14.2 -g
npx skills add lgtm-hq/ai-skills@v0.14.2 -g
pnpm dlx skills add lgtm-hq/ai-skills@v0.14.2 -g
```

</details>
<!-- markdownlint-enable MD033 -->

> [!WARNING]
> Pin the gateway (or skills CLI) to a release. Floating `main` / unpinned
> installs pull instructions you have not reviewed. Skills are instructions
> your agents execute — bump deliberately.

### Vendors, pins, and locks

- **Vendors (v1):** `mattpocock/skills`, `anthropics/skills`,
  `anthropics/claude-code`, and `JuliusBrussee/caveman`, full trees at a
  **commit SHA** (Renovate bumps SHAs). Skill discovery uses baked indexes
  shipped inside the npm package — no GitHub API at install time.
- **Licenses:** see root [`NOTICE.md`](./NOTICE.md) and `vendors.yaml`.
- **Gateway lockfiles** (do not overwrite stock `skills-lock.json`):
  - Global: `~/.ai-skills/lock.json`
  - Project: `./ai-skills-lock.json`
- **`update`** refreshes lock-managed skills to the current first-party tag /
  vendor SHAs and prunes entries missing on disk.
- **`remove`** / **`list`** operate on the gateway lock after shelling out to
  `skills` where needed.
- **`adopt`** imports existing `skills add` installs into the gateway lock from
  `skills-lock.json` + on-disk agent skill dirs (no reinstall). Ambiguous
  sources are skipped with a report under `-y`, or confirmed interactively.

## Skills

Every skill links to its `SKILL.md` — the exact instructions your agent will
run. Groups below match the installer's bundle picker; see
[AGENTS.md](./AGENTS.md) for the flat machine-readable index.

<!-- skills:start -->
<!-- markdownlint-disable MD013 -->
<!-- Generated by scripts/generate_readme.py from bundles.yaml and SKILL.md frontmatter; do not edit by hand. -->

### Git & PR Workflow

Branching, commits, rebases, and pull requests.

- **[branch](skills/branch/SKILL.md)** — Start work on a new branch or worktree.
- **[commit](skills/commit/SKILL.md)** — Pre-commit workflow and commit guidelines.
- **[rebase](skills/rebase/SKILL.md)** — Rebase the current branch onto the latest main.
- **[pr](skills/pr/SKILL.md)** — Create pull requests with proper templates and metadata.
- **[reconcile](skills/reconcile/SKILL.md)** — Consolidate worktrees and clean up stale branches.
- **[issue](skills/issue/SKILL.md)** — Create GitHub issues with proper formatting, labels, and AI implementation prompts.

### Pre-Push Review

Lint, test, and AI review before pushing or opening a PR.

- **[lint](skills/lint/SKILL.md)** — Run linting and formatting.
- **[test](skills/test/SKILL.md)** — Run tests with coverage reporting.
- **[greptile](skills/greptile/SKILL.md)** — Run Greptile CLI for pre-push AI branch review.
- **[coderabbit](skills/coderabbit/SKILL.md)** — Run CodeRabbit CLI for pre-push AI diff review.

### Standards

Language and CI coding standards applied while writing code.

- **[stand-general](skills/stand-general/SKILL.md)** — Global coding standards for all projects and languages.
- **[stand-py](skills/stand-py/SKILL.md)** — Python >= 3.11 coding standards.
- **[stand-ts](skills/stand-ts/SKILL.md)** — TypeScript and JavaScript standards.
- **[stand-rust](skills/stand-rust/SKILL.md)** — Rust coding standards.
- **[stand-odin](skills/stand-odin/SKILL.md)** — Odin coding standards.
- **[stand-ci](skills/stand-ci/SKILL.md)** — CI/CD and GitHub Actions guidelines.

### Raycast

Raycast extension development and store submissions.

- **[raycast](skills/raycast/SKILL.md)** — Raycast extension development standards.
- **[pr-raycast](skills/pr-raycast/SKILL.md)** — Prepare and open a pull request to raycast/extensions.

### Analysis

Manual pre-review analysis of code, projects, and test suites.

- **[analyze-code](skills/analyze-code/SKILL.md)** — Code-level quality analysis.
- **[analyze-project](skills/analyze-project/SKILL.md)** — High-level project analysis.
- **[analyze-tests](skills/analyze-tests/SKILL.md)** — Test suite analysis.

### Agents

Autonomous agents that shepherd PRs and work issue backlogs.

- **[babysit-pr](skills/babysit-pr/SKILL.md)** — Autonomously drive an open PR to merge-ready state by triaging Greptile and CodeRabbit review comments, fixing CI failures, handling CodeRabbit rate limits, and looping until checks are green with no unresolved actionable threads.
- **[backlog](skills/backlog/SKILL.md)** — Interactive dispatcher for backlog work.
- **[implement-issues](skills/implement-issues/SKILL.md)** — Implement a set of GitHub issues in parallel - triage or take an explicit issue list, group by file-conflict, create a worktree per lane, delegate to sub-agents, open a PR per lane; never merges.
- **[which-pr](skills/which-pr/SKILL.md)** — Report which PR is being worked on in the current conversation.

### Testing

Playwright and BATS test-writing standards.

- **[test-api](skills/test-api/SKILL.md)** — Playwright API testing best practices.
- **[test-ui](skills/test-ui/SKILL.md)** — Playwright E2E testing best practices.
- **[test-ui-qsf](skills/test-ui-qsf/SKILL.md)** — QSF project conventions for the Playwright E2E suite.
- **[test-shell](skills/test-shell/SKILL.md)** — BATS shell script testing.

### Other

Project-specific and optional skills (the installer's "Other" bucket).

- **[jira](skills/jira/SKILL.md)** — Generate Jira-style ticket descriptions.
- **[lintro-add](skills/lintro-add/SKILL.md)** — Guide for adding new linting/formatting tools to lintro.
- **[lintro-verify](skills/lintro-verify/SKILL.md)** — Verify that a lintro tool implementation is complete and follows all project standards.
- **[properize](skills/properize/SKILL.md)** — Promote a quick-and-dirty prototype to an lgtm-hq-standard repo - commit WIP lint-clean, grill the design, spec the backlog as milestone/epic/issue tree, then implement issue by issue.
- **[scorecard](skills/scorecard/SKILL.md)** — Audit the OpenSSF Scorecard rating for py-lintro.
- **[turbo-add](skills/turbo-add/SKILL.md)** — Guide for adding a new theme family to turbo-themes.
- **[turbo-test](skills/turbo-test/SKILL.md)** — Run the full turbo-themes build and test pipeline.
- **[turbo-verify](skills/turbo-verify/SKILL.md)** — Verify that a theme implementation is complete and follows all project standards.

<!-- markdownlint-enable MD013 -->
<!-- skills:end -->

## Verify a release

Every release ships a `skills-manifest.json` asset mapping each skill name to
the sha256 of its `SKILL.md`, attested with GitHub build provenance:

```bash
gh release download v0.14.2 -R lgtm-hq/ai-skills -p skills-manifest.json
gh attestation verify skills-manifest.json -R lgtm-hq/ai-skills
shasum -a 256 <install-dir>/<name>/SKILL.md  # compare against the manifest
```

Use your agent's install directory for `<install-dir>` — for example
`~/.claude/skills` for Claude Code, or the equivalent skills directory for
Cursor, Codex, or other agents.

## Advanced install

Power users and CI can skip the interactive picker via the gateway or the
upstream CLI escape hatch:

```bash
# Gateway: unattended first-party bundle (globally installed → `skill`)
skill install -y --global -a cursor \
  --bundle pre-push

# Gateway: unattended vendor skill at the baked SHA, pinned + install-free
bunx --package=@lgtm-hq/ai-skills@0.14.2 skill install -y --global -a cursor \
  --vendor anthropics --skill frontend-design

# Escape hatch: all first-party skills via skills CLI
bunx skills add lgtm-hq/ai-skills@v0.14.2 -g --all
```

### Update installed skills

Prefer the gateway for installs it manages (globally installed → `skill`; for a
pinned, install-free run swap in `bunx --package=@lgtm-hq/ai-skills@0.14.2 skill`):

```bash
skill update -y --global -a cursor
skill list --global
skill remove -y --global -a cursor --skill lint
```

The upstream CLI updates by **skill name** or **scope**, not by package slug
(`update lgtm-hq/ai-skills` does not match installed skills):

```bash
bunx skills update -g
bunx skills update lint commit -g
```

To move first-party skills to a specific release via the escape hatch, reinstall
with a tag:

```bash
bunx skills add lgtm-hq/ai-skills@v0.14.2 -g --all
```

List or remove stock installs with `bunx skills ls -g` and
`bunx skills remove <name> -g`. See the
[upstream CLI docs](https://github.com/vercel-labs/skills) for more flags.

### Known limitations

<!-- markdownlint-disable MD033 -- collapsible limitation details -->
<details>
<summary><strong>Partial agent failures on <code>--all</code> installs</strong></summary>

A global `--all` install targets every detected agent, and some agents do not
support global skill installation. The run can end with per-agent errors such as:

```text
✗ coderabbit → PromptScript: PromptScript does not support global skill installation
```

These are per-agent failures, not a failed install — every other agent in the
summary was still updated. Read the summary line by line; failures are informational
unless an agent you rely on is listed.

</details>

<details>
<summary><strong>Retired skills are not pruned on upgrade</strong></summary>

`bunx skills update -g` and tagged reinstall (`bunx skills add
lgtm-hq/ai-skills@vX.Y.Z -g --all`) refresh skills present in the release, but
do **not** remove skills you installed earlier that were since dropped from the
catalog. Known retirements: `review` (split into `coderabbit` + `greptile`,
[#42](https://github.com/lgtm-hq/ai-skills/issues/42)) and `dashboard-redesign`
(retired, [#55](https://github.com/lgtm-hq/ai-skills/issues/55)); the removal
records live in the CHANGELOG's **Removed** sections. After upgrading, check the
**Removed** sections in the [CHANGELOG](./CHANGELOG.md), compare
`bunx skills ls -g` against [AGENTS.md](./AGENTS.md), and remove orphans
manually:

```bash
bunx skills remove review -g -y
bunx skills remove dashboard-redesign -g -y
```

</details>
<!-- markdownlint-enable MD033 -->

## Community

- [Contributing](./CONTRIBUTING.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)

## Repository layout

```text
skills/<name>/SKILL.md          # Canonical first-party skill definitions
bundles.yaml                    # Installer group + README section source of truth
vendors.yaml                    # SHA-pinned third-party vendor registry
vendor-indexes/                 # Baked skill indexes for the gateway picker
NOTICE.md                       # Third-party license notices for the npm package
npm/ai-skills/                  # @lgtm-hq/ai-skills gateway package
.claude-plugin/marketplace.json # Generated grouped picker manifest
AGENTS.md                       # Human- and agent-readable skill index
scripts/validate.sh             # Frontmatter, AGENTS, bundles, README, marketplace checks
tests/                          # Pytest wraps for scripts
.github/workflows/              # CI + org reusable workflows + npm publish
```

The `## Skills` section above and the release-tag / npm-version pins in install
examples are generated — edit `bundles.yaml` or SKILL.md frontmatter, then run
`uv run python scripts/generate_readme.py`. Architecture diagrams, CI details,
npm publish, and release mechanics live in
**[CONTRIBUTING.md](./CONTRIBUTING.md)**.

## License

MIT — see [LICENSE](./LICENSE).
