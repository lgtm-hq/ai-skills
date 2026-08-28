import { spawn } from "node:child_process";

/**
 * Host CLI binary for native plugin install/uninstall.
 */
export const CLI_BY_AGENT = {
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
 * @typedef {{status: number, stderr: string, stdout: string}} ExecResult
 */

/**
 * Run a CLI plugin command.
 *
 * @param {string} command - Executable name.
 * @param {string[]} args - Argument vector.
 * @returns {Promise<ExecResult>} Exit status and captured streams.
 */
export function spawnExec(command, args) {
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
 *
 * @param {object} args - Named arguments.
 * @param {string} args.agent - `claude-code` or `copilot`.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} args.source - Marketplace source (`owner/repo@tag`).
 * @param {string} [args.marketplace] - Marketplace name in `id@marketplace`.
 * @param {(command: string, cliArgs: string[]) => Promise<ExecResult>} [args.exec] - Injectable exec.
 * @returns {Promise<{alreadyPresent: boolean}>} Whether host install was already satisfied.
 */
export async function installCliPlugin(args) {
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
 *
 * @param {object} args - Named arguments.
 * @param {string} args.agent - `claude-code` or `copilot`.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} [args.marketplace] - Marketplace name in `id@marketplace`.
 * @param {(command: string, cliArgs: string[]) => Promise<ExecResult>} [args.exec] - Injectable exec.
 * @returns {Promise<void>} Resolves when uninstall succeeds or the plugin is already gone.
 */
export async function uninstallCliPlugin(args) {
  const cli = cliForAgent(args.agent);
  const exec = args.exec ?? spawnExec;
  const marketplace = args.marketplace ?? FIRST_PARTY_MARKETPLACE;
  const removed = await exec(cli, ["plugin", "uninstall", `${args.pluginId}@${marketplace}`]);
  if (removed.status !== 0 && !isAlreadyAbsent(removed)) {
    throw new Error(`${cli} plugin uninstall failed: ${detail(removed)}`);
  }
}

/**
 * @param {string} agent - Host identifier.
 * @returns {string} CLI binary.
 */
function cliForAgent(agent) {
  const cli = CLI_BY_AGENT[agent];
  if (!cli) {
    throw new Error(`No native CLI projector for agent ${agent}`);
  }
  return cli;
}

/**
 * @param {ExecResult} result - CLI result.
 * @returns {boolean} Whether add/install was already satisfied.
 */
function isAlreadyPresent(result) {
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  return /\balready (exists|installed|added|present)\b/.test(text);
}

/**
 * @param {ExecResult} result - CLI result.
 * @returns {boolean} Whether uninstall was already a no-op.
 */
function isAlreadyAbsent(result) {
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

/**
 * @param {ExecResult} result - CLI result.
 * @returns {string} Compact failure detail.
 */
function detail(result) {
  return (result.stderr || result.stdout || `exit ${result.status}`).trim();
}

/**
 * Copilot `plugin marketplace add` takes OWNER/REPO without a git tag.
 *
 * @param {string} source - `owner/repo` or `owner/repo@tag`.
 * @returns {string} `owner/repo`.
 */
function stripGitTag(source) {
  return source.replace(/@[^/]+$/, "");
}
