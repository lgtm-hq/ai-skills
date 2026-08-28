# Manual smoke ritual

CI cannot see a live Claude Code, Cursor, or Copilot session. After installing
a plugin on a real host, run this ritual once per host so native delivery is
not a paper success.

Use a throwaway plugin (`review` is small) and an explicit scope.

## Claude Code

1. `sk doctor -y --global -a claude-code` — capability should be `native` when
   `claude plugin` responds.
2. `sk install -y --global -a claude-code --skill review`
3. In Claude Code, invoke a skill from the `review` plugin (for example lint).
4. `sk remove -y --global -a claude-code --skill review`
5. Confirm the plugin is gone from `claude plugin list` / the host UI.

## Cursor

1. `sk doctor -y --global -a cursor` — capability should be `native` when
   `~/.cursor/plugins/local/` exists.
2. From a catalog checkout: `sk install -y --global -a cursor --skill review`
3. Confirm `~/.cursor/plugins/local/review` exists and the skill fires in Cursor.
4. `sk remove -y --global -a cursor --skill review`
5. Confirm the local plugin directory is gone.

Published npm / `bunx` installs have no catalog checkout. Cursor then stays
on explode (`~/.cursor/skills`) unless you run from this repository.

## GitHub Copilot

1. `sk doctor -y --global -a copilot` — capability should be `native` when
   `copilot plugin` responds.
2. `sk install -y --global -a copilot --skill review`
3. Invoke a review skill in Copilot.
4. `sk remove -y --global -a copilot --skill review`
5. Confirm the plugin is gone from `copilot plugin list`.

## Repair and migrate

- Missing lock files: `sk doctor -y --global --repair` re-materializes only
  **missing** installs. Modified files stay put.
- Projector cutover (host became native, or native is no longer available):
  `sk doctor -y --global --migrate cursor`. Without `-y`, doctor asks before
  acting. Install never switches projector silently.
