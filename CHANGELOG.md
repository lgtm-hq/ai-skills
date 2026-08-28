<!-- markdownlint-disable MD024 MD013 -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **vendors**: registry schema for vendor plugin definitions — optional
  `plugins[]` with `skillsRoot`, `skills` (`"*"` or paths), `extraSkills`,
  `renameSkills`, and `agents` (kebab-case agent `.md` component names).
  Python tooling fail-closed validates slices; collision renames are
  reviewed registry edits (ADR-0005). The five vendors stay index-only
  until the bake-the-vendors issue fills them.

### Changed

- **vendors**: `skillRoots` entries must be canonical relative POSIX
  paths (no trailing slash, whitespace, backslashes, or `.` / `..`
  components), matching plugin `skillsRoot` rules. Globs remain allowed.

### Deprecated

### Removed

### Fixed

### Security

## [0.26.0] - 2026-08-28

### Added

- **gateway**: add sk doctor with cached probe, repair, and migrate (#405) (00ba8ee)
- **gateway**: `sk doctor` — cached per-host capability probe, lock↔disk
  report, `--repair` for missing installs, and explicit `--migrate <host>`
  for projector cutover. Install consults `~/.ai-skills/doctor.json` instead
  of probing on every run. Ambiguous hosts ask once and persist; `-y` fails
  closed. Manual host ritual: `docs/smoke-test.md`.

### Changed

- **deps**: update lintro (#404) (bd07c4f)

## [0.25.0] - 2026-08-28

### Added

- **gateway**: transactional explode fallback with collision handling (#402) (84f4415)
- **gateway**: transactional explode fallback — stage, collision-check, then
  commit. Byte-identical dests are skipped and not owned; different content
  hard-errors before any dest write. Remove unlinks dest skill symlinks
  without following into the managed store, hash-verifies copied trees,
  leaves modified files, and prunes nested empty directory trees. Dangling
  dest skill symlinks are treated as empty (replaceable on explode, unlinked
  on remove) so they cannot poison later installs. An unowned leftover store
  is replaced when dest is absent and no other dest or lock plugin still
  consumes it, so remove-then-reinstall cannot collide. A live consumer of
  that store is a hard error, including owned updates that would rewrite a
  shared store. Update preserves `--copy` dest directories
  instead of rewriting them as store symlinks, including the skills-CLI
  fallback path. Vendor installs
  and first-party installs without a catalog checkout still use the skills
  CLI (no collision doctrine until bake). That CLI lock records the full dest
  tree so later remove can hash-verify nested files, not only `SKILL.md`.
  Install repair preserves existing `--copy` dest directories the same way
  update does. Identical dest skips emit a warning (ADR-0005 class 1). A
  regular file at a dest skill path is a collision, not a `SKILL.md` match.
  Update snapshots catalog-retired dests, then unlinks them before writing
  the new lock. A cleanup failure leaves the previous lock owning those
  paths; a later lock-write failure restores the snapshots. Stale cleanup
  does not unlink a dest another plugin in the same update still catalogs.
  Empty explode
  claims retain prior owned files still in the current catalog. A CLI-fallback
  update hashes the full dest skill tree so nested files are locked and later
  remove can delete them.

## [0.24.0] - 2026-08-28

### Added

- **gateway**: native projectors for Cursor, Claude, and Copilot (#400) (c6e9ee2)
- **gateway**: native projectors for Cursor (local plugin tree), Claude Code,
  and GitHub Copilot (host CLI). `--projector native|explode` overrides the
  per-host default until `sk doctor` lands. Vendor installs stay exploded.

## [0.23.0] - 2026-08-28

### Added

- **gateway**: plugin-only selection UX for install/list/update/remove (#398) (05959c9)

### Changed

- **gateway**: plugin-only selection for install/list/update/remove. `--skill`
  names a plugin, not a skill; vendor cherry-picks are rejected. `update`
  no-ops when the pin and files match; `remove` hash-verifies deletes and
  leaves modified files with a warning. A failed plugin install rolls back
  newly written skill directories. Wipe and reinstall (`sk remove` then
  `sk install --bundle` / `--skill` / `--vendor`) if an older per-skill
  cart left a mixed lock.

## [0.22.1] - 2026-08-28

### Fixed

- **gateway**: default lockEnvironment so production install writes a lock (#396)
  (a5f0197)

## [0.22.0] - 2026-08-28

### Added

- **gateway**: lock schema v2 with disk reconciliation (#394) (ca4ea90)
- **docs**: six ADRs recording the plugin-canonical architecture (#370).

### Changed

- **readme**: rewrite for plugin marketplace installs (#393) (d3a3e2b)
- **adr**: record plugin-canonical architecture decisions (#391) (3be710d)
- **docs**: rewrite README for plugin marketplace installs, generated plugin
  table, and harness-agnostic framing (#371). Former `bunx skills add --all`
  / Clack wizard users should switch to host `plugin marketplace add` plus
  `plugin install <id>@ai-skills`, or gateway `sk install --bundle`.
- **manifests**: stamp Claude marketplace `name` / `owner` so host install
  commands resolve `@ai-skills` (#371).
- **gateway**: lock schema v2 records plugin-level entries with per-agent
  file hashes and reconciles them against disk (#372). Existing v1
  `ai-skills-lock.json` / `~/.ai-skills/lock.json` files are treated as
  empty — wipe and reinstall (`sk install`) to rebuild. `skill list`
  annotates MISSING and MODIFIED installs instead of listing them as
  healthy. Closes #367.

## [0.21.0] - 2026-08-27

### Added

- **manifests**: generate Cursor marketplace adapter (#390) (1a716da)

### Changed

- **manifests**: generated Cursor marketplace adapter at
  `.cursor-plugin/marketplace.json`, plus `$generated` do-not-edit markers
  on both host adapters (#369).

## [0.20.0] - 2026-08-27

### Added

- **bundles**: add kebab-case plugin ids and sliced marketplace (#388) (b719476)

### Changed

- add Cloud Agent development environment config (#387) (83613f8)
- **bundles**: kebab-case plugin ids, `pre-push` → `review`, `agents` →
  `subagents`, and metadata-sliced marketplace entries (#368). Gateway
  `--bundle pre-push` / `--bundle agents` become `--bundle review` /
  `--bundle subagents`.

## [0.19.0] - 2026-08-26

### Added

- add org AI review via lgtm-ci reusable (#365) (5ff0c14)

### Changed

- **deps**: update lintro (#364) (1569e07)
- **deps**: lock file maintenance (#363) (57edfe2)
- **deps**: update lintro (#362) (147930c)
- **deps**: update lintro (#361) (7e34465)
- **deps**: update lintro (#360) (7174af5)
- **deps**: update lintro (#359) (864095e)
- **deps**: update lintro (#358) (99fb559)
- **deps**: update lintro (#357) (5e9721b)
- **deps**: update lintro (#356) (5ded36a)
- **deps**: update lintro (#355) (8c4f827)
- **deps**: lock file maintenance (#354) (4a1f6f6)
- **deps**: update lintro (#352) (105c4e0)
- **deps**: update dependency lgtm-hq/lgtm-ci to v0.63.1 (patch) (#349) (9c32471)
- **deps**: update astral-sh/setup-uv action to v10.0.1 (major) (#342) (a651a97)
- **deps**: update github-actions (#334) (a90fbd5)
- **deps**: update lintro (#351) (74c318b)
- **deps**: update lintro (#350) (bb0c253)
- **deps**: update lintro (#348) (eb1c24e)
- **deps**: update lintro (#347) (59c33ed)
- **deps**: update lintro (#345) (347d1eb)
- **deps**: update lintro (#344) (7430a19)
- **deps**: update lintro (#343) (5891a7a)
- **deps**: update lintro (#341) (374601b)
- **deps**: update lintro (#340) (048e416)
- **deps**: update lintro (#339) (3f64cbc)
- **deps**: update lintro (#338) (72a7b98)
- **deps**: lock file maintenance (#337) (a970d1f)
- **deps**: update lintro (#336) (62c6a43)
- **deps**: update lintro (#335) (f338412)
- **deps**: update lintro (#333) (eb859ee)
- **deps**: update lintro (#332) (dbc09bd)
- **deps**: update lintro (#331) (35d3752)
- **deps**: update lintro (#329) (a49c4f8)
- **deps**: update step-security/harden-runner action to v2.20.1 (patch) (#330)
  (b3c848c)
- **deps**: update lintro (#328) (293e56f)
- **deps**: update lintro (#327) (d421fc2)
- **deps**: update lintro (#326) (61de697)

## [0.18.0] - 2026-08-04

### Added

- **npm**: surface installed skills and update signals in install wizard (#324)
  (d46b856)

### Changed

- **deps**: update lintro (#322) (17ba8f0)

## [0.17.0] - 2026-08-04

### Added

- **skills**: add sweep-prs skill (#318) (1dcc949)

## [0.16.1] - 2026-08-04

### Fixed

- **babysit-pr**: forbid --subject/--body on gh pr merge (#317) (501f806)

## [0.16.0] - 2026-08-04

### Added

- **vendors**: add davidondrej/skills as SHA-pinned gateway vendor (#313, #316) (05c975e)

### Changed

- **scripts**: document TypeError in changed Raises contracts (#314) (0c8764d)

## [0.15.0] - 2026-08-04

### Added

- **skills**: add audit-merges skill (#309) (8c1d071)

### Changed

- **babysit-pr**: make CodeRabbit rate limit non-blocking on exit (#275) (8db4ac4)
- **deps**: update dependency lgtm-hq/lgtm-ci to v0.63.0 (minor) (#295) (a76c90a)
- **deps**: update lintro (#307) (22dfb69)
- **deps**: lock file maintenance (#310) (57e61e3)
- **deps**: update lintro (#306) (1791ac3)
- **deps**: lock file maintenance (#305) (d8fc164)
- **deps**: update lintro (#304) (b11c059)
- **deps**: update lintro (#303) (455d30d)
- **deps**: update lintro (#302) (570d9ca)
- **deps**: update lintro (#301) (b249016)
- **deps**: update lintro (#300) (60325f6)
- **deps**: update lintro (#299) (57c157a)
- **deps**: update lintro (#298) (454be5f)
- **deps**: update lintro (#297) (81c5d08)
- **deps**: update lintro (#296) (f3fed24)
- **deps**: update lintro (#294) (28f025f)
- **deps**: update lintro (#293) (c6c73fe)
- **deps**: update lintro (#292) (1900cee)
- **deps**: update lintro (#291) (89082b7)
- **deps**: update lintro (#290) (f53d329)
- **deps**: update lintro (#289) (01917ad)
- **deps**: update lintro (#288) (7097a81)
- **deps**: update dependency lgtm-hq/lgtm-ci to v0.59.2 (patch) (#283) (0934d13)
- **deps**: update astral-sh/setup-uv action to v9.0.0 (major) (#287) (2384cf2)
- **deps**: update lintro (#286) (89fd4fc)
- **deps**: update lintro (#284) (a09a642)

## [0.14.2] - 2026-07-20

### Changed

- **deps**: update actions/checkout action to v7.0.1 (patch) (#233) (175fc0b)
- **deps**: update lintro (#279) (d76ecc7)

### Fixed

- **ci**: update lgtm-hq/lgtm-ci to v0.59.1 to unstick auto-tag releases (#282)
  (7badb09)

## [0.14.1] - 2026-07-20

### Changed

- **changelog**: codify one commit-pointer convention for CHANGELOG entries (#268)
  (62b9fb0)
- adopt pr-labeler and semantic-pr-title callers (#273) (ff819b2)
- **deps**: update actions/setup-python action to v7.0.0 (major) (#277) (95bb0c5)
- **deps**: update lintro (#278) (7ba8476)

### Fixed

- **scripts**: replace grep bare-assert scan with AST check (#272) (bec21cd)

## [0.14.0] - 2026-07-19

### Added

- **backlog**: add backlog routing skill (#271) (63c328b)

### Changed

- **deps**: update lintro (#259) (51fe084)
- **deps**: update lintro (#258) (af0f293)
- **deps-dev**: update dependency lintro to 0.80.10 (patch) (#257) (dac7614)

## [0.13.0] - 2026-07-18

### Added

- **cli**: expose skill and sk binaries for installed gateway UX (#249) (87bdaaa)
- **gateway**: expose first-class `skill` and `sk` binaries for the installed
  gateway CLI (#243)

### Removed

- **gateway**: remove the `ai-skills` binary in favor of `skill` / `sk` (#243)

## [0.12.0] - 2026-07-18

### Added

- **gateway**: add manage_vendors CLI for SHA-pinned vendors (#248) (12fd543)

### Changed

- **deps**: update dependency lgtm-hq/lgtm-ci to v0.59.0 (minor) (#247) (9afadad)
- **deps-dev**: update dependency lintro to 0.80.9 (patch) (#254) (6d98e18)

## [0.11.1] - 2026-07-18

### Changed

- add Cursor Cloud environment setup notes to AGENTS.md (#245) (96dc061)
- **deps**: update lintro (#252) (d7a4182)
- **deps**: update lintro (#251) (8029ebc)
- **deps**: update lintro (#246) (4648008)
- **deps**: update lintro (#244) (113f89b)

### Fixed

- **ci**: repin link-check to lgtm-ci v0.54.0 and restore single-SHA lockstep (#250)
  (7380494)

## [0.11.0] - 2026-07-16

### Added

- **gateway**: add JuliusBrussee/caveman SHA-pinned vendor (#240) (3f672a5)

## [0.10.2] - 2026-07-16

### Changed

- **deps**: update dependency lgtm-hq/lgtm-ci to v0.54.0 (minor) (#225) (15b0994)
- **deps**: update actions/setup-node action to v7.0.0 (major) (#234) (2a35bdb)
- **deps**: update lintro (#235) (54d87fb)
- **deps**: update lintro (#232) (68acc6b)
- **deps**: update lintro (#229) (24e7734)
- **deps**: lock file maintenance (#228) (17c2b5b)
- **deps**: update lintro (#227) (4f8dc36)

### Fixed

- **ci**: drop removed scorecards inputs for lgtm-ci v0.54.0 (#237) (ba7194b)

## [0.10.1] - 2026-07-12

### Fixed

- **ci**: re-enable Scorecard publish_results on lgtm-ci v0.52.4 (#224) (8e4b65d)

## [0.10.0] - 2026-07-12

### Added

- **skills**: per-repo AGENTS.md/CLAUDE.md context convention (#221) (3eae062)

## [0.9.7] - 2026-07-12

### Fixed

- **ci**: treat already-published npm versions as dry-run success (#219) (1a22305)

## [0.9.6] - 2026-07-12

### Fixed

- **ci**: allowlist github-releases host for SBOM attach (#217) (24046cf)

## [0.9.5] - 2026-07-12

### Fixed

- **docs**: refresh CONTRIBUTING architecture and lgtm-ci baseline (#215) (54e99f8)

## [0.9.4] - 2026-07-12

### Fixed

- **docs**: move skill retirement records under Removed (#213) (3ef7c77)

## [0.9.3] - 2026-07-12

### Changed

- **deps**: update lintro (#210) (1dfe3d5)

### Fixed

- **docs**: sync README prose npm↔tag version pair on release (#211) (6392cdd)

## [0.9.2] - 2026-07-12

### Fixed

- **ci**: group lintro pin with py-lintro Docker digests (#208) (25860fc)

## [0.9.1] - 2026-07-12

### Fixed

- **ci**: restore green main for lintro pin and Link Check (#199) (46cbb34)

## [0.9.0] - 2026-07-12

### Added

- **gateway**: group vendor skills by path at install time (#195) (e22d4c9)

## [0.8.1] - 2026-07-12

### Fixed

- **ci**: grant pull-requests write for Link Check reusable (#193) (2f92b34)

## [0.8.0] - 2026-07-12

### Added

- **gateway**: add interactive install home/cart wizard (#190) (d69a15e)

## [0.7.1] - 2026-07-12

### Fixed

- **ci**: sync lintro pin and image digests to 0.77.1 (#186) (160d852)

## [0.7.0] - 2026-07-12

### Added

- **gateway**: use single-catalog picker with grouped skill multi-select (#183)
  (b4c0ea2)

### Changed

- **deps**: update dependency python to 3.14.6 (minor) (#172) (af2aa38)
- **deps-dev**: update dependency lintro to 0.77.2 (patch) (#184) (a7138de)

## [0.6.0] - 2026-07-11

### Added

- **gateway**: improve interactive install UX with Clack (#179) (193a79b)

## [0.5.5] - 2026-07-11

### Changed

- **ci**: adopt canonical emoji check names (#176) (6465f89)
- **ci**: add version comments to lgtm-ci pins for Renovate tracking (#170) (038be01)

### Fixed

- **gateway**: pin upstream skills CLI to published 1.x (#177) (00d2812)

## [0.5.4] - 2026-07-11

### Fixed

- **ci**: allow uploads.github.com for SBOM release attach (#167) (773100e)

## [0.5.3] - 2026-07-11

### Fixed

- **ci**: allow PyPI/astral egress for release version PR (#165) (080e4df)
- **ci**: repin lgtm-ci to v0.52.3 for SBOM contents:write (#163) (f5ba1eb)

## [0.5.2] - 2026-07-11

### Fixed

- **ci**: grant contents:write for SBOM release asset upload (#160) (06315f9)

## [0.5.1] - 2026-07-11

### Changed

- **deps-dev**: update lintro to 0.74.0 (minor) (#155) (d5dc836)

### Fixed

- **ci**: disable Scorecard API publish to unblock main (#158) (c0cfe63)

## [0.5.0] - 2026-07-11

### Added

- **skills**: add properize skill (#130) (b3f36e3)

## [0.4.0] - 2026-07-11

### Added

- **issue**: add backlog-stewardship conventions (#127) (b8e26a6)

### Changed

- **lgtm-ci**: repin test-python, align lintro, adopt version guard (#132) (37bc4e9)
- **link-check**: adopt lgtm-ci reusable link-check workflow (#131) (9e7f33a)
- **release**: add SBOM generation via lgtm-ci reusable workflow (#129) (822b622)
- **codeql**: adopt reusable-codeql for python static analysis (#128) (5ccaae5)
- **scorecards**: adopt reusable OpenSSF Scorecard workflow (#126) (09926bc)
- **security**: add dependency-review workflow (#125) (5060455)
- **deps**: update astral-sh/setup-uv to v8.3.2 (major) (#145) (8bf5b36)
- **deps**: update actions/setup-python to v6.3.0 (minor) (#144) (6f71ec8)

## [0.3.0] - 2026-07-10

### Added

- **gateway**: adopt existing skills-lock installs into gateway lock (#152) (6558fcd)
- **gateway**: adopt existing skills-lock installs into the gateway lockfile (#139)

## [0.2.0] - 2026-07-10

### Added

- **gateway**: add anthropics/claude-code vendor via skillRoots (#151) (ad9afb3)

- **gateway**: register anthropics/claude-code vendor via skillRoots (#138)
- **gateway**: document gateway install, vendors, locks, and npm publish (#137)

### Changed

- **gateway**: document gateway install, vendors, and escape hatches (#147) (af95a59)

## [0.1.27] - 2026-07-10

### Fixed

- **release**: allow minor bumps from feat commits (#148) (ee64ff1)
- **release**: raise version-PR `max-bump` from patch to minor so `feat`
  commits produce minor releases as documented in the PR template

## [0.1.26] - 2026-07-10

### Added

- **gateway**: gateway lockfile and update command (#146) (6f4e449)
- **gateway**: gateway lockfile plus `update` / `remove` / `list` commands (#136)

## [0.1.25] - 2026-07-10

### Added

- **gateway**: publish @lgtm-hq/ai-skills install wrapper MVP (#142) (11e11f4)
- **gateway**: SHA-pinned vendor registry with skillRoots (#141) (93abd31)

- **gateway**: add SHA-pinned vendor registry and baked skill indexes (#134)

### Changed

- **gateway**: drop design skill and retire upstream drift (#140) (8a3a93a)
- **tests**: adopt assertpy for all assertions (#96) (123deb5)

### Removed

- **gateway**: drop the design skill and retire upstream-drift vendoring in
  preparation for the gateway migration (#133)

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

### Removed

- **skills**: retire dashboard-redesign skill (#60) (998416c)
- **skills**: retire dashboard-redesign skill (finished-project context dump) (#55)

### Previously Unreleased

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

### Removed

- **skills**: remove `review` skill — not backward-compatible; invoke `/coderabbit`
  and `/greptile` instead

### Previously Unreleased

- **skills**: add `greptile` skill for Greptile CLI pre-push review
- **skills**: add `coderabbit` skill — replaces `review` with rewritten CodeRabbit
  CLI docs (`--agent` instead of deprecated `--prompt-only`; `doctor`, `findings`,
  committed vs uncommitted scope)
- **skills**: document dual pre-push workflow (`/greptile` + `/coderabbit`) in
  `stand-general` and `pr-raycast`

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

[Unreleased]: https://github.com/lgtm-hq/ai-skills/compare/v0.26.0...HEAD
[0.26.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.22.1...v0.23.0
[0.22.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.22.0...v0.22.1
[0.22.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.14.2...v0.15.0
[0.14.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.10.2...v0.11.0
[0.10.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.7...v0.10.0
[0.9.7]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.6...v0.9.7
[0.9.6]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.5...v0.9.6
[0.9.5]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.4...v0.9.5
[0.9.4]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.3...v0.9.4
[0.9.3]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.5...v0.6.0
[0.5.5]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.4...v0.5.5
[0.5.4]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.27...v0.2.0
[0.1.27]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.26...v0.1.27
[0.1.26]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.25...v0.1.26
[0.1.25]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.24...v0.1.25
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
