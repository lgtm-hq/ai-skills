import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline/promises";

import { loadBundles } from "./catalog.js";
import { listSkills } from "./gateway-commands.js";
import {
  AGENT_SKILL_PATHS,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  agentProjector,
  hashFile,
  pluginSkillNames,
  readLockfile,
  skillNamesFromFiles,
} from "./lockfile.js";
import { resolveScope } from "./options.js";
import { CLI_BY_AGENT, spawnExec, uninstallCliPlugin } from "./projectors/native-cli.js";
import { NATIVE_PROJECTOR_AGENTS } from "./projectors/defaults.js";
import { removeExplodedFiles } from "./projectors/explode.js";
import { cursorPluginsRoot, removeCursorPlugin } from "./projectors/native-cursor.js";

export const DOCTOR_CACHE_SCHEMA = 1;

export const DOCTOR_CACHE_RELATIVE = join(".ai-skills", "doctor.json");

/**
 * @typedef {{capability: "native" | "explode", source: "probe" | "prompt", version: string}} HostCapability
 * @typedef {{hosts: Record<string, HostCapability>, schemaVersion: number}} DoctorCache
 */

/**
 * Absolute doctor cache path.
 *
 * @param {string} [home] - Home directory.
 * @returns {string} ``~/.ai-skills/doctor.json``.
 */
export function doctorCachePath(home = homedir()) {
  return join(home, DOCTOR_CACHE_RELATIVE);
}

/**
 * Load the host-capability cache, or an empty cache when missing/malformed.
 *
 * @param {{home?: string, read?: typeof readFile}} [environment] - Injectable fs.
 * @returns {Promise<DoctorCache>} Parsed cache.
 */
export async function readDoctorCache(environment = {}) {
  const read = environment.read ?? readFile;
  const path = doctorCachePath(environment.home ?? homedir());
  try {
    const parsed = JSON.parse(await read(path, "utf8"));
    if (parsed?.schemaVersion !== DOCTOR_CACHE_SCHEMA || typeof parsed.hosts !== "object") {
      return emptyDoctorCache();
    }
    return { hosts: parsed.hosts ?? {}, schemaVersion: DOCTOR_CACHE_SCHEMA };
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return emptyDoctorCache();
    }
    return emptyDoctorCache();
  }
}

/**
 * Persist the host-capability cache.
 *
 * @param {DoctorCache} cache - Cache to write.
 * @param {{home?: string, mkdir?: typeof mkdir, write?: typeof writeFile}} [environment] - Injectable fs.
 * @returns {Promise<void>} Resolves when the file is written.
 */
export async function writeDoctorCache(cache, environment = {}) {
  const path = doctorCachePath(environment.home ?? homedir());
  const makeDir = environment.mkdir ?? mkdir;
  const write = environment.write ?? writeFile;
  const move = environment.rename ?? rename;
  await makeDir(dirname(path), { recursive: true });
  const staging = `${path}.${process.pid}.tmp`;
  await write(staging, `${JSON.stringify(cache, null, 2)}\n`);
  await move(staging, path);
}

/**
 * Probe one host's plugin capability and current version.
 *
 * Claude Code / Copilot: the host CLI responds to ``plugin``. Cursor: a
 * ``plugins/local`` directory exists. Codex is always explode.
 *
 * @param {string} agent - Host identifier.
 * @param {{
 *   access?: (path: string) => Promise<boolean>,
 *   cwd?: string,
 *   exec?: typeof spawnExec,
 *   home?: string,
 *   scope?: "global" | "project",
 *   version?: string,
 * }} [environment] - Injectable probe environment.
 * @returns {Promise<{capability: "native" | "explode" | "ambiguous", version: string}>} Probe result.
 */
export async function probeHost(agent, environment = {}) {
  if (!NATIVE_PROJECTOR_AGENTS.has(agent)) {
    return { capability: PROJECTOR_EXPLODE, version: environment.version ?? "n/a" };
  }
  const version = environment.version ?? (await hostVersion(agent, environment));
  if (agent === "cursor") {
    const capable = await cursorPluginsLocalExists(environment);
    return { capability: capable ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE, version };
  }
  const cli = CLI_BY_AGENT[agent];
  const exec = environment.exec ?? spawnExec;
  try {
    const result = await exec(cli, ["plugin"]);
    return { capability: classifyCliPluginProbe(result), version };
  } catch (error) {
    if (isMissingExecutable(error)) {
      return { capability: PROJECTOR_EXPLODE, version };
    }
    return { capability: "ambiguous", version };
  }
}

/**
 * Return a cached capability, probing and persisting on miss or version change.
 *
 * Ambiguous probes ask once when a prompt is provided; unattended callers
 * must pass ``yes: true`` and get a hard error instead.
 *
 * @param {string} agent - Host identifier.
 * @param {{
 *   access?: (path: string) => Promise<boolean>,
 *   cache?: DoctorCache,
 *   cwd?: string,
 *   exec?: typeof spawnExec,
 *   home?: string,
 *   prompt?: (agent: string) => Promise<"native" | "explode">,
 *   scope?: "global" | "project",
 *   yes?: boolean,
 * }} [environment] - Injectable environment.
 * @returns {Promise<HostCapability>} Cached or freshly probed capability.
 */
export async function ensureHostCapability(agent, environment = {}) {
  const cache = environment.cache ?? (await readDoctorCache(environment));
  const version = await hostVersion(agent, environment);
  const cached = cache.hosts[agent];
  if (
    cached &&
    cached.version === version &&
    (cached.capability === PROJECTOR_NATIVE || cached.capability === PROJECTOR_EXPLODE)
  ) {
    return cached;
  }
  const probed = await probeHost(agent, { ...environment, version });
  if (probed.capability === PROJECTOR_NATIVE || probed.capability === PROJECTOR_EXPLODE) {
    const entry = { capability: probed.capability, source: "probe", version };
    cache.hosts[agent] = entry;
    await persistDoctorCache(cache, environment);
    return entry;
  }
  if (environment.yes) {
    throw new Error(
      `Capability for host "${agent}" is ambiguous; run sk doctor or pass --projector`,
    );
  }
  const prompt = environment.prompt ?? defaultCapabilityPrompt;
  const capability = await prompt(agent);
  const entry = { capability, source: "prompt", version };
  cache.hosts[agent] = entry;
  await persistDoctorCache(cache, environment);
  return entry;
}

/**
 * Resolve per-agent projectors for a first-party install without ``--projector``.
 *
 * Locked agents keep their projector. Remaining agents consult the doctor
 * cache (probe on miss). Vendor installs and explicit ``--projector`` skip
 * this path.
 *
 * @param {string[]} agents - Agents about to install.
 * @param {import("./lockfile.js").PluginLockEntry | undefined} existing - Existing lock entry.
 * @param {{
 *   hostCapabilities?: Record<string, "native" | "explode">,
 * } & Parameters<typeof ensureHostCapability>[1]} environment - Injectable doctor env.
 * @returns {Promise<Record<string, "native" | "explode">>} Capability map.
 */
export async function resolveDoctorCapabilities(agents, existing, environment = {}) {
  /** @type {Record<string, "native" | "explode">} */
  const capabilities = { ...environment.hostCapabilities };
  const cache = environment.cache ?? (await readDoctorCache(environment));
  for (const agent of agents) {
    if (capabilities[agent]) {
      continue;
    }
    if (existing?.agents?.[agent]) {
      continue;
    }
    const entry = await ensureHostCapability(agent, { ...environment, cache });
    capabilities[agent] = entry.capability;
  }
  return capabilities;
}

/**
 * Run ``sk doctor``: report, optional ``--repair``, optional ``--migrate``.
 *
 * @param {{
 *   agents: string[],
 *   global: boolean,
 *   migrate: string | null,
 *   project: boolean,
 *   repair: boolean,
 *   yes: boolean,
 * }} options - Parsed doctor options.
 * @param {{
 *   confirm?: (message: string) => Promise<boolean>,
 *   hash?: typeof hashFile,
 *   installExtras?: object,
 *   log?: (line: string) => void,
 *   lockEnvironment?: Parameters<typeof readLockfile>[1],
 *   now?: () => Date,
 *   readLock?: typeof readLockfile,
 *   remove?: typeof import("node:fs/promises").rm,
 *   run?: (args: string[]) => Promise<void>,
 *   warn?: (message: string) => void,
 * } & Parameters<typeof ensureHostCapability>[1]} [dependencies] - Injectable I/O.
 * @returns {Promise<{migrated: string[], repaired: string[]}>} Action summary.
 */
export async function runDoctor(options, dependencies = {}) {
  if (options.repair && options.migrate) {
    throw new Error("Choose only one doctor action: --repair or --migrate");
  }
  if (options.migrate && !Object.hasOwn(AGENT_SKILL_PATHS, options.migrate)) {
    throw new Error(`Unknown agent: ${options.migrate}`);
  }
  const log = dependencies.log ?? ((line) => console.log(line));
  const scope = resolveScope(options);
  const environment = {
    ...dependencies,
    cwd: dependencies.lockEnvironment?.cwd ?? dependencies.cwd,
    home: dependencies.lockEnvironment?.home ?? dependencies.home ?? homedir(),
    scope,
    yes: options.yes,
  };
  const hosts = doctorHosts(options.agents);
  for (const agent of hosts) {
    const capability = await ensureHostCapability(agent, environment);
    log(["host", agent, capability.capability, capability.source, capability.version].join("\t"));
  }
  const plugins = await listSkills(options, {
    lockEnvironment: dependencies.lockEnvironment,
    readLock: dependencies.readLock,
  });
  for (const plugin of plugins) {
    for (const agent of plugin.agentNames) {
      if (options.agents.length > 0 && !options.agents.includes(agent)) {
        continue;
      }
      const projector = agentProjector(plugin, agent);
      const status = plugin.agentStatus?.[agent] ?? "";
      log(["plugin", plugin.name, agent, projector, status].join("\t"));
    }
  }
  for (const orphan of await listOrphanSkillDirs(scope, plugins, environment)) {
    if (options.agents.length > 0 && !options.agents.includes(orphan.agent)) {
      continue;
    }
    log(["orphan", orphan.agent, orphan.path].join("\t"));
  }
  if (options.repair) {
    return { migrated: [], repaired: await repairMissing(options, plugins, dependencies) };
  }
  if (options.migrate) {
    return {
      migrated: await migrateHost(options.migrate, options, environment, dependencies),
      repaired: [],
    };
  }
  return { migrated: [], repaired: [] };
}

/**
 * @returns {DoctorCache} Empty cache.
 */
function emptyDoctorCache() {
  return { hosts: {}, schemaVersion: DOCTOR_CACHE_SCHEMA };
}

/**
 * Persist the doctor cache, ignoring write failures so a probe still returns.
 *
 * @param {DoctorCache} cache - Cache to write.
 * @param {Parameters<typeof writeDoctorCache>[1]} environment - Injectable fs.
 * @returns {Promise<void>} Resolves after write or a swallowed persistence error.
 */
async function persistDoctorCache(cache, environment = {}) {
  try {
    await writeDoctorCache(cache, environment);
  } catch {
    // Capability is already known; a missing cache only costs another probe.
  }
}

/**
 * @param {string[]} agents - CLI ``-a`` filter.
 * @returns {string[]} Hosts to probe.
 */
function doctorHosts(agents) {
  if (agents.length > 0) {
    return [...new Set(agents)];
  }
  return [...NATIVE_PROJECTOR_AGENTS, "codex"].sort();
}

/**
 * @param {string} agent - Host identifier.
 * @param {Parameters<typeof probeHost>[1]} environment - Probe env.
 * @returns {Promise<string>} Version string, or ``unknown``.
 */
async function hostVersion(agent, environment = {}) {
  if (agent === "cursor") {
    const capable = await cursorPluginsLocalExists(environment);
    const scope = environment.scope ?? "global";
    const exec = environment.exec ?? spawnExec;
    try {
      const result = await exec("cursor", ["--version"]);
      const text = (result.stdout || result.stderr).trim().split("\n")[0] ?? "";
      if (text) {
        return `${scope}:${capable ? "present" : "absent"}:${text.slice(0, 80)}`;
      }
    } catch {
      // Directory presence is enough when the CLI is missing.
    }
    return `${scope}:${capable ? "present" : "absent"}:nocli`;
  }
  const cli = CLI_BY_AGENT[agent];
  if (!cli) {
    return "n/a";
  }
  const exec = environment.exec ?? spawnExec;
  try {
    const result = await exec(cli, ["--version"]);
    const text = (result.stdout || result.stderr).trim().split("\n")[0] ?? "";
    return text ? text.slice(0, 80) : "unknown";
  } catch (error) {
    if (isMissingExecutable(error)) {
      return "absent";
    }
    return "unknown";
  }
}

/**
 * @param {Parameters<typeof probeHost>[1]} environment - Probe env.
 * @returns {Promise<boolean>} Whether a Cursor plugins/local dir exists.
 */
async function cursorPluginsLocalExists(environment = {}) {
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const candidates = [join(home, ".cursor", "plugins", "local")];
  if (environment.scope === "project") {
    candidates.push(join(cwd, ".cursor", "plugins", "local"));
  }
  const access =
    environment.access ??
    (async (path) => {
      try {
        const info = await stat(path);
        return info.isDirectory();
      } catch {
        return false;
      }
    });
  for (const dir of candidates) {
    if (await access(dir)) {
      return true;
    }
  }
  return false;
}

/**
 * @param {{status: number, stderr: string, stdout: string}} result - CLI result.
 * @returns {"native" | "explode" | "ambiguous"} Classification.
 */
function classifyCliPluginProbe(result) {
  if (result.status === 0) {
    return PROJECTOR_NATIVE;
  }
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  if (
    /\bunknown (?:sub)?command\b/.test(text) ||
    /\bunrecognized (?:subcommand|command|argument)s?\b/.test(text) ||
    /\b(?:command |file )?not found\b/.test(text)
  ) {
    return PROJECTOR_EXPLODE;
  }
  return "ambiguous";
}

/**
 * @param {unknown} error - Spawn failure.
 * @returns {boolean} True when the executable is missing.
 */
function isMissingExecutable(error) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

/**
 * @param {string} agent - Host identifier.
 * @returns {Promise<"native" | "explode">} Persisted answer.
 */
async function defaultCapabilityPrompt(agent) {
  const prompt = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (
      await prompt.question(`Host "${agent}" capability is unclear. Use native projector? [y/N] `)
    )
      .trim()
      .toLowerCase();
    return answer === "y" || answer === "yes" ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE;
  } finally {
    prompt.close();
  }
}

/**
 * @param {"global" | "project"} scope - Lock scope.
 * @param {Awaited<ReturnType<typeof listSkills>>} plugins - Lock plugins.
 * @param {{cwd?: string, home?: string}} environment - Path roots.
 * @returns {Promise<Array<{agent: string, path: string}>>} Untracked skill dirs.
 */
async function listOrphanSkillDirs(scope, plugins, environment) {
  /** @type {Map<string, Set<string>>} */
  const explodeTracked = new Map();
  const nativeCursorIds = new Set();
  for (const plugin of plugins) {
    for (const agent of plugin.agentNames) {
      const projector = agentProjector(plugin, agent);
      if (projector === PROJECTOR_EXPLODE) {
        const names = explodeTracked.get(agent) ?? new Set();
        const files = plugin.agents?.[agent]?.files ?? {};
        for (const name of skillNamesFromFiles(files)) {
          names.add(name);
        }
        explodeTracked.set(agent, names);
      } else if (agent === "cursor") {
        nativeCursorIds.add(plugin.name);
      }
    }
  }
  /** @type {Array<{agent: string, path: string}>} */
  const orphans = [];
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const base = scope === "project" ? cwd : home;
  for (const [agent, relative] of Object.entries(AGENT_SKILL_PATHS)) {
    const root = join(base, relative);
    orphans.push(...(await orphanEntries(agent, root, explodeTracked.get(agent) ?? new Set())));
  }
  const nativeRoot = cursorPluginsRoot({ cwd, home, scope });
  orphans.push(...(await orphanEntries("cursor", nativeRoot, nativeCursorIds)));
  return orphans.sort((left, right) => left.path.localeCompare(right.path));
}

/**
 * @param {string} agent - Host identifier.
 * @param {string} root - Directory to list.
 * @param {Set<string>} known - Lock-tracked names.
 * @returns {Promise<Array<{agent: string, path: string}>>} Unknown child dirs.
 */
async function orphanEntries(agent, root, known) {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch (error) {
    const code = error && typeof error === "object" && "code" in error ? error.code : "";
    if (code === "ENOENT" || code === "EACCES" || code === "ENOTDIR") {
      return [];
    }
    throw error;
  }
  return entries
    .filter((entry) => {
      if (entry.name.startsWith(".") || known.has(entry.name)) {
        return false;
      }
      return entry.isDirectory() || entry.isSymbolicLink();
    })
    .map((entry) => ({ agent, path: join(root, entry.name) }));
}

/**
 * Re-materialize lock entries whose files are missing, without changing projector.
 *
 * @param {Parameters<typeof runDoctor>[0]} options - Doctor options.
 * @param {Awaited<ReturnType<typeof listSkills>>} plugins - Lock plugins.
 * @param {Parameters<typeof runDoctor>[1]} dependencies - Injectable I/O.
 * @returns {Promise<string[]>} Repaired plugin ids.
 */
async function repairMissing(options, plugins, dependencies = {}) {
  const { install } = await import("./install.js");
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  /** @type {string[]} */
  const repaired = [];
  for (const plugin of plugins) {
    const missingAgents = plugin.agentNames.filter((agent) => {
      if (options.agents.length > 0 && !options.agents.includes(agent)) {
        return false;
      }
      return plugin.agentStatus?.[agent] === "MISSING";
    });
    if (missingAgents.length === 0) {
      continue;
    }
    const identity = await installIdentity(plugin.name, plugin);
    let didRepair = false;
    for (const agent of missingAgents) {
      const locked = plugin.agents?.[agent];
      if (locked && (await agentHasModifiedFiles(locked, dependencies.lockEnvironment))) {
        warn(`skipping repair of ${plugin.name} on ${agent}: tracked files were modified`);
        continue;
      }
      try {
        await install(
          {
            agents: [agent],
            bundle: identity.bundle,
            copy: false,
            global: options.global,
            onConflict: "overwrite",
            project: options.project,
            projector: agentProjector(plugin, agent),
            skills: identity.skills,
            vendor: identity.vendor,
            yes: true,
          },
          dependencies.run,
          dependencies.now,
          dependencies.lockEnvironment,
          dependencies.installExtras,
        );
        didRepair = true;
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        warn(`repair failed for ${plugin.name} on ${agent}: ${detail}`);
      }
    }
    if (didRepair) {
      repaired.push(plugin.name);
    }
  }
  return repaired;
}

/**
 * Re-deliver one host's locked plugins through the probed projector.
 *
 * Installs the new projection first so a failure leaves the old dests and lock
 * intact. Old dests are removed only after a successful install.
 *
 * @param {string} host - Agent to migrate.
 * @param {Parameters<typeof runDoctor>[0]} options - Doctor options.
 * @param {Parameters<typeof ensureHostCapability>[1]} environment - Probe env.
 * @param {Parameters<typeof runDoctor>[1]} dependencies - Injectable I/O.
 * @returns {Promise<string[]>} Migrated plugin ids.
 */
async function migrateHost(host, options, environment, dependencies = {}) {
  if (!Object.hasOwn(AGENT_SKILL_PATHS, host)) {
    throw new Error(`Unknown agent: ${host}`);
  }
  const target = await ensureHostCapability(host, environment);
  const readLock = dependencies.readLock ?? readLockfile;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const scope = resolveScope(options);
  const lock = await readLock(scope, dependencies.lockEnvironment);
  const toMigrate = Object.entries(lock.plugins).filter(
    ([, entry]) => entry.agents[host] && agentProjector(entry, host) !== target.capability,
  );
  if (toMigrate.length === 0) {
    return [];
  }
  if (!options.yes) {
    const confirm = dependencies.confirm ?? defaultMigrateConfirm;
    const accepted = await confirm(
      `Migrate ${host} from its locked projector to ${target.capability} for ${toMigrate.length} plugin(s)? [y/N] `,
    );
    if (!accepted) {
      throw new Error("Migrate cancelled");
    }
  }
  const { install } = await import("./install.js");
  /** @type {string[]} */
  const migrated = [];
  for (const [pluginId, entry] of toMigrate) {
    if (entry.vendor && entry.vendor !== "lgtm-hq" && target.capability === PROJECTOR_NATIVE) {
      warn(`skipping vendor plugin ${pluginId}: native migrate is first-party only`);
      continue;
    }
    const snapshot = entry.agents[host];
    const identity = await installIdentity(pluginId, entry);
    try {
      await install(
        {
          agents: [host],
          bundle: identity.bundle,
          copy: false,
          global: options.global,
          onConflict: "overwrite",
          project: options.project,
          projector: target.capability,
          skills: identity.skills,
          vendor: identity.vendor,
          yes: true,
        },
        dependencies.run,
        dependencies.now,
        dependencies.lockEnvironment,
        dependencies.installExtras,
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      warn(`migrate failed for ${pluginId} on ${host}: ${detail}`);
      continue;
    }
    try {
      await removeLockedAgentProjection(
        pluginId,
        { ...entry, agents: { [host]: snapshot } },
        host,
        {
          ...dependencies,
          force: true,
          scope,
        },
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      warn(
        `migrate installed ${pluginId} on ${host} but could not remove the old projection: ${detail}`,
      );
    }
    migrated.push(pluginId);
  }
  return migrated;
}

/**
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @returns {Promise<{bundle: string | null, skills: string[], vendor: string | null}>} Install identity.
 */
async function installIdentity(pluginId, entry) {
  if (entry.vendor && entry.vendor !== "lgtm-hq") {
    return { bundle: null, skills: [], vendor: entry.vendor };
  }
  const bundles = await loadBundles();
  const bundle = bundles.groups[pluginId];
  const recorded = pluginSkillNames(entry);
  if (bundle && recordedLooksLikeBundle(recorded, pluginId, bundle.skills)) {
    return { bundle: pluginId, skills: [], vendor: null };
  }
  return { bundle: null, skills: recorded, vendor: null };
}

/**
 * Whether recorded membership is the catalog bundle rather than an adopted skill
 * that happens to share the bundle id (``raycast`` is both).
 *
 * @param {string[]} recorded - Skill names from the lock entry.
 * @param {string} pluginId - Lock key.
 * @param {string[]} catalogSkills - Bundle skill list.
 * @returns {boolean} True when this entry should reinstall as the bundle.
 */
function recordedLooksLikeBundle(recorded, pluginId, catalogSkills) {
  if (recorded.length === 0) {
    return true;
  }
  const catalog = new Set(catalogSkills);
  return recorded.some((name) => name !== pluginId && catalog.has(name));
}

/**
 * @param {import("./lockfile.js").AgentInstall} install - Tracked agent files.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable fs.
 * @returns {Promise<boolean>} True when any existing tracked file drifted.
 */
async function agentHasModifiedFiles(install, lockEnvironment = {}) {
  const exists = lockEnvironment.exists;
  const hash = lockEnvironment.hash ?? hashFile;
  for (const [relative, expected] of Object.entries(install.files ?? {})) {
    const absolute = join(install.root, relative);
    try {
      if (exists && !(await exists(absolute))) {
        continue;
      }
      if ((await hash(absolute)) !== expected) {
        return true;
      }
    } catch {
      // Missing files are the repair case, not user edits.
    }
  }
  return false;
}

/**
 * Remove one agent's recorded projection from disk without rewriting the lock.
 *
 * Used after a successful projector cutover so leftover dests do not stay
 * host-visible. ``force`` deletes explode skill dirs even when hashes drifted.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry snapshot.
 * @param {string} agent - Agent to uninstall.
 * @param {Parameters<typeof runDoctor>[1] & {force?: boolean, scope?: "global" | "project"}} [dependencies] - Injectable I/O.
 * @returns {Promise<void>} Resolves when dest files are gone.
 */
export async function removeLockedAgentProjection(pluginId, entry, agent, dependencies = {}) {
  const install = entry.agents[agent];
  if (!install) {
    return;
  }
  const projector = agentProjector(entry, agent);
  if (projector === PROJECTOR_EXPLODE) {
    if (dependencies.force) {
      await forceRemoveExplodeSkillDirs(install, dependencies);
      return;
    }
    await removeExplodedFiles({
      files: Object.entries(install.files).map(([relative, digest]) => ({
        digest,
        relative,
        root: install.root,
      })),
      hash: dependencies.hash ?? dependencies.lockEnvironment?.hash ?? hashFile,
      pluginId,
      warn: dependencies.warn,
    });
    return;
  }
  if (agent === "cursor") {
    await removeCursorPlugin({
      destRoot: dirname(install.root),
      pluginId,
      remove: dependencies.remove,
    });
    return;
  }
  const scope = dependencies.scope ?? "global";
  const readLock = dependencies.readLock ?? readLockfile;
  if (
    await siblingLockHasCliNative(pluginId, agent, scope, readLock, dependencies.lockEnvironment)
  ) {
    const warn = dependencies.warn ?? ((message) => console.warn(message));
    warn(`skipping ${agent} CLI uninstall; sibling scope still owns ${pluginId}`);
    return;
  }
  await uninstallCliPlugin({ agent, exec: dependencies.exec, pluginId });
}

/**
 * @param {import("./lockfile.js").AgentInstall} install - Exploded agent snapshot.
 * @param {{remove?: typeof rm}} dependencies - Injectable rm.
 * @returns {Promise<void>} Resolves when skill dirs are gone.
 */
async function forceRemoveExplodeSkillDirs(install, dependencies) {
  const remove = dependencies.remove ?? rm;
  for (const name of skillNamesFromFiles(install.files)) {
    await remove(join(install.root, name), { force: true, recursive: true });
  }
}

/**
 * Whether the other gateway scope still records this plugin as CLI-native.
 *
 * Host CLIs are user-scoped; uninstalling while a sibling lock still owns the
 * plugin would strand that scope.
 *
 * @param {string} pluginId - Plugin id being removed.
 * @param {string} agent - CLI-native agent name.
 * @param {"global" | "project"} scope - Scope of the removal.
 * @param {typeof readLockfile} readLock - Lock reader.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Path environment.
 * @returns {Promise<boolean>} True when uninstall must be skipped.
 */
async function siblingLockHasCliNative(pluginId, agent, scope, readLock, lockEnvironment) {
  const siblingScope = scope === "global" ? "project" : "global";
  const sibling = await readLock(siblingScope, lockEnvironment);
  if (sibling.scope !== siblingScope) {
    return false;
  }
  const siblingEntry = sibling.plugins[pluginId];
  if (!siblingEntry?.agents?.[agent]) {
    return false;
  }
  return agentProjector(siblingEntry, agent) === PROJECTOR_NATIVE;
}

/**
 * @param {string} message - Confirm prompt.
 * @returns {Promise<boolean>} Whether the user accepted.
 */
async function defaultMigrateConfirm(message) {
  const prompt = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await prompt.question(message)).trim().toLowerCase();
    return answer === "y" || answer === "yes";
  } finally {
    prompt.close();
  }
}
