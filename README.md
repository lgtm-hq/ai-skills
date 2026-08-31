# ai-skills

<!-- markdownlint-disable MD033 MD013 -- badges and centered intro -->
<p align="center">
Canonical <a href="https://agentskills.io">Agent Skills</a> library — content ships as
<strong>plugins</strong> for Claude Code, Cursor, and GitHub Copilot.
</p>

<p align="center">
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT"></a>
<a href="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/lgtm-hq/ai-skills/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
<a href="https://github.com/lgtm-hq/ai-skills/releases/latest"><img src="https://img.shields.io/github/v/release/lgtm-hq/ai-skills?label=release" alt="Release"></a>
<a href="https://skills.sh/lgtm-hq/ai-skills"><img src="https://skills.sh/b/lgtm-hq/ai-skills" alt="skills.sh"></a>
</p>

<!-- markdownlint-enable MD033 MD013 -->

Validated **plugins** for real engineering workflows — commit, review, PR, and
language standards. Claude Code, Cursor, and GitHub Copilot are verified
hosts. Third-party vendor catalogs ship SHA-pinned via the gateway; curated
content stays first-party only.

## Install

The unit of install is a **plugin**. A plugin is a named group of skills (and,
later, other components). Contents stay visible; native hosts install the
plugin as a whole. The gateway (`sk`) installs plugins atomically — the
TUI is a plugin checklist, `--skill` / `--bundle` name a plugin, and
`--vendor` installs every baked slice for that vendor. Native projectors are the
default for Cursor, Claude Code, and GitHub Copilot when the doctor cache
(`~/.ai-skills/doctor.json`) says native — install probes and writes that
cache on a miss. Ambiguous Claude Code / Copilot probes ask once; `-y`
fails closed without writing the cache (`--projector explode` still
writes skill directories). Codex stays exploded. If you previously
used the skills CLI or a per-skill gateway cart, wipe and reinstall, or
switch to a host plugin marketplace command below.

Pin the gateway to a release. Native `marketplace add` tracks the default
branch unless you append a git tag. The npm version matches the git tag
(`@0.29.0` ↔ `v0.29.0`).

### Claude Code

```bash
claude plugin marketplace add lgtm-hq/ai-skills@v0.29.0
claude plugin install git-pr@ai-skills
```

### GitHub Copilot

```bash
copilot plugin marketplace add lgtm-hq/ai-skills
copilot plugin install git-pr@ai-skills
```

Copilot's add takes `OWNER/REPO` and tracks the default branch; install uses
the same kebab-case plugin ids as the table below.

### Cursor

**Local:** clone this repo and symlink the catalog into Cursor's local
plugin dir (`~/.cursor/plugins/local/ai-skills`). The generated Cursor
adapter is `.cursor-plugin/marketplace.json`; skill-list slicing still
lives in the Claude-format adapter
([ADR 0003](./docs/adr/0003-upstream-native-slicing.md)).

```bash
git clone https://github.com/lgtm-hq/ai-skills.git
mkdir -p ~/.cursor/plugins/local
ln -s "$(pwd)/ai-skills" ~/.cursor/plugins/local/ai-skills
```

**Native:** on Teams/Enterprise, import `lgtm-hq/ai-skills` from
**Dashboard → Plugins**, then install a plugin from Customize.

### Gateway (`sk`)

```bash
bun add -g @lgtm-hq/ai-skills@0.29.0
sk install -y --global -a cursor --bundle review
```

`skill` is an alias for `sk`. For a pinned, install-free run:

```bash
bunx --package=@lgtm-hq/ai-skills@0.29.0 sk install -y --global \
  -a cursor --bundle review
```

Unattended installs need an explicit scope and agent. `--bundle` and
`--skill` take a plugin id from the table below (`git-pr`, `review`,
`standards`, …) or a baked vendor plugin id (`document-skills`,
`hookify`, …). `--vendor <id>` installs every baked slice for that
vendor.
`--projector native|explode` overrides delivery. Without it, install consults
`sk doctor`'s host cache (`~/.ai-skills/doctor.json`) for hosts that are not
already locked: probe Claude Code / Copilot for a working `plugin`
subcommand, and Cursor for `~/.cursor/plugins/local/`. Ambiguous Claude
Code / Copilot probes ask once; `-y` fails closed without writing the
cache. Locked agents keep their projector until `--migrate` or
`--projector`. Codex stays exploded.
Vendor installs stay exploded. Cursor native still needs a catalog checkout
(`skills/` + `.claude-plugin/`). Published npm / `bunx` installs fall back
to explode only when native is implicit; `--projector native` without a
checkout fails closed.
`sk doctor` prints capability, lock↔disk drift, and orphans;
`--repair` restores missing files; `--migrate <host>` cutovers locked
first-party plugins on that host (native migrate skips vendor plugins).
`sk install --projector` cutovers one plugin.
See [docs/smoke-test.md](docs/smoke-test.md).

> [!WARNING]
> Pin the gateway to a release. Plugins are instructions your agents
> execute — bump deliberately.

## Plugins

First-party plugins, generated from `bundles.yaml`:

<!-- plugins:start -->
<!-- markdownlint-disable MD013 -->
<!-- Generated by scripts/generate_readme.py from bundles.yaml; do not edit by hand. -->

| Plugin | Id | Description | Skills |
| --- | --- | --- | --- |
| Git & PR Workflow | `git-pr` | Branching, commits, rebases, and pull requests. | [branch](skills/branch/SKILL.md), [commit](skills/commit/SKILL.md), [rebase](skills/rebase/SKILL.md), [pr](skills/pr/SKILL.md), [reconcile](skills/reconcile/SKILL.md), [issue](skills/issue/SKILL.md) |
| Review | `review` | Lint, test, and AI review before pushing or opening a PR. | [lint](skills/lint/SKILL.md), [test](skills/test/SKILL.md), [greptile](skills/greptile/SKILL.md), [coderabbit](skills/coderabbit/SKILL.md) |
| Standards | `standards` | Language and CI coding standards applied while writing code. | [stand-general](skills/stand-general/SKILL.md), [stand-py](skills/stand-py/SKILL.md), [stand-ts](skills/stand-ts/SKILL.md), [stand-rust](skills/stand-rust/SKILL.md), [stand-odin](skills/stand-odin/SKILL.md), [stand-ci](skills/stand-ci/SKILL.md) |
| Raycast | `raycast` | Raycast extension development and store submissions. | [raycast](skills/raycast/SKILL.md), [pr-raycast](skills/pr-raycast/SKILL.md) |
| Analysis | `analysis` | Manual pre-review analysis of code, projects, and test suites. | [analyze-code](skills/analyze-code/SKILL.md), [analyze-project](skills/analyze-project/SKILL.md), [analyze-tests](skills/analyze-tests/SKILL.md), [audit-merges](skills/audit-merges/SKILL.md), [sweep-prs](skills/sweep-prs/SKILL.md) |
| Subagents | `subagents` | Autonomous agents that shepherd PRs and work issue backlogs. | [babysit-pr](skills/babysit-pr/SKILL.md), [backlog](skills/backlog/SKILL.md), [implement-issues](skills/implement-issues/SKILL.md), [which-pr](skills/which-pr/SKILL.md) |
| Testing | `testing` | Playwright and BATS test-writing standards. | [test-api](skills/test-api/SKILL.md), [test-ui](skills/test-ui/SKILL.md), [test-ui-qsf](skills/test-ui-qsf/SKILL.md), [test-shell](skills/test-shell/SKILL.md) |

Skills listed under `ungrouped` in `bundles.yaml` are not marketplace plugins. See [AGENTS.md](./AGENTS.md) for the full skill index.

<!-- markdownlint-enable MD013 -->
<!-- plugins:end -->

## Harness-agnostic by construction

Canonical metadata is **`bundles.yaml`** (first-party plugins) and
**`vendors.yaml`** (SHA-pinned third-party catalogs). Host manifests under
`.claude-plugin/` and `.cursor-plugin/` are generated adapters — do not edit
them. Contributors edit the YAML, then run
`scripts/generate_marketplace.py`. CI fails if an adapter is stale or
missing.

The catalog is harness-agnostic by construction: one authoring tree, per-host
JSON as build output. Settled *why* lives in
[docs/adr/](./docs/adr/README.md).

## Vendors, pins, and locks

- **Vendors (v1):** `mattpocock/skills`, `anthropics/skills`,
  `anthropics/claude-code`, `JuliusBrussee/caveman`, and `davidondrej/skills`,
  full trees at a **commit SHA** (Renovate bumps SHAs). Discovery uses baked
  indexes shipped inside the npm package — no GitHub API at install time.
- **Licenses:** see root [`NOTICE.md`](./NOTICE.md) and `vendors.yaml`.
- **Gateway lockfiles** (schema v2; do not overwrite stock `skills-lock.json`):
  - Global: `~/.ai-skills/lock.json`
  - Project: `./ai-skills-lock.json`
  - v1 locks are treated as empty — wipe and reinstall. `list` annotates
    MISSING and MODIFIED installs instead of listing them as healthy.
- **`update`** refreshes lock-managed plugins whose pin moved or files
  drifted; current matching pins are a no-op. Entries missing on disk
  are pruned.
- **`remove`** deletes a whole plugin: hash-verified files only, with a
  warning for locally modified paths, then prunes empty directory trees.
- **`list`** shows installed plugins, per-agent status, and contained
  skill names (read-only).
- **`adopt`** imports existing `skills add` installs into the gateway lock
  from `skills-lock.json` + on-disk agent skill dirs (no reinstall).
  Ambiguous sources are skipped with a report under `-y`, or confirmed
  interactively.

```bash
sk vendors   # offline: baked vendors + SHAs
sk list --global
sk update -y --global -a cursor
sk adopt -y --project
```

First-party gateway installs resolve `lgtm-hq/ai-skills@v0.29.0`.

## Verify a release

Every release ships a `skills-manifest.json` asset mapping each skill name to
the sha256 of its `SKILL.md`, attested with GitHub build provenance:

```bash
gh release download v0.29.0 -R lgtm-hq/ai-skills -p skills-manifest.json
gh attestation verify skills-manifest.json -R lgtm-hq/ai-skills
shasum -a 256 <install-dir>/<name>/SKILL.md  # compare against the manifest
```

Use the host's plugin or skills directory for `<install-dir>`.

## Community

- [Contributing](./CONTRIBUTING.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)

## Repository layout

```text
skills/<name>/SKILL.md          # Canonical first-party skill definitions
bundles.yaml                    # Plugin groups + README table source of truth
vendors.yaml                    # SHA-pinned third-party vendor registry
vendor-indexes/                 # Baked skill indexes for the gateway picker
NOTICE.md                       # Third-party license notices for the npm package
npm/ai-skills/                  # @lgtm-hq/ai-skills gateway package
.claude-plugin/marketplace.json # Generated Claude marketplace adapter
.cursor-plugin/marketplace.json # Generated Cursor marketplace adapter
docs/adr/                       # Plugin-canonical architecture decision records
AGENTS.md                       # Human- and agent-readable skill index
scripts/validate.sh             # Frontmatter, AGENTS, bundles, README, marketplace checks
tests/                          # Pytest wraps for scripts
.github/workflows/              # CI + org reusable workflows + npm publish
```

The plugin table above is generated from `bundles.yaml`. The release-tag /
npm-version pins in install examples are generated from `pyproject.toml`.
Edit the relevant source, then run
`uv run python scripts/generate_readme.py`. Architecture diagrams, CI
details, npm publish, and release mechanics live in
**[CONTRIBUTING.md](./CONTRIBUTING.md)**.

## License

MIT — see [LICENSE](./LICENSE).
