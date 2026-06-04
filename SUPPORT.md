# Support

## Questions and bug reports

- **This repository:** open an **[issue](https://github.com/lgtm-hq/ai-skills/issues)**
  for problems with skill content, installation docs, CI, or validation.
- Prefer the issue templates when they match your request (bug, feature, question).

## Skill CLI and agents

Install/update flows use the upstream [**Vercel Labs `skills` CLI**][skills-cli]. For
CLI-only bugs or agent detection issues, check upstream documentation and issues first;
open an issue here if the fix belongs in our **`skills/`** tree or documented install
steps.

**Updates:** use scope-based commands (for example `bunx skills update -g` for all
global skills, or `bunx skills update lint -g` for named skills). The package slug
form (`skills update lgtm-hq/ai-skills`) is not supported by the current CLI — see
[README](./README.md) and [issue #22](https://github.com/lgtm-hq/ai-skills/issues/22).

[skills-cli]: https://github.com/vercel-labs/skills

## Organization resources

Shared **support and contributor** expectations for LGTM-HQ are published in the
**[`.github` repository](https://github.com/lgtm-hq/.github)** (for example
**[SUPPORT.md](https://github.com/lgtm-hq/.github/blob/main/SUPPORT.md)** where
present).

## Security

For **security vulnerabilities**, follow **[SECURITY.md](./SECURITY.md)**. Do not use
public issues for undisclosed security reports.
