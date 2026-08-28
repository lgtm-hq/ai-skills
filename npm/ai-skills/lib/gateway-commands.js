import { rmdir, unlink } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";

import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import {
  agentProjector,
  hashFile,
  hashTree,
  isCliOwnedNativeInstall,
  LOCKFILE_VERSION,
  pluginAgentNames,
  pluginSkillNames,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  pruneMissingLockEntries,
  readLockfile,
  reconcileLock,
  writeLockfile,
} from "./lockfile.js";
import { resolveScope } from "./options.js";
import { getPackageVersion } from "./package-version.js";
import { installCliPlugin, uninstallCliPlugin } from "./projectors/native-cli.js";
import {
  cursorPluginsRoot,
  findCatalogSourceRoot,
  installCursorPlugin,
  removeCursorPlugin,
} from "./projectors/native-cursor.js";
import { buildSkillsArguments, buildSkillsRemoveArguments, runSkills } from "./skills-runner.js";

/**
 * Refresh lock-managed plugins using the current package tag or vendor registry pins.
 *
 * Entries absent from every tracked agent directory are pruned instead of reinstalled.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{
 *   exec?: (command: string, args: string[]) => Promise<{status: number, stderr: string, stdout: string}>,
 *   hash?: typeof import("./lockfile.js").hashFile,
 *   isInstalled?: Parameters<typeof pruneMissingLockEntries>[1],
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   now?: () => Date,
 *   readLock?: typeof readLockfile,
 *   rmdir?: typeof rmdir,
 *   run?: typeof runSkills,
 *   sourceRoot?: string | null,
 *   unlink?: typeof unlink,
 *   warn?: (message: string) => void,
 *   writeLock?: typeof writeLockfile,
 * }} [dependencies] - Injectable command dependencies.
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
  const { vendors } = await loadVendors();
  const updated = [];
  for (const [pluginId, entry] of Object.entries(selected)) {
    if (await pluginNeedsRefresh(pluginId, entry, prunedLock.scope, vendors, dependencies)) {
      updated.push(pluginId);
    }
  }
  const catalogSkills = {};
  const hash = dependencies.hash ?? hashFile;
  const removeFile = dependencies.unlink ?? unlink;
  const removeDir = dependencies.rmdir ?? rmdir;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  for (const pluginId of updated) {
    const entry = selected[pluginId];
    const skills = await currentPluginSkills(pluginId, entry);
    catalogSkills[pluginId] = skills;
    const source =
      entry.vendor === "lgtm-hq"
        ? `lgtm-hq/ai-skills@v${getPackageVersion()}`
        : resolveVendorSource(entry, vendors);
    const lanes = partitionLockedLanes(entry);
    if (lanes.explode.length > 0) {
      await run(
        buildSkillsArguments(
          {
            ...scopedOptions,
            agents: lanes.explode,
            copy: false,
            onConflict: "overwrite",
            skills,
          },
          source,
        ),
      );
    }
    if (lanes.cursorNative.length > 0) {
      await rematerializeCursorPlugin(pluginId, entry, skills, dependencies, prunedLock.scope);
    }
    for (const agent of lanes.cliNative) {
      await installCliPlugin({
        agent,
        exec: dependencies.exec,
        pluginId,
        source,
      });
    }
    await removeStalePluginSkills(pluginId, entry, skills, {
      hash,
      removeDir,
      removeFile,
      run,
      scopedOptions: { ...scopedOptions, agents: lanes.explode },
      warn,
    });
  }
  const installedAt = now().toISOString();
  const plugins = {};
  for (const [pluginId, entry] of Object.entries(prunedLock.plugins)) {
    if (!updated.includes(pluginId)) {
      plugins[pluginId] = entry;
      continue;
    }
    const hashed = await rematerializePluginFiles(
      entry,
      catalogSkills[pluginId] ?? pluginSkillNames(entry),
      hash,
    );
    plugins[pluginId] = {
      ...hashed,
      installedAt,
      skills: catalogSkills[pluginId] ?? pluginSkillNames(entry),
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
 * @param {{
 *   exec?: (command: string, args: string[]) => Promise<{status: number, stderr: string, stdout: string}>,
 *   hash?: typeof hashFile,
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   readLock?: typeof readLockfile,
 *   rmdir?: typeof rmdir,
 *   run?: typeof runSkills,
 *   unlink?: typeof unlink,
 *   warn?: (message: string) => void,
 *   writeLock?: typeof writeLockfile,
 * }} [dependencies] - Injectable command dependencies.
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
  const hash = dependencies.hash ?? hashFile;
  const removeFile = dependencies.unlink ?? unlink;
  const removeDir = dependencies.rmdir ?? rmdir;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const lock = await readLock(scope);
  const selected = Object.keys(selectPlugins(lock.plugins, options.skills));
  if (selected.length === 0) {
    return [];
  }
  for (const pluginId of selected) {
    const entry = lock.plugins[pluginId];
    const classified = await classifyPluginFiles(pluginId, entry, { hash, warn });
    const lanes = partitionLockedLanes(entry);
    if (lanes.explode.length > 0 && classified.removableSkills.length > 0) {
      await run(
        buildSkillsRemoveArguments(
          {
            ...scopedOptions,
            agents: lanes.explode,
          },
          classified.removableSkills,
        ),
      );
    }
    await deleteVerifiedFiles(classified.verified, { removeDir, removeFile });
    if (lanes.cursorNative.length > 0 && !classified.modified) {
      const destRoot = cursorPluginsRoot({
        cwd: dependencies.lockEnvironment?.cwd,
        home: dependencies.lockEnvironment?.home,
        scope,
      });
      await removeCursorPlugin({ destRoot, pluginId });
    }
    for (const agent of lanes.cliNative) {
      await uninstallCliPlugin({
        agent,
        exec: dependencies.exec,
        pluginId,
      });
    }
  }
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
 *   agentStatus: Record<string, "" | "MISSING" | "MODIFIED">,
 *   name: string,
 *   skills: string[],
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
      agentStatus: agentReconcileStatus(name, entry, reconciliation),
      skills: pluginSkillNames(entry),
      status: statusByPlugin.get(name) ?? "",
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/**
 * Whether a plugin pin moved or tracked files drifted.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {"global" | "project"} scope - Lock scope.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @param {{lockEnvironment?: Parameters<typeof reconcileLock>[1]}} dependencies - Injectable fs.
 * @returns {Promise<boolean>} True when the plugin should be re-materialized.
 */
async function pluginNeedsRefresh(pluginId, entry, scope, vendors, dependencies) {
  const expectedSha = sourceSha(entry.vendor, entry.sha, vendors);
  const expectedVersion = entry.vendor === "lgtm-hq" ? getPackageVersion() : expectedSha;
  if (entry.sha !== expectedSha || entry.version !== expectedVersion) {
    return true;
  }
  const reconciliation = await reconcileLock(
    {
      gatewayVersion: "",
      plugins: { [pluginId]: entry },
      scope,
      version: LOCKFILE_VERSION,
    },
    dependencies.lockEnvironment,
  );
  return reconciliation.missing.length > 0 || reconciliation.modified.length > 0;
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
 * Hash-verified delete of skills that left the catalog since the last lock write.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Pre-update lock entry.
 * @param {string[]} currentSkills - Skill names in the current catalog.
 * @param {{
 *   hash: typeof hashFile,
 *   removeDir: typeof rmdir,
 *   removeFile: typeof unlink,
 *   run: typeof runSkills,
 *   scopedOptions: {agents: string[], global: boolean, project: boolean, yes: boolean},
 *   warn: (message: string) => void,
 * }} io - Injectable command dependencies.
 * @returns {Promise<void>} Resolves when stale members are removed or left with a warning.
 */
async function removeStalePluginSkills(pluginId, entry, currentSkills, io) {
  const current = new Set(currentSkills);
  const staleNames = pluginSkillNames(entry).filter((name) => !current.has(name));
  if (staleNames.length === 0) {
    return;
  }
  const stale = {
    ...entry,
    agents: Object.fromEntries(
      Object.entries(entry.agents).map(([agent, install]) => [
        agent,
        {
          ...install,
          files: Object.fromEntries(
            Object.entries(install.files).filter(([relative]) =>
              staleNames.includes(relative.split("/")[0]),
            ),
          ),
        },
      ]),
    ),
  };
  const classified = await classifyPluginFiles(pluginId, stale, { hash: io.hash, warn: io.warn });
  if (classified.removableSkills.length > 0 && io.scopedOptions.agents.length > 0) {
    await io.run(
      buildSkillsRemoveArguments(
        {
          ...io.scopedOptions,
          agents: pluginAgentNames(entry),
        },
        classified.removableSkills,
      ),
    );
  }
  await deleteVerifiedFiles(classified.verified, {
    removeDir: io.removeDir,
    removeFile: io.removeFile,
  });
}

/**
 * Current catalog skill names for a plugin, falling back to lock membership.
 *
 * First-party bundle ids and vendor plugin ids rematerialize from the baked
 * catalog. Leftover per-skill lock entries keep their tracked names.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @returns {Promise<string[]>} Skill directory names to re-materialize.
 */
async function currentPluginSkills(pluginId, entry) {
  if (entry.vendor === "lgtm-hq") {
    const bundles = await loadBundles();
    const bundle = bundles.groups[pluginId];
    if (bundle) {
      return [...bundle.skills];
    }
  } else if (pluginId === entry.vendor) {
    const index = await loadVendorIndex(entry.vendor);
    return index.skills.map((skill) => skill.name);
  }
  return pluginSkillNames(entry);
}

/**
 * Rebuild an entry's tracked files for the current plugin skill list.
 *
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {string[]} skillNames - Skill directory names to hash.
 * @param {typeof hashFile} hash - Injectable hasher.
 * @returns {Promise<import("./lockfile.js").PluginLockEntry>} Entry with rebuilt file maps.
 */
async function rematerializePluginFiles(entry, skillNames, hash) {
  const current = new Set(skillNames);
  const agents = {};
  for (const [agent, install] of Object.entries(entry.agents)) {
    const projector = agentProjector(entry, agent);
    if (projector === PROJECTOR_NATIVE && agent === "cursor") {
      agents[agent] = { ...install, files: await hashTree(install.root, hash) };
      continue;
    }
    if (isCliOwnedNativeInstall(install, entry.projector)) {
      agents[agent] = {
        ...install,
        files: Object.fromEntries(skillNames.map((name) => [`${name}/SKILL.md`, ""])),
      };
      continue;
    }
    const files = {};
    for (const relative of Object.keys(install.files)) {
      const name = relative.split("/")[0];
      if (!current.has(name)) {
        continue;
      }
      try {
        files[relative] = await hash(join(install.root, relative));
      } catch {
        files[relative] = "";
      }
    }
    for (const name of skillNames) {
      const relative = `${name}/SKILL.md`;
      if (relative in files) {
        continue;
      }
      try {
        files[relative] = await hash(join(install.root, relative));
      } catch {
        files[relative] = "";
      }
    }
    agents[agent] = { ...install, files };
  }
  return { ...entry, agents };
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
 * Classify tracked files before any delete so modified paths stay on disk.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {{
 *   hash: typeof hashFile,
 *   warn: (message: string) => void,
 * }} io - Injectable hasher and warning sink.
 * @returns {Promise<{
 *   removableSkills: string[],
 *   verified: Array<{absolute: string, root: string}>,
 * }>} Skills safe to pass upstream and files safe to unlink.
 */
async function classifyPluginFiles(pluginId, entry, io) {
  /** @type {Set<string>} */
  const modifiedSkills = new Set();
  /** @type {Array<{absolute: string, root: string}>} */
  const verified = [];
  for (const install of Object.values(entry.agents)) {
    if (isCliOwnedNativeInstall(install, entry.projector)) {
      continue;
    }
    for (const [relative, digest] of Object.entries(install.files)) {
      const absolute = resolveTrackedPath(install.root, relative);
      try {
        const current = await io.hash(absolute);
        if (current !== digest) {
          io.warn(`left modified ${pluginId} file ${relative}`);
          const skillName = relative.split("/")[0];
          if (skillName) {
            modifiedSkills.add(skillName);
          }
          continue;
        }
        verified.push({ absolute, root: install.root });
      } catch (error) {
        if (isAbsentFsError(error)) {
          continue;
        }
        throw error;
      }
    }
  }
  return {
    modified: modifiedSkills.size > 0,
    removableSkills: pluginSkillNames(entry).filter((name) => !modifiedSkills.has(name)),
    verified,
  };
}

/**
 * Unlink hash-matching files and prune empty ancestor directories.
 *
 * @param {Array<{absolute: string, root: string}>} verified - Files that matched the lock digest.
 * @param {{
 *   removeDir: typeof rmdir,
 *   removeFile: typeof unlink,
 * }} io - Injectable filesystem.
 * @returns {Promise<void>} Resolves when verified deletes finish.
 */
async function deleteVerifiedFiles(verified, io) {
  for (const file of verified) {
    try {
      await io.removeFile(file.absolute);
      await pruneEmptyAncestors(dirname(file.absolute), file.root, io.removeDir);
    } catch (error) {
      if (isAbsentFsError(error)) {
        continue;
      }
      throw error;
    }
  }
}

/**
 * Whether an fs failure means the path is already gone.
 *
 * @param {unknown} error - Caught rejection.
 * @returns {boolean} True when the code is ENOENT.
 */
function isAbsentFsError(error) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

/**
 * Resolve a lock-relative path and reject escapes outside the agent root.
 *
 * @param {string} root - Agent skills root from the lock.
 * @param {string} relative - Tracked path relative to that root.
 * @returns {string} Absolute path inside the root.
 * @throws {Error} When the relative path escapes the root.
 */
function resolveTrackedPath(root, relative) {
  if (
    relative.includes("\0") ||
    relative.startsWith("/") ||
    relative.split(/[\\/]/).includes("..")
  ) {
    throw new Error(`Refusing to delete path outside plugin root: ${relative}`);
  }
  const absolute = resolve(join(root, relative));
  const resolvedRoot = resolve(root);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  if (absolute !== resolvedRoot && !absolute.startsWith(prefix)) {
    throw new Error(`Refusing to delete path outside plugin root: ${relative}`);
  }
  return absolute;
}

/**
 * Remove empty directories from a deleted file up to the agent skills root.
 *
 * @param {string} start - Directory that contained a deleted file.
 * @param {string} root - Agent skills root; not removed.
 * @param {typeof rmdir} removeDir - Injectable rmdir.
 * @returns {Promise<void>} Resolves when pruning stops.
 */
async function pruneEmptyAncestors(start, root, removeDir) {
  const resolvedRoot = resolve(root);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  let current = resolve(start);
  while (current.startsWith(prefix) && current !== resolvedRoot) {
    try {
      await removeDir(current);
    } catch {
      return;
    }
    current = dirname(current);
  }
}

/**
 * Per-agent reconcile annotation for one plugin.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {import("./lockfile.js").ReconcileResult} reconciliation - Partition.
 * @returns {Record<string, "" | "MISSING" | "MODIFIED">} Agent id to status.
 */
function agentReconcileStatus(pluginId, entry, reconciliation) {
  /** @type {Record<string, "" | "MISSING" | "MODIFIED">} */
  const status = {};
  for (const agent of pluginAgentNames(entry)) {
    status[agent] = "";
  }
  for (const item of reconciliation.modified) {
    if (item.pluginId === pluginId) {
      status[item.agent] = "MODIFIED";
    }
  }
  for (const item of reconciliation.missing) {
    if (item.pluginId === pluginId) {
      status[item.agent] = "MISSING";
    }
  }
  return status;
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

/**
 * Split a lock entry's agents by owning projector.
 *
 * @param {import("./lockfile.js").PluginLockEntry} entry - Plugin lock entry.
 * @returns {{cliNative: string[], cursorNative: string[], explode: string[]}} Lanes.
 */
function partitionLockedLanes(entry) {
  const explode = [];
  const cursorNative = [];
  const cliNative = [];
  for (const agent of pluginAgentNames(entry)) {
    const projector = agentProjector(entry, agent);
    if (projector === PROJECTOR_EXPLODE) {
      explode.push(agent);
    } else if (agent === "cursor") {
      cursorNative.push(agent);
    } else {
      cliNative.push(agent);
    }
  }
  return { cliNative, cursorNative, explode };
}

/**
 * Re-assemble a Cursor-local plugin tree from the current catalog membership.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {string[]} skills - Current catalog skill names.
 * @param {{
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   sourceRoot?: string | null,
 * }} dependencies - Injectable catalog root and paths.
 * @param {"global" | "project"} scope - Installation scope.
 * @returns {Promise<void>} Resolves when the tree is rewritten.
 */
async function rematerializeCursorPlugin(pluginId, entry, skills, dependencies, scope) {
  const sourceRoot =
    dependencies.sourceRoot !== undefined
      ? dependencies.sourceRoot
      : findCatalogSourceRoot(dependencies.lockEnvironment?.cwd ?? process.cwd());
  if (!sourceRoot) {
    throw new Error(
      "Native Cursor projector requires a catalog checkout (skills/ + " +
        ".claude-plugin/marketplace.json). Use --projector explode, or run from the " +
        "ai-skills repository.",
    );
  }
  const destRoot = cursorPluginsRoot({
    cwd: dependencies.lockEnvironment?.cwd,
    home: dependencies.lockEnvironment?.home,
    scope,
  });
  const bundles = await loadBundles();
  await installCursorPlugin({
    description: bundles.groups[pluginId]?.description ?? pluginId,
    destRoot,
    pluginId,
    skills,
    sourceRoot,
    version: entry.vendor === "lgtm-hq" ? getPackageVersion() : entry.version,
  });
}
