import { spawn } from "node:child_process";

import { MINIMUM_SKILLS_VERSION } from "./options.js";

/**
 * Build arguments for the upstream skills CLI.
 *
 * @param {{agents: string[], copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], yes: boolean}} options - Selected install options.
 * @param {string} source - Pinned skills repository source.
 * @returns {string[]} Arguments passed to `bunx`.
 */
export function buildSkillsArguments(options, source) {
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
  if (options.onConflict) {
    args.push("--on-conflict", options.onConflict);
  }
  if (options.yes) {
    args.push("-y");
  }
  return args;
}

/**
 * Build arguments for removing known gateway-managed skills.
 *
 * @param {{agents: string[], global: boolean, yes: boolean}} options - Selected command options.
 * @param {string[]} skills - Skills to remove.
 * @returns {string[]} Arguments passed to `bunx`.
 */
export function buildSkillsRemoveArguments(options, skills) {
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
 *
 * @param {string[]} args - Arguments for `bunx`.
 * @param {(command: string, args: string[], options: import("node:child_process").SpawnOptions) => import("node:child_process").ChildProcess} [spawnCommand] - Injectable process launcher for tests.
 * @returns {Promise<void>} Resolves on a successful install.
 */
export function runSkills(args, spawnCommand = spawn) {
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
