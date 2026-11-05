import type { HostDefinition } from "../types.ts";

/** Cursor: native plugins as a local tree drop, skills under `.cursor/skills`. */
export const CURSOR_HOST: HostDefinition = {
  id: "cursor",
  label: "Cursor (~/.cursor/plugins/local)",
  skillDir: ".cursor/skills",
  defaultMode: "native",
  native: {
    kind: "tree",
    adapter: "cursor-drop",
    pluginsDir: ".cursor/plugins/local",
    versionBinary: "cursor",
  },
};
