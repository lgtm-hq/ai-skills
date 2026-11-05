import { readdir, rmdir, unlink } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { loadBakedPlugin, loadBundles, loadVendorIndex, loadVendors } from "./catalog.ts";
import {
  agentProjector,
  allAgentSkillRoots,
  hashFile,
  hashLockEntryPath,
  isCliOwnedNativeInstall,
  LOCKFILE_VERSION,
  otherPluginSkillNames,
  pluginAgentNames,
  pluginSkillNames,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  pruneMissingLockEntries,
  reconcileLock,
  skillNamesFromFiles,
} from "./lockfile.ts";
import { resolveScope } from "./options.ts";
import { getPackageVersion } from "./package-version.ts";
import { nativeRoute } from "./adapters/hosts.ts";
import { findCatalogSourceRoot, ownedPluginTreeFiles } from "./adapters/cursor/drop.ts";
import { assertPlansInsideRoots, PlanApplyError, planOps } from "./adapters/execute.ts";
import { cliUninstallOp } from "./adapters/shared/native-cli.ts";
import {
  defaultStoreRoot,
  destSkillIsSymlink,
  pruneEmptyAncestors,
  pruneEmptyDirTrees,
  removeExplodedFiles,
  resolveExplodeSourceSkills,
  resolveTrackedPath,
  unlinkDestSkillSymlink,
} from "./adapters/shared/skill-explode.ts";
import type { AdapterPlan } from "./adapters/types.ts";
import { adapterFingerprints, composeInstallPlans, irreversibleEffects } from "./install-plan.ts";
import { readInstallState } from "./journal/receipts.ts";
import { withStateSession } from "./journal/recover.ts";
import type { DynamicOps, JournalHooks } from "./journal/recover.ts";
import { runSkills, unmanagedRequiredMessage } from "./skills-runner.ts";

/**
 * Refresh lock-managed plugins using the current package tag or vendor registry pins.
 *
 * Entries absent from every tracked agent directory are pruned instead of
 * reinstalled. Every lane is re-planned through its adapter and applied in one
 * journaled transaction; skills that left the catalog are removed (hash
 * verified) in the same transaction, and the receipt commits it.
 */
export async function updateSkills(
  options: {
    agents: string[];
    global: boolean;
    project: boolean;
    skills: string[];
    yes: boolean;
    keepGenerations?: number | null;
  },
  dependencies: {
    exec?: (
      command: string,
      args: string[],
    ) => Promise<{ status: number; stderr: string; stdout: string }>;
    hash?: typeof import("./lockfile.ts").hashFile;
    isInstalled?: Parameters<typeof pruneMissingLockEntries>[1];
    journal?: JournalHooks;
    lockEnvironment?: Parameters<typeof reconcileLock>[1];
    now?: () => Date;
    run?: typeof runSkills;
    sourceRoot?: string | null;
    sourceSkills?: Record<string, string>;
    storeRoot?: string;
    warn?: (message: string) => void;
  } = {},
): Promise<{ pruned: string[]; updated: string[] }> {
  const scope = resolveScope(options);
  const now = dependencies.now ?? (() => new Date());
  const hash = dependencies.hash ?? hashFile;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const environment = dependencies.lockEnvironment ?? {};
  return withStateSession(
    {
      env: environment,
      hooks: dependencies.exec ? { exec: dependencies.exec } : {},
      report: warn,
      scope,
      ...(dependencies.journal?.lockWaitMs === undefined
        ? {}
        : { lockWaitMs: dependencies.journal.lockWaitMs }),
    },
    async (session) => {
      const { lock: prunedLock, pruned } = await pruneMissingLockEntries(
        session.view,
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
      if (updated.length === 0 && pruned.length === 0) {
        return { pruned, updated };
      }
      const catalogSkills: Record<string, string[]> = {};
      const owned: Record<
        string,
        Record<string, { root: string; files: Record<string, string> }>
      > = {};
      const plans: AdapterPlan[] = [];
      for (const pluginId of updated) {
        const entry = selected[pluginId]!;
        const skills = await currentPluginSkills(pluginId, entry);
        catalogSkills[pluginId] = skills;
        if (entry.vendor !== "lgtm-hq") {
          // Fails closed when the vendor left the registry.
          resolveVendorSource(entry, vendors);
        }
        const composition = await updateComposition(pluginId, entry, skills, {
          dependencies,
          lock: prunedLock,
          scope: prunedLock.scope,
        });
        const pluginPlans = await composeInstallPlans(composition);
        plans.push(...pluginPlans);
        owned[pluginId] = Object.fromEntries(
          pluginPlans.flatMap((plan) => (plan.owns ? [[plan.host, plan.owns]] : [])),
        );
      }
      await assertPlansInsideRoots(plans);
      for (const note of plans.flatMap((plan) => plan.notes)) {
        warn(note);
      }
      for (const effect of irreversibleEffects(plans)) {
        warn(`note: ${effect} is not undone by rollback`);
      }
      const installedAt = now().toISOString();
      const plugins: Record<string, import("./lockfile.ts").PluginLockEntry> = {};
      for (const [pluginId, entry] of Object.entries(prunedLock.plugins)) {
        if (!updated.includes(pluginId)) {
          plugins[pluginId] = entry;
          continue;
        }
        const hashed = await rematerializePluginFiles(
          entry,
          catalogSkills[pluginId] ?? pluginSkillNames(entry),
          hash,
          owned[pluginId] ?? {},
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
              : ((await loadBakedPlugin(pluginId))?.version ??
                sourceSha(entry.vendor, entry.sha, vendors)),
        };
      }
      const stale = updated.filter((pluginId) =>
        pluginSkillNames(selected[pluginId]!).some(
          (name) => !(catalogSkills[pluginId] ?? []).includes(name),
        ),
      );
      try {
        await session.transact({
          hooks: dependencies.journal,
          keepGenerations: options.keepGenerations,
          kind: "update",
          next: {
            artifactDigest: null,
            fingerprints: { adapters: adapterFingerprints(plans), policy: null },
            plugins,
          },
          ops: planOps(plans),
          ...(stale.length === 0
            ? {}
            : {
                dynamic: async (ops: DynamicOps) => {
                  for (const pluginId of stale) {
                    await removeStalePluginSkills(
                      pluginId,
                      selected[pluginId]!,
                      catalogSkills[pluginId] ?? [],
                      {
                        catalogSkills,
                        hash,
                        lock: prunedLock,
                        pluginId,
                        removeDir: (path) => ops.removeDir(String(path)),
                        removeFile: (path) => ops.removeFile(String(path)),
                        warn,
                      },
                    );
                  }
                },
                dynamicOrigin: {
                  origin: { adapter: "gateway", host: "", owner: "" },
                  roots: stale.flatMap((pluginId) => installRoots(selected[pluginId]!)),
                },
              }),
        });
      } catch (error) {
        if (error instanceof PlanApplyError) {
          throw new Error(`Update rolled back: ${error.message}`);
        }
        throw error;
      }
      return { pruned, updated };
    },
  );
}

/**
 * Remove selected lock-managed plugins in one journaled transaction.
 *
 * Owned files are removed only when their hash still matches (modified ones
 * are kept and reported), CLI-native hosts are uninstalled inside the same
 * transaction, and the receipt drops the plugins at commit. A failure undoes
 * every removal from the journal's preimages.
 */
export async function removeSkills(
  options: {
    agents: string[];
    global: boolean;
    project: boolean;
    skills: string[];
    yes: boolean;
    keepGenerations?: number | null;
  },
  dependencies: {
    exec?: (
      command: string,
      args: string[],
    ) => Promise<{ status: number; stderr: string; stdout: string }>;
    hash?: typeof hashFile;
    journal?: JournalHooks;
    lockEnvironment?: Parameters<typeof reconcileLock>[1];
    run?: typeof runSkills;
    warn?: (message: string) => void;
  } = {},
): Promise<string[]> {
  const scope = resolveScope(options);
  const hash = dependencies.hash ?? hashFile;
  const warn = dependencies.warn ?? ((message) => console.warn(message));
  const environment = dependencies.lockEnvironment ?? {};
  return withStateSession(
    {
      env: environment,
      hooks: dependencies.exec ? { exec: dependencies.exec } : {},
      report: warn,
      scope,
      ...(dependencies.journal?.lockWaitMs === undefined
        ? {}
        : { lockWaitMs: dependencies.journal.lockWaitMs }),
    },
    async (session) => {
      const lock = session.view;
      const selected = Object.keys(selectPlugins(lock.plugins, options.skills));
      if (selected.length === 0) {
        return [];
      }
      const plugins = { ...lock.plugins };
      selected.forEach((pluginId) => delete plugins[pluginId]);
      try {
        await session.transact({
          dynamic: async (ops) => {
            for (const pluginId of selected) {
              await removePlugin(pluginId, lock.plugins[pluginId]!, ops, {
                environment,
                hash,
                scope,
                warn,
              });
            }
          },
          dynamicOrigin: {
            origin: { adapter: "gateway", host: "", owner: "" },
            roots: selected.flatMap((pluginId) => installRoots(lock.plugins[pluginId]!)),
          },
          hooks: dependencies.journal,
          keepGenerations: options.keepGenerations,
          kind: "remove",
          next: {
            artifactDigest: session.receipt?.artifactDigest ?? null,
            fingerprints: { adapters: {}, policy: session.receipt?.fingerprints.policy ?? null },
            plugins,
          },
          ops: [],
        });
      } catch (error) {
        if (error instanceof PlanApplyError) {
          throw new Error(`Remove rolled back: ${error.message}`);
        }
        throw error;
      }
      return selected;
    },
  );
}

/**
 * Journaled removal of one plugin: hash-verified deletes, then host uninstall.
 */
async function removePlugin(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  ops: DynamicOps,
  context: {
    environment: Parameters<typeof reconcileLock>[1];
    hash: typeof hashFile;
    scope: "global" | "project";
    warn: (message: string) => void;
  },
): Promise<void> {
  const removeFile = (path: unknown) => ops.removeFile(String(path));
  const removeDir = (path: unknown) => ops.removeDir(String(path));
  const explodeFiles = explodeTrackedFiles(entry);
  if (explodeFiles.length > 0) {
    await removeExplodedFiles({
      files: explodeFiles,
      hash: context.hash,
      pluginId,
      removeDir,
      removeFile,
      warn: context.warn,
    });
  }
  const classified = await classifyPluginFiles(pluginId, entry, {
    hash: context.hash,
    warn: context.warn,
  });
  const lanes = partitionLockedLanes(entry);
  await deleteVerifiedFiles(classified.verified, {
    modifiedSkills: classified.modifiedSkills,
    removeDir,
    removeFile,
  });
  for (const agent of lanes.treeNative) {
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
        context.scope,
        readInstallState,
        context.environment,
      )
    ) {
      continue;
    }
    await ops.exec(cliUninstallOp(agent, pluginId), {
      adapter: "gateway",
      host: agent,
      owner: pluginId,
    });
  }
}

/**
 * Filesystem roots a plugin record owns paths under (CLI records own none).
 */
function installRoots(entry: import("./lockfile.ts").PluginLockEntry): string[] {
  return Object.values(entry.agents).flatMap((install) =>
    typeof install.root === "string" && !install.root.startsWith("cli:") ? [install.root] : [],
  );
}

/**
 * List lock-managed plugins for the selected scope.
 */
export async function listSkills(
  options: { global: boolean; project: boolean },
  dependencies: {
    lockEnvironment?: Parameters<typeof reconcileLock>[1];
    readLock?: typeof readInstallState;
  } = {},
): Promise<
  Array<
    {
      agentNames: string[];
      agentStatus: Record<string, "" | "MISSING" | "MODIFIED">;
      name: string;
      skills: string[];
      status: "" | "MISSING" | "MODIFIED";
    } & import("./lockfile.ts").PluginLockEntry
  >
> {
  const readLock = dependencies.readLock ?? readInstallState;
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
      status: statusByPlugin.get(name) ?? ("" as const),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/**
 * Whether a plugin pin moved or tracked files drifted.
 */
async function pluginNeedsRefresh(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  scope: "global" | "project",
  vendors: Array<{ id: string; repo: string; sha: string }>,
  dependencies: { lockEnvironment?: Parameters<typeof reconcileLock>[1] },
): Promise<boolean> {
  const expectedSha = sourceSha(entry.vendor, entry.sha, vendors);
  const baked = entry.vendor === "lgtm-hq" ? null : await loadBakedPlugin(pluginId);
  const expectedVersion =
    entry.vendor === "lgtm-hq" ? getPackageVersion() : (baked?.version ?? expectedSha);
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
 * @throws {Error} When a requested plugin is not lock-managed.
 */
function selectPlugins(
  plugins: Record<string, import("./lockfile.ts").PluginLockEntry>,
  names: string[],
): Record<string, import("./lockfile.ts").PluginLockEntry> {
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
 * Resolve a vendor entry to its current registry pin (validation only now:
 * managed updates explode the baked tree and never fetch this source).
 *
 * @throws {Error} When a lock entry's vendor has been removed from the registry.
 */
function resolveVendorSource(
  entry: import("./lockfile.ts").PluginLockEntry,
  vendors: Array<{ id: string; repo: string; sha: string }>,
): string {
  const vendor = vendors.find((candidate) => candidate.id === entry.vendor);
  if (!vendor || vendor.repo !== entry.repo) {
    throw new Error(`Vendor is no longer available in the gateway registry: ${entry.vendor}`);
  }
  return `${vendor.repo}@${vendor.sha}`;
}

/**
 * Hash-verified delete of skills that left the catalog since the last commit.
 *
 * Runs inside the update transaction with journaled `removeFile`/`removeDir`,
 * so a later failure restores every removed path from its preimage.
 */
async function removeStalePluginSkills(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  currentSkills: string[],
  io: {
    catalogSkills?: Record<string, string[]>;
    pluginId?: string;
    hash: typeof hashFile;
    lock?: import("./lockfile.ts").GatewayLock;
    removeDir: typeof rmdir;
    removeFile: typeof unlink;
    warn: (message: string) => void;
  },
): Promise<void> {
  const current = new Set(currentSkills);
  const staleNames = pluginSkillNames(entry).filter((name) => !current.has(name));
  if (staleNames.length === 0) {
    return;
  }
  const keepDest = (dest: string | null, relative: string) =>
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
 */
async function currentPluginSkills(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
): Promise<string[]> {
  if (entry.vendor === "lgtm-hq") {
    const bundles = await loadBundles();
    const bundle = bundles.groups[pluginId];
    if (bundle) {
      return [...bundle.skills];
    }
  }
  const baked = await loadBakedPlugin(pluginId);
  if (baked && baked.vendor === entry.vendor) {
    return [...baked.skills];
  }
  if (pluginId === entry.vendor) {
    const index = await loadVendorIndex(entry.vendor);
    return index.skills.map((skill) => skill.name);
  }
  return pluginSkillNames(entry);
}

/**
 * Rebuild an entry's tracked files for the current plugin skill list.
 */
async function rematerializePluginFiles(
  entry: import("./lockfile.ts").PluginLockEntry,
  skillNames: string[],
  hash: typeof hashFile,
  owned: Record<string, { root: string; files: Record<string, string> }>,
): Promise<import("./lockfile.ts").PluginLockEntry> {
  const current = new Set(skillNames);
  const agents: Record<string, import("./lockfile.ts").AgentInstall> = {};
  for (const [agent, install] of Object.entries(entry.agents)) {
    const projector = agentProjector(entry, agent);
    if (projector === PROJECTOR_EXPLODE) {
      // Ownership comes from the plan's claims; skipped dests keep prior ownership.
      const claimed = owned[agent]?.files;
      if (claimed && Object.keys(claimed).length > 0) {
        agents[agent] = { ...install, files: claimed };
        continue;
      }
      const retained: Record<string, string> = {};
      for (const [relative, digest] of Object.entries(install.files)) {
        if (current.has(relative.split("/")[0]!)) {
          retained[relative] = digest;
        }
      }
      if (Object.keys(retained).length > 0) {
        agents[agent] = { ...install, files: retained };
      }
      continue;
    }
    if (projector === PROJECTOR_NATIVE && nativeRoute(agent)?.kind === "tree") {
      agents[agent] = {
        ...install,
        files: ownedPluginTreeFiles(owned[agent]?.files ?? {}, skillNames),
        root: owned[agent]?.root ?? install.root,
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
    const files: Record<string, string> = {};
    for (const relative of Object.keys(install.files)) {
      const name = relative.split("/")[0];
      if (!current.has(name!)) {
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
 * Resolve the replacement SHA or first-party tag for a refreshed entry.
 */
function sourceSha(
  vendor: string,
  currentSha: string,
  vendors: Array<{ id: string; repo: string; sha: string }>,
): string {
  if (vendor === "lgtm-hq") {
    return `v${getPackageVersion()}`;
  }
  return vendors.find((candidate) => candidate.id === vendor)?.sha ?? currentSha;
}

/**
 * Dest skill directory for a tracked relative path.
 *
 * Exploded installs use ``<skill>/...``. Native plugin trees use
 * ``skills/<skill>/...``.
 */
function staleSkillDestPath(root: string, relative: string): string | null {
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
 */
function otherPluginsKeepStaleDest(
  pluginId: string,
  dest: string,
  skillName: string,
  lock: import("./lockfile.ts").GatewayLock,
  catalogSkills: Record<string, string[]>,
): boolean {
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
 */
function explodeTrackedFiles(
  entry: import("./lockfile.ts").PluginLockEntry,
): Array<{ absolute: string; digest: string; relative: string; root: string }> {
  const files: Array<{ absolute: string; digest: string; relative: string; root: string }> = [];
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
 */
async function classifyPluginFiles(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  io: {
    hash: typeof hashFile;
    warn: (message: string) => void;
  },
): Promise<{
  modified: boolean;
  modifiedSkills: Set<string>;
  removableSkills: string[];
  verified: Array<{ absolute: string; relative: string; root: string }>;
}> {
  const modifiedSkills: Set<string> = new Set();

  const verified: Array<{ absolute: string; relative: string; root: string }> = [];
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
 */
async function deleteVerifiedFiles(
  verified: Array<{ absolute: string; relative?: string; root: string }>,
  io: {
    modifiedSkills?: Set<string>;
    removeDir: typeof rmdir;
    removeFile: typeof unlink;
  },
): Promise<void> {
  const skillDirs = new Map<string, string>();

  const skipSkillDirs: Set<string> = new Set();
  const modifiedSkills = io.modifiedSkills ?? new Set();
  for (const file of verified) {
    const skillName = (file.relative ?? "").split("/")[0];
    const skillDir = skillName ? join(file.root, skillName) : "";
    if (skillDir && !skipSkillDirs.has(skillDir)) {
      if (modifiedSkills.has(skillName!) && (await destSkillIsSymlink(skillDir))) {
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
 */
function isAbsentFsError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

/**
 * Per-agent reconcile annotation for one plugin.
 */
function agentReconcileStatus(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  reconciliation: import("./lockfile.ts").ReconcileResult,
): Record<string, "" | "MISSING" | "MODIFIED"> {
  const status: Record<string, "" | "MISSING" | "MODIFIED"> = {};
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
 */
function pluginReconcileStatus(
  reconciliation: import("./lockfile.ts").ReconcileResult,
): Map<string, "MISSING" | "MODIFIED"> {
  const status: Map<string, "MISSING" | "MODIFIED"> = new Map<string, "MISSING" | "MODIFIED">();
  for (const item of reconciliation.modified) {
    status.set(item.pluginId, "MODIFIED");
  }
  for (const item of reconciliation.missing) {
    status.set(item.pluginId, "MISSING");
  }
  return status;
}

/**
 * Split a lock entry's agents by owning projector and native route kind.
 */
function partitionLockedLanes(entry: import("./lockfile.ts").PluginLockEntry): {
  cliNative: string[];
  treeNative: string[];
  explode: string[];
} {
  const explode = [];
  const treeNative = [];
  const cliNative = [];
  for (const agent of pluginAgentNames(entry)) {
    const projector = agentProjector(entry, agent);
    if (projector === PROJECTOR_EXPLODE) {
      explode.push(agent);
    } else if (nativeRoute(agent)?.kind === "tree") {
      treeNative.push(agent);
    } else {
      cliNative.push(agent);
    }
  }
  return { cliNative, treeNative, explode };
}

/**
 * Whether the other gateway scope still records this plugin as CLI-native.
 *
 * Host CLIs are user-scoped; uninstalling while a sibling lock still owns the
 * plugin would strand that scope. Injected `readLock` helpers that ignore the
 * scope argument (and return the current lock) are treated as having no sibling.
 */
async function siblingLockHasCliNative(
  pluginId: string,
  agent: string,
  scope: "global" | "project",
  readLock: typeof readInstallState,
  lockEnvironment?: Parameters<typeof readInstallState>[1],
): Promise<boolean> {
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
 * Whether a tracked relative path belongs to one of the named skills.
 */
function skillNamesBelongTo(relative: string, names: string[]): boolean {
  const wanted = new Set(names);
  for (const name of skillNamesFromFiles({ [relative]: "" })) {
    if (wanted.has(name)) {
      return true;
    }
  }
  return false;
}

/**
 * Composition for re-delivering a locked plugin to every host it records.
 *
 * Explode lanes take the baked vendor tree or the catalog checkout; native
 * lanes need the catalog checkout (first-party only) and never fall back to a
 * remote marketplace.
 *
 * @throws {Error} When a lane has no local source.
 */
async function updateComposition(
  pluginId: string,
  entry: import("./lockfile.ts").PluginLockEntry,
  skills: string[],
  context: {
    dependencies: {
      lockEnvironment?: Parameters<typeof reconcileLock>[1];
      sourceRoot?: string | null;
      sourceSkills?: Record<string, string>;
      storeRoot?: string;
    };
    lock: import("./lockfile.ts").GatewayLock;
    scope: "global" | "project";
  },
): Promise<import("./install-plan.ts").InstallComposition> {
  const { dependencies, scope } = context;
  const lanes = partitionLockedLanes(entry);
  const environment = dependencies.lockEnvironment ?? {};
  const catalogRoot =
    dependencies.sourceRoot !== undefined
      ? dependencies.sourceRoot
      : findCatalogSourceRoot(environment.cwd ?? process.cwd());
  const baked = entry.vendor === "lgtm-hq" ? null : await loadBakedPlugin(pluginId);
  const explode =
    lanes.explode.length === 0
      ? null
      : resolveExplodeSourceSkills(
          skills,
          dependencies,
          baked ? baked.pluginRoot : entry.vendor === "lgtm-hq" ? catalogRoot : null,
        );
  if (lanes.explode.length > 0 && !explode) {
    // Managed updates never hand off to the unmanaged skills CLI.
    throw new Error(unmanagedRequiredMessage(pluginId));
  }
  let native: Record<string, string> | null = null;
  if (lanes.treeNative.length > 0 || lanes.cliNative.length > 0) {
    if (entry.vendor !== "lgtm-hq") {
      throw new Error("Native delivery is first-party only");
    }
    native = resolveExplodeSourceSkills(skills, dependencies, catalogRoot);
    if (!native && lanes.treeNative.length > 0) {
      throw new Error(
        "Native Cursor projector requires a catalog checkout (skills/ + " +
          ".claude-plugin/marketplace.json). Run update from the ai-skills " +
          "repository, or remove and reinstall with --projector explode.",
      );
    }
    if (!native) {
      throw new Error(
        `Native ${lanes.cliNative.join(", ")} update of ${pluginId} requires a locally ` +
          "rendered artifact (a catalog checkout with skills/); the remote marketplace is " +
          "never used. Run update from the ai-skills repository.",
      );
    }
  }
  const bundles = await loadBundles();
  return {
    copy: false,
    description: baked?.description ?? bundles.groups[pluginId]?.description ?? pluginId,
    destRoots: allAgentSkillRoots(scope, environment, context.lock),
    env: {
      cwd: environment.cwd ?? process.cwd(),
      home: environment.home ?? homedir(),
    },
    existing: entry,
    lanes,
    pluginId,
    retainStoreSkills: [...otherPluginSkillNames(context.lock, pluginId)],
    scope,
    skills,
    sources: { explode, native },
    storeRoot: dependencies.storeRoot ?? defaultStoreRoot(scope, environment),
    version: entry.vendor === "lgtm-hq" ? getPackageVersion() : (baked?.version ?? entry.sha),
  };
}
