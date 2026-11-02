import { spawn } from "node:child_process";

/**
 * Host CLI binary for native plugin install/uninstall.
 */
export const CLI_BY_AGENT: Record<string, string> = {
  "claude-code": "claude",
  copilot: "copilot",
};

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
 * Native CLI installs are user-scoped by the host. The gateway lock still
 * records `--global` / `--project`; host CLIs do not take a gateway scope flag.
 */
export async function installCliPlugin(args: {
  agent: string;
  pluginId: string;
  source: string;
  marketplace?: string;
  exec?: (command: string, cliArgs: string[]) => Promise<ExecResult>;
}): Promise<{ alreadyPresent: boolean }> {
  const cli = cliForAgent(args.agent);
  const exec = args.exec ?? spawnExec;
  const marketplace = args.marketplace ?? FIRST_PARTY_MARKETPLACE;
  const marketplaceSource = args.agent === "copilot" ? stripGitTag(args.source) : args.source;
  const added = await exec(cli, ["plugin", "marketplace", "add", marketplaceSource]);
  if (added.status !== 0 && !isAlreadyPresent(added)) {
    throw new Error(`${cli} plugin marketplace add failed: ${detail(added)}`);
  }
  const installed = await exec(cli, ["plugin", "install", `${args.pluginId}@${marketplace}`]);
  if (installed.status !== 0 && !isAlreadyPresent(installed)) {
    throw new Error(`${cli} plugin install failed: ${detail(installed)}`);
  }
  return {
    alreadyPresent: isAlreadyPresent(installed),
  };
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

function isAlreadyPresent(result: ExecResult): boolean {
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  return /\balready (exists|installed|added|present)\b/.test(text);
}

function isAlreadyAbsent(result: ExecResult): boolean {
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

function detail(result: ExecResult): string {
  return (result.stderr || result.stdout || `exit ${result.status}`).trim();
}

/**
 * Copilot `plugin marketplace add` takes OWNER/REPO without a git tag.
 */
function stripGitTag(source: string): string {
  return source.replace(/@[^/]+$/, "");
}

export interface ExecResult {
  status: number;
  stderr: string;
  stdout: string;
}
