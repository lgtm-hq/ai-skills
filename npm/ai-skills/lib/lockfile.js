import { createHash } from "node:crypto";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { getPackageVersion } from "./package-version.js";

export const LOCKFILE_VERSION = 2;

export const PROJECTOR_EXPLODE = "explode";
export const PROJECTOR_NATIVE = "native";

export const AGENT_SKILL_PATHS = {
  "claude-code": ".claude/skills",
  cursor: ".cursor/skills",
  codex: ".codex/skills",
};

/**
 * @typedef {{root: string, files: Record<string, string>}} AgentInstall
 * Per-agent tracked paths and sha256 hashes, relative to ``root``.
 */

/**
 * @typedef {{
 *   agents: Record<string, AgentInstall>,
 *   installedAt: string,
 *   projector: "native" | "explode",
 *   repo: string,
 *   sha: string,
 *   vendor: string,
 *   version: string,
 * }} PluginLockEntry
 */

/**
 * @typedef {{
 *   gatewayVersion: string,
 *   plugins: Record<string, PluginLockEntry>,
 *   scope: "global" | "project",
 *   version: number,
 * }} GatewayLock
 */

/**
 * @typedef {{agent: string, pluginId: string}} ReconcileItem
 */

/**
 * @typedef {{missing: ReconcileItem[], modified: ReconcileItem[], present: ReconcileItem[]}} ReconcileResult
 */

/**
 * Resolve the gateway lockfile path for an installation scope.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string}} [environment] - Injectable path environment.
 * @returns {string} Absolute lockfile path.
 */
export function getLockfilePath(scope, environment = {}) {
  const cwd = environment.cwd ?? process.cwd();
  const home = environment.home ?? homedir();
  return scope === "global"
    ? join(home, ".ai-skills", "lock.json")
    : join(cwd, "ai-skills-lock.json");
}

/**
 * Read a gateway lockfile, returning an empty v2 lock when it does not exist
 * or when a v1 lock is encountered (wipe-and-reinstall).
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string, read?: typeof readFile}} [environment] - Injectable file environment.
 * @returns {Promise<GatewayLock>} Parsed lockfile.
 * @throws {Error} When a present v2 lockfile is malformed or mismatched to its scope.
 */
export async function readLockfile(scope, environment = {}) {
  const read = environment.read ?? readFile;
  const path = getLockfilePath(scope, environment);
  try {
    const lock = JSON.parse(await read(path, "utf8"));
    if (lock.version === 1) {
      return createLockfile(scope);
    }
    if (lock.version !== LOCKFILE_VERSION) {
      throw new Error(`Invalid gateway lockfile: ${path}`);
    }
    if (!isValidV2Lock(lock, scope)) {
      throw new Error(`Invalid gateway lockfile: ${path}`);
    }
    return lock;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return createLockfile(scope);
    }
    throw error;
  }
}

/**
 * Write a gateway lockfile atomically.
 *
 * @param {GatewayLock} lock - Lockfile contents.
 * @param {{cwd?: string, home?: string, mkdir?: typeof mkdir, rename?: typeof rename, write?: typeof writeFile}} [environment] - Injectable file environment.
 * @returns {Promise<void>} Resolves after persisting the lockfile.
 */
export async function writeLockfile(lock, environment = {}) {
  const path = getLockfilePath(lock.scope, environment);
  const makeDirectory = environment.mkdir ?? mkdir;
  const move = environment.rename ?? rename;
  const write = environment.write ?? writeFile;
  await makeDirectory(dirname(path), { recursive: true });
  const temporaryPath = `${path}.tmp`;
  await write(temporaryPath, `${JSON.stringify(lock, null, 2)}\n`, "utf8");
  await move(temporaryPath, path);
}

/**
 * Merge installed plugins into a lockfile without discarding tracked agents.
 *
 * @param {GatewayLock} lock - Existing lockfile.
 * @param {Record<string, PluginLockEntry>} entries - Newly installed plugin records.
 * @returns {GatewayLock} Updated lockfile.
 */
export function mergeLockEntries(lock, entries) {
  const plugins = { ...lock.plugins };
  for (const [pluginId, entry] of Object.entries(entries)) {
    const existing = plugins[pluginId];
    plugins[pluginId] = existing ? mergePluginEntries(existing, entry) : entry;
  }
  return {
    ...lock,
    plugins,
  };
}

/**
 * Verify each tracked path exists and hashes match.
 *
 * @param {GatewayLock} lock - Lock to reconcile.
 * @param {{
 *   exists?: (path: string) => Promise<boolean>,
 *   hash?: (path: string) => Promise<string>,
 * }} [environment] - Injectable filesystem.
 * @returns {Promise<ReconcileResult>} Present, missing, and modified plugin/agent pairs.
 */
export async function reconcileLock(lock, environment = {}) {
  const exists = environment.exists ?? pathExists;
  const hash = environment.hash ?? hashFile;
  /** @type {ReconcileResult} */
  const result = { missing: [], modified: [], present: [] };
  for (const [pluginId, entry] of Object.entries(lock.plugins)) {
    for (const [agent, install] of Object.entries(entry.agents)) {
      const item = { agent, pluginId };
      const status = await reconcileAgentInstall(install, exists, hash);
      result[status].push(item);
    }
  }
  return result;
}

/**
 * Remove lock entries whose plugin is absent from every tracked agent.
 *
 * @param {GatewayLock} lock - Existing lockfile.
 * @param {(pluginId: string, entry: PluginLockEntry, scope: "global" | "project") => Promise<boolean>} [isInstalled] - Disk presence check.
 * @returns {Promise<{lock: GatewayLock, pruned: string[]}>} Updated lockfile and removed plugin ids.
 */
export async function pruneMissingLockEntries(lock, isInstalled = isPluginInstalled) {
  const plugins = {};
  const pruned = [];
  for (const [pluginId, entry] of Object.entries(lock.plugins)) {
    if (await isInstalled(pluginId, entry, lock.scope)) {
      plugins[pluginId] = entry;
    } else {
      pruned.push(pluginId);
    }
  }
  return {
    lock: {
      ...lock,
      plugins,
    },
    pruned,
  };
}

/**
 * Check whether a plugin still has at least one healthy agent install.
 *
 * Unknown agent layouts are retained because their absence cannot be established
 * safely from the gateway.
 *
 * @param {string} pluginId - Plugin id.
 * @param {PluginLockEntry} entry - Lockfile entry.
 * @param {"global" | "project"} _scope - Installation scope.
 * @param {{
 *   exists?: (path: string) => Promise<boolean>,
 *   hash?: (path: string) => Promise<string>,
 * }} [environment] - Injectable file environment.
 * @returns {Promise<boolean>} Whether the plugin remains installed on disk.
 */
export async function isPluginInstalled(pluginId, entry, _scope, environment = {}) {
  const agentNames = Object.keys(entry.agents);
  if (agentNames.some((agent) => !AGENT_SKILL_PATHS[agent])) {
    return true;
  }
  const reconciliation = await reconcileLock(
    {
      gatewayVersion: "",
      plugins: { [pluginId]: entry },
      scope: "project",
      version: LOCKFILE_VERSION,
    },
    environment,
  );
  return reconciliation.present.length + reconciliation.modified.length > 0;
}

/**
 * Skill-directory roots keyed by upstream agent id.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {string} agent - Agent identifier.
 * @param {{cwd?: string, home?: string}} [environment] - Injectable path environment.
 * @returns {string} Absolute agent skills directory.
 */
export function agentSkillsRoot(scope, agent, environment = {}) {
  const relative = AGENT_SKILL_PATHS[agent];
  if (!relative) {
    throw new Error(`Unknown agent layout: ${agent}`);
  }
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  return join(root, relative);
}

/**
 * Sha256 a file's contents as hex.
 *
 * @param {string} path - File path.
 * @returns {Promise<string>} Hex digest.
 */
export async function hashFile(path) {
  const body = await readFile(path);
  return createHash("sha256").update(body).digest("hex");
}

/**
 * Re-hash every tracked file on a plugin entry, recording an empty digest when a path is absent.
 *
 * @param {PluginLockEntry} entry - Plugin lock entry.
 * @param {(path: string) => Promise<string>} [hash] - Injectable hasher.
 * @returns {Promise<PluginLockEntry>} Entry with refreshed file digests.
 */
export async function refreshPluginFileHashes(entry, hash = hashFile) {
  const agents = {};
  for (const [agent, install] of Object.entries(entry.agents)) {
    const files = {};
    for (const relative of Object.keys(install.files)) {
      files[relative] = await hashTrackedPath(join(install.root, relative), hash);
    }
    agents[agent] = { ...install, files };
  }
  return { ...entry, agents };
}

/**
 * Agent ids tracked on a plugin lock entry.
 *
 * @param {PluginLockEntry} entry - Plugin lock entry.
 * @returns {string[]} Sorted agent ids.
 */
export function pluginAgentNames(entry) {
  return Object.keys(entry.agents).sort();
}

/**
 * Exploded skill directory names tracked on a plugin lock entry.
 *
 * @param {PluginLockEntry} entry - Plugin lock entry.
 * @returns {string[]} Sorted skill directory names.
 */
export function pluginSkillNames(entry) {
  const names = new Set();
  for (const install of Object.values(entry.agents)) {
    for (const relative of Object.keys(install.files)) {
      const name = relative.split("/")[0];
      if (name) {
        names.add(name);
      }
    }
  }
  return [...names].sort();
}

/**
 * @typedef {PluginLockEntry} LockEntry
 */

/**
 * Create an empty version-two lockfile.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @returns {GatewayLock} Empty lockfile.
 */
function createLockfile(scope) {
  return {
    gatewayVersion: getPackageVersion(),
    plugins: {},
    scope,
    version: LOCKFILE_VERSION,
  };
}

/**
 * Whether a parsed document is a well-formed version-two lock for ``scope``.
 *
 * @param {object} lock - Parsed JSON.
 * @param {"global" | "project"} scope - Expected scope.
 * @returns {boolean} Whether the lock can be consumed as v2.
 */
function isValidV2Lock(lock, scope) {
  if (
    lock.scope !== scope ||
    typeof lock.plugins !== "object" ||
    lock.plugins === null ||
    Array.isArray(lock.plugins)
  ) {
    return false;
  }
  for (const entry of Object.values(lock.plugins)) {
    if (!isValidPluginEntry(entry)) {
      return false;
    }
  }
  return true;
}

/**
 * Whether a plugin record has the v2 agent map, projector, and string provenance.
 *
 * @param {unknown} entry - Candidate plugin entry.
 * @returns {boolean} Whether the entry is structurally valid.
 */
function isValidPluginEntry(entry) {
  if (typeof entry !== "object" || entry === null) {
    return false;
  }
  if (entry.projector !== PROJECTOR_EXPLODE && entry.projector !== PROJECTOR_NATIVE) {
    return false;
  }
  if (
    typeof entry.vendor !== "string" ||
    typeof entry.repo !== "string" ||
    typeof entry.sha !== "string" ||
    typeof entry.version !== "string" ||
    typeof entry.installedAt !== "string"
  ) {
    return false;
  }
  if (typeof entry.agents !== "object" || entry.agents === null || Array.isArray(entry.agents)) {
    return false;
  }
  return Object.values(entry.agents).every(
    (install) =>
      typeof install === "object" &&
      install !== null &&
      typeof install.root === "string" &&
      typeof install.files === "object" &&
      install.files !== null &&
      !Array.isArray(install.files) &&
      Object.values(install.files).every((digest) => typeof digest === "string"),
  );
}

/**
 * Merge two plugin entries, unioning per-agent file maps.
 *
 * @param {PluginLockEntry} existing - Previously tracked plugin.
 * @param {PluginLockEntry} incoming - Newly installed plugin.
 * @returns {PluginLockEntry} Combined entry.
 */
function mergePluginEntries(existing, incoming) {
  const agents = { ...existing.agents };
  for (const [agent, install] of Object.entries(incoming.agents)) {
    const previous = agents[agent];
    agents[agent] = previous
      ? {
          root: install.root,
          files: { ...previous.files, ...install.files },
        }
      : install;
  }
  return {
    ...incoming,
    agents,
  };
}

/**
 * Classify one agent's tracked files as present, missing, or modified.
 *
 * @param {AgentInstall} install - Tracked agent files.
 * @param {(path: string) => Promise<boolean>} exists - Existence check.
 * @param {(path: string) => Promise<string>} hash - Content hash.
 * @returns {Promise<"present" | "missing" | "modified">} Classification.
 */
async function reconcileAgentInstall(install, exists, hash) {
  const paths = Object.entries(install.files);
  if (paths.length === 0) {
    return (await exists(install.root)) ? "present" : "missing";
  }
  let sawMissing = false;
  let sawModified = false;
  for (const [relative, expected] of paths) {
    const absolute = join(install.root, relative);
    if (!(await exists(absolute))) {
      sawMissing = true;
      continue;
    }
    if ((await hash(absolute)) !== expected) {
      sawModified = true;
    }
  }
  if (sawMissing) {
    return "missing";
  }
  if (sawModified) {
    return "modified";
  }
  return "present";
}

/**
 * Test whether a path exists.
 *
 * @param {string} path - File path.
 * @returns {Promise<boolean>} Whether the path exists.
 */
async function pathExists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Hash a path, using an empty digest when the file is absent.
 *
 * @param {string} path - Absolute file path.
 * @param {(path: string) => Promise<string>} hash - Hasher.
 * @returns {Promise<string>} Hex digest, or empty string when missing.
 */
async function hashTrackedPath(path, hash) {
  try {
    return await hash(path);
  } catch {
    return "";
  }
}
