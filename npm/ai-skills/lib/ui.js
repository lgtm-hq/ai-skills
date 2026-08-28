import * as clack from "@clack/prompts";

import { pluginAgentNames } from "./lockfile.js";

/**
 * Agents the gateway surfaces in interactive install.
 *
 * Keep labels user-facing; values match upstream `skills -a` identifiers.
 */
export const KNOWN_AGENTS = [
  { value: "claude-code", label: "Claude Code (~/.claude/skills)" },
  { value: "cursor", label: "Cursor (~/.cursor/skills)" },
  { value: "codex", label: "Codex (~/.codex/skills)" },
];

/**
 * Informational suffix for a vendor row whose upstream moved past the baked pin.
 *
 * Deliberately phrased as a signal, not an action: the newer commits become
 * installable only after the gateway re-pins them in a new release.
 */
export const VENDOR_DRIFT_SUFFIX =
  " (upstream has newer commits — installable after a gateway re-pin)";

/**
 * One-line home-screen summary of the installed plugins in the given lock state.
 *
 * @param {{plugins: Record<string, import("./lockfile.js").PluginLockEntry>}} lock - Lock state (single scope, or merged scopes when undetermined).
 * @returns {string | null} Summary such as `12 plugins installed · 3 agents`, or null when empty.
 */
export function formatInstalledSummary(lock) {
  const entries = Object.values(lock.plugins ?? {});
  if (entries.length === 0) {
    return null;
  }
  const agents = new Set(entries.flatMap((entry) => pluginAgentNames(entry)));
  const pluginLabel = entries.length === 1 ? "plugin" : "plugins";
  const agentLabel = agents.size === 1 ? "agent" : "agents";
  return `${entries.length} ${pluginLabel} installed · ${agents.size} ${agentLabel}`;
}

/**
 * One-line install result: new agents, already healthy, and repaired.
 *
 * @param {{alreadyPresent: number, installed: number, repaired: number}} counts - Install summary counts.
 * @returns {string} Summary such as `1 installed · 0 already present · 1 repaired`.
 */
export function formatInstallCounts(counts) {
  return `${counts.installed} installed · ${counts.alreadyPresent} already present · ${counts.repaired} repaired`;
}

/**
 * Header notice for a newer published gateway release, with exact remedies.
 *
 * @param {{current: string, latest: string}} update - Running and latest versions.
 * @returns {string} Multi-line notice body.
 */
export function formatGatewayUpdateNotice(update) {
  return [
    `Update available: v${update.current} → v${update.latest}`,
    "  bun update -g @lgtm-hq/ai-skills",
    `  (or: bunx --package=@lgtm-hq/ai-skills@${update.latest} skill)`,
  ].join("\n");
}

/**
 * Strip C0/C1 control characters (ANSI ESC, OSC, etc.) from untrusted display text.
 *
 * Lockfiles are user-editable JSON, so agent names must not be able to smuggle
 * terminal control sequences into Clack labels (CWE-150).
 *
 * @param {string} text - Untrusted text destined for terminal output.
 * @returns {string} Text with control characters removed.
 */
function stripControlCharacters(text) {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\u0000-\u001f\u007f-\u009f]/g, "");
}

/**
 * Status suffix for an installed skill row in a browse list.
 *
 * @param {object} args - Named arguments.
 * @param {import("./lockfile.js").PluginLockEntry | undefined} args.entry - Lockfile entry for the skill in this catalog, if installed.
 * @param {boolean} args.drifted - Whether the installed pin is behind the baked catalog.
 * @returns {string} Suffix such as ` ✔ installed (claude-code) · update available (run skill update)`, or empty.
 */
export function formatSkillStatusSuffix({ entry, drifted }) {
  if (!entry) {
    return "";
  }
  const names = pluginAgentNames(entry);
  const agents =
    names.length > 0 ? ` (${names.map((agent) => stripControlCharacters(agent)).join(", ")})` : "";
  const drift = drifted ? " · update available (run skill update)" : "";
  return ` ✔ installed${agents}${drift}`;
}

/**
 * Build the default interactive UI (Clack).
 *
 * @returns {{
 *   intro: (message: string) => void,
 *   outro: (message: string) => void,
 *   note: (message: string, title?: string) => void,
 *   select: (options: {message: string, options: {value: string, label: string}[], initialValue?: string}) => Promise<string | symbol>,
 *   multiselect: (options: {message: string, options: {value: string, label: string}[], initialValues?: string[], required?: boolean}) => Promise<string[] | symbol>,
 *   groupMultiselect: (options: {message: string, options: Record<string, {value: string, label: string}[]>, initialValues?: string[], required?: boolean}) => Promise<string[] | symbol>,
 *   confirm: (options: {message: string, initialValue?: boolean}) => Promise<boolean | symbol>,
 *   isCancel: (value: unknown) => boolean,
 * }} Interactive UI adapter.
 */
export function createClackUi() {
  return {
    intro: clack.intro,
    outro: clack.outro,
    note: clack.note,
    select: clack.select,
    multiselect: clack.multiselect,
    groupMultiselect: clack.groupMultiselect,
    confirm: clack.confirm,
    isCancel: clack.isCancel,
  };
}
