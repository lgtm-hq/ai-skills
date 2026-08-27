import { loadVendors } from "./catalog.js";
import { getPackageVersion } from "./package-version.js";
import {
  hashFile,
  pluginAgentNames,
  pluginSkillNames,
  pruneMissingLockEntries,
  readLockfile,
  reconcileLock,
  refreshPluginFileHashes,
  writeLockfile,
} from "./lockfile.js";
import { resolveScope } from "./options.js";
import { buildSkillsArguments, buildSkillsRemoveArguments, runSkills } from "./skills-runner.js";

/**
 * Refresh lock-managed plugins using the current package tag or vendor registry pins.
 *
 * Entries absent from every tracked agent directory are pruned instead of reinstalled.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{hash?: typeof import("./lockfile.js").hashFile, isInstalled?: Parameters<typeof pruneMissingLockEntries>[1], now?: () => Date, readLock?: typeof readLockfile, run?: typeof runSkills, writeLock?: typeof writeLockfile}} [dependencies] - Injectable command dependencies.
 * @returns {Promise<{pruned: string[], updated: string[]}>} Updated and pruned plugin ids.
 */
export async function updateSkills(options, dependencies = {}) {
  const scope = resolveScope(options);
  const scopedOptions = {
    ...options,
    global: scope === "global",
    project: scope === "project",
  };
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const run = dependencies.run ?? runSkills;
  const now = dependencies.now ?? (() => new Date());
  const lock = await readLock(scope);
  const { lock: prunedLock, pruned } = await pruneMissingLockEntries(
    lock,
    dependencies.isInstalled,
  );
  const selected = selectPlugins(prunedLock.plugins, options.skills);
  const updated = Object.keys(selected);
  const { vendors } = await loadVendors();
  const sources = resolveSources(selected, vendors);
  for (const [source, group] of sources) {
    const agents = [...group.agents].sort();
    await run(
      buildSkillsArguments(
        {
          ...scopedOptions,
          agents: agents.length > 0 ? agents : scopedOptions.agents,
          copy: false,
          onConflict: "overwrite",
          skills: group.skills,
        },
        source,
      ),
    );
  }
  const installedAt = now().toISOString();
  const hash = dependencies.hash ?? hashFile;
  const plugins = {};
  for (const [pluginId, entry] of Object.entries(prunedLock.plugins)) {
    if (!updated.includes(pluginId)) {
      plugins[pluginId] = entry;
      continue;
    }
    const hashed = await refreshPluginFileHashes(entry, hash);
    plugins[pluginId] = {
      ...hashed,
      installedAt,
      sha: sourceSha(entry.vendor, entry.sha, vendors),
      version:
        entry.vendor === "lgtm-hq"
          ? getPackageVersion()
          : sourceSha(entry.vendor, entry.sha, vendors),
    };
  }
  await writeLock({
    ...prunedLock,
    gatewayVersion: getPackageVersion(),
    plugins,
  });
  return { pruned, updated };
}

/**
 * Remove selected lock-managed plugins through the upstream CLI and then unlock them.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{readLock?: typeof readLockfile, run?: typeof runSkills, writeLock?: typeof writeLockfile}} [dependencies] - Injectable command dependencies.
 * @returns {Promise<string[]>} Removed plugin ids.
 */
export async function removeSkills(options, dependencies = {}) {
  const scope = resolveScope(options);
  const scopedOptions = {
    ...options,
    global: scope === "global",
    project: scope === "project",
  };
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const run = dependencies.run ?? runSkills;
  const lock = await readLock(scope);
  const selected = Object.keys(selectPlugins(lock.plugins, options.skills));
  if (selected.length === 0) {
    return [];
  }
  const skillNames = [
    ...new Set(selected.flatMap((pluginId) => pluginSkillNames(lock.plugins[pluginId]))),
  ].sort();
  await run(buildSkillsRemoveArguments(scopedOptions, skillNames));
  const plugins = { ...lock.plugins };
  selected.forEach((pluginId) => delete plugins[pluginId]);
  await writeLock({
    ...lock,
    plugins,
  });
  return selected;
}

/**
 * List lock-managed plugins for the selected scope.
 *
 * @param {{global: boolean, project: boolean}} options - Validated command options.
 * @param {{
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   readLock?: typeof readLockfile,
 * }} [dependencies] - Injectable command dependencies.
 * @returns {Promise<Array<{
 *   agentNames: string[],
 *   name: string,
 *   status: "" | "MISSING" | "MODIFIED",
 * } & import("./lockfile.js").PluginLockEntry>>} Lock-managed entries.
 */
export async function listSkills(options, dependencies = {}) {
  const readLock = dependencies.readLock ?? readLockfile;
  const lock = await readLock(resolveScope(options));
  const reconciliation = await reconcileLock(lock, dependencies.lockEnvironment);
  const statusByPlugin = pluginReconcileStatus(reconciliation);
  return Object.entries(lock.plugins)
    .map(([name, entry]) => ({
      name,
      ...entry,
      agentNames: pluginAgentNames(entry),
      status: statusByPlugin.get(name) ?? "",
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/**
 * Select named plugin entries, or every entry when no names were provided.
 *
 * @param {Record<string, import("./lockfile.js").PluginLockEntry>} plugins - Lock entries.
 * @param {string[]} names - Requested plugin ids.
 * @returns {Record<string, import("./lockfile.js").PluginLockEntry>} Selected entries.
 * @throws {Error} When a requested plugin is not lock-managed.
 */
function selectPlugins(plugins, names) {
  if (names.length === 0) {
    return plugins;
  }
  return Object.fromEntries(
    names.map((name) => {
      if (!plugins[name]) {
        throw new Error(`Plugin is not managed by this gateway lockfile: ${name}`);
      }
      return [name, plugins[name]];
    }),
  );
}

/**
 * Resolve updated source strings grouped by their lock entries.
 *
 * @param {Record<string, import("./lockfile.js").PluginLockEntry>} plugins - Selected lock entries.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {Map<string, {agents: Set<string>, skills: string[]}>} Source string to tracked agents and exploded skill names.
 */
function resolveSources(plugins, vendors) {
  /** @type {Map<string, {agents: Set<string>, skills: Set<string>}>} */
  const sources = new Map();
  for (const entry of Object.values(plugins)) {
    const source =
      entry.vendor === "lgtm-hq"
        ? `lgtm-hq/ai-skills@v${getPackageVersion()}`
        : resolveVendorSource(entry, vendors);
    const group = sources.get(source) ?? { agents: new Set(), skills: new Set() };
    for (const agent of pluginAgentNames(entry)) {
      group.agents.add(agent);
    }
    for (const name of pluginSkillNames(entry)) {
      group.skills.add(name);
    }
    sources.set(source, group);
  }
  return new Map(
    [...sources].map(([source, group]) => [
      source,
      { agents: group.agents, skills: [...group.skills].sort() },
    ]),
  );
}

/**
 * Resolve a vendor entry to its current registry pin.
 *
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {string} Pinned source.
 * @throws {Error} When a lock entry's vendor has been removed from the registry.
 */
function resolveVendorSource(entry, vendors) {
  const vendor = vendors.find((candidate) => candidate.id === entry.vendor);
  if (!vendor || vendor.repo !== entry.repo) {
    throw new Error(`Vendor is no longer available in the gateway registry: ${entry.vendor}`);
  }
  return `${vendor.repo}@${vendor.sha}`;
}

/**
 * Resolve the replacement SHA or first-party tag for a refreshed entry.
 *
 * @param {string} vendor - Vendor identifier.
 * @param {string} currentSha - Existing resolved SHA.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {string} Updated SHA or tag.
 */
function sourceSha(vendor, currentSha, vendors) {
  if (vendor === "lgtm-hq") {
    return `v${getPackageVersion()}`;
  }
  return vendors.find((candidate) => candidate.id === vendor)?.sha ?? currentSha;
}

/**
 * Collapse per-agent reconcile results into a plugin-level list annotation.
 *
 * Missing outranks modified so a partially absent plugin is not listed as healthy.
 *
 * @param {import("./lockfile.js").ReconcileResult} reconciliation - Per-agent partition.
 * @returns {Map<string, "MISSING" | "MODIFIED">} Plugin id to annotation.
 */
function pluginReconcileStatus(reconciliation) {
  /** @type {Map<string, "MISSING" | "MODIFIED">} */
  const status = new Map();
  for (const item of reconciliation.modified) {
    status.set(item.pluginId, "MODIFIED");
  }
  for (const item of reconciliation.missing) {
    status.set(item.pluginId, "MISSING");
  }
  return status;
}
