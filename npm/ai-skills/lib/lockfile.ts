import { createHash } from "node:crypto";
import { access, lstat, readdir, readFile, readlink } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import { hostSkillPaths } from "./adapters/hosts.ts";
import { getPackageVersion } from "./package-version.ts";

export const LOCKFILE_VERSION = 2;

export const PROJECTOR_EXPLODE = "explode";
export const PROJECTOR_NATIVE = "native";

/** Kebab-case plugin ids; rejects path segments that could escape a dest root. */
export const PLUGIN_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Whether a lock key is a kebab-case plugin id.
 */
export function isSafePluginId(pluginId: unknown): boolean {
  return typeof pluginId === "string" && PLUGIN_ID_RE.test(pluginId);
}

/**
 * Exploded skills directory per host, read from the adapter host table.
 */
export const AGENT_SKILL_PATHS: Record<string, string> = hostSkillPaths();

/**
 * Resolve the gateway lockfile path for an installation scope.
 */
export function getLockfilePath(
  scope: "global" | "project",
  environment: { cwd?: string; home?: string } = {},
): string {
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
 * Lock v2 is read-only input now: installs commit machine-local receipts
 * (`lib/journal/receipts.ts`) and never write this file; #586 converts it.
 *
 * @throws {Error} When a present v2 lockfile is malformed or mismatched to its scope.
 */
export async function readLockfile(
  scope: "global" | "project",
  environment: LockEnvironment = {},
): Promise<GatewayLock> {
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
 * Merge installed plugins into a lockfile without discarding tracked agents.
 */
export function mergeLockEntries(
  lock: GatewayLock,
  entries: Record<string, PluginLockEntry>,
): GatewayLock {
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
 */
export async function reconcileLock(
  lock: GatewayLock,
  environment: LockEnvironment = {},
): Promise<ReconcileResult> {
  const exists = environment.exists ?? pathExists;
  const hash = environment.hash ?? hashFile;

  const result: ReconcileResult = { missing: [], modified: [], present: [] };
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
 */
export async function pruneMissingLockEntries(
  lock: GatewayLock,
  isInstalled: (
    pluginId: string,
    entry: PluginLockEntry,
    scope: "global" | "project",
  ) => Promise<boolean> = isPluginInstalled,
): Promise<{ lock: GatewayLock; pruned: string[] }> {
  const plugins: Record<string, PluginLockEntry> = {};
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
 */
export async function isPluginInstalled(
  pluginId: string,
  entry: PluginLockEntry,
  _scope: "global" | "project",
  environment: LockEnvironment = {},
): Promise<boolean> {
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
 */
export function agentSkillsRoot(
  scope: "global" | "project",
  agent: string,
  environment: { cwd?: string; home?: string } = {},
): string {
  const relative = AGENT_SKILL_PATHS[agent];
  if (!relative) {
    throw new Error(`Unknown agent layout: ${agent}`);
  }
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  return join(root, relative);
}

/**
 * Explode-owned skill names tracked by lock plugins other than ``pluginId``.
 *
 * Native installs namespace per plugin and do not consume the explode store.
 */
export function otherPluginSkillNames(
  lock: GatewayLock | { plugins?: Record<string, PluginLockEntry> },
  pluginId: string,
): Set<string> {
  const names = new Set<string>();
  for (const [id, entry] of Object.entries(lock.plugins ?? {})) {
    if (id === pluginId) {
      continue;
    }
    for (const [agent, install] of Object.entries(entry.agents ?? {})) {
      if (agentProjector(entry, agent) !== PROJECTOR_EXPLODE) {
        continue;
      }
      for (const name of skillNamesFromFiles(install.files)) {
        names.add(name);
      }
    }
  }
  return names;
}

/**
 * Exploded dest roots for known agent layouts, plus any lock-recorded dests.
 */
export function allAgentSkillRoots(
  scope: "global" | "project",
  environment: { cwd?: string; home?: string } = {},
  lock?: GatewayLock | { plugins?: Record<string, PluginLockEntry> },
): string[] {
  const roots = Object.keys(AGENT_SKILL_PATHS).map((agent) =>
    agentSkillsRoot(scope, agent, environment),
  );
  if (!lock?.plugins) {
    return roots;
  }
  const seen = new Set(roots.map((root) => resolve(root)));
  for (const entry of Object.values(lock.plugins)) {
    for (const install of Object.values(entry.agents ?? {})) {
      if (typeof install.root !== "string" || install.root.startsWith("cli:")) {
        continue;
      }
      const resolved = resolve(install.root);
      if (!seen.has(resolved)) {
        seen.add(resolved);
        roots.push(install.root);
      }
    }
  }
  return roots;
}

/**
 * Sha256 a file's contents as hex.
 */
export async function hashFile(path: string): Promise<string> {
  const body = await readFile(path);
  return createHash("sha256").update(body).digest("hex");
}

/**
 * Re-hash every tracked file on a plugin entry, recording an empty digest when a path is absent.
 */
export async function refreshPluginFileHashes(
  entry: PluginLockEntry,
  hash: (path: string) => Promise<string> = hashFile,
): Promise<PluginLockEntry> {
  const agents: Record<string, AgentInstall> = {};
  for (const [agent, install] of Object.entries(entry.agents)) {
    const files: Record<string, string> = {};
    for (const relative of Object.keys(install.files)) {
      files[relative] = await hashTrackedPath(join(install.root, relative), hash);
    }
    agents[agent] = { ...install, files };
  }
  return { ...entry, agents };
}

/**
 * Agent ids tracked on a plugin lock entry.
 */
export function pluginAgentNames(entry: PluginLockEntry): string[] {
  return Object.keys(entry.agents).sort();
}

/**
 * Skill directory names tracked on a plugin lock entry.
 */
export function pluginSkillNames(entry: PluginLockEntry): string[] {
  if (Array.isArray(entry.skills) && entry.skills.every((name) => typeof name === "string")) {
    return [...new Set(entry.skills)].sort();
  }
  const names = new Set<string>();
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
 * Exploded installs use ``<skill>/SKILL.md``. Native plugin trees use
 * ``skills/<skill>/...`` plus ``.claude-plugin/plugin.json`` (ignored).
 */
export function skillNamesFromFiles(files: Record<string, string>): Set<string> {
  const names = new Set<string>();
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
 */
export function agentProjector(entry: PluginLockEntry, agent: string): "native" | "explode" {
  return projectorOf(entry.agents[agent], entry.projector);
}

/**
 * Whether a native install is CLI-owned (host plugin, no hashed tree).
 *
 * CLI-delivered native installs record ``root: "cli:<agent>"``. Tree-drop
 * native installs hash ``plugin.json`` and copied skill files under a
 * filesystem root; an empty file map there is missing, not CLI-owned.
 */
export function isCliOwnedNativeInstall(
  install: AgentInstall,
  pluginProjector: "native" | "explode" = PROJECTOR_EXPLODE,
): boolean {
  if (projectorOf(install, pluginProjector) !== PROJECTOR_NATIVE) {
    return false;
  }
  return typeof install.root === "string" && install.root.startsWith("cli:");
}

/**
 * Sha256 every regular file and in-tree symlink under ``root``, keyed by
 * POSIX-relative paths. Symlink digests encode the link target so a dest
 * missing the symlink does not compare equal.
 */
export async function hashTree(
  root: string,
  hash: (path: string) => Promise<string> = hashFile,
  fs: TreeReader = nodeTreeReader,
): Promise<Record<string, string>> {
  const files: Record<string, string> = {};
  await walkHashTree(root, "", files, hash, fs);
  return files;
}

/** Directory reads ``hashTree`` needs; adapters pass a read-only view. */
export interface TreeReader {
  readdir(
    path: string,
  ): Promise<
    Array<{ name: string; isDirectory(): boolean; isFile(): boolean; isSymbolicLink(): boolean }>
  >;
  readlink(path: string): Promise<string>;
}

const nodeTreeReader: TreeReader = {
  readdir: (path) => readdir(path, { withFileTypes: true }),
  readlink: (path) => readlink(path),
};

/**
 * Create an empty version-two lockfile.
 */
function createLockfile(scope: "global" | "project"): GatewayLock {
  return {
    gatewayVersion: getPackageVersion(),
    plugins: {},
    scope,
    version: LOCKFILE_VERSION,
  };
}

/**
 * Whether a parsed document is a well-formed version-two lock for ``scope``.
 */
function isValidV2Lock(lock: Record<string, unknown>, scope: "global" | "project"): boolean {
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
 * Whether every entry of a plugin map is a well-formed record under a safe id.
 */
export function arePluginEntriesValid(plugins: Record<string, unknown>): boolean {
  return Object.entries(plugins).every(
    ([pluginId, entry]) => isSafePluginId(pluginId) && isValidPluginEntry(entry),
  );
}

/**
 * Whether a plugin record has the v2 agent map, projector, and string provenance.
 */
function isValidPluginEntry(entry: unknown): boolean {
  if (typeof entry !== "object" || entry === null) {
    return false;
  }
  const record = entry as Record<string, unknown>;
  if (record.projector !== PROJECTOR_EXPLODE && record.projector !== PROJECTOR_NATIVE) {
    return false;
  }
  if (
    typeof record.vendor !== "string" ||
    typeof record.repo !== "string" ||
    typeof record.sha !== "string" ||
    typeof record.version !== "string" ||
    typeof record.installedAt !== "string"
  ) {
    return false;
  }
  if (typeof record.agents !== "object" || record.agents === null || Array.isArray(record.agents)) {
    return false;
  }
  return Object.values(record.agents).every((install) => isValidAgentInstall(install));
}

/**
 * Whether a per-agent install record is structurally valid.
 */
function isValidAgentInstall(install: unknown): boolean {
  if (typeof install !== "object" || install === null) {
    return false;
  }
  const record = install as Record<string, unknown>;
  if (typeof record.root !== "string") {
    return false;
  }
  if (
    typeof record.files !== "object" ||
    record.files === null ||
    Array.isArray(record.files) ||
    !Object.values(record.files).every((digest) => typeof digest === "string")
  ) {
    return false;
  }
  if (
    record.projector != null &&
    record.projector !== PROJECTOR_EXPLODE &&
    record.projector !== PROJECTOR_NATIVE
  ) {
    return false;
  }
  return true;
}

/**
 * Merge two plugin entries, unioning per-agent file maps.
 */
function mergePluginEntries(existing: PluginLockEntry, incoming: PluginLockEntry): PluginLockEntry {
  const agents: Record<string, AgentInstall> = {};
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
 */
async function reconcileAgentInstall(
  install: AgentInstall,
  exists: (path: string) => Promise<boolean>,
  hash: (path: string) => Promise<string>,
  pluginProjector: "native" | "explode" = PROJECTOR_EXPLODE,
): Promise<"present" | "missing" | "modified"> {
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
 */
async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Hash a path, using an empty digest when the file is absent.
 */
async function hashTrackedPath(
  path: string,
  hash: (path: string) => Promise<string>,
): Promise<string> {
  try {
    return await hashLockEntryPath(path, hash);
  } catch {
    return "";
  }
}

/**
 * Hash a path the same way ``hashTree`` records it: symlink targets as
 * ``sha256("symlink:" + target)``, regular files via ``hash``.
 */
export async function hashLockEntryPath(
  path: string,
  hash: (path: string) => Promise<string> = hashFile,
): Promise<string> {
  const info = await lstat(path);
  if (info.isSymbolicLink()) {
    const target = await readlink(path);
    return createHash("sha256").update(`symlink:${target}`).digest("hex");
  }
  return hash(path);
}

/**
 * Stamp a missing per-agent projector from the plugin-level value.
 */
function stampAgentProjector(
  install: AgentInstall,
  pluginProjector: "native" | "explode",
): AgentInstall {
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
 */
function pluginProjectorFromAgents(
  agents: Record<string, AgentInstall>,
  fallback: "native" | "explode",
): "native" | "explode" {
  const values = Object.values(agents).map((install) => projectorOf(install, fallback));
  if (values.length === 0) {
    return fallback === PROJECTOR_NATIVE ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
  }
  return values.every((value) => value === PROJECTOR_NATIVE) ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
}

/**
 * Merge two per-agent installs, unioning file maps and keeping a projector.
 */
function mergeAgentInstalls(previous: AgentInstall, incoming: AgentInstall): AgentInstall {
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

function projectorOf(
  install: AgentInstall | undefined,
  pluginProjector: "native" | "explode",
): "native" | "explode" {
  if (install?.projector === PROJECTOR_NATIVE || install?.projector === PROJECTOR_EXPLODE) {
    return install.projector;
  }
  return pluginProjector === PROJECTOR_NATIVE ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
}

async function walkHashTree(
  dir: string,
  prefix: string,
  files: Record<string, string>,
  hash: (path: string) => Promise<string>,
  fs: TreeReader,
): Promise<void> {
  let entries;
  try {
    entries = await fs.readdir(dir);
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
      await walkHashTree(absolute, relative, files, hash, fs);
    } else if (entry.isSymbolicLink()) {
      const target = await fs.readlink(absolute);
      files[relative] = createHash("sha256").update(`symlink:${target}`).digest("hex");
    } else if (entry.isFile()) {
      files[relative] = await hash(absolute);
    }
  }
}

/** Per-agent tracked paths and sha256 hashes, relative to ``root``.
 * ``projector`` overrides the plugin-level projector for this agent. */
export interface AgentInstall {
  files: Record<string, string>;
  projector?: "native" | "explode";
  root: string;
}

export interface PluginLockEntry {
  agents: Record<string, AgentInstall>;
  installedAt: string;
  projector: "native" | "explode";
  repo: string;
  sha: string;
  skills?: string[];
  vendor: string;
  version: string;
}

export interface GatewayLock {
  gatewayVersion: string;
  plugins: Record<string, PluginLockEntry>;
  scope: "global" | "project";
  version: number;
}

export interface ReconcileItem {
  agent: string;
  pluginId: string;
}

export interface ReconcileResult {
  missing: ReconcileItem[];
  modified: ReconcileItem[];
  present: ReconcileItem[];
}

export type LockEntry = PluginLockEntry;

export interface LockEnvironment {
  cwd?: string;
  home?: string;
  read?: (path: string, encoding: "utf8") => Promise<string>;
  exists?: (path: string) => Promise<boolean>;
  hash?: (path: string) => Promise<string>;
}
