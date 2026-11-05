import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline/promises";

import { loadBundles } from "./catalog.ts";
import { listSkills } from "./gateway-commands.ts";
import {
  AGENT_SKILL_PATHS,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  agentProjector,
  hashFile,
  pluginSkillNames,
  readLockfile,
  skillNamesFromFiles,
} from "./lockfile.ts";
import {
  hostIds,
  hostPluginsRoot,
  isKnownHost,
  nativeRoute,
  treeHostIds,
} from "./adapters/hosts.ts";
import { removeCursorPlugin } from "./adapters/cursor/drop.ts";
import { spawnExec, uninstallCliPlugin } from "./adapters/shared/native-cli.ts";
import { removeExplodedFiles } from "./adapters/shared/skill-explode.ts";
import { resolveScope } from "./options.ts";

export const DOCTOR_CACHE_SCHEMA = 1;

export const DOCTOR_CACHE_RELATIVE = join(".ai-skills", "doctor.json");

/**
 * Absolute doctor cache path.
 */
export function doctorCachePath(home: string = homedir()): string {
  return join(home, DOCTOR_CACHE_RELATIVE);
}

/**
 * Load the host-capability cache, or an empty cache when missing/malformed.
 */
export async function readDoctorCache(
  environment: { home?: string; read?: typeof readFile } = {},
): Promise<DoctorCache> {
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
 */
export async function writeDoctorCache(
  cache: DoctorCache,
  environment: {
    home?: string;
    mkdir?: typeof mkdir;
    write?: typeof writeFile;
    rename?: typeof rename;
  } = {},
): Promise<void> {
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
 * The host definition picks the probe: CLI routes ask the host CLI for
 * ``plugin``; tree routes check that the local plugins directory exists;
 * hosts without a native route are always explode.
 */
export async function probeHost(
  agent: string,
  environment: {
    access?: (path: string) => Promise<boolean>;
    cwd?: string;
    exec?: typeof spawnExec;
    home?: string;
    scope?: "global" | "project";
    version?: string;
  } = {},
): Promise<{ capability: "native" | "explode" | "ambiguous"; version: string }> {
  const route = nativeRoute(agent);
  if (!route) {
    return { capability: PROJECTOR_EXPLODE, version: environment.version ?? "n/a" };
  }
  const version = environment.version ?? (await hostVersion(agent, environment));
  if (route.kind === "tree") {
    const capable = await pluginsLocalExists(agent, environment);
    return { capability: capable ? PROJECTOR_NATIVE : PROJECTOR_EXPLODE, version };
  }
  const exec = environment.exec ?? spawnExec;
  try {
    const result = await exec(route.binary, ["plugin"]);
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
 */
export async function ensureHostCapability(
  agent: string,
  environment: {
    access?: (path: string) => Promise<boolean>;
    cache?: DoctorCache;
    write?: typeof writeFile;
    warn?: (message: string) => void;
    cwd?: string;
    exec?: typeof spawnExec;
    home?: string;
    prompt?: (agent: string) => Promise<"native" | "explode">;
    scope?: "global" | "project";
    yes?: boolean;
  } = {},
): Promise<HostCapability> {
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
    const entry: HostCapability = { capability: probed.capability, source: "probe", version };
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
  const entry: HostCapability = { capability, source: "prompt", version };
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
 */
export async function resolveDoctorCapabilities(
  agents: string[],
  existing: import("./lockfile.ts").PluginLockEntry | undefined,
  environment: {
    hostCapabilities?: Record<string, "native" | "explode">;
  } & Parameters<typeof ensureHostCapability>[1] = {},
): Promise<Record<string, "native" | "explode">> {
  const capabilities: Record<string, "native" | "explode"> = { ...environment.hostCapabilities };
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
 */
export async function runDoctor(
  options: {
    agents: string[];
    global: boolean;
    migrate: string | null;
    project: boolean;
    repair: boolean;
    yes: boolean;
  },
  dependencies: {
    confirm?: (message: string) => Promise<boolean>;
    hash?: typeof hashFile;
    install?: typeof import("./install.ts").install;
    installExtras?: Parameters<typeof import("./install.ts").install>[4];
    log?: (line: string) => void;
    lockEnvironment?: import("./lockfile.ts").LockEnvironment;
    now?: () => Date;
    readLock?: typeof readLockfile;
    remove?: typeof import("node:fs/promises").rm;
    run?: (args: string[]) => Promise<void>;
    warn?: (message: string) => void;
  } & Parameters<typeof ensureHostCapability>[1] = {},
): Promise<{ migrated: string[]; repaired: string[] }> {
  if (options.repair && options.migrate) {
    throw new Error("Choose only one doctor action: --repair or --migrate");
  }
  if (options.migrate && !isKnownHost(options.migrate)) {
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
    try {
      const capability = await ensureHostCapability(agent, environment);
      log(["host", agent, capability.capability, capability.source, capability.version].join("\t"));
    } catch (error) {
      if (options.migrate !== agent && isAmbiguousCapabilityError(error)) {
        log(["host", agent, "ambiguous", "error", ""].join("\t"));
        continue;
      }
      throw error;
    }
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

function emptyDoctorCache(): DoctorCache {
  return { hosts: {}, schemaVersion: DOCTOR_CACHE_SCHEMA };
}

/**
 * Persist the doctor cache, ignoring write failures so a probe still returns.
 */
async function persistDoctorCache(
  cache: DoctorCache,
  environment: Parameters<typeof writeDoctorCache>[1] & { warn?: (message: string) => void } = {},
): Promise<void> {
  try {
    await writeDoctorCache(cache, environment);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const warn = environment.warn ?? ((message) => console.warn(message));
    warn(`could not write doctor cache: ${detail}`);
  }
}

function doctorHosts(agents: string[]): string[] {
  if (agents.length > 0) {
    return [...new Set(agents)];
  }
  return hostIds().sort();
}

async function hostVersion(
  agent: string,
  environment: Parameters<typeof probeHost>[1] = {},
): Promise<string> {
  const route = nativeRoute(agent);
  if (route?.kind === "tree") {
    const capable = await pluginsLocalExists(agent, environment);
    const scope = environment.scope ?? "global";
    const exec = environment.exec ?? spawnExec;
    try {
      const result = await exec(route.versionBinary, ["--version"]);
      const text = (result.stdout || result.stderr).trim().split("\n")[0] ?? "";
      if (text) {
        return `${scope}:${capable ? "present" : "absent"}:${text.slice(0, 80)}`;
      }
    } catch {
      // Directory presence is enough when the CLI is missing.
    }
    return `${scope}:${capable ? "present" : "absent"}:nocli`;
  }
  if (!route) {
    return "n/a";
  }
  const exec = environment.exec ?? spawnExec;
  try {
    const result = await exec(route.binary, ["--version"]);
    const text = (result.stdout || result.stderr).trim().split("\n")[0] ?? "";
    return text ? text.slice(0, 80) : "unknown";
  } catch (error) {
    if (isMissingExecutable(error)) {
      return "absent";
    }
    return "unknown";
  }
}

async function pluginsLocalExists(
  agent: string,
  environment: Parameters<typeof probeHost>[1] = {},
): Promise<boolean> {
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const candidates = [hostPluginsRoot(agent, { cwd, home, scope: "global" })!];
  if (environment.scope === "project") {
    candidates.push(hostPluginsRoot(agent, { cwd, home, scope: "project" })!);
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

function classifyCliPluginProbe(result: {
  status: number;
  stderr: string;
  stdout: string;
}): "native" | "explode" | "ambiguous" {
  if (result.status === 0) {
    return PROJECTOR_NATIVE;
  }
  const text = `${result.stdout} ${result.stderr}`.toLowerCase();
  if (
    /\bunknown (?:sub)?command\b/.test(text) ||
    /\bunrecognized (?:subcommand|command|argument)s?\b/.test(text) ||
    /\b(?:command|file) not found\b/.test(text)
  ) {
    return PROJECTOR_EXPLODE;
  }
  return "ambiguous";
}

function isMissingExecutable(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

function isAmbiguousCapabilityError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("ambiguous");
}

async function defaultCapabilityPrompt(agent: string): Promise<"native" | "explode"> {
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

async function listOrphanSkillDirs(
  scope: "global" | "project",
  plugins: Awaited<ReturnType<typeof listSkills>>,
  environment: { cwd?: string; home?: string },
): Promise<Array<{ agent: string; path: string }>> {
  const explodeTracked: Map<string, Set<string>> = new Map();
  const nativeTreeIds: Map<string, Set<string>> = new Map();
  for (const plugin of plugins) {
    for (const agent of plugin.agentNames) {
      const projector = agentProjector(plugin, agent);
      if (projector === PROJECTOR_EXPLODE) {
        const names = explodeTracked.get(agent) ?? new Set<string>();
        const files = plugin.agents?.[agent]?.files ?? {};
        for (const name of skillNamesFromFiles(files)) {
          names.add(name);
        }
        explodeTracked.set(agent, names);
      } else if (nativeRoute(agent)?.kind === "tree") {
        const ids = nativeTreeIds.get(agent) ?? new Set<string>();
        ids.add(plugin.name);
        nativeTreeIds.set(agent, ids);
      }
    }
  }

  const orphans: Array<{ agent: string; path: string }> = [];
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const base = scope === "project" ? cwd : home;
  for (const [agent, relative] of Object.entries(AGENT_SKILL_PATHS)) {
    const root = join(base, relative);
    orphans.push(...(await orphanEntries(agent, root, explodeTracked.get(agent) ?? new Set())));
  }
  for (const agent of treeHostIds()) {
    const nativeRoot = hostPluginsRoot(agent, { cwd, home, scope })!;
    orphans.push(
      ...(await orphanEntries(agent, nativeRoot, nativeTreeIds.get(agent) ?? new Set())),
    );
  }
  return orphans.sort((left, right) => left.path.localeCompare(right.path));
}

async function orphanEntries(
  agent: string,
  root: string,
  known: Set<string>,
): Promise<Array<{ agent: string; path: string }>> {
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
 */
async function repairMissing(
  options: Parameters<typeof runDoctor>[0],
  plugins: Awaited<ReturnType<typeof listSkills>>,
  dependencies: Parameters<typeof runDoctor>[1] = {},
): Promise<string[]> {
  const { install: defaultInstall } = await import("./install.ts");
  const install = dependencies.install ?? defaultInstall;
  const warn = dependencies.warn ?? ((message) => console.warn(message));

  const repaired: string[] = [];

  const failed: string[] = [];
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
        failed.push(`${plugin.name}:${agent}`);
      }
    }
    if (didRepair) {
      repaired.push(plugin.name);
    }
  }
  if (failed.length > 0) {
    throw new Error(`Repair failed for ${failed.join(", ")}`);
  }
  return repaired;
}

/**
 * Re-deliver one host's locked plugins through the probed projector.
 *
 * Installs the new projection first so a failure leaves the old dests and lock
 * intact. Old dests are removed only after a successful install.
 */
async function migrateHost(
  host: string,
  options: Parameters<typeof runDoctor>[0],
  environment: Parameters<typeof ensureHostCapability>[1],
  dependencies: Parameters<typeof runDoctor>[1] = {},
): Promise<string[]> {
  if (!isKnownHost(host)) {
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
  const { install } = await import("./install.ts");

  const migrated: string[] = [];

  const failed: string[] = [];
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
      failed.push(pluginId);
      continue;
    }
    try {
      await removeLockedAgentProjection(
        pluginId,
        { ...entry, agents: { [host]: snapshot! } },
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
      failed.push(pluginId);
      continue;
    }
    migrated.push(pluginId);
  }
  if (failed.length > 0) {
    throw new Error(`Migrate failed for ${failed.join(", ")}`);
  }
  return migrated;
}

async function installIdentity(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
): Promise<{ bundle: string | null; skills: string[]; vendor: string | null }> {
  if (entry.vendor && entry.vendor !== "lgtm-hq") {
    return { bundle: pluginId, skills: [], vendor: entry.vendor };
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
 */
function recordedLooksLikeBundle(
  recorded: string[],
  pluginId: string,
  catalogSkills: string[],
): boolean {
  if (recorded.length === 0) {
    return true;
  }
  const catalog = new Set(catalogSkills);
  return recorded.some((name) => name !== pluginId && catalog.has(name));
}

async function agentHasModifiedFiles(
  install: import("./lockfile.ts").AgentInstall,
  lockEnvironment: Parameters<typeof readLockfile>[1] = {},
): Promise<boolean> {
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
 */
export async function removeLockedAgentProjection(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  agent: string,
  dependencies: Parameters<typeof runDoctor>[1] & {
    force?: boolean;
    scope?: "global" | "project";
  } = {},
): Promise<void> {
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
  if (nativeRoute(agent)?.kind === "tree") {
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

async function forceRemoveExplodeSkillDirs(
  install: import("./lockfile.ts").AgentInstall,
  dependencies: { remove?: typeof rm },
): Promise<void> {
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
 */
async function siblingLockHasCliNative(
  pluginId: string,
  agent: string,
  scope: "global" | "project",
  readLock: typeof readLockfile,
  lockEnvironment?: import("./lockfile.ts").LockEnvironment,
): Promise<boolean> {
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

async function defaultMigrateConfirm(message: string): Promise<boolean> {
  const prompt = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await prompt.question(message)).trim().toLowerCase();
    return answer === "y" || answer === "yes";
  } finally {
    prompt.close();
  }
}

export interface HostCapability {
  capability: "native" | "explode";
  source: "probe" | "prompt";
  version: string;
}

export interface DoctorCache {
  hosts: Record<string, HostCapability>;
  schemaVersion: number;
}
