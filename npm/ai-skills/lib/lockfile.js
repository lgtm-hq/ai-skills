import { createHash } from "node:crypto";
import { access, mkdir, readdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { getPackageVersion } from "./package-version.js";

export const LOCKFILE_VERSION = 2;

export const PROJECTOR_EXPLODE = "explode";
export const PROJECTOR_NATIVE = "native";

/** Kebab-case plugin ids; rejects path segments that could escape a dest root. */
export const PLUGIN_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Whether a lock key is a kebab-case plugin id.
 *
 * @param {unknown} pluginId - Candidate plugin id.
 * @returns {boolean} True when the id is a safe folder name.
 */
export function isSafePluginId(pluginId) {
  return typeof pluginId === "string" && PLUGIN_ID_RE.test(pluginId);
}

export const AGENT_SKILL_PATHS = {
  "claude-code": ".claude/skills",
  copilot: ".copilot/skills",
  cursor: ".cursor/skills",
  codex: ".codex/skills",
};

/**
 * @typedef {{
 *   files: Record<string, string>,
 *   projector?: "native" | "explode",
 *   root: string,
 * }} AgentInstall
 * Per-agent tracked paths and sha256 hashes, relative to ``root``.
 * ``projector`` overrides the plugin-level projector for this agent.
 */

/**
 * @typedef {{
 *   agents: Record<string, AgentInstall>,
 *   installedAt: string,
 *   projector: "native" | "explode",
 *   repo: string,
 *   sha: string,
 *   skills?: string[],
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
      const status = await reconcileAgentInstall(install, exists, hash, entry.projector);
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
 * Skill directory names tracked on a plugin lock entry.
 *
 * @param {PluginLockEntry} entry - Plugin lock entry.
 * @returns {string[]} Sorted skill directory names.
 */
export function pluginSkillNames(entry) {
  if (Array.isArray(entry.skills) && entry.skills.every((name) => typeof name === "string")) {
    return [...new Set(entry.skills)].sort();
  }
  const names = new Set();
  for (const install of Object.values(entry.agents)) {
    for (const name of skillNamesFromFiles(install.files)) {
      names.add(name);
    }
  }
  return [...names].sort();
}

/**
 * Skill directory names implied by a tracked file map.
 *
 * Exploded installs use ``<skill>/SKILL.md``. Cursor native trees use
 * ``skills/<skill>/...`` plus ``.claude-plugin/plugin.json`` (ignored).
 *
 * @param {Record<string, string>} files - Relative path to digest.
 * @returns {Set<string>} Skill directory names.
 */
export function skillNamesFromFiles(files) {
  const names = new Set();
  for (const relative of Object.keys(files)) {
    const parts = relative.split("/");
    if (parts[0] === ".claude-plugin") {
      continue;
    }
    if (parts[0] === "skills" && parts[1]) {
      names.add(parts[1]);
      continue;
    }
    if (parts[0]) {
      names.add(parts[0]);
    }
  }
  return names;
}

/**
 * Projector recorded for one agent, falling back to the plugin-level value.
 *
 * @param {PluginLockEntry} entry - Plugin lock entry.
 * @param {string} agent - Agent identifier.
 * @returns {"native" | "explode"} Effective projector.
 */
export function agentProjector(entry, agent) {
  return projectorOf(entry.agents[agent], entry.projector);
}

/**
 * Whether a native install is CLI-owned (host plugin, no hashed tree).
 *
 * Claude Code and Copilot native installs record ``root: "cli:<agent>"``.
 * Cursor native trees hash ``plugin.json`` and copied skill files under a
 * filesystem root; an empty file map there is missing, not CLI-owned.
 *
 * @param {AgentInstall} install - Per-agent lock record.
 * @param {"native" | "explode"} [pluginProjector] - Plugin-level projector.
 * @returns {boolean} True when disk hashes are not the source of truth.
 */
export function isCliOwnedNativeInstall(install, pluginProjector = PROJECTOR_EXPLODE) {
  if (projectorOf(install, pluginProjector) !== PROJECTOR_NATIVE) {
    return false;
  }
  return typeof install.root === "string" && install.root.startsWith("cli:");
}

/**
 * Sha256 every regular file under ``root``, keyed by POSIX-relative paths.
 *
 * @param {string} root - Directory to walk.
 * @param {(path: string) => Promise<string>} [hash] - Injectable hasher.
 * @returns {Promise<Record<string, string>>} Relative path to hex digest.
 */
export async function hashTree(root, hash = hashFile) {
  const files = {};
  await walkHashTree(root, "", files, hash);
  return files;
}

/**
 * Keep only gateway-owned Cursor plugin paths so untracked dest files stay
 * out of the lock (and therefore out of hash-verified remove).
 *
 * @param {Record<string, string>} files - Relative path to digest.
 * @param {string[]} skillNames - Catalog skill directory names.
 * @returns {Record<string, string>} Manifest plus `skills/<name>/` paths.
 */
export function ownedCursorTreeFiles(files, skillNames) {
  const names = new Set(skillNames);
  const owned = {};
  for (const [relative, digest] of Object.entries(files)) {
    if (relative === ".claude-plugin/plugin.json") {
      owned[relative] = digest;
      continue;
    }
    const match = /^skills\/([^/]+)\//.exec(relative);
    if (match && names.has(match[1])) {
      owned[relative] = digest;
    }
  }
  return owned;
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
  for (const [pluginId, entry] of Object.entries(lock.plugins)) {
    if (!isSafePluginId(pluginId) || !isValidPluginEntry(entry)) {
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
  return Object.values(entry.agents).every((install) => isValidAgentInstall(install));
}

/**
 * Whether a per-agent install record is structurally valid.
 *
 * @param {unknown} install - Candidate agent install.
 * @returns {boolean} Whether the install can be consumed.
 */
function isValidAgentInstall(install) {
  if (typeof install !== "object" || install === null) {
    return false;
  }
  if (typeof install.root !== "string") {
    return false;
  }
  if (
    typeof install.files !== "object" ||
    install.files === null ||
    Array.isArray(install.files) ||
    !Object.values(install.files).every((digest) => typeof digest === "string")
  ) {
    return false;
  }
  if (
    install.projector != null &&
    install.projector !== PROJECTOR_EXPLODE &&
    install.projector !== PROJECTOR_NATIVE
  ) {
    return false;
  }
  return true;
}

/**
 * Merge two plugin entries, unioning per-agent file maps.
 *
 * @param {PluginLockEntry} existing - Previously tracked plugin.
 * @param {PluginLockEntry} incoming - Newly installed plugin.
 * @returns {PluginLockEntry} Combined entry.
 */
function mergePluginEntries(existing, incoming) {
  /** @type {Record<string, AgentInstall>} */
  const agents = {};
  for (const [agent, install] of Object.entries(existing.agents)) {
    agents[agent] = stampAgentProjector(install, existing.projector);
  }
  for (const [agent, install] of Object.entries(incoming.agents)) {
    const previous = agents[agent];
    const stamped = stampAgentProjector(install, incoming.projector);
    agents[agent] = previous ? mergeAgentInstalls(previous, stamped) : stamped;
  }
  return {
    ...incoming,
    agents,
    projector: pluginProjectorFromAgents(agents, existing.projector),
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
async function reconcileAgentInstall(install, exists, hash, pluginProjector = PROJECTOR_EXPLODE) {
  if (isCliOwnedNativeInstall(install, pluginProjector)) {
    return "present";
  }
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

/**
 * Stamp a missing per-agent projector from the plugin-level value.
 *
 * @param {AgentInstall} install - Per-agent lock record.
 * @param {"native" | "explode"} pluginProjector - Plugin-level projector.
 * @returns {AgentInstall} Install with an explicit projector when the plugin had one.
 */
function stampAgentProjector(install, pluginProjector) {
  if (install.projector === PROJECTOR_NATIVE || install.projector === PROJECTOR_EXPLODE) {
    return install;
  }
  if (pluginProjector === PROJECTOR_NATIVE || pluginProjector === PROJECTOR_EXPLODE) {
    return { ...install, projector: pluginProjector };
  }
  return install;
}

/**
 * Plugin-level projector after a mixed merge: native only when every agent is native.
 *
 * @param {Record<string, AgentInstall>} agents - Merged agent map.
 * @param {"native" | "explode"} fallback - Existing plugin-level projector.
 * @returns {"native" | "explode"} Plugin-level projector.
 */
function pluginProjectorFromAgents(agents, fallback) {
  const values = Object.values(agents).map((install) => projectorOf(install, fallback));
  if (values.length === 0) {
    return fallback === PROJECTOR_NATIVE ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
  }
  return values.every((value) => value === PROJECTOR_NATIVE) ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
}

/**
 * Merge two per-agent installs, unioning file maps and keeping a projector.
 *
 * @param {AgentInstall} previous - Previously tracked agent install.
 * @param {AgentInstall} incoming - Newly installed agent install.
 * @returns {AgentInstall} Combined install.
 */
function mergeAgentInstalls(previous, incoming) {
  const projector = incoming.projector ?? previous.projector;
  const replaceFiles =
    previous.root !== incoming.root ||
    (previous.projector !== undefined &&
      incoming.projector !== undefined &&
      previous.projector !== incoming.projector);
  return {
    files: replaceFiles ? { ...incoming.files } : { ...previous.files, ...incoming.files },
    root: incoming.root,
    ...(projector === PROJECTOR_NATIVE || projector === PROJECTOR_EXPLODE ? { projector } : {}),
  };
}

/**
 * @param {AgentInstall | undefined} install - Per-agent lock record.
 * @param {"native" | "explode"} pluginProjector - Plugin-level projector.
 * @returns {"native" | "explode"} Effective projector.
 */
function projectorOf(install, pluginProjector) {
  if (install?.projector === PROJECTOR_NATIVE || install?.projector === PROJECTOR_EXPLODE) {
    return install.projector;
  }
  return pluginProjector === PROJECTOR_NATIVE ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
}

/**
 * @param {string} dir - Directory to walk.
 * @param {string} prefix - Relative prefix from the tree root.
 * @param {Record<string, string>} files - Accumulator.
 * @param {(path: string) => Promise<string>} hash - Hasher.
 * @returns {Promise<void>} Resolves when this directory has been walked.
 */
async function walkHashTree(dir, prefix, files, hash) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return;
    }
    throw error;
  }
  for (const entry of entries) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolute = join(dir, entry.name);
    if (entry.isDirectory()) {
      await walkHashTree(absolute, relative, files, hash);
    } else if (entry.isFile()) {
      files[relative] = await hash(absolute);
    }
  }
}
