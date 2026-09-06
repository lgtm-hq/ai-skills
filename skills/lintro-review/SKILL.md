---
name: lintro-review
description: >-
  AI branch review using lintro's own `lintro review` — a standard local pre-push
  pass alongside the coderabbit and greptile CLIs, and the review of record when
  those are rate-limited or unavailable. Use when asked for a lintro review, an
  interim/fallback AI review, or as part of the default pre-push review set.
---

# Lintro AI Review (standard local pass)

Run **lintro's own** AI diff review (`lintro review`) on the branch. Since 2026-08-02
(owner instruction) this is a **standard third local pre-push pass** alongside
`coderabbit` and `greptile`, not just a fallback — and when those two are rate-limited
or down, the lintro pass is the AI review of record for the push.

## When to use

- As part of the default pre-push review set (`coderabbit` + `greptile` + this).
- CodeRabbit and/or Greptile are rate-limited, erroring, or otherwise unavailable.
- You want an AI pass on the branch diff (or working tree) right now.

At **final merge**, bot threads that did get posted on the PR must still be triaged;
a local lintro pass doesn't resolve GitHub threads.

## Two correctness rules (do not skip)

1. **Use released lintro via `uvx`, never `uv run lintro`.** The reviewer engine must be
   stable and independent of the working tree — especially when the branch is itself
   modifying lintro's AI/provider layer (you must not review half-migrated code with
   itself). Floor is **`>=0.94.7`**: that release carries both the CLI auth-mode
   detection (#1859, subscription OAuth works) and the CLI stdout error surfacing
   (#1836).
2. **Enable AI locally behind a `skip-worktree` guard.** Many repos (incl. py-lintro)
   ship `.lintro-config.yaml` with no `ai:` block or `ai.enabled: false`. Flip it on
   locally in a way that cannot be staged or committed.

## Steps

1. **Enable AI locally without commit risk** — only if the project config has AI
   disabled (`grep -A2 '^ai:' .lintro-config.yaml`; skip this step if already
   `enabled: true` / `review: true`):

   ```bash
   git update-index --skip-worktree .lintro-config.yaml
   ```

   Then merge this `ai:` mapping into `.lintro-config.yaml` (append/merge the block —
   the rest of the project config stays as-is, so `--with-lint` keeps working):

   ```yaml
   ai:
     enabled: true
     review: true
     provider: cursor
     model: cursor-grok-4.5-high
   ```

2. **Preflight the engine — Cursor + Grok 4.5 is the standard reviewer (owner
   instruction, 2026-08-11):**
   - **Provider is `cursor`, model is `cursor-grok-4.5-high`** (Cursor's Grok 4.5 id —
     confirm with `cursor-agent models` if it errors), via `--transport cli`. Verify the
     CLI exists with `cursor-agent --version`.
   - **Workspace trust is required once per directory**, or lintro's invocation dies
     with "Workspace Trust Required". Grant it non-interactively from the repo/worktree
     root: `cursor-agent -p 'Reply with exactly: ok' --trust --model cursor-grok-4.5-high
     --output-format text` — trust persists for subsequent runs.
   - **Fallbacks, in order, only when `cursor-agent` is missing or erroring** (say so in
     the report): logged-in `claude` CLI with `--transport cli` and no `ANTHROPIC_API_KEY`
     in the environment (OAuth session, subscription billing; lintro ≥0.94.7 handles
     `--bare` detection); then `ANTHROPIC_API_KEY` with either transport; then
     `OPENAI_API_KEY` with `ai.provider: openai` and `--transport api`. Each fallback
     also updates the step-1 yaml's `ai.provider` to the matching engine (e.g.
     `anthropic` for Claude, `openai` for OpenAI) and fixes or removes `ai.model` so
     the provider never sees `cursor-grok-4.5-high` (removing it uses the provider
     default) — then reruns `uvx`; the review command reads the config, not the
     fallback list.
   - **No engine available** → run the step-5 teardown first (it is mandatory whenever
     step 1 ran), then STOP and report which credential/binary is missing.

3. **Run the review** against the *fresh* base (a stale local `main` reviews the wrong
   diff), including lint:

   ```bash
   base="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || echo main)"
   git fetch --quiet origin "$base"
   uvx --from 'lintro[ai]>=0.94.7' lintro review --base "origin/$base" --with-lint --transport cli --timeout 600
   ```

   - Swap `--transport cli` for `api` per the step-2 outcome. CLI-transport turns run the
     whole review in one `claude` invocation — pass `--timeout 600` (the 60s default is
     API-stream-sized and will kill a CLI turn; #1900).
   - Omitting `--depth`/`--strictness` uses the project's configured review defaults.
     For a heavier final pass, add `--strictness thorough --depth 3` (more spend).

4. **Triage** — fix real findings; note any you dismiss and why, as you would in a
   CR/Greptile thread.

5. **Tear down** the local toggle so it can never land (un-skip **first**, then restore):

   ```bash
   git update-index --no-skip-worktree .lintro-config.yaml
   git checkout .lintro-config.yaml
   ```

## Relationship to coderabbit / greptile

Default pre-push flow runs all three where available:

```text
commit → [greptile ‖ coderabbit ‖ lintro-review] → pr
```

When CR/Greptile are rate-limited, do **not** wait for their reset — the lintro pass
(plus whichever of the other two ran) is the pre-push review of record. Still triage any
bot threads that get posted on the PR afterward.

## Notes

- **Do not run the project's test suite while the step-1 `ai.enabled: true` toggle is
  active.** It leaks into config/doctor tests and fails them (a false red that looks
  like a code defect). Tear the toggle down (step 5) before running any tests, or don't
  run tests during a review.
- Review exit code 2 means "no review was produced" (missing credential, provider
  unreachable, quota); the JSON error envelope names the kind. Since 0.94.1 the CLI's
  stdout error detail is surfaced — read it before diagnosing.
- If `--transport cli` fails on a flag the installed `claude` doesn't accept, that's live
  signal for the AI CLI-transport contract tests (py-lintro #1614) — report it.
