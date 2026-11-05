import type { HostDefinition } from "../types.ts";

/**
 * Codex: skill directory only. Its native plugin route (#384) is not
 * registered yet, so Codex stays exploded.
 */
export const CODEX_HOST: HostDefinition = {
  id: "codex",
  label: "Codex (~/.codex/skills)",
  skillDir: ".codex/skills",
  defaultMode: "explode",
  native: null,
};
