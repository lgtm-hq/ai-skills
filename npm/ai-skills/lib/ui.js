import * as clack from "@clack/prompts";

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
 * One-line home-screen summary of the scope's installed skills.
 *
 * @param {{skills: Record<string, {agents: string[]}>}} lock - Scope lockfile.
 * @returns {string | null} Summary such as `12 skills installed · 3 agents`, or null when empty.
 */
export function formatInstalledSummary(lock) {
  const entries = Object.values(lock.skills);
  if (entries.length === 0) {
    return null;
  }
  const agents = new Set(entries.flatMap((entry) => entry.agents));
  const skillLabel = entries.length === 1 ? "skill" : "skills";
  const agentLabel = agents.size === 1 ? "agent" : "agents";
  return `${entries.length} ${skillLabel} installed · ${agents.size} ${agentLabel}`;
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
 * Status suffix for an installed skill row in a browse list.
 *
 * @param {object} args - Named arguments.
 * @param {{agents: string[]} | undefined} args.entry - Lockfile entry for the skill in this catalog, if installed.
 * @param {boolean} args.drifted - Whether the installed pin is behind the baked catalog.
 * @returns {string} Suffix such as ` ✔ installed (claude-code) · update available (run skill update)`, or empty.
 */
export function formatSkillStatusSuffix({ entry, drifted }) {
  if (!entry) {
    return "";
  }
  const agents = entry.agents.length > 0 ? ` (${entry.agents.join(", ")})` : "";
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
