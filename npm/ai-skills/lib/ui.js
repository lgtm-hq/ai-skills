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
 * Build the default interactive UI (Clack).
 *
 * @returns {{
 *   intro: (message: string) => void,
 *   outro: (message: string) => void,
 *   note: (message: string, title?: string) => void,
 *   select: (options: {message: string, options: {value: string, label: string}[], initialValue?: string}) => Promise<string | symbol>,
 *   multiselect: (options: {message: string, options: {value: string, label: string}[], initialValues?: string[], required?: boolean}) => Promise<string[] | symbol>,
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
    confirm: clack.confirm,
    isCancel: clack.isCancel,
  };
}
