#!/bin/bash
# Cursor load-path probe for lgtm-hq/ai-skills#563 (personal macOS machine).
#
# Runs Cursor in a fully isolated profile (throwaway HOME, user-data and
# extensions dirs under a temp root), installs sentinel test items for each
# role/scope/mode, tells you what to check after each restart, records your
# answers, verifies removal, and deletes everything it created.
#
# It never writes to your real ~/.cursor, ~/.claude or ~/.agents, and never
# touches an employer-managed machine. Results contain no personal paths.
#
# Usage:  bash cursor-macos-probe.sh            (interactive, ~20-30 min)
#         bash cursor-macos-probe.sh --keep     (keep the temp root for debugging)
# Output: ./cursor-probe-results-<timestamp>.json  -> send it back (Discord or #563).
#
# Compatible with macOS /bin/bash 3.2. Needs: Cursor.app, python3, shasum.

set -euo pipefail

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

TOKEN="PROBE-7f3a"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS="$PWD/cursor-probe-results-$STAMP.json"
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ai-skills-563-cursor.XXXXXX")"
# Canonical path: macOS TMPDIR is under /var -> /private/var; Cursor resolves the
# real path and project-scoped items failed to load via the /var alias.
ROOT="$(cd "$ROOT" && pwd -P)"
PHOME="$ROOT/home"
PROJ="$ROOT/project"
UDATA="$ROOT/user-data"
EXTS="$ROOT/extensions"
LOGS="$ROOT/logs"
SENT="$ROOT/sentinels"
mkdir -p "$PHOME" "$PROJ" "$UDATA" "$EXTS" "$LOGS" "$SENT"
HOOK_LOG="$LOGS/hook.log"
MCP_LOG="$LOGS/mcp.log"
: >"$HOOK_LOG"
: >"$MCP_LOG"
REC="$LOGS/records.jsonl"
: >"$REC"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

cleanup() {
  stop_cursor quiet || true
  restore_keychains || true
  if [ "$KEEP" -eq 0 ]; then
    rm -rf "$ROOT"
  else
    printf 'Kept temp root: %s\n' "$ROOT"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- preflight
APP=""
for c in "/Applications/Cursor.app" "$HOME/Applications/Cursor.app"; do
  [ -d "$c" ] && APP="$c" && break
done
[ -n "$APP" ] || { echo "Cursor.app not found in /Applications or ~/Applications" >&2; exit 1; }
CLI="$APP/Contents/Resources/app/bin/cursor"
[ -x "$CLI" ] || { echo "Cursor CLI launcher not found at $CLI" >&2; exit 1; }
command -v python3 >/dev/null && python3 -c 'import json' 2>/dev/null ||
  { echo "python3 is required (hook and MCP sentinels). Install Xcode CLT or python3 first." >&2; exit 1; }

CURSOR_VERSION="$(/usr/bin/defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo unknown)"
OS_ID="darwin-$(uname -m)"
OS_VERSION="$(sw_vers -productVersion 2>/dev/null || echo unknown)"

bold "ai-skills #563 Cursor probe — Cursor $CURSOR_VERSION on macOS $OS_VERSION ($OS_ID)"
note "Isolated root (deleted at the end): $ROOT"
note "Your real ~/.cursor, ~/.claude and ~/.agents are only READ (before/after fingerprint)."
note "Answers: y = token returned / item works, d = listed but not invoked, n = absent/no, s = skip."
note "Do not type personal info into notes."
echo
echo "Before starting: QUIT your normal Cursor completely (Cmd+Q). The isolated window"
echo "needs its own sign-in, and the browser login callback must reach the isolated one."
printf 'Press Enter when your normal Cursor is closed... '
read -r _

# Throwaway keychain for the isolated HOME. Without it Cursor shows "Keychain Not
# Found"; NEVER click "Reset To Defaults" there (it resets your REAL keychain).
ORIG_KC="$(security list-keychains -d user | sed 's/^ *//; s/"//g')"
mkdir -p "$PHOME/Library/Keychains"
ISO_KC="$PHOME/Library/Keychains/login.keychain-db"
security create-keychain -p "" "$ISO_KC" >/dev/null 2>&1 || true
# create-keychain may add the new keychain to YOUR search list: put it back exactly.
# shellcheck disable=SC2086
security list-keychains -d user -s $ORIG_KC
restore_keychains() {
  security delete-keychain "$ISO_KC" >/dev/null 2>&1 || true
  # shellcheck disable=SC2086
  security list-keychains -d user -s $ORIG_KC
  now="$(security list-keychains -d user | sed 's/^ *//; s/"//g')"
  [ "$now" = "$ORIG_KC" ] && echo "  Keychain search list unchanged." ||
    echo "  WARNING: keychain search list differs from the start; check: security list-keychains"
}

snapshot() {
  # paths + sizes + sha256 only; skips caches/extensions/logs
  for d in "$HOME/.cursor" "$HOME/.claude" "$HOME/.agents"; do
    [ -d "$d" ] || continue
    find "$d" -type f \
      -not -path '*/extensions/*' -not -path '*/logs/*' -not -path '*/cache*' \
      -not -path '*/Cache*' -not -path '*/projects/*' -not -path '*/sessions/*' \
      -size -5M -print0 2>/dev/null | xargs -0 shasum -a 256 2>/dev/null
  done | sort
}
snapshot >"$LOGS/real-before.txt"

# ---------------------------------------------------------------- launch/stop
running() { pgrep -f -- "--user-data-dir=$UDATA" >/dev/null 2>&1 || pgrep -f -- "$UDATA" >/dev/null 2>&1; }

start_cursor() {
  env HOME="$PHOME" TMPDIR="$ROOT/tmp" PROBE_HOOK_LOG="$HOOK_LOG" \
    "$CLI" --new-window --user-data-dir="$UDATA" --extensions-dir="$EXTS" "$PROJ" \
    >"$LOGS/launch.log" 2>&1 || true
  mkdir -p "$ROOT/tmp"
  i=0
  while ! running && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
  if ! running; then
    echo "Isolated Cursor did not start (see $LOGS/launch.log)." >&2
    exit 1
  fi
  sleep 3
  # Isolation check: Cursor must have created its home folder data under the
  # throwaway HOME (argv.json), not only under your real ~/.cursor.
  if [ ! -e "$PHOME/.cursor/argv.json" ] && [ -z "${ISO_WARNED:-}" ]; then
    ISO_WARNED=1
    echo "  WARNING: no isolated ~/.cursor/argv.json yet. If the window shows your normal"
    echo "  projects/account, isolation failed: quit it and abort (Ctrl+C)."
  fi
}

stop_cursor() {
  running || return 0
  [ "${1:-}" = "quiet" ] || {
    echo
    echo "  -> Quit the ISOLATED Cursor window now (focus it, Cmd+Q). Your normal Cursor stays closed."
    printf '     Press Enter once it has quit... '
    read -r _
  }
  i=0
  while running && [ $i -lt 15 ]; do sleep 1; i=$((i + 1)); done
  if running; then
    pkill -f -- "$UDATA" 2>/dev/null || true
    sleep 2
  fi
}

restart() {
  stop_cursor
  start_cursor
  echo
  echo "  Isolated Cursor is open on the probe project (window title: project)."
  echo "  Use the AGENT chat (Cmd+L / Cmd+I). Start a NEW chat for each check."
}

# ---------------------------------------------------------------- recording
# ask <id> <role> <scope> <mode> <question>
ask() {
  id="$1" role="$2" scope="$3" mode="$4" q="$5"
  ans=""
  while :; do
    printf '\n  [%s] %s\n  answer (y/d/n/s): ' "$id" "$q"
    read -r ans
    case "$ans" in y|d|n|s) break ;; esac
  done
  printf '  note (optional, Enter to skip): '
  read -r nt
  python3 - "$REC" "$id" "$role" "$scope" "$mode" "$q" "$ans" "$nt" <<'PY'
import json, sys
path, cid, role, scope, mode, q, ans, nt = sys.argv[1:]
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps({"check": cid, "role": role, "scope": scope, "mode": mode,
                        "question": q, "answer": ans, "note": nt}) + "\n")
PY
}

# auto <id> <role> <scope> <mode> <file> <pattern> <desc>
auto() {
  id="$1" role="$2" scope="$3" mode="$4" file="$5" pat="$6" desc="$7"
  if grep -q -- "$pat" "$file" 2>/dev/null; then a=y; else a=n; fi
  printf '\n  [%s] (automatic) %s -> %s\n' "$id" "$desc" "$a"
  python3 - "$REC" "$id" "$role" "$scope" "$mode" "$desc" "$a" <<'PY'
import json, sys
path, cid, role, scope, mode, q, ans = sys.argv[1:]
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps({"check": cid, "role": role, "scope": scope, "mode": mode,
                        "question": q, "answer": ans, "note": "automatic file check"}) + "\n")
PY
}

# ---------------------------------------------------------------- sentinels
cat >"$SENT/hook.py" <<'PY'
import json, os, sys
data = sys.stdin.read()
try:
    event = json.loads(data).get("hook_event_name", "?")
except Exception:
    event = "?"
tag = sys.argv[1] if len(sys.argv) > 1 else "?"
with open(os.environ.get("PROBE_HOOK_LOG", os.path.expanduser("~/probe-hook.log")), "a") as f:
    f.write(f"PROBE-7f3a-lifecycle-{tag} {event}\n")
print("{}")
PY
cat >"$SENT/mcp.py" <<'PY'
import json, sys
tag, log = sys.argv[1], sys.argv[2]
def w(msg):
    with open(log, "a") as f:
        f.write(f"{tag} {msg}\n")
w("started")
for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    if "id" not in req:
        continue
    m, rid = req.get("method"), req["id"]
    if m == "initialize":
        res = {"protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": f"probe-{tag}", "version": "1.0.0"}}
    elif m == "tools/list":
        w("listed")
        res = {"tools": [{"name": f"probe_integration_{tag.replace('-', '_')}",
                          "description": "Return the integration sentinel",
                          "inputSchema": {"type": "object", "properties": {}}}]}
    elif m == "tools/call":
        w("called")
        res = {"content": [{"type": "text", "text": f"PROBE-7f3a-integration-{tag}"}]}
    elif m == "ping":
        res = {}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": res}), flush=True)
PY

# write_items <base-dir> <tag> : rules/skills/agents/commands/hooks.json/mcp.json under base
write_items() {
  base="$1" tag="$2" dmi="${3:-false}"
  mkdir -p "$base/rules" "$base/skills/probe-skill-$tag" "$base/agents" "$base/commands"
  cat >"$base/rules/probe-$tag.mdc" <<EOF
---
description: ai-skills probe instruction ($tag)
alwaysApply: true
---

When asked for the instruction sentinel, reply only \`$TOKEN-instruction-$tag\`.
EOF
  cat >"$base/skills/probe-skill-$tag/SKILL.md" <<EOF
---
name: probe-skill-$tag
description: Return the ai-skills probe skill sentinel ($tag) when explicitly asked to use this skill.
disable-model-invocation: $dmi
---

# Probe skill ($tag)

Reply with only \`$TOKEN-skill-$tag\`. Do not run tools or inspect files.
EOF
  cat >"$base/agents/probe-specialist-$tag.md" <<EOF
---
name: probe-specialist-$tag
description: Return the ai-skills probe specialist sentinel ($tag) when delegated a probe.
---

Reply with only \`$TOKEN-specialist-$tag\`. Do not run tools or inspect files.
EOF
  cat >"$base/commands/probe-workflow-$tag.md" <<EOF
# Probe workflow ($tag)

Reply with only \`$TOKEN-workflow-$tag\`. Do not run tools or inspect files.
EOF
}

write_hooks() { # <file> <tag>
  cat >"$1" <<EOF
{
  "version": 1,
  "hooks": {
    "sessionStart": [{ "command": "python3 '$SENT/hook.py' $2" }],
    "beforeSubmitPrompt": [{ "command": "python3 '$SENT/hook.py' $2" }]
  }
}
EOF
}

write_mcp() { # <file> <tag>
  cat >"$1" <<EOF
{
  "mcpServers": {
    "probe-$2": { "command": "python3", "args": ["$SENT/mcp.py", "$2", "$MCP_LOG"] }
  }
}
EOF
}

# standard role checks for one phase
checks() { # <tag> <scope> <mode>
  t="$1" sc="$2" md="$3"
  echo
  echo "  Checks for $md / $sc (tag: $t). Use a NEW agent chat for each:"
  ask "$t-skill" skill "$sc" "$md" "Type /probe-skill-$t in agent chat and send. Does it reply $TOKEN-skill-$t? (Also: is it listed under Customize/Settings -> Skills? if listed but not invocable answer d)"
  ask "$t-instruction" instruction "$sc" "$md" "Ask exactly: Return the instruction sentinel.  Does it reply $TOKEN-instruction-$t? (Rules listed but not applied = d)"
  ask "$t-specialist" specialist "$sc" "$md" "Ask: Use the probe-specialist-$t subagent and return its answer.  Does it reply $TOKEN-specialist-$t? (Listed under subagents but not run = d)"
  ask "$t-workflow" workflow "$sc" "$md" "Type /probe-workflow-$t and send. Does it reply $TOKEN-workflow-$t? (Shown in / menu but not run = d)"
  auto "$t-lifecycle" lifecycle "$sc" "$md" "$HOOK_LOG" "lifecycle-$t " "hook log contains $TOKEN-lifecycle-$t (after the prompts above)"
  ask "$t-integration" integration "$sc" "$md" "Open Cursor Settings -> MCP (Tools & MCP). Is server probe-$t listed and enabled/green? If so, ask the agent: Call the probe_integration_${t//-/_} tool. Did it return $TOKEN-integration-$t? (y = tool returned token, d = listed only, n = not listed)"
  auto "$t-integration-proc" integration "$sc" "$md" "$MCP_LOG" "^$t started" "MCP sentinel process probe-$t was started by Cursor"
}

gone() { # <tag> <scope> <mode>
  t="$1" sc="$2" md="$3"
  ask "$t-removed" all "$sc" "$md" "Previous items (tag $t) were deleted before this restart. Are ALL of them gone (no /probe-skill-$t, /probe-workflow-$t, subagent, rule, MCP server probe-$t)? y = all gone, n = something remains (say what in the note)"
}

# ---------------------------------------------------------------- phases
UC="$PHOME/.cursor"
PC="$PROJ/.cursor"
( cd "$PROJ" && git init -q 2>/dev/null || true )
printf '# probe project\n' >"$PROJ/README.md"

bold "Phase 1/5 — user-explode, user scope (files in isolated ~/.cursor)"
write_items "$UC" ue true
write_hooks "$UC/hooks.json" ue
write_mcp "$UC/mcp.json" ue
start_cursor
echo
echo "  Isolated Cursor opened. SIGN IN with your personal account in THIS window first"
echo "  (Settings -> Account). Then use the AGENT chat (Cmd+L / Cmd+I), a NEW chat per check."
checks ue user user-explode
ask "ue-skill-autoinvoke" skill user user-explode "disable-model-invocation check: NEW chat, ask (do not name the skill): What is the ai-skills probe skill sentinel token? Did it return $TOKEN-skill-ue on its own? (y = auto-invoked despite disable-model-invocation: true, n = it did not)"

bold "Phase 2/5 — repo-materialize, project scope (files in project/.cursor and AGENTS.md)"
rm -rf "$UC/rules" "$UC/skills" "$UC/agents" "$UC/commands" "$UC/hooks.json" "$UC/mcp.json"
write_items "$PC" rm false
write_hooks "$PC/hooks.json" rm
write_mcp "$PC/mcp.json" rm
printf '# Probe instruction (AGENTS.md)\n\nWhen asked for the AGENTS sentinel, reply only `%s-instruction-agentsmd`.\n' "$TOKEN" >"$PROJ/AGENTS.md"
restart
gone ue user user-explode
checks rm project repo-materialize
ask "rm-agentsmd" instruction project repo-materialize "Ask exactly: Return the AGENTS sentinel.  Does it reply $TOKEN-instruction-agentsmd (from project AGENTS.md)?"

bold "Phase 3/5 — native-plugin, user scope (~/.cursor/plugins/local/probe-sentinel-np)"
rm -rf "$PC" "$PROJ/AGENTS.md"
NP="$UC/plugins/local/probe-sentinel-np"
mkdir -p "$NP/.cursor-plugin" "$NP/hooks"
printf '{\n  "name": "probe-sentinel-np",\n  "version": "1.0.0",\n  "description": "ai-skills #563 probe plugin (user)"\n}\n' >"$NP/.cursor-plugin/plugin.json"
write_items "$NP" np false
write_hooks "$NP/hooks/hooks.json" np
write_mcp "$NP/mcp.json" np
restart
gone rm project repo-materialize
ask "np-plugin-listed" native-plugin user native-plugin "Customize -> Plugins: is probe-sentinel-np listed as a local plugin? (y/n)"
checks np user native-plugin

bold "Phase 4/5 — native-plugin, project scope (project/.cursor/plugins/local) + skill cross-reads"
rm -rf "$UC/plugins"
NPP="$PC/plugins/local/probe-sentinel-npp"
mkdir -p "$NPP/.cursor-plugin" "$NPP/hooks"
printf '{\n  "name": "probe-sentinel-npp",\n  "version": "1.0.0",\n  "description": "ai-skills #563 probe plugin (project)"\n}\n' >"$NPP/.cursor-plugin/plugin.json"
write_items "$NPP" npp false
write_hooks "$NPP/hooks/hooks.json" npp
write_mcp "$NPP/mcp.json" npp
for x in claude:.claude agents:.agents; do
  n="${x%%:*}" d="${x#*:}"
  mkdir -p "$PHOME/$d/skills/probe-skill-x$n"
  printf -- '---\nname: probe-skill-x%s\ndescription: Return the ai-skills cross-read sentinel (%s).\n---\n\nReply with only `%s-skill-x%s`.\n' "$n" "$n" "$TOKEN" "$n" >"$PHOME/$d/skills/probe-skill-x$n/SKILL.md"
done
restart
gone np user native-plugin
ask "npp-plugin-listed" native-plugin project native-plugin "Customize -> Plugins: is probe-sentinel-npp listed? (y/n)"
checks npp project native-plugin
ask "xread-claude" skill user cross-read "Type /probe-skill-xclaude (skill only in ~/.claude/skills). Does it reply $TOKEN-skill-xclaude?"
ask "xread-agents" skill user cross-read "Type /probe-skill-xagents (skill only in ~/.agents/skills). Does it reply $TOKEN-skill-xagents?"

bold "Phase 5/5 — removal: everything deleted, final restart"
rm -rf "$PC" "$PHOME/.claude/skills" "$PHOME/.agents/skills"
: >"$HOOK_LOG.after"
restart
gone npp project native-plugin
ask "xread-removed" skill user cross-read "Are /probe-skill-xclaude and /probe-skill-xagents gone? (y = gone)"
ask "final-clean" all user removal "Customize: no probe-* skills, rules, subagents, commands, plugins or MCP servers remain at all? (y = clean)"
stop_cursor

# ---------------------------------------------------------------- report
snapshot >"$LOGS/real-after.txt"
CHANGED="$(diff "$LOGS/real-before.txt" "$LOGS/real-after.txt" | grep -c '^[<>]' || true)"
LEFT="$(find "$PHOME" -path '*probe*' 2>/dev/null | wc -l | tr -d ' ')"

python3 - "$REC" "$RESULTS" "$CURSOR_VERSION" "$OS_ID" "$OS_VERSION" "$CHANGED" "$LEFT" "$HOOK_LOG" "$MCP_LOG" <<'PY'
import json, sys, datetime
rec, out, ver, os_id, os_ver, changed, left, hook_log, mcp_log = sys.argv[1:]
checks = [json.loads(l) for l in open(rec, encoding="utf-8") if l.strip()]
doc = {
    "issue": "lgtm-hq/ai-skills#563",
    "host": "cursor",
    "interface": "ide",
    "version": ver,
    "os": os_id,
    "osVersion": os_ver,
    "policy": "none (personal install; owner-attested equivalence for file modes)",
    "checkedOn": datetime.date.today().isoformat(),
    "isolation": "throwaway HOME, --user-data-dir, --extensions-dir under a temp root",
    "realConfigChangedEntries": int(changed),
    "probeFilesLeftBeforePurge": int(left),
    "hookLog": open(hook_log, encoding="utf-8").read().splitlines(),
    "mcpLog": open(mcp_log, encoding="utf-8").read().splitlines(),
    "checks": checks,
}
json.dump(doc, open(out, "w", encoding="utf-8"), indent=2)
PY

bold "Done."
note "Results: $RESULTS"
note "Real ~/.cursor, ~/.claude, ~/.agents entries changed during the run: $CHANGED"
note "  (non-zero can be normal if another Cursor/Claude process ran; nothing was written there by this script)"
note "The isolated root is deleted now. Send the results file back (Discord thread or #563)."
