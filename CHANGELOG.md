<!-- markdownlint-disable MD024 MD013 -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

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

[Unreleased]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lgtm-hq/ai-skills/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lgtm-hq/ai-skills/releases/tag/v0.1.0
[#1]: https://github.com/lgtm-hq/ai-skills/pull/1
[#2]: https://github.com/lgtm-hq/ai-skills/pull/2
[#3]: https://github.com/lgtm-hq/ai-skills/pull/3
[#7]: https://github.com/lgtm-hq/ai-skills/pull/7
