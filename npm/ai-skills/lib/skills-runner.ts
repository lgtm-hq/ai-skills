import { spawn } from "node:child_process";

import { MINIMUM_SKILLS_VERSION } from "./options.ts";

/**
 * Build arguments for the upstream skills CLI.
 */
export function buildSkillsArguments(
  options: {
    agents: string[];
    copy: boolean;
    global: boolean;
    onConflict: string | null;
    project: boolean;
    skills: string[];
    yes: boolean;
  },
  source: string,
): string[] {
  const args = [`skills@^${MINIMUM_SKILLS_VERSION}`, "add", source];
  if (options.global) {
    args.push("-g");
  }
  // The upstream CLI uses its default scope for project installs. The wrapper
  // consumes --project so unattended calls declare their intent explicitly.
  if (options.agents.length > 0) {
    args.push("-a", ...options.agents);
  }
  if (options.skills.length > 0) {
    args.push("--skill", ...options.skills);
  }
  if (options.copy) {
    args.push("--copy");
  }
  // Gateway still accepts --on-conflict for unattended fail-closed API stability,
  // but upstream `skills` (through 1.5.x) does not implement that flag — do not
  // forward a no-op that implies conflict handling the CLI does not provide.
  if (options.yes) {
    args.push("-y");
  }
  return args;
}

/**
 * Build arguments for removing known gateway-managed skills.
 */
export function buildSkillsRemoveArguments(
  options: { agents: string[]; global: boolean; yes: boolean },
  skills: string[],
): string[] {
  // Upstream `skills remove` mirrors `add`: `-g` selects global; omitting it
  // targets the project scope. There is no separate `--project` remove flag.
  const args = [`skills@^${MINIMUM_SKILLS_VERSION}`, "remove", ...skills];
  if (options.global) {
    args.push("-g");
  }
  if (options.agents.length > 0) {
    args.push("-a", ...options.agents);
  }
  if (options.yes) {
    args.push("-y");
  }
  return args;
}

/**
 * Execute the upstream skills CLI.
 */
export function runSkills(
  args: string[],
  spawnCommand: (
    command: string,
    args: string[],
    options: import("node:child_process").SpawnOptions,
  ) => import("node:child_process").ChildProcess = spawn,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawnCommand("bunx", args, {
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`skills CLI exited with status ${code ?? "unknown"}`));
    });
  });
}
