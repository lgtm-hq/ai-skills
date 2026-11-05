import type { HostDefinition } from "../types.ts";

/** GitHub Copilot: native plugins through the `copilot` CLI, skills under `.copilot/skills`. */
export const COPILOT_HOST: HostDefinition = {
  id: "copilot",
  label: "GitHub Copilot (plugin CLI)",
  skillDir: ".copilot/skills",
  defaultMode: "native",
  native: { kind: "cli", adapter: "copilot-cli", binary: "copilot", stripSourceTag: true },
};
