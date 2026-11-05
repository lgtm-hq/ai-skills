import type { HostDefinition } from "../types.ts";

/** Claude Code: native plugins through the `claude` CLI, skills under `.claude/skills`. */
export const CLAUDE_CODE_HOST: HostDefinition = {
  id: "claude-code",
  label: "Claude Code (plugin CLI)",
  skillDir: ".claude/skills",
  defaultMode: "native",
  native: { kind: "cli", adapter: "claude-cli", binary: "claude" },
};
