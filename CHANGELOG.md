<!-- markdownlint-disable MD024 MD013 -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **gateway**: add SHA-pinned vendor registry and baked skill indexes (#134)

### Changed

### Deprecated

### Removed

- **gateway**: drop the design skill and retire upstream-drift vendoring in
  preparation for the gateway migration (#133)

### Fixed

### Security

## [0.1.24] - 2026-07-09

### Added

- **ci**: run pytest suite via CI (#97) (c3cf40b)

### Changed

- **lint**: codify root-cause-first ignore policy (#93) (2d7b4bd)
- **ci**: add lgtm-ci adoption audit and plan (#94) (3740e19)
- **deps**: update astral-sh/setup-uv to v8.3.2 (#117) (62cc9b7)

## [0.1.23] - 2026-07-08

### Added

- **readme**: revamp README with generated skills section and pin drift guards (#118) (f1e88ef)
- **docs**: generate the README skills section from bundles.yaml with hyperlinked SKILL.md entries (scripts/generate_readme.py, wired into scripts/validate.sh)
- **release**: auto-bump README release-tag pins in the version PR (scripts/update-readme-version.sh via version-update-script)

### Changed

- **docs**: revamp README — bundle sections with per-skill links, collapsible install variants and known limitations, unpinned-install warning callout

### Fixed

- **docs**: sync README bundles with bundles.yaml (stand-odin, implement-issues, test-ui-qsf were missing) and refresh stale v0.1.10 install pins

## [0.1.22] - 2026-07-06

### Added

- **ci**: add merge_group trigger for merge queue support (#113) (c38a3cd)

## [0.1.21] - 2026-07-06

### Added

- **implement-issues**: add orchestrator skill for parallel issue implementation (#109) (6a41ca7)

## [0.1.20] - 2026-07-06

### Added

- **babysit-pr**: add --merge flag for merge-queue shepherding (#108) (53ed625)

## [0.1.19] - 2026-07-06

### Added

- **analyze-project**: add ground rules, backlog/dead-surface checks, scorecard (#107) (fa81383)

## [0.1.18] - 2026-07-06

### Added

- **analyze-code**: add ground rules, repo-shape table, and supply-chain checks (#106) (9a5e1a4)

### Changed

- **design**: sync with upstream frontend-design (#92) (cf53536)
- **design**: sync `skills/design/SKILL.md` body with the rewritten upstream
  `anthropics/claude-code` frontend-design skill v1.1.0 (studio-brief framing,
  two-pass plan/critique process, writing-for-design section); refreshed the
  skill description to match the new intent and regenerated `AGENTS.md` (#82)

## [0.1.17] - 2026-07-06

### Changed

- **deps**: update digest (#46) (6bfd56d)
- **deps**: update actions/checkout to v7.0.0 (major) (#74) (3fde4ea)

### Fixed

- **ci**: grant release failure-reporting permissions to callers (#99) (3faa362)
- **ci**: repin lgtm-ci and adopt release fixes (#98) (85de1e2)

## [0.1.16] - 2026-07-05

### Features

- **ci**: track upstream frontend-design drift (#81) (09a39a6)

### Previously Unreleased

- **ci**: track upstream `anthropics/claude-code` frontend-design drift (#18):
  weekly `upstream-drift` workflow runs `scripts/check_upstream_drift.py`
  (normalized body compare, idempotent tracking issue); `upstream` provenance
  block in `skills/design/SKILL.md` frontmatter; `validate_skills.py` now
  validates `upstream` blocks and requires the tracking workflow for skills
  that declare one

## [0.1.15] - 2026-07-05

### Bug Fixes

- **ci**: add pr-auto-assign workflow (#77) (21c7a11)

### Documentation

- **readme**: document install limitations and retired-skill cleanup (#79) (6ce33f8)

## [0.1.14] - 2026-07-05

### Features

- **stand-odin**: add Odin coding standards skill (#78) (456e4e4)

### Previously Unreleased

- **skills**: add `stand-odin` Odin coding standards skill — idiomatic `or_else`
  / `or_return` error handling, allocator discipline, naming conventions, and
  `core:testing` guidance as compact Don't/Do pairs (#36)

## [0.1.13] - 2026-07-05

### Features

- **stand-general**: add writing-time DRY and pre-implementation guidance (#76) (d612455)

## [0.1.12] - 2026-07-05

### Features

- **skills**: add idiom don't/do pairs to stand-py and stand-rust (#80) (50d2544)

### Other Changes

- **deps**: bump msgpack to 1.2.1 (Dependabot high: OOB read) (#75) (fab0052)

## [0.1.11] - 2026-07-05

### Features

- **analyze-code**: add LLM-typical idiom smells and duplication scan (#72) (67884cd)
- **security**: add release integrity manifest, pinned-install guidance, and skill content policy (#63) (5c448cd)
- **skills**: mark Claude-only skills and portable cross-refs (#65) (d37b99f)

### Bug Fixes

- **skills**: resolve cross-skill contradictions (#62) (6eb7e73)
- **validate**: validate frontmatter values via Python --check gate (#64) (1da014f)

### Other Changes

- **repo**: gitignore skills-CLI artifacts and re-lock version (#61) (2585c48)
- **skills**: slim project-locked mega-skills (lintro-add, turbo-add, turbo-verify, test-ui) (#66) (6371d57)
- **skills**: retire dashboard-redesign skill (#60) (998416c)

### Previously Unreleased

- **skills**: retire dashboard-redesign skill (finished-project context dump) (#55)
- **skills**: resolve five cross-skill contradictions (#54): remove `test`'s dangling
  `/stand-general` coverage-report claim (coverage rule now owned inline by `test`);
  replace `lintro-add`'s banned `verify-manifest-sync.py` references with the
  `generate-tool-versions.py --check` pattern per `stand-ci`; add explicit
  tool-development exception to `lint`'s `--tools` ban (covers `lintro-add` /
  `lintro-verify` workflows); point `turbo-verify` and `turbo-add` stale
  BaseLayout.astro fix advice at data-driven `theme-meta.ts`; align `commit`'s Raycast
  test guidance with `raycast` (Vitest optional, `bun run dev` smoke test, drop
  `ray test`)

## [0.1.10] - 2026-07-02

### Features

- **install**: add grouped marketplace installer UX (#51) (90178f5)

## [0.1.9] - 2026-07-02

### Features

- **skills**: add babysit-pr skill for autonomous PR shepherding (#48) (26f74bb)

### Other Changes

- **deps**: update digest (#45) (512bfb6)

## [0.1.8] - 2026-06-06

### Features

- **skills**: split review into coderabbit and greptile skills (#42) (9172968)

### Documentation

- **readme**: fix skills update and document selective install (#40) (84c36c3)

### Previously Unreleased

- **skills**: add `greptile` skill for Greptile CLI pre-push review
- **skills**: add `coderabbit` skill — replaces `review` with rewritten CodeRabbit
  CLI docs (`--agent` instead of deprecated `--prompt-only`; `doctor`, `findings`,
  committed vs uncommitted scope)
- **skills**: document dual pre-push workflow (`/greptile` + `/coderabbit`) in
  `stand-general` and `pr-raycast`
- **skills**: remove `review` skill — not backward-compatible; invoke `/coderabbit`
  and `/greptile` instead

## [0.1.7] - 2026-06-04

### Features

- **skills**: add pr-raycast skill and streamline raycast skill (#38) (7cbeb42)

## [0.1.6] - 2026-05-26

### Features

- **skills**: deduplicate lint/commit/test rules across stand-general, commit, and lint (#30) (b156cd4)

## [0.1.5] - 2026-05-26

### Features

- **skills**: make design skill actionable with concrete constraints (#29) (764232a)

## [0.1.4] - 2026-05-26

### Features

- **skills**: deduplicate testing guidance across test, stand-py, and stand-ts (#31) (b0344c5)

## [0.1.3] - 2026-05-26

### Features

- **skills**: sharpen analyze-* skills into procedural workflows (#28) (dbb0b96)

### Other Changes

- **deps**: update digest (#23) (c8f63fa)

## [0.1.2] - 2026-05-24

### Features

- **skills**: review stand-* skills, add Rust, centralize linting (#20) (80f7f63)

### Other Changes

- **deps**: update digest (#17) (75486ca)
- align reusable lgtm-ci workflows (#15) (dfa5fec)
- **deps**: update ghcr.io/lgtm-hq/py-lintro digest (#5) (3e49605)

## [0.1.1] - 2026-05-12

### Bug Fixes

- **deps**: rely on org Renovate preset for Actions automerge (#12) (35e7b64)

### Documentation

- **readme**: add badges, npx skills install, architecture, and release pins (#11) (0e9dca6)

### Other Changes

- **deps**: update digest (#6) (e92c658)

### Previously Unreleased

- community docs: `CONTRIBUTING.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
- `.editorconfig` aligned with other LGTM-HQ repos (Markdown / YAML / JSON spacing)
- README: prefer **Bun** (`bunx`) for the `skills` CLI; document **npm** / **pnpm**
  equivalents
- README: drop hardcoded skill count; **SECURITY.md** lists both security contacts;
  bug report repro steps show explicit `bunx` / `npx` / `pnpm dlx` commands

## [0.1.0] - 2026-05-12

### Features

- migrate canonical skills and add agents index (#2) (9bb67a3)

### Bug Fixes

- **ci**: pin lgtm-ci reusable release workflows to published SHA (#7) (4ad294b)

### Other Changes

- **changelog**: add initial CHANGELOG for release automation (#8) (df92a2d)
- adopt lgtm-ci workflows (#3) (7bc2d87)
- bootstrap base files and GitHub templates (#1) (90355b0)
- Initial commit (193c30e)

### Previously Unreleased

- Bootstrap base files and GitHub templates ([#1])
- Migrate canonical Agent Skills tree and regenerate AGENTS index ([#2])
- CI with py-lintro image, `scripts/validate.sh`, and pytest coverage ([#3])
- Pin `lgtm-hq/lgtm-ci` reusable release workflows to commits present on GitHub ([#7])

[Unreleased]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.24...HEAD
[0.1.24]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.23...v0.1.24
[0.1.23]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.22...v0.1.23
[0.1.22]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.21...v0.1.22
[0.1.21]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.20...v0.1.21
[0.1.20]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.19...v0.1.20
[0.1.19]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.18...v0.1.19
[0.1.18]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.17...v0.1.18
[0.1.17]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.16...v0.1.17
[0.1.16]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.15...v0.1.16
[0.1.15]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.14...v0.1.15
[0.1.14]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.13...v0.1.14
[0.1.13]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lgtm-hq/ai-skills/releases/tag/v0.1.0
[#1]: https://github.com/lgtm-hq/ai-skills/pull/1
[#2]: https://github.com/lgtm-hq/ai-skills/pull/2
[#3]: https://github.com/lgtm-hq/ai-skills/pull/3
[#7]: https://github.com/lgtm-hq/ai-skills/pull/7
