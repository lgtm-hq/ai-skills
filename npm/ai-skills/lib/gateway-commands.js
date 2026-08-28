import { readdir, rmdir, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";

import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import {
  agentProjector,
  allAgentSkillRoots,
  hashFile,
  hashLockEntryPath,
  hashTree,
  isCliOwnedNativeInstall,
  ownedCursorTreeFiles,
  LOCKFILE_VERSION,
  otherPluginSkillNames,
  pluginAgentNames,
  pluginSkillNames,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  pruneMissingLockEntries,
  readLockfile,
  reconcileLock,
  skillNamesFromFiles,
  writeLockfile,
} from "./lockfile.js";
import { resolveScope } from "./options.js";
import { getPackageVersion } from "./package-version.js";
import {
  defaultStoreRoot,
  destSkillIsSymlink,
  destUsesCopyMaterialization,
  discardExplodeBackups,
  explodePlugin,
  pruneEmptyAncestors,
  pruneEmptyDirTrees,
  removeExplodedFiles,
  resolveExplodeSourceSkills,
  resolveTrackedPath,
  restoreExplodeInstall,
  snapshotDestPath,
  unlinkDestSkillSymlink,
  warnSkippedExplodeDests,
} from "./projectors/explode.js";
import { installCliPlugin, uninstallCliPlugin } from "./projectors/native-cli.js";
import {
  cursorPluginsRoot,
  discardCursorPluginBackup,
  findCatalogSourceRoot,
  installCursorPlugin,
  restoreCursorPluginInstall,
} from "./projectors/native-cursor.js";
import { buildSkillsArguments, runSkills } from "./skills-runner.js";

/**
 * Refresh lock-managed plugins using the current package tag or vendor registry pins.
 *
 * Entries absent from every tracked agent directory are pruned instead of reinstalled.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{
 *   exec?: (command: string, args: string[]) => Promise<{status: number, stderr: string, stdout: string}>,
 *   explode?: typeof explodePlugin,
 *   hash?: typeof import("./lockfile.js").hashFile,
 *   isInstalled?: Parameters<typeof pruneMissingLockEntries>[1],
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   move?: typeof import("node:fs/promises").rename,
 *   now?: () => Date,
 *   readLock?: typeof readLockfile,
 *   rmdir?: typeof rmdir,
 *   run?: typeof runSkills,
 *   sourceRoot?: string | null,
 *   sourceSkills?: Record<string, string>,
 *   storeRoot?: string,
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
  /** @type {Record<string, Record<string, Record<string, string>>>} */
  const explodeClaimsByPlugin = {};
  const hash = dependencies.hash ?? hashFile;
  const removeFile = dependencies.unlink ?? unlink;
  const removeDir = dependencies.rmdir ?? rmdir;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const cursorBackups = [];
  /** @type {import("./projectors/explode.js").ExplodeResult[]} */
  const explodeBackups = [];
  /** @type {Array<{backup: string, dest: string}>} */
  const staleDestBackups = [];
  let lockCommitted = false;
  try {
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
        const explodeSources = resolveExplodeSourceSkills(
          skills,
          dependencies,
          entry.vendor === "lgtm-hq"
            ? dependencies.sourceRoot !== undefined
              ? dependencies.sourceRoot
              : findCatalogSourceRoot(dependencies.lockEnvironment?.cwd ?? process.cwd())
            : null,
        );
        if (explodeSources) {
          const explode = dependencies.explode ?? explodePlugin;
          const exploded = await explode({
            agents: await Promise.all(
              lanes.explode.map(async (agent) => {
                const root = entry.agents[agent].root;
                const files = entry.agents[agent]?.files ?? {};
                return {
                  id: agent,
                  copy: await destUsesCopyMaterialization(root, [
                    ...new Set([...skills, ...skillNamesFromFiles(files)]),
                  ]),
                  replace: new Set(skillNamesFromFiles(files)),
                  root,
                };
              }),
            ),
            copy: false,
            hash,
            keepBackups: true,
            skills,
            sourceSkills: explodeSources,
            destRoots: allAgentSkillRoots(scope, dependencies.lockEnvironment, prunedLock),
            retainStoreSkills: otherPluginSkillNames(prunedLock, pluginId),
            storeRoot:
              dependencies.storeRoot ?? defaultStoreRoot(scope, dependencies.lockEnvironment),
          });
          explodeClaimsByPlugin[pluginId] = exploded.claimed;
          explodeBackups.push(exploded);
          warnSkippedExplodeDests(exploded.skipped, warn);
        } else {
          // Vendor / non-checkout first-party still uses the skills CLI.
          const copyAgents = [];
          const symlinkAgents = [];
          for (const agent of lanes.explode) {
            const root = entry.agents[agent].root;
            const files = entry.agents[agent]?.files ?? {};
            const names = [...new Set([...skills, ...skillNamesFromFiles(files)])];
            if (await destUsesCopyMaterialization(root, names)) {
              copyAgents.push(agent);
            } else {
              symlinkAgents.push(agent);
            }
          }
          for (const [agents, copy] of [
            [symlinkAgents, false],
            [copyAgents, true],
          ]) {
            if (agents.length === 0) {
              continue;
            }
            await run(
              buildSkillsArguments(
                {
                  ...scopedOptions,
                  agents,
                  copy,
                  onConflict: "overwrite",
                  skills,
                },
                source,
              ),
            );
          }
        }
      }
      if (lanes.cursorNative.length > 0) {
        const cursorProgress = { swapped: false };
        try {
          cursorBackups.push(
            await rematerializeCursorPlugin(
              pluginId,
              entry,
              skills,
              dependencies,
              prunedLock.scope,
              cursorProgress,
            ),
          );
        } catch (error) {
          if (cursorProgress.swapped && cursorProgress.destRoot) {
            cursorBackups.push({
              destRoot: cursorProgress.destRoot,
              pluginId,
              swapped: true,
            });
          }
          throw error;
        }
      }
      for (const agent of lanes.cliNative) {
        await installCliPlugin({
          agent,
          exec: dependencies.exec,
          pluginId,
          source,
        });
      }
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
        explodeClaimsByPlugin[pluginId],
      );
      if (Object.keys(hashed.agents).length === 0) {
        continue;
      }
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
    for (const pluginId of updated) {
      const entry = selected[pluginId];
      await removeStalePluginSkills(pluginId, entry, catalogSkills[pluginId] ?? [], {
        catalogSkills,
        hash,
        lock: prunedLock,
        pluginId,
        removeDir,
        removeFile,
        staleDestBackups,
        warn,
      });
    }
    await writeLock({
      ...prunedLock,
      gatewayVersion: getPackageVersion(),
      plugins,
    });
    lockCommitted = true;
    for (const item of explodeBackups) {
      try {
        await discardExplodeBackups(item);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        warn(`Warning: could not discard explode backups after update (${detail})`);
      }
    }
    for (const item of cursorBackups) {
      try {
        await discardCursorPluginBackup(item);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        warn(`Warning: could not discard Cursor plugin backup after update (${detail})`);
      }
    }
    try {
      await discardExplodeBackups({ swappedDests: staleDestBackups });
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      warn(`Warning: could not discard stale dest backups after update (${detail})`);
    }
    return { pruned, updated };
  } catch (error) {
    const restoreErrors = [];
    if (!lockCommitted) {
      try {
        await restoreExplodeInstall(
          { swappedDests: staleDestBackups },
          {
            move: dependencies.move,
            remove: dependencies.remove,
          },
        );
      } catch (restoreError) {
        restoreErrors.push(restoreError);
      }
      for (const item of explodeBackups) {
        try {
          await restoreExplodeInstall(item, {
            move: dependencies.move,
            remove: dependencies.remove,
          });
        } catch (restoreError) {
          restoreErrors.push(restoreError);
        }
      }
      for (const item of cursorBackups) {
        try {
          await restoreCursorPluginInstall({
            ...item,
            created: !item.swapped,
            move: dependencies.move,
          });
        } catch (restoreError) {
          restoreErrors.push(restoreError);
        }
      }
      if (restoreErrors.length > 0) {
        const original = error instanceof Error ? error.message : String(error);
        const restore = restoreErrors
          .map((item) => (item instanceof Error ? item.message : String(item)))
          .join("; ");
        throw new Error(`${original} (update restore also failed: ${restore})`);
      }
    }
    throw error;
  }
}

/**
 * Remove selected lock-managed plugins, persist the lock removal, then uninstall host CLIs.
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
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const hash = dependencies.hash ?? hashFile;
  const removeFile = dependencies.unlink ?? unlink;
  const removeDir = dependencies.rmdir ?? rmdir;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const lock = await readLock(scope);
  const selected = Object.keys(selectPlugins(lock.plugins, options.skills));
  if (selected.length === 0) {
    return [];
  }
  /** @type {Array<{agent: string, pluginId: string}>} */
  const pendingCliUninstall = [];
  for (const pluginId of selected) {
    const entry = lock.plugins[pluginId];
    const explodeFiles = explodeTrackedFiles(entry);
    if (explodeFiles.length > 0) {
      await removeExplodedFiles({
        files: explodeFiles,
        hash,
        pluginId,
        removeDir,
        removeFile,
        warn,
      });
    }
    const classified = await classifyPluginFiles(pluginId, entry, { hash, warn });
    const lanes = partitionLockedLanes(entry);
    await deleteVerifiedFiles(classified.verified, {
      modifiedSkills: classified.modifiedSkills,
      removeDir,
      removeFile,
    });
    for (const agent of lanes.cursorNative) {
      const pluginDir = entry.agents[agent]?.root;
      if (!pluginDir) {
        continue;
      }
      try {
        await removeDir(pluginDir);
      } catch {
        // Untracked files remain; keep the folder.
      }
    }
    for (const agent of lanes.cliNative) {
      if (
        await siblingLockHasCliNative(
          pluginId,
          agent,
          scope,
          readLock,
          dependencies.lockEnvironment,
        )
      ) {
        continue;
      }
      pendingCliUninstall.push({ agent, pluginId });
    }
  }
  const plugins = { ...lock.plugins };
  selected.forEach((pluginId) => delete plugins[pluginId]);
  await writeLock({
    ...lock,
    plugins,
  });
  /** @type {Map<string, Set<string>>} */
  const remainingAgents = new Map();
  for (const item of pendingCliUninstall) {
    const agents = remainingAgents.get(item.pluginId) ?? new Set();
    agents.add(item.agent);
    remainingAgents.set(item.pluginId, agents);
  }
  try {
    for (const item of pendingCliUninstall) {
      await uninstallCliPlugin({
        agent: item.agent,
        exec: dependencies.exec,
        pluginId: item.pluginId,
      });
      const agents = remainingAgents.get(item.pluginId);
      if (!agents) {
        continue;
      }
      agents.delete(item.agent);
      if (agents.size === 0) {
        remainingAgents.delete(item.pluginId);
      }
    }
  } catch (error) {
    await restoreLockAfterCliUninstallFailure({
      lock,
      plugins,
      remainingAgents,
      warn,
      writeLock,
    });
    throw error;
  }
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
  const lock = await readLock(resolveScope(options), dependencies.lockEnvironment);
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
 * Existing dest skill directories are snapshotted first so a later lock-write
 * failure can restore paths the previous lock still claims.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Pre-update lock entry.
 * @param {string[]} currentSkills - Skill names in the current catalog.
 * @param {{
 *   catalogSkills?: Record<string, string[]>,
 *   hash: typeof hashFile,
 *   lock?: import("./lockfile.js").GatewayLock,
 *   removeDir: typeof rmdir,
 *   removeFile: typeof unlink,
 *   staleDestBackups?: Array<{backup: string, dest: string}>,
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
  const keepDest = (dest, relative) =>
    Boolean(
      dest &&
      io.lock &&
      otherPluginsKeepStaleDest(
        pluginId,
        dest,
        [...skillNamesFromFiles({ [relative]: "" })][0] ?? "",
        io.lock,
        io.catalogSkills ?? {},
      ),
    );
  if (io.staleDestBackups) {
    await snapshotStaleSkillDests(entry, staleNames, io.staleDestBackups, keepDest);
  }
  const stale = {
    ...entry,
    skills: staleNames,
    agents: Object.fromEntries(
      Object.entries(entry.agents).map(([agent, install]) => [
        agent,
        {
          ...install,
          files: Object.fromEntries(
            Object.entries(install.files).filter(([relative]) => {
              if (!skillNamesBelongTo(relative, staleNames)) {
                return false;
              }
              return !keepDest(staleSkillDestPath(install.root, relative), relative);
            }),
          ),
        },
      ]),
    ),
  };
  const explodeFiles = explodeTrackedFiles(stale);
  if (explodeFiles.length > 0) {
    await removeExplodedFiles({
      files: explodeFiles,
      hash: io.hash,
      pluginId,
      removeDir: io.removeDir,
      removeFile: io.removeFile,
      warn: io.warn,
    });
  }
  const classified = await classifyPluginFiles(pluginId, stale, { hash: io.hash, warn: io.warn });
  await deleteVerifiedFiles(classified.verified, {
    modifiedSkills: classified.modifiedSkills,
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
 * @param {Record<string, Record<string, string>>} [explodeClaims] - Owned explode
 *   files from this update (skipped dests omitted). Absent when the CLI fallback ran,
 *   in which case explode dests are hashed as full skill trees.
 * @returns {Promise<import("./lockfile.js").PluginLockEntry>} Entry with rebuilt file maps.
 */
async function rematerializePluginFiles(entry, skillNames, hash, explodeClaims) {
  const current = new Set(skillNames);
  const agents = {};
  for (const [agent, install] of Object.entries(entry.agents)) {
    const projector = agentProjector(entry, agent);
    if (projector === PROJECTOR_EXPLODE) {
      if (explodeClaims) {
        const claimed = explodeClaims[agent];
        if (claimed && Object.keys(claimed).length > 0) {
          agents[agent] = { ...install, files: claimed };
          continue;
        }
        const retained = {};
        for (const [relative, digest] of Object.entries(install.files)) {
          if (current.has(relative.split("/")[0])) {
            retained[relative] = digest;
          }
        }
        if (Object.keys(retained).length > 0) {
          agents[agent] = { ...install, files: retained };
        }
        continue;
      }
      const files = await hashCliExplodeDestFiles(install.root, skillNames, hash);
      if (Object.keys(files).length > 0) {
        agents[agent] = { ...install, files };
      }
      continue;
    }
    if (projector === PROJECTOR_NATIVE && agent === "cursor") {
      agents[agent] = {
        ...install,
        files: ownedCursorTreeFiles(await hashTree(install.root, hash), skillNames),
      };
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
      } catch (error) {
        if (!isAbsentFsError(error)) {
          throw error;
        }
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
      } catch (error) {
        if (!isAbsentFsError(error)) {
          throw error;
        }
        files[relative] = "";
      }
    }
    agents[agent] = { ...install, files };
  }
  return { ...entry, agents };
}

/**
 * Hash explode dest skill trees after a skills-CLI fallback update.
 *
 * Matches install ``createLockEntries``: walk each current skill directory so
 * nested files are locked. An empty or missing dest falls back to a
 * ``SKILL.md`` sentinel (detect-mode mocks). A dest that is a file hashes as
 * ``SKILL.md``.
 *
 * @param {string} root - Agent skills root from the lock.
 * @param {string[]} skillNames - Current catalog skill names.
 * @param {typeof hashFile} hash - Injectable hasher.
 * @returns {Promise<Record<string, string>>} Relative path to digest.
 */
async function hashCliExplodeDestFiles(root, skillNames, hash) {
  const files = {};
  for (const name of skillNames) {
    const skillDir = join(root, name);
    let tree = {};
    try {
      tree = await hashTree(skillDir, hash);
    } catch (error) {
      if (error && typeof error === "object" && "code" in error && error.code === "ENOTDIR") {
        try {
          files[`${name}/SKILL.md`] = await hash(skillDir);
        } catch (hashError) {
          if (!isAbsentFsError(hashError)) {
            throw hashError;
          }
          files[`${name}/SKILL.md`] = "";
        }
        continue;
      }
      throw error;
    }
    if (Object.keys(tree).length === 0) {
      const relative = `${name}/SKILL.md`;
      try {
        files[relative] = await hash(join(skillDir, "SKILL.md"));
      } catch (error) {
        if (!isAbsentFsError(error)) {
          throw error;
        }
        files[relative] = "";
      }
      continue;
    }
    for (const [relative, digest] of Object.entries(tree)) {
      files[`${name}/${relative}`] = digest;
    }
  }
  return files;
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
 * Snapshot catalog-retired skill dests before hash-verified unlink.
 *
 * Dest skill directories are copied (symlink-preserving) so a later lock-write
 * failure can restore paths the previous lock still claims.
 *
 * @param {import("./lockfile.js").PluginLockEntry} entry - Pre-update lock entry.
 * @param {string[]} staleNames - Skill names leaving the catalog.
 * @param {Array<{backup: string, dest: string}>} backups - Accumulator for restore/discard.
 * @param {(dest: string | null, relative: string) => boolean} [keepDest] - Skip dests another plugin still catalogs.
 * @returns {Promise<void>} Resolves when existing dests are snapshotted.
 */
async function snapshotStaleSkillDests(entry, staleNames, backups, keepDest = () => false) {
  const seen = new Set();
  for (const install of Object.values(entry.agents)) {
    if (isCliOwnedNativeInstall(install, entry.projector)) {
      continue;
    }
    for (const relative of Object.keys(install.files)) {
      if (!skillNamesBelongTo(relative, staleNames)) {
        continue;
      }
      const dest = staleSkillDestPath(install.root, relative);
      if (!dest || seen.has(dest) || keepDest(dest, relative)) {
        continue;
      }
      seen.add(dest);
      const snapshot = await snapshotDestPath(dest);
      if (snapshot) {
        backups.push(snapshot);
      }
    }
  }
}

/**
 * Dest skill directory for a tracked relative path.
 *
 * Exploded installs use ``<skill>/...``. Cursor native trees use
 * ``skills/<skill>/...``.
 *
 * @param {string} root - Agent skills root from the lock.
 * @param {string} relative - Tracked path relative to that root.
 * @returns {string | null} Skill directory to snapshot, or null when the path is metadata.
 */
function staleSkillDestPath(root, relative) {
  const parts = relative.split("/");
  if (parts[0] === ".claude-plugin") {
    return null;
  }
  if (parts[0] === "skills" && parts[1]) {
    return join(root, "skills", parts[1]);
  }
  if (parts[0]) {
    return join(root, parts[0]);
  }
  return null;
}

/**
 * Whether another lock plugin still catalogs this skill at the same dest root.
 *
 * A skill-move in one update must not let the retiring plugin unlink a dest
 * the surviving plugin skipped or still catalogs.
 *
 * @param {string} pluginId - Plugin whose stale dests are being considered.
 * @param {string} dest - Absolute dest skill directory.
 * @param {string} skillName - Skill directory name.
 * @param {import("./lockfile.js").GatewayLock} lock - Pre-update lock.
 * @param {Record<string, string[]>} catalogSkills - Current catalog names for plugins in this update.
 * @returns {boolean} True when another plugin still wants this dest.
 */
function otherPluginsKeepStaleDest(pluginId, dest, skillName, lock, catalogSkills) {
  if (!skillName) {
    return false;
  }
  for (const [otherId, other] of Object.entries(lock.plugins ?? {})) {
    if (otherId === pluginId) {
      continue;
    }
    const names = catalogSkills[otherId] ?? pluginSkillNames(other);
    if (!names.includes(skillName)) {
      continue;
    }
    for (const install of Object.values(other.agents ?? {})) {
      if (isCliOwnedNativeInstall(install, other.projector)) {
        continue;
      }
      if (typeof install.root !== "string" || install.root.startsWith("cli:")) {
        continue;
      }
      if (
        dest === join(install.root, skillName) ||
        dest === join(install.root, "skills", skillName)
      ) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Lock-owned explode files for hash-verified dest unlink.
 *
 * @param {import("./lockfile.js").PluginLockEntry} entry - Plugin lock entry.
 * @returns {Array<{absolute: string, digest: string, relative: string, root: string}>}
 *   Files owned by explode-projected agents.
 */
function explodeTrackedFiles(entry) {
  /** @type {Array<{absolute: string, digest: string, relative: string, root: string}>} */
  const files = [];
  for (const [agent, install] of Object.entries(entry.agents)) {
    if (agentProjector(entry, agent) !== PROJECTOR_EXPLODE) {
      continue;
    }
    for (const [relative, digest] of Object.entries(install.files)) {
      files.push({
        absolute: resolveTrackedPath(install.root, relative),
        digest,
        relative,
        root: install.root,
      });
    }
  }
  return files;
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
 *   modifiedSkills: Set<string>,
 *   removableSkills: string[],
 *   verified: Array<{absolute: string, relative: string, root: string}>,
 * }>} Skills safe to pass upstream and files safe to unlink.
 */
async function classifyPluginFiles(pluginId, entry, io) {
  /** @type {Set<string>} */
  const modifiedSkills = new Set();
  /** @type {Array<{absolute: string, root: string}>} */
  const verified = [];
  for (const [agent, install] of Object.entries(entry.agents)) {
    if (isCliOwnedNativeInstall(install, entry.projector)) {
      continue;
    }
    if (agentProjector(entry, agent) === PROJECTOR_EXPLODE) {
      continue;
    }
    for (const [relative, digest] of Object.entries(install.files)) {
      const absolute = resolveTrackedPath(install.root, relative);
      try {
        const current = await hashLockEntryPath(absolute, io.hash);
        if (current !== digest) {
          io.warn(`left modified ${pluginId} file ${relative}`);
          for (const skillName of skillNamesFromFiles({ [relative]: digest })) {
            modifiedSkills.add(skillName);
          }
          continue;
        }
        verified.push({ absolute, relative, root: install.root });
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
    modifiedSkills,
    removableSkills: pluginSkillNames(entry).filter((name) => !modifiedSkills.has(name)),
    verified,
  };
}

/**
 * Unlink hash-matching files and prune empty directory trees.
 *
 * @param {Array<{absolute: string, relative?: string, root: string}>} verified - Files that matched the lock digest.
 * @param {{
 *   modifiedSkills?: Set<string>,
 *   removeDir: typeof rmdir,
 *   removeFile: typeof unlink,
 * }} io - Injectable filesystem.
 * @returns {Promise<void>} Resolves when verified deletes finish.
 */
async function deleteVerifiedFiles(verified, io) {
  /** @type {Map<string, string>} */
  const skillDirs = new Map();
  /** @type {Set<string>} */
  const skipSkillDirs = new Set();
  const modifiedSkills = io.modifiedSkills ?? new Set();
  for (const file of verified) {
    const skillName = (file.relative ?? "").split("/")[0];
    const skillDir = skillName ? join(file.root, skillName) : "";
    if (skillDir && !skipSkillDirs.has(skillDir)) {
      if (modifiedSkills.has(skillName) && (await destSkillIsSymlink(skillDir))) {
        skipSkillDirs.add(skillDir);
        continue;
      }
      if (await unlinkDestSkillSymlink(skillDir, io.removeFile)) {
        skipSkillDirs.add(skillDir);
        continue;
      }
    }
    if (skillDir && skipSkillDirs.has(skillDir)) {
      continue;
    }
    try {
      await io.removeFile(file.absolute);
      if (skillDir) {
        skillDirs.set(skillDir, file.root);
      }
      await pruneEmptyAncestors(dirname(file.absolute), file.root, io.removeDir);
    } catch (error) {
      if (isAbsentFsError(error)) {
        continue;
      }
      throw error;
    }
  }
  for (const [skillDir, root] of skillDirs) {
    await pruneEmptyDirTrees(skillDir, root, {
      readDir: (dir) => readdir(dir, { withFileTypes: true }),
      removeDir: io.removeDir,
    });
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
 * Whether the other gateway scope still records this plugin as CLI-native.
 *
 * Host CLIs are user-scoped; uninstalling while a sibling lock still owns the
 * plugin would strand that scope. Injected `readLock` helpers that ignore the
 * scope argument (and return the current lock) are treated as having no sibling.
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
  const entry = sibling.plugins[pluginId];
  if (!entry) {
    return false;
  }
  return partitionLockedLanes(entry).cliNative.includes(agent);
}

/**
 * Put plugins back in the lock when host CLI uninstall fails after the write.
 *
 * Lock removal is persisted before uninstall so a write failure cannot drop a
 * still-tracked host plugin. If uninstall then fails, restore only unfinished
 * CLI agents. Cursor-native and explode lanes are already deleted before the
 * lock write; restamping them would report MISSING and rematerialize on update.
 *
 * @param {object} args - Named arguments.
 * @param {import("./lockfile.js").GatewayLock} args.lock - Lock snapshot from before this remove.
 * @param {import("./lockfile.js").GatewayLock["plugins"]} args.plugins - Lock plugins after this remove.
 * @param {Map<string, Set<string>>} args.remainingAgents - Unfinished CLI agents by plugin id.
 * @param {(message: string) => void} args.warn - Warning sink.
 * @param {typeof writeLockfile} args.writeLock - Lock writer.
 * @returns {Promise<void>} Resolves after restore or a failed restore warning.
 */
async function restoreLockAfterCliUninstallFailure(args) {
  if (args.remainingAgents.size === 0) {
    return;
  }
  const restoredPlugins = { ...args.plugins };
  for (const [pluginId, remaining] of args.remainingAgents) {
    const original = args.lock.plugins[pluginId];
    /** @type {import("./lockfile.js").PluginLockEntry["agents"]} */
    const restoredAgents = {};
    for (const agent of remaining) {
      const install = original.agents[agent];
      if (install) {
        restoredAgents[agent] = install;
      }
    }
    if (Object.keys(restoredAgents).length === 0) {
      continue;
    }
    const restoredEntry = {
      ...original,
      agents: restoredAgents,
    };
    const projectorValues = Object.keys(restoredAgents).map((agent) =>
      agentProjector(restoredEntry, agent),
    );
    restoredPlugins[pluginId] = {
      ...restoredEntry,
      projector: projectorValues.every((value) => value === PROJECTOR_NATIVE)
        ? PROJECTOR_NATIVE
        : PROJECTOR_EXPLODE,
    };
  }
  try {
    await args.writeLock({
      ...args.lock,
      plugins: restoredPlugins,
    });
  } catch (restoreError) {
    const detail = restoreError instanceof Error ? restoreError.message : String(restoreError);
    args.warn(`Warning: could not restore lock after CLI uninstall failure (${detail})`);
  }
}

/**
 * Re-assemble a Cursor-local plugin tree from the current catalog membership.
 *
 * @param {string} pluginId - Plugin id.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Lock entry.
 * @param {string[]} skills - Current catalog skill names.
 * @param {{
 *   lockEnvironment?: Parameters<typeof reconcileLock>[1],
 *   move?: typeof import("node:fs/promises").rename,
 *   sourceRoot?: string | null,
 * }} dependencies - Injectable catalog root and paths.
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{destRoot?: string, swapped?: boolean}} [progress] - Filled with dest root; `swapped` after dest→`.bak`.
 * @returns {Promise<{destRoot: string, pluginId: string, swapped: boolean}>} Dest root and whether dest was swapped aside.
 */
async function rematerializeCursorPlugin(
  pluginId,
  entry,
  skills,
  dependencies,
  scope,
  progress = {},
) {
  if (entry.vendor !== "lgtm-hq") {
    throw new Error("Native Cursor projector is first-party only");
  }
  const sourceRoot =
    dependencies.sourceRoot !== undefined
      ? dependencies.sourceRoot
      : findCatalogSourceRoot(dependencies.lockEnvironment?.cwd ?? process.cwd());
  if (!sourceRoot) {
    throw new Error(
      "Native Cursor projector requires a catalog checkout (skills/ + " +
        ".claude-plugin/marketplace.json). Run update from the ai-skills " +
        "repository, or remove and reinstall with --projector explode.",
    );
  }
  const destRoot = cursorPluginsRoot({
    cwd: dependencies.lockEnvironment?.cwd,
    home: dependencies.lockEnvironment?.home,
    scope,
  });
  progress.destRoot = destRoot;
  const bundles = await loadBundles();
  await installCursorPlugin({
    commit: false,
    description: bundles.groups[pluginId]?.description ?? pluginId,
    destRoot,
    move: dependencies.move,
    pluginId,
    progress,
    replace: true,
    skills,
    sourceRoot,
    version: getPackageVersion(),
  });
  return { destRoot, pluginId, swapped: Boolean(progress.swapped) };
}

/**
 * Whether a tracked relative path belongs to one of the named skills.
 *
 * @param {string} relative - Path relative to the agent root.
 * @param {string[]} names - Skill directory names.
 * @returns {boolean} True when the path is inside one of those skills.
 */
function skillNamesBelongTo(relative, names) {
  const wanted = new Set(names);
  for (const name of skillNamesFromFiles({ [relative]: "" })) {
    if (wanted.has(name)) {
      return true;
    }
  }
  return false;
}
