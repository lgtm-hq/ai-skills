#!/bin/bash
# Cursor load-path probe for lgtm-hq/ai-skills#563 (personal macOS machine).
#
# Runs Cursor in a fully isolated profile (throwaway HOME, user-data and
# extensions dirs under a temp root), installs sentinel test items for each
# role/scope/mode, tells you what to check after each restart, records your
# answers and removal observations, and purges its owned scratch root.
#
# It never writes to your real ~/.cursor, ~/.claude or ~/.agents, and never
# touches an employer-managed machine. Review the sanitized JSON before sharing.
#
# Usage:  bash cursor-macos-probe-driver.sh            (interactive, ~20-30 min)
#         bash cursor-macos-probe-driver.sh --keep     (keep the temp root for debugging)
# Optional: CURSOR_PROBE_APP=/absolute/path/Cursor.app selects one app only;
# an invalid override aborts without falling back to an installed app.
# Output: ./cursor-probe-results-<timestamp>.json  -> send it back (Discord or #563).
#
# Compatible with macOS /bin/bash 3.2. Needs: Cursor.app, python3, shasum.

set -euo pipefail
umask 077

[ "$(uname -s)" = Darwin ] || {
  echo "Personal macOS only; no probe started." >&2
  exit 1
}

KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

TOKEN="PROBE-7f3a"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS="$PWD/cursor-probe-results-$STAMP.json"
# Resolve the parent before allocating scratch: a failed cd cannot leak a root.
# Cursor resolves /var to /private/var; use one physical project identity.
PROBE_TEMP_PARENT="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
ROOT="$(mktemp -d "$PROBE_TEMP_PARENT/ai-skills-563-cursor.XXXXXX")"
PHOME="$ROOT/home"
PROJ="$ROOT/project"
UDATA="$ROOT/user-data"
EXTS="$ROOT/extensions"
LOGS="$ROOT/logs"
SENT="$ROOT/sentinels"
HOOK_LOG="$ROOT/tmp/probe-hook.log"
MCP_LOG="$LOGS/mcp.log"
REC="$LOGS/records.jsonl"
REMOVALS="$LOGS/hook-removals.jsonl"
RUN_STATUS=incomplete
REPORT_REASON=preflight-incomplete
COMPARISON_STATUS=unverified
COMPARISON_REASON=not-collected
CHANGED="" LEFT=""
CURSOR_VERSION=unknown OS_ID=unknown OS_VERSION=unknown
KEYCHAINS_CAPTURED=0
ORIGINAL_KEYCHAINS=()
ISO_KEYCHAIN=""

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

cleanup() {
  local status=0
  if declare -F stop_cursor >/dev/null; then stop_cursor quiet || status=1; fi
  if declare -F restore_keychains >/dev/null; then restore_keychains || status=1; fi
  # Retain scratch if process termination or keychain restoration is unverified.
  [ "$status" -eq 0 ] || return "$status"
  if [ "$KEEP" -eq 0 ]; then
    rm -rf "$ROOT" || status=1
    [ ! -e "$ROOT" ] || status=1
  else
    printf 'Kept temp root: %s\n' "$ROOT"
  fi
  return "$status"
}

write_report() {
  python3 - "$REC" "$RESULTS" "$CURSOR_VERSION" "$OS_ID" "$OS_VERSION" "$CHANGED" "$LEFT" "$HOOK_LOG" "$MCP_LOG" "$ROOT" "$HOME" "$RUN_STATUS" "$REPORT_REASON" "$COMPARISON_STATUS" "$COMPARISON_REASON" "$REMOVALS" "$KEEP" <<'PY'
import json, sys, datetime, os
rec, out, ver, os_id, os_ver, changed, left, hook_log, mcp_log, root, home, status, reason, comparison, comparison_reason, removals, keep = sys.argv[1:]
errors = []
def lines(path, label, records=False):
    result = []
    try:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                if not records:
                    result.append(line.rstrip("\n"))
                elif line.strip():
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError("record must be an object")
                        result.append(record)
                    except ValueError:
                        errors.append(label + "-invalid-record")
    except (OSError, UnicodeError):
        errors.append(label + "-unreadable")
    return result

def sanitize(value):
    import re
    if isinstance(value, str):
        value = value.replace(root, "<probe-root>").replace(home, "<personal-home>")
        value = re.sub(r"(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])[^\n\"']+", "<redacted-path>", value)
        value = re.sub(r"\b(?:github_pat_|gh[pousr]_|sk-)[A-Za-z0-9_-]+", "<redacted-token>", value)
        value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-token>", value)
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "<redacted-key>", value, flags=re.S)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<redacted-email>", value)
        return value
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {sanitize(key): sanitize(item) for key, item in value.items()}
    return value

checks = lines(rec, "checks", records=True)
hooks = lines(hook_log, "hook-log")
mcp = lines(mcp_log, "mcp-log")
removal_evidence = lines(removals, "hook-removals", records=True)
if errors:
    status, reason = "incomplete", "report-collection-incomplete"
    comparison, comparison_reason = "unverified", "report-collection-incomplete"
doc = {
    "issue": "lgtm-hq/ai-skills#563",
    "host": "cursor",
    "interface": "ide",
    "version": ver,
    "os": os_id,
    "osVersion": os_ver,
    "policy": "none",
    "policySource": "https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548",
    "checkedOn": datetime.date.today().isoformat(),
    "isolation": "throwaway HOME, --user-data-dir, --extensions-dir under a temp root",
    "runStatus": status,
    "incompleteReason": reason if status != "complete" else None,
    "configComparisonStatus": comparison,
    "configComparisonReason": comparison_reason if comparison != "complete" else None,
    "realConfigChangedEntries": int(changed) if comparison == "complete" and changed else None,
    "configComparisonScope": "selected regular files below .cursor/.claude/.agents, excluding runtime-like paths and files >=5M; path+SHA256 diff lines, not distinct changed-file count or whole inventory",
    "probeFilesLeftBeforePurge": int(left) if left else None,
    "cleanup": {"mode": "keep" if keep == "1" else "purge", "status": "pending"},
    "collectionErrors": sorted(set(errors)),
    "hookLog": hooks,
    "mcpLog": mcp,
    "hookRemovalEvidence": removal_evidence,
    "checks": checks,
}
text = json.dumps(sanitize(doc), indent=2) + "\n"
try:
    with open(out + ".tmp", "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(out + ".tmp", out)
except OSError:
    # Preserve sanitized observations on stdout if the output directory fails.
    doc["runStatus"], doc["incompleteReason"] = "incomplete", "report-write-failed"
    doc["configComparisonStatus"], doc["configComparisonReason"] = "unverified", "report-write-failed"
    doc["realConfigChangedEntries"] = None
    print(json.dumps(sanitize(doc), indent=2))
    sys.exit(1)
sys.exit(1 if errors else 0)
PY
}

finish() {
  local status=$? report_status=0 cleanup_status=0
  trap - EXIT INT TERM
  set +e
  if [ "$status" -ne 0 ]; then
    RUN_STATUS=incomplete
    REPORT_REASON="${REPORT_REASON:-driver-command-failed}"
    COMPARISON_STATUS=unverified
    COMPARISON_REASON="$REPORT_REASON"
  fi
  # Save observations before deleting any private records, logs or fingerprints.
  local fallback_json=""
  fallback_json="$(write_report)" || report_status=$?
  cleanup || cleanup_status=$?
  # Update only the already sanitized artifact, never recollect purged inputs.
  python3 - "$RESULTS" "$KEEP" "$cleanup_status" "$fallback_json" <<'PY' || report_status=1
import json, sys, os
path, keep, failed, fallback = sys.argv[1:]
if fallback:
    doc = json.loads(fallback)
else:
    with open(path, encoding="utf-8") as stream:
        doc = json.load(stream)
doc["cleanup"]["status"] = "unverified" if failed != "0" else ("retained" if keep == "1" else "purged")
if failed != "0":
    doc["runStatus"], doc["incompleteReason"] = "incomplete", "cleanup-unverified"
try:
    with open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(doc, stream, indent=2)
        stream.write("\n")
    os.replace(path + ".tmp", path)
except OSError:
    print(json.dumps(doc, indent=2))
    sys.exit(1)
PY
  if [ "$status" -eq 0 ] && { [ "$report_status" -ne 0 ] || [ "$cleanup_status" -ne 0 ]; }; then status=1; fi
  if [ -f "$RESULTS" ]; then
    printf 'Sanitized results (review runStatus and comparison status): %s\n' "$RESULTS"
  else
    printf 'Sanitized results are on stdout; no results file was written.\n' >&2
  fi
  exit "$status"
}
trap finish EXIT
trap 'RUN_STATUS=incomplete; REPORT_REASON=interrupted-int; exit 130' INT
trap 'RUN_STATUS=incomplete; REPORT_REASON=interrupted-term; exit 143' TERM

mkdir -p "$PHOME" "$PROJ" "$UDATA" "$EXTS" "$LOGS" "$SENT" "$ROOT/tmp"
: >"$HOOK_LOG"
: >"$MCP_LOG"
: >"$REC"
: >"$REMOVALS"

# ---------------------------------------------------------------- preflight
select_cursor_app() { # <global-candidate> <home-candidate>
  local c
  APP=""
  if [ "${CURSOR_PROBE_APP+x}" = x ]; then
    # Presence, including an empty override, disables all default discovery.
    APP="$CURSOR_PROBE_APP"
  else
    for c in "$@"; do
      if [ -d "$c" ]; then
        APP="$c"
        break
      fi
    done
  fi
  case "$APP" in
  /*) ;;
  *)
    echo "Cursor app must be an absolute directory path (CURSOR_PROBE_APP if set)." >&2
    return 1
    ;;
  esac
  [ -d "$APP" ] || {
    echo "Cursor app directory not found at $APP" >&2
    return 1
  }
  APP="$(cd "$APP" && pwd -P)" || return 1
  CLI="$APP/Contents/Resources/app/bin/cursor"
  [ -f "$CLI" ] && [ -x "$CLI" ] || {
    echo "Cursor CLI launcher not found or not executable at $CLI" >&2
    return 1
  }
}
select_cursor_app "/Applications/Cursor.app" "$HOME/Applications/Cursor.app"
if ! command -v python3 >/dev/null || ! python3 -c 'import json' 2>/dev/null; then
  echo "python3 is required (hook and MCP sentinels)." >&2
  exit 1
fi

CURSOR_VERSION="$(/usr/bin/defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo unknown)"
OS_ID="darwin-$(uname -m)"
OS_VERSION="$(sw_vers -productVersion 2>/dev/null || echo unknown)"

bold "ai-skills #563 Cursor probe — Cursor $CURSOR_VERSION on macOS $OS_VERSION ($OS_ID)"
note "Isolated root (deleted at the end): $ROOT"
note "Your real ~/.cursor, ~/.claude and ~/.agents are only READ (before/after fingerprint)."
note "Answers: y = token returned / item works, d = listed but not invoked, n = absent/no, s = skip."
note "Only personal Cursor; do not enter org policy details or personal info."
note "Verify Allow Local Plugin Imports is enabled for the personal native-plugin control."
note "Select This Mac (local agent); a Cloud agent cannot read these local files."
echo
echo "Before starting: QUIT your normal Cursor completely (Cmd+Q). The isolated window"
echo "needs its own sign-in, and the browser login callback must reach the isolated one."
printf 'Press Enter when your normal Cursor is closed... '
read -r _

restore_keychains() {
  [ "$KEYCHAINS_CAPTURED" -eq 1 ] || return 0
  # Array elements preserve spaces; an empty original list is restored too.
  security list-keychains -d user -s ${ORIGINAL_KEYCHAINS[@]+"${ORIGINAL_KEYCHAINS[@]}"} || return 1
  [ -z "$ISO_KEYCHAIN" ] || security delete-keychain "$ISO_KEYCHAIN" || return 1
  local current
  current="$(security list-keychains -d user)" || return 1
  [ "$current" = "$ORIGINAL_KEYCHAIN_OUTPUT" ] || {
    echo "Keychain search list restoration failed; private scratch retained." >&2
    return 1
  }
}

prepare_keychain() {
  # Without this Cursor reports Keychain Not Found. NEVER choose Reset To Defaults:
  # that resets the logged-in account's real keychain.
  local line
  ORIGINAL_KEYCHAIN_OUTPUT="$(security list-keychains -d user)" || return 1
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    line="${line#*\"}"
    line="${line%\"*}"
    ORIGINAL_KEYCHAINS+=("$line")
  done <<<"$ORIGINAL_KEYCHAIN_OUTPUT"
  KEYCHAINS_CAPTURED=1
  mkdir -p "$PHOME/Library/Keychains"
  ISO_KEYCHAIN="$PHOME/Library/Keychains/login.keychain-db"
  security create-keychain -p "" "$ISO_KEYCHAIN" || return 1
  # Creation can modify the real account search list; restore it immediately.
  security list-keychains -d user -s ${ORIGINAL_KEYCHAINS[@]+"${ORIGINAL_KEYCHAINS[@]}"}
}
REPORT_REASON=keychain-setup-failed
prepare_keychain

snapshot() {
  # Selected paths + SHA-256 only. Not a whole-home inventory or no-residue proof.
  # Guard an empty array for stock macOS Bash 3.2 with set -u.
  local d
  local roots=()
  for d in .cursor .claude .agents; do
    if [ -d "$HOME/$d" ]; then roots+=("$d"); fi
  done
  for d in ${roots[@]+"${roots[@]}"}; do
    # Relative traversal prevents an ancestor named cache from excluding HOME.
    (cd "$HOME" && find "$d" \
      \( -path "$d/extensions" -o -path "$d/logs" -o -path "$d/cache" \
      -o -path "$d/Cache" -o -path "$d/projects" -o -path "$d/sessions" \) -prune \
      -o -type f -size -5M -exec shasum -a 256 {} +) || return 1
  done | sort
}
REPORT_REASON=baseline-snapshot-failed
snapshot >"$LOGS/real-before.txt"
REPORT_REASON=checks-interrupted

# ---------------------------------------------------------------- launch/stop
CURSOR_PROCESS_PATTERN="$(
  python3 - "$APP" "$UDATA" <<'PY'
import sys
def literal_ere(value: str) -> str:
    """Escape POSIX ERE metacharacters, leaving spaces and quotes literal."""
    return "".join("\\" + char if char in r".^$*+?{}[]\|()" else char for char in value)
app, udata = map(literal_ere, sys.argv[1:])
# Anchor to this app's executables so shells mentioning the path cannot match.
# ps/pgrep flatten argv with spaces; accept both flag forms and bound its value.
print(r"^" + app + r"/Contents/.*[[:space:]]--user-data-dir(=|[[:space:]])"
      + udata + r"([[:space:]]|$)")
PY
)"
running() { pgrep -f -- "$CURSOR_PROCESS_PATTERN" >/dev/null 2>&1; }

start_cursor() {
  env -i PATH="$PATH" HOME="$PHOME" TMPDIR="$ROOT/tmp" \
    XDG_CONFIG_HOME="$ROOT/config" XDG_CACHE_HOME="$ROOT/cache" \
    XDG_DATA_HOME="$ROOT/data" XDG_STATE_HOME="$ROOT/state" \
    "$CLI" --new-window --user-data-dir="$UDATA" --extensions-dir="$EXTS" "$PROJ" \
    >"$LOGS/launch.log" 2>&1 || true
  i=0
  while ! running && [ $i -lt 30 ]; do
    sleep 1
    i=$((i + 1))
  done
  if ! running; then
    echo "Isolated Cursor did not start (see $LOGS/launch.log)." >&2
    exit 1
  fi
  sleep 3
  # Isolation check: Cursor must have created its home folder data under the
  # throwaway HOME (argv.json), not only under your real ~/.cursor.
  if [ ! -e "$PHOME/.cursor/argv.json" ] && [ -z "${ISO_WARNED:-}" ]; then
    ISO_WARNED=1
    echo "  No isolated ~/.cursor/argv.json: isolation is unconfirmed. Aborting." >&2
    exit 1
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
  while running && [ $i -lt 15 ]; do
    sleep 1
    i=$((i + 1))
  done
  if running; then
    pkill -f -- "$CURSOR_PROCESS_PATTERN" 2>/dev/null || true
    sleep 2
  fi
  if running; then
    echo "Isolated Cursor still running; cleanup verification incomplete." >&2
    return 1
  fi
}

restart() {
  stop_cursor
  start_cursor
  echo
  echo "  Isolated Cursor is open on the probe project (window title: project)."
  echo "  Use the AGENT chat (Cmd+L / Cmd+I). Start a NEW chat for each check."
  echo "  Agent location must be This Mac, so the agent can see local probe files."
}

# ---------------------------------------------------------------- recording
# ask <id> <role> <scope> <mode> <question>
ask() {
  id="$1" role="$2" scope="$3" mode="$4" q="$5"
  ans=""
  while :; do
    printf '\n  [%s] %s\n  answer (y/d/n/s): ' "$id" "$q"
    read -r ans
    case "$ans" in y | d | n | s) break ;; esac
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
except (ValueError, AttributeError):
    event = "?"
tag = sys.argv[1] if len(sys.argv) > 1 else "?"
with open(os.path.join(os.environ["TMPDIR"], "probe-hook.log"), "a", encoding="utf-8") as f:
    f.write(f"PROBE-7f3a-lifecycle-{tag} {event}\n")
print("{}")
PY
cat >"$SENT/mcp.py" <<'PY'
import json, math, sys
tag, log = sys.argv[1], sys.argv[2]
def w(msg):
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{tag} {msg}\n")
w("started")
for line in sys.stdin:
    try:
        req = json.loads(line, parse_constant=lambda value: None)
    except ValueError:
        continue
    if (not isinstance(req, dict) or req.get("jsonrpc") != "2.0"
            or not isinstance(req.get("method"), str)
            or type(req.get("id")) not in (str, int, float, type(None))
            or ("id" in req and req["id"] is None)
            or (isinstance(req.get("id"), float) and not math.isfinite(req["id"]))):
        continue
    if "id" not in req:
        continue
    m, rid = req.get("method"), req["id"]
    params = req.get("params", {})
    if not isinstance(params, dict):
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid params"}}), flush=True)
        continue
    if m == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": f"probe-{tag}", "version": "1.0.0"}}
    elif m == "tools/list":
        w("listed")
        res = {"tools": [{"name": f"probe_integration_{tag.replace('-', '_')}",
                          "description": "Return the integration sentinel",
                          "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}
    elif m == "tools/call":
        arguments = params.get("arguments", {})
        if (params.get("name") != f"probe_integration_{tag.replace('-', '_')}"
                or not isinstance(arguments, dict) or arguments):
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid params"}}), flush=True)
            continue
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
  python3 - "$1" "$SENT/hook.py" "$2" <<'PY'
import json, shlex, sys
path, hook, tag = sys.argv[1:]
command = " ".join(shlex.quote(arg) for arg in ("python3", hook, tag))
with open(path, "w", encoding="utf-8") as stream:
    json.dump({"version": 1, "hooks": {
        "sessionStart": [{"command": command}],
        "beforeSubmitPrompt": [{"command": command}],
    }}, stream, indent=2)
    stream.write("\n")
PY
}

write_mcp() { # <file> <tag>
  python3 - "$1" "$SENT/mcp.py" "$2" "$MCP_LOG" <<'PY'
import json, sys
path, sentinel, tag, log = sys.argv[1:]
with open(path, "w", encoding="utf-8") as stream:
    json.dump({"mcpServers": {
        "probe-" + tag: {"command": "python3", "args": [sentinel, tag, log]},
    }}, stream, indent=2)
    stream.write("\n")
PY
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
  ask "$t-removed" all "$sc" "$md" "Previous items (tag $t) were deleted before this restart. Open a NEW chat and send: Reply OK. Are ALL items gone (no /probe-skill-$t, /probe-workflow-$t, subagent, rule, hooks, MCP server probe-$t)? y = all gone AND fresh prompt completed, n = something remains, s = prompt not completed (say what in the note). Hook removal is also checked automatically below."
  python3 - "$HOOK_LOG" "$REMOVALS" "$REC" "$t" "$sc" "$md" "$HOOK_BOUNDARY" "$HOOK_LINE_BOUNDARY" "$ans" <<'PY'
import json, sys
log, evidence, records, tag, scope, mode, boundary, line_boundary, human = sys.argv[1:]
boundary, line_boundary = int(boundary), int(line_boundary)
count = None
invocation_control = "s"
status, answer = "unverified", "s"
try:
    with open(records, encoding="utf-8") as stream:
        checks = [json.loads(line) for line in stream if line.strip()]
    invocation_control = next((check["answer"] for check in checks
        if check["check"] == tag + "-lifecycle"), "s")
    with open(log, "rb") as stream:
        data = stream.read()
    if len(data) >= boundary:
        prefix = f"PROBE-7f3a-lifecycle-{tag} ".encode()
        count = sum(line.startswith(prefix) for line in data[boundary:].splitlines())
        if count:
            status, answer = "still-firing", "n"
        elif human in ("y", "n") and invocation_control == "y":
            status, answer = "verified-absent", "y"
except (OSError, ValueError, UnicodeError):
    pass
event = {"tag": tag, "scope": scope, "mode": mode, "phase": "after-restart-fresh-prompt",
         "byteBoundary": boundary, "lineBoundary": line_boundary,
         "newRemovedTagEntries": count, "status": status, "invocationControl": invocation_control}
with open(evidence, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(event) + "\n")
with open(records, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"check": tag + "-lifecycle-removed", "role": "lifecycle",
                            "scope": scope, "mode": mode, "question": "No new removed-tag hook entries after restart and fresh prompt",
                            "answer": answer, "note": event}) + "\n")
print(f"  [{tag}-lifecycle-removed] {status} (new removed-tag entries: {count})")
PY
}

removal_restart() { # <removed-tag> <scope> <mode>
  HOOK_BOUNDARY="$(wc -c <"$HOOK_LOG" | tr -d ' ')"
  HOOK_LINE_BOUNDARY="$(wc -l <"$HOOK_LOG" | tr -d ' ')"
  python3 - "$REMOVALS" "$1" "$2" "$3" "$HOOK_BOUNDARY" "$HOOK_LINE_BOUNDARY" <<'PY'
import json, sys
path, tag, scope, mode, boundary, line_boundary = sys.argv[1:]
with open(path, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"tag": tag, "scope": scope, "mode": mode,
                             "phase": "before-removal-restart", "status": "pending",
                             "byteBoundary": int(boundary), "lineBoundary": int(line_boundary)}) + "\n")
PY
  restart
}

# ---------------------------------------------------------------- phases
UC="$PHOME/.cursor"
PC="$PROJ/.cursor"
(cd "$PROJ" && git init -q 2>/dev/null || true)
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
cat >"$PROJ/AGENTS.md" <<EOF
# Probe instruction (AGENTS.md)

When asked for the AGENTS sentinel, reply only \`$TOKEN-instruction-agentsmd\`.
EOF
removal_restart ue user user-explode
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
removal_restart rm project repo-materialize
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
  cat >"$PHOME/$d/skills/probe-skill-x$n/SKILL.md" <<EOF
---
name: probe-skill-x$n
description: Return the ai-skills cross-read sentinel ($n).
---

Reply with only \`$TOKEN-skill-x$n\`.
EOF
done
removal_restart np user native-plugin
gone np user native-plugin
ask "npp-plugin-listed" native-plugin project native-plugin "Customize -> Plugins: is probe-sentinel-npp listed? (y/n)"
checks npp project native-plugin
ask "xread-claude" skill user cross-read "Type /probe-skill-xclaude (skill only in ~/.claude/skills). Does it reply $TOKEN-skill-xclaude?"
ask "xread-agents" skill user cross-read "Type /probe-skill-xagents (skill only in ~/.agents/skills). Does it reply $TOKEN-skill-xagents?"

bold "Phase 5/5 — removal: everything deleted, final restart"
rm -rf "$PC" "$PHOME/.claude/skills" "$PHOME/.agents/skills"
removal_restart npp project native-plugin
gone npp project native-plugin
ask "xread-removed" skill user cross-read "Are /probe-skill-xclaude and /probe-skill-xagents gone? (y = gone)"
ask "final-clean" all user removal "Customize: no probe-* skills, rules, subagents, commands, plugins or MCP servers remain at all? (y = clean)"
stop_cursor

# ---------------------------------------------------------------- report
REPORT_REASON=final-snapshot-failed
COMPARISON_REASON=final-snapshot-failed
snapshot >"$LOGS/real-after.txt"
REPORT_REASON=config-diff-failed
COMPARISON_REASON=config-diff-failed
diff_status=0
diff "$LOGS/real-before.txt" "$LOGS/real-after.txt" >"$LOGS/config.diff" || diff_status=$?
[ "$diff_status" -le 1 ] || {
  echo "Config comparison incomplete." >&2
  exit 1
}
CHANGED="$(grep -c '^[<>]' "$LOGS/config.diff" || test "$?" -eq 1)"
COMPARISON_STATUS=complete
COMPARISON_REASON=""
REPORT_REASON=report-collection-failed
LEFT="$(cd "$PHOME" && find . -name '*probe*' | wc -l | tr -d ' ')"
RUN_STATUS=complete
REPORT_REASON=""

bold "Checks finished; saving report and cleaning up on exit."
note "Selected real-config fingerprint diff lines: $CHANGED (not distinct files or a whole inventory)."
note "No cause is inferred from changes; do not restore over concurrent work."
note "Review runStatus, configComparisonStatus and cleanup in the sanitized JSON before sharing."
note "--keep retains private scratch state and is not a purge."
