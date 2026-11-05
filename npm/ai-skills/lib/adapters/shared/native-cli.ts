import { spawn } from "node:child_process";

import { HOST_DEFINITIONS } from "../hosts.ts";

/**
 * Host CLI binary for native plugin install/uninstall, read from host definitions.
 */
export const CLI_BY_AGENT: Readonly<Record<string, string>> = Object.fromEntries(
  HOST_DEFINITIONS.flatMap((host) =>
    host.native?.kind === "cli" ? [[host.id, host.native.binary]] : [],
  ),
);

/**
 * Marketplace source name first-party plugins install from.
 *
 * Keep in sync with `.claude-plugin/marketplace.json` `name`.
 */
export const FIRST_PARTY_MARKETPLACE = "ai-skills";

/**
 * Run a CLI plugin command.
 */
export function spawnExec(command: string, args: string[]): Promise<ExecResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (status) => {
      resolve({ status: status ?? 1, stderr, stdout });
    });
  });
}

/**
 * Uninstall one plugin through a host CLI.
 */
export async function uninstallCliPlugin(args: {
  agent: string;
  pluginId: string;
  marketplace?: string;
  exec?: (command: string, cliArgs: string[]) => Promise<ExecResult>;
}): Promise<void> {
  const cli = cliForAgent(args.agent);
  const exec = args.exec ?? spawnExec;
  const marketplace = args.marketplace ?? FIRST_PARTY_MARKETPLACE;
  const removed = await exec(cli, ["plugin", "uninstall", `${args.pluginId}@${marketplace}`]);
  if (removed.status !== 0 && !isAlreadyAbsent(removed)) {
    throw new Error(`${cli} plugin uninstall failed: ${detail(removed)}`);
  }
}

function cliForAgent(agent: string): string {
  const cli = CLI_BY_AGENT[agent];
  if (!cli) {
    throw new Error(`No native CLI projector for agent ${agent}`);
  }
  return cli;
}

export function isAlreadyPresent(result: ExecResult): boolean {
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  return /\balready (exists|installed|added|present)\b/.test(text);
}

export function isAlreadyAbsent(result: ExecResult): boolean {
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  if (/\balready (uninstalled|removed|absent)\b/.test(text)) {
    return true;
  }
  if (/\bmarketplace\b/.test(text)) {
    return false;
  }
  return (
    /\bplugin\b/.test(text) &&
    (/\bnot (found|installed)\b/.test(text) || /\bdoes not exist\b/.test(text))
  );
}

export function detail(result: ExecResult): string {
  return (result.stderr || result.stdout || `exit ${result.status}`).trim();
}

/**
 * Drop a trailing git tag: the recorded Copilot deviation (#584).
 */
export function stripGitTag(source: string): string {
  return source.replace(/@[^/]+$/, "");
}

export interface ExecResult {
  status: number;
  stderr: string;
  stdout: string;
}
