# Security policy

## Reporting a vulnerability

Please **do not** open public GitHub issues for undisclosed security vulnerabilities.
Use one of the paths below so we can fix issues before they are widely known.

### Preferred: GitHub private reporting

If [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/about-coordinated-disclosure-of-security-vulnerabilities)
is enabled for this repository, use the **Report a vulnerability** flow from the
**Security** tab.

### Email

Send mail to **either** address (use whichever you can reach):

- [security@lgtm-hq.com](mailto:security@lgtm-hq.com)
- [turbocoder13@gmail.com](mailto:turbocoder13@gmail.com)

An earlier security-policy draft used only the Gmail address
([PR #9](https://github.com/lgtm-hq/ai-skills/pull/9), later folded into the docs work on
[#11](https://github.com/lgtm-hq/ai-skills/pull/11)); **both** inbox names remain valid
reporting paths for this repository.

Include with your report:

- A clear description of the issue and suspected impact
- Steps to reproduce (proof-of-concept if possible)
- Affected releases, commits, or paths (if known)

Put **`ai-skills`** (or **`lgtm-hq/ai-skills`**) in the subject line so routing is
unambiguous.

### What to expect

- We aim to **acknowledge** valid reports within **72 hours**
- We will work toward a **fix** and **coordinated disclosure** where applicable

## Scope

In scope: this repository’s **skill definitions** (`skills/**/SKILL.md`), **maintenance
scripts** under `scripts/`, **tests**, and **GitHub Actions workflows** defined here.

Out of scope: vulnerabilities in third-party agents, CLIs, or runtimes unless they stem
from how this repo recommends invoking them and we can document a safe alternative.

## Hardening reminders for contributors

- Do not commit secrets, tokens, or personal data
- Prefer small, reviewable changes to anything that runs in CI or touches publishing
