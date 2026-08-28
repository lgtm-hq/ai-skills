import { randomUUID } from "node:crypto";
import {
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readdir,
  realpath,
  rename,
  rm,
  rmdir,
  symlink,
  unlink,
} from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

import { hashFile, hashTree, isSafePluginId } from "../lockfile.js";

/**
 * @typedef {{id: string, replace?: Set<string>, root: string}} ExplodeAgent
 * Agent id plus the exploded skills directory root. ``replace`` is the set of
 * skill names this agent already owns in the lock (not skipped dests).
 */

/**
 * @typedef {{
 *   claimed: Record<string, Record<string, string>>,
 *   createdDests: string[],
 *   createdStores: string[],
 *   skipped: Array<{agent: string, skill: string, dest: string}>,
 *   swappedDests: Array<{backup: string, dest: string}>,
 *   swappedStores: Array<{backup: string, storeDir: string}>,
 * }} ExplodeResult
 * Files this plugin owns after a successful commit. Skipped dests are
 * byte-identical and must not be recorded in the lock. ``keepBackups``
 * leaves dest/store ``.bak`` trees for the caller to discard after lock write.
 */

/**
 * Resolve first-party skill directories from a catalog root.
 *
 * @param {string[]} skills - Skill directory names.
 * @param {{
 *   sourceRoot?: string | null,
 *   sourceSkills?: Record<string, string>,
 * }} extras - Explicit maps win; ``sourceRoot: null`` disables catalog lookup.
 * @param {string | null} [catalogRoot] - ``findCatalogSourceRoot`` result.
 * @returns {Record<string, string> | null} Skill name to absolute source dir,
 *   or ``null`` to keep the skills-CLI fallback (vendor / no checkout).
 */
export function resolveExplodeSourceSkills(skills, extras = {}, catalogRoot = null) {
  if (extras.sourceSkills) {
    return extras.sourceSkills;
  }
  if (extras.sourceRoot === null) {
    return null;
  }
  const root = extras.sourceRoot ?? catalogRoot;
  if (!root) {
    return null;
  }
  /** @type {Record<string, string>} */
  const sourceSkills = {};
  for (const name of skills) {
    sourceSkills[name] = join(root, "skills", name);
  }
  return sourceSkills;
}

/**
 * Managed store that exploded dests symlink to (``~/.agents/skills``).
 *
 * @param {"global" | "project"} scope - Install scope.
 * @param {{cwd?: string, home?: string}} [environment] - Path roots.
 * @returns {string} Absolute store directory.
 */
export function defaultStoreRoot(scope, environment = {}) {
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  return join(root, ".agents", "skills");
}

/**
 * Stage a whole-plugin explode, reject dest collisions, then commit atomically.
 *
 * Dest trees that already match the staged bytes are skipped and not claimed.
 * Different dest content hard-errors before any dest write. Source trees may
 * not contain escaping symlinks. ``failAfter`` injects a failure after staging
 * (``"stage"``) or after the first dest commit (``"commit"``).
 *
 * @param {object} args - Named arguments.
 * @param {ExplodeAgent[]} args.agents - Destinations to project into.
 * @param {string[]} args.skills - Skill directory names.
 * @param {Record<string, string>} args.sourceSkills - Skill name to source dir.
 * @param {boolean} [args.copy=false] - Copy dest trees instead of store symlinks.
 * @param {string} [args.storeRoot] - Managed store for symlink mode.
 * @param {boolean} [args.keepBackups=false] - Leave dest/store ``.bak`` for the caller.
 * @param {"stage" | "commit"} [args.failAfter] - Injected failure checkpoint.
 * @param {(path: string) => Promise<string>} [args.hash] - Injectable hasher.
 * @param {typeof cp} [args.copyFn] - Injectable recursive copy.
 * @param {typeof mkdir} [args.makeDir] - Injectable mkdir.
 * @param {typeof rename} [args.move] - Injectable rename.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @param {typeof symlink} [args.link] - Injectable symlink.
 * @returns {Promise<ExplodeResult>} Claimed file maps and skipped dests.
 */
export async function explodePlugin(args) {
  const copyFn = args.copyFn ?? cp;
  const makeDir = args.makeDir ?? mkdir;
  const move = args.move ?? rename;
  const remove = args.remove ?? rm;
  const link = args.link ?? symlink;
  const hash = args.hash ?? hashFile;
  const copy = Boolean(args.copy);
  const keepBackups = Boolean(args.keepBackups);
  const storeRoot = args.storeRoot;

  if (!copy && !storeRoot) {
    throw new Error("explodePlugin requires storeRoot unless copy is true");
  }

  const staging = await mkdtemp(join(tmpdir(), "ai-skills-explode-"));
  /** @type {string[]} */
  const createdDests = [];
  /** @type {Array<{backup: string, dest: string}>} */
  const swappedDests = [];
  /** @type {string[]} */
  const createdStores = [];
  /** @type {Array<{backup: string, storeDir: string}>} */
  const swappedStores = [];
  /** @type {Set<string>} */
  const writtenStores = new Set();
  try {
    /** @type {Record<string, string>} */
    const stagedSkills = {};
    /** @type {Record<string, Record<string, string>>} */
    const stagedHashes = {};
    for (const name of args.skills) {
      assertSafeSkillName(name);
      const source = args.sourceSkills[name];
      if (!source) {
        throw new Error(`Missing explode source for skill ${JSON.stringify(name)}`);
      }
      const dest = join(staging, name);
      assertInsideRoot(staging, dest);
      await assertSafeSourceTree(source);
      await copyFn(source, dest, { recursive: true });
      stagedSkills[name] = dest;
      stagedHashes[name] = await hashTree(dest, hash);
    }

    const plans = await planExplodeCommits({
      agents: args.agents,
      copy,
      hash,
      stagedHashes,
      stagedSkills,
      storeRoot,
    });

    await checkpoint(args.failAfter, "stage");

    for (const plan of plans.toWrite) {
      const destExisted = await pathExists(plan.dest);
      if (destExisted) {
        const destBackup = uniqueBackupPath(plan.dest);
        await move(plan.dest, destBackup);
        swappedDests.push({ backup: destBackup, dest: plan.dest });
      }
      if (copy) {
        await commitCopiedSkill({
          copyFn,
          dest: plan.dest,
          makeDir,
          move,
          remove,
          staged: plan.staged,
        });
      } else {
        if (!writtenStores.has(plan.storeDir)) {
          const storeExisted = await pathExists(plan.storeDir);
          if (storeExisted && plan.replace) {
            const storeBackup = uniqueBackupPath(plan.storeDir);
            await move(plan.storeDir, storeBackup);
            swappedStores.push({ backup: storeBackup, storeDir: plan.storeDir });
          }
          const createdStore = await commitStoreSkill({
            copyFn,
            makeDir,
            move,
            remove,
            replace: plan.replace,
            staged: plan.staged,
            storeDir: plan.storeDir,
          });
          if (createdStore) {
            createdStores.push(plan.storeDir);
          }
          writtenStores.add(plan.storeDir);
        }
        await makeDir(dirname(plan.dest), { recursive: true });
        await link(plan.storeDir, plan.dest);
      }
      if (!destExisted) {
        createdDests.push(plan.dest);
      }
      await checkpoint(args.failAfter, "commit");
    }

    await remove(staging, { force: true, recursive: true });
    if (!keepBackups) {
      await discardExplodeBackups({ swappedDests, swappedStores }, { remove });
    }
    return {
      claimed: plans.claimed,
      createdDests,
      createdStores,
      skipped: plans.skipped,
      swappedDests,
      swappedStores,
    };
  } catch (error) {
    const rollbackErrors = [];
    try {
      await restoreExplodeInstall(
        { createdDests, createdStores, swappedDests, swappedStores },
        { move, remove },
      );
    } catch (failed) {
      rollbackErrors.push(failed);
    }
    try {
      await remove(staging, { force: true, recursive: true });
    } catch (failed) {
      rollbackErrors.push(failed);
    }
    if (rollbackErrors.length > 0) {
      const original = error instanceof Error ? error.message : String(error);
      const rollback = rollbackErrors
        .map((item) => (item instanceof Error ? item.message : String(item)))
        .join("; ");
      throw new Error(`${original} (explode rollback also failed: ${rollback})`);
    }
    throw error;
  }
}

/**
 * Discard dest/store ``.bak`` trees after the gateway lock write succeeds.
 *
 * @param {Pick<ExplodeResult, "swappedDests" | "swappedStores">} result - Swap sidecars.
 * @param {{remove?: typeof rm}} [io] - Injectable rm.
 * @returns {Promise<void>} Resolves when sidecars are gone.
 */
export async function discardExplodeBackups(result, io = {}) {
  const remove = io.remove ?? rm;
  for (const item of result.swappedDests ?? []) {
    await remove(item.backup, { force: true, recursive: true });
  }
  for (const item of result.swappedStores ?? []) {
    await remove(item.backup, { force: true, recursive: true });
  }
}

/**
 * Restore dest/store trees when explode committed but the lock write failed.
 *
 * @param {Pick<ExplodeResult, "createdDests" | "createdStores" | "swappedDests" | "swappedStores">} result - Commit progress.
 * @param {{move?: typeof rename, remove?: typeof rm}} [io] - Injectable rename/rm.
 * @returns {Promise<void>} Resolves when dests and stores are restored.
 */
export async function restoreExplodeInstall(result, io = {}) {
  const move = io.move ?? rename;
  const remove = io.remove ?? rm;
  const rollbackErrors = [];
  for (const dest of [...(result.createdDests ?? [])].reverse()) {
    try {
      await remove(dest, { force: true, recursive: true });
    } catch (failed) {
      rollbackErrors.push(failed);
    }
  }
  for (const item of [...(result.swappedDests ?? [])].reverse()) {
    try {
      await remove(item.dest, { force: true, recursive: true });
      await move(item.backup, item.dest);
    } catch (failed) {
      rollbackErrors.push(failed);
    }
  }
  for (const storeDir of [...(result.createdStores ?? [])].reverse()) {
    try {
      await remove(storeDir, { force: true, recursive: true });
    } catch (failed) {
      rollbackErrors.push(failed);
    }
  }
  for (const item of [...(result.swappedStores ?? [])].reverse()) {
    try {
      await remove(item.storeDir, { force: true, recursive: true });
      await move(item.backup, item.storeDir);
    } catch (failed) {
      rollbackErrors.push(failed);
    }
  }
  if (rollbackErrors.length > 0) {
    throw new Error(
      rollbackErrors
        .map((item) => (item instanceof Error ? item.message : String(item)))
        .join("; "),
    );
  }
}

/**
 * Hash-verified delete of owned exploded files, leaving modified paths.
 *
 * Empty directory trees under each touched skill dir are pruned recursively,
 * then empty ancestors up to the agent root.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id for warning text.
 * @param {Array<{absolute: string, digest: string, relative: string, root: string}>} args.files - Lock-owned files.
 * @param {(path: string) => Promise<string>} [args.hash] - Injectable hasher.
 * @param {typeof unlink} [args.removeFile] - Injectable unlink.
 * @param {typeof rmdir} [args.removeDir] - Injectable rmdir.
 * @param {(dir: string) => Promise<import("node:fs").Dirent[]>} [args.readDir] - Injectable readdir.
 * @param {(message: string) => void} [args.warn] - Warning sink.
 * @returns {Promise<{modified: string[], removed: string[]}>} Relative paths kept vs deleted.
 */
export async function removeExplodedFiles(args) {
  const hash = args.hash ?? hashFile;
  const removeFile = args.removeFile ?? unlink;
  const removeDir = args.removeDir ?? rmdir;
  const readDir = args.readDir ?? ((dir) => readdir(dir, { withFileTypes: true }));
  const warn = args.warn ?? ((message) => console.warn(message));
  /** @type {string[]} */
  const modified = [];
  /** @type {string[]} */
  const removed = [];
  /** @type {Map<string, {files: typeof args.files, root: string}>} */
  const groups = new Map();
  for (const file of args.files) {
    const skillName = file.relative.split("/")[0] ?? "";
    const skillDir = skillName ? join(file.root, skillName) : file.root;
    const group = groups.get(skillDir) ?? { files: [], root: file.root };
    group.files.push(file);
    groups.set(skillDir, group);
  }
  /** @type {Map<string, string>} */
  const skillDirs = new Map();
  for (const [skillDir, group] of groups) {
    if (skillDir !== group.root) {
      const unlinked = await unlinkDestSkillIfUnmodified(
        skillDir,
        group,
        args,
        hash,
        removeFile,
        warn,
        modified,
        removed,
      );
      if (unlinked) {
        continue;
      }
    }
    for (const file of group.files) {
      const absolute = resolveTrackedPath(file.root, file.relative);
      try {
        const current = await hash(absolute);
        if (current !== file.digest) {
          warn(`left modified ${args.pluginId} file ${file.relative}`);
          modified.push(file.relative);
          continue;
        }
        await removeFile(absolute);
        removed.push(file.relative);
        if (skillDir !== file.root) {
          skillDirs.set(skillDir, file.root);
        }
      } catch (error) {
        if (isAbsentFsError(error)) {
          continue;
        }
        throw error;
      }
    }
  }
  for (const [skillDir, root] of skillDirs) {
    await pruneEmptyDirTrees(skillDir, root, {
      readDir,
      removeDir,
    });
  }
  for (const file of args.files) {
    await pruneEmptyAncestors(dirname(join(file.root, file.relative)), file.root, removeDir);
  }
  return { modified, removed };
}

/**
 * Whether a dest skill directory is a symlink (store layout), without following it.
 *
 * @param {string} skillDir - Dest skill directory.
 * @returns {Promise<boolean>} True when the dest path is a symlink.
 */
export async function destSkillIsSymlink(skillDir) {
  try {
    const info = await lstat(skillDir);
    return info.isSymbolicLink();
  } catch (error) {
    if (isAbsentFsError(error)) {
      return false;
    }
    throw error;
  }
}

/**
 * Unlink a dest skill symlink without following it into the managed store.
 *
 * Default explode layout is dest → store. Unlinking files through that link
 * would delete store trees other agents may still share.
 *
 * @param {string} skillDir - Dest skill directory (may be a symlink).
 * @param {typeof unlink} [removeFile] - Injectable unlink.
 * @returns {Promise<boolean>} True when dest was a symlink and is now gone.
 */
export async function unlinkDestSkillSymlink(skillDir, removeFile = unlink) {
  try {
    const info = await lstat(skillDir);
    if (!info.isSymbolicLink()) {
      return false;
    }
    await removeFile(skillDir);
    return true;
  } catch (error) {
    if (isAbsentFsError(error)) {
      return false;
    }
    throw error;
  }
}

/**
 * Hash-verify a dest symlink, then unlink it without following into the store.
 *
 * Modified dests stay linked. Matching dests drop the dest link only.
 *
 * @param {string} skillDir - Dest skill directory.
 * @param {{files: Array<{digest: string, relative: string, root: string}>, root: string}} group - Owned files under this dest.
 * @param {{pluginId: string}} args - Warning context.
 * @param {(path: string) => Promise<string>} hash - Hasher.
 * @param {typeof unlink} removeFile - Unlink.
 * @param {(message: string) => void} warn - Warning sink.
 * @param {string[]} modified - Out: relative paths left in place.
 * @param {string[]} removed - Out: relative paths whose dest link was dropped.
 * @returns {Promise<boolean>} True when dest was a symlink (handled).
 */
async function unlinkDestSkillIfUnmodified(
  skillDir,
  group,
  args,
  hash,
  removeFile,
  warn,
  modified,
  removed,
) {
  try {
    const info = await lstat(skillDir);
    if (!info.isSymbolicLink()) {
      return false;
    }
  } catch (error) {
    if (isAbsentFsError(error)) {
      return false;
    }
    throw error;
  }
  let anyModified = false;
  for (const file of group.files) {
    const absolute = resolveTrackedPath(file.root, file.relative);
    try {
      const current = await hash(absolute);
      if (current !== file.digest) {
        warn(`left modified ${args.pluginId} file ${file.relative}`);
        modified.push(file.relative);
        anyModified = true;
      }
    } catch (error) {
      if (isAbsentFsError(error)) {
        continue;
      }
      throw error;
    }
  }
  if (anyModified) {
    return true;
  }
  await removeFile(skillDir);
  for (const file of group.files) {
    removed.push(file.relative);
  }
  return true;
}

/**
 * Recursively remove empty directory trees down from ``start``, then ``start``
 * itself when empty. ``stopAt`` is never removed.
 *
 * @param {string} start - Directory that may contain nested empty dirs.
 * @param {string} stopAt - Ancestor that must remain.
 * @param {{
 *   readDir: (dir: string) => Promise<import("node:fs").Dirent[]>,
 *   removeDir: typeof rmdir,
 * }} io - Injectable filesystem.
 * @returns {Promise<boolean>} True when ``start`` was removed or was absent.
 */
export async function pruneEmptyDirTrees(start, stopAt, io) {
  const resolvedStart = resolve(start);
  const resolvedStop = resolve(stopAt);
  if (resolvedStart === resolvedStop) {
    return false;
  }
  let entries;
  try {
    entries = await io.readDir(resolvedStart);
  } catch (error) {
    if (isAbsentFsError(error)) {
      return true;
    }
    throw error;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      return false;
    }
    const childGone = await pruneEmptyDirTrees(join(resolvedStart, entry.name), stopAt, io);
    if (!childGone) {
      return false;
    }
  }
  try {
    await io.removeDir(resolvedStart);
    return true;
  } catch (error) {
    if (isPruneStopError(error)) {
      return false;
    }
    throw error;
  }
}

/**
 * Remove empty ancestors from a deleted file up to the agent skills root.
 *
 * @param {string} start - Directory that contained a deleted file.
 * @param {string} root - Agent skills root; not removed.
 * @param {typeof rmdir} removeDir - Injectable rmdir.
 * @returns {Promise<void>} Resolves when pruning stops.
 */
export async function pruneEmptyAncestors(start, root, removeDir) {
  const resolvedRoot = resolve(root);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  let current = resolve(start);
  while (current.startsWith(prefix) && current !== resolvedRoot) {
    try {
      await removeDir(current);
    } catch (error) {
      if (isPruneStopError(error)) {
        return;
      }
      throw error;
    }
    current = dirname(current);
  }
}

/**
 * Resolve a lock-relative path and reject escapes outside the agent root.
 *
 * @param {string} root - Agent skills root from the lock.
 * @param {string} relative - Tracked path relative to that root.
 * @returns {string} Absolute path inside the root.
 * @throws {Error} When the relative path escapes the root.
 */
export function resolveTrackedPath(root, relative) {
  if (
    relative.includes("\0") ||
    relative.startsWith("/") ||
    relative.split(/[\\/]/).includes("..")
  ) {
    throw new Error(`Refusing to touch path outside explode root: ${relative}`);
  }
  const absolute = resolve(join(root, relative));
  assertInsideRoot(root, absolute);
  return absolute;
}

/**
 * @param {string} name - Candidate skill directory name.
 * @returns {void}
 * @throws {Error} When the name is not kebab-case.
 */
export function assertSafeSkillName(name) {
  if (!isSafePluginId(name)) {
    throw new Error(`Refusing skill name ${JSON.stringify(name)}: must be kebab-case`);
  }
}

/**
 * @param {string} root - Directory that must contain ``candidate``.
 * @param {string} candidate - Path joined from ``root``.
 * @returns {void}
 * @throws {Error} When ``candidate`` escapes ``root``.
 */
export function assertInsideRoot(root, candidate) {
  const resolvedRoot = resolve(root);
  const resolvedCandidate = resolve(candidate);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  if (resolvedCandidate !== resolvedRoot && !resolvedCandidate.startsWith(prefix)) {
    throw new Error(`Refusing to touch path outside explode root: ${candidate}`);
  }
}

/**
 * @param {"stage" | "commit" | undefined} failAfter - Injected checkpoint.
 * @param {"stage" | "commit"} name - Current checkpoint.
 * @returns {Promise<void>} Resolves unless this is the injected failure.
 */
async function checkpoint(failAfter, name) {
  if (failAfter === name) {
    throw new Error(`injected failure: ${name}`);
  }
}

/**
 * @param {object} args - Plan inputs.
 * @param {ExplodeAgent[]} args.agents - Destinations.
 * @param {boolean} args.copy - Copy vs symlink.
 * @param {(path: string) => Promise<string>} args.hash - Hasher.
 * @param {Record<string, Record<string, string>>} args.stagedHashes - Staged trees.
 * @param {Record<string, string>} args.stagedSkills - Staged dirs.
 * @param {string | undefined} args.storeRoot - Store root for symlink mode.
 * @returns {Promise<{
 *   claimed: Record<string, Record<string, string>>,
 *   skipped: Array<{agent: string, dest: string, skill: string}>,
 *   toWrite: Array<{
 *     agent: string,
 *     dest: string,
 *     replace: boolean,
 *     skill: string,
 *     staged: string,
 *     storeDir: string,
 *   }>,
 * }>} Commit plan.
 */
async function planExplodeCommits(args) {
  /** @type {Record<string, Record<string, string>>} */
  const claimed = {};
  /** @type {Array<{agent: string, dest: string, skill: string}>} */
  const skipped = [];
  /** @type {Array<{
   *     agent: string,
   *     dest: string,
   *     replace: boolean,
   *     skill: string,
   *     staged: string,
   *     storeDir: string,
   *   }>} */
  const toWrite = [];
  for (const agent of args.agents) {
    claimed[agent.id] = {};
    const owned = agent.replace ?? new Set();
    for (const [skill, staged] of Object.entries(args.stagedSkills)) {
      const dest = join(agent.root, skill);
      assertInsideRoot(agent.root, dest);
      const storeDir = args.storeRoot ? join(args.storeRoot, skill) : dest;
      if (args.storeRoot) {
        assertInsideRoot(args.storeRoot, storeDir);
      }
      let replace = owned.has(skill);
      if (args.storeRoot && !owned.has(skill) && (await pathExists(storeDir))) {
        const storeHashes = await hashExistingTree(storeDir, args.hash);
        const storeEmpty = Object.keys(storeHashes).length === 0;
        if (!storeEmpty && !sameHashes(storeHashes, args.stagedHashes[skill])) {
          throw new Error(
            `Explode collision at ${storeDir}: existing store content differs from incoming ${skill}`,
          );
        }
        if (storeEmpty) {
          replace = true;
        }
      }
      if (await pathExists(dest)) {
        const existing = await hashExistingTree(dest, args.hash);
        const isEmpty = Object.keys(existing).length === 0;
        if (!isEmpty && owned.has(skill)) {
          toWrite.push({
            agent: agent.id,
            dest,
            replace: true,
            skill,
            staged,
            storeDir,
          });
          Object.assign(claimed[agent.id], prefixHashes(skill, args.stagedHashes[skill]));
          continue;
        }
        if (!isEmpty && sameHashes(existing, args.stagedHashes[skill])) {
          skipped.push({ agent: agent.id, dest, skill });
          continue;
        }
        if (!isEmpty) {
          throw new Error(
            `Explode collision at ${dest}: existing content differs from incoming ` +
              `${skill} (byte-identical dests are skipped and not owned; different ` +
              "content is a hard error)",
          );
        }
      }
      toWrite.push({
        agent: agent.id,
        dest,
        replace,
        skill,
        staged,
        storeDir,
      });
      Object.assign(claimed[agent.id], prefixHashes(skill, args.stagedHashes[skill]));
    }
    if (Object.keys(claimed[agent.id]).length === 0) {
      delete claimed[agent.id];
    }
  }
  return { claimed, skipped, toWrite };
}

/**
 * @param {object} args - Copy commit.
 * @param {typeof cp} args.copyFn - Recursive copy.
 * @param {string} args.dest - Destination skill dir.
 * @param {typeof mkdir} args.makeDir - mkdir.
 * @param {typeof rename} args.move - rename.
 * @param {typeof rm} args.remove - rm.
 * @param {string} args.staged - Staged skill dir (shared; do not consume).
 * @returns {Promise<void>} Resolves when dest exists.
 */
async function commitCopiedSkill(args) {
  await args.remove(args.dest, { force: true, recursive: true });
  await args.makeDir(dirname(args.dest), { recursive: true });
  const destStage = `${args.dest}.staging`;
  await args.remove(destStage, { force: true, recursive: true });
  await args.copyFn(args.staged, destStage, { recursive: true });
  try {
    await args.move(destStage, args.dest);
  } catch (error) {
    if (!isCrossDeviceError(error)) {
      await args.remove(destStage, { force: true, recursive: true });
      throw error;
    }
    await args.copyFn(destStage, args.dest, { recursive: true });
    await args.remove(destStage, { force: true, recursive: true });
  }
}

/**
 * @param {object} args - Store commit.
 * @param {typeof cp} args.copyFn - Recursive copy.
 * @param {typeof mkdir} args.makeDir - mkdir.
 * @param {typeof rename} args.move - rename.
 * @param {typeof rm} args.remove - rm.
 * @param {boolean} args.replace - Refresh an existing store tree this lock owns.
 * @param {string} args.staged - Staged skill dir.
 * @param {string} args.storeDir - Store skill dir.
 * @returns {Promise<boolean>} True when this call created the store tree.
 */
async function commitStoreSkill(args) {
  const existed = await pathExists(args.storeDir);
  if (existed && !args.replace) {
    return false;
  }
  await args.makeDir(dirname(args.storeDir), { recursive: true });
  const storeStage = `${args.storeDir}.staging`;
  await args.remove(storeStage, { force: true, recursive: true });
  await args.copyFn(args.staged, storeStage, { recursive: true });
  if (existed) {
    await args.remove(args.storeDir, { force: true, recursive: true });
  }
  try {
    await args.move(storeStage, args.storeDir);
  } catch (error) {
    if (!isCrossDeviceError(error)) {
      await args.remove(storeStage, { force: true, recursive: true });
      throw error;
    }
    await args.copyFn(storeStage, args.storeDir, { recursive: true });
    await args.remove(storeStage, { force: true, recursive: true });
  }
  return !existed;
}

/**
 * Reject source trees that contain symlinks escaping the skill root.
 *
 * @param {string} root - Skill source directory.
 * @returns {Promise<void>} Resolves when the tree is safe to copy.
 */
async function assertSafeSourceTree(root) {
  const resolvedRoot = await realpath(root);
  await walkRejectingEscapes(resolvedRoot, resolvedRoot);
}

/**
 * @param {string} dir - Directory to walk.
 * @param {string} root - Skill root that must contain every realpath.
 * @returns {Promise<void>} Resolves when this directory is safe.
 */
async function walkRejectingEscapes(dir, root) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const absolute = join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      let target;
      try {
        target = await realpath(absolute);
      } catch {
        throw new Error(`Refusing dangling symlink in explode source: ${absolute}`);
      }
      assertInsideRoot(root, target);
      const info = await lstat(target);
      if (info.isDirectory()) {
        await walkRejectingEscapes(target, root);
      }
      continue;
    }
    if (entry.isDirectory()) {
      await walkRejectingEscapes(absolute, root);
    }
  }
}

/**
 * Hash an existing dest, following dest-root symlinks for content compare.
 *
 * @param {string} dest - Existing dest file or directory.
 * @param {(path: string) => Promise<string>} hash - Hasher.
 * @returns {Promise<Record<string, string>>} Relative path to digest.
 */
async function hashExistingTree(dest, hash) {
  const info = await lstat(dest);
  if (info.isFile()) {
    return { "SKILL.md": await hash(dest) };
  }
  if (info.isSymbolicLink()) {
    const target = await realpath(dest);
    const targetInfo = await lstat(target);
    if (targetInfo.isFile()) {
      return { "SKILL.md": await hash(dest) };
    }
    return hashTree(target, hash);
  }
  return hashTree(dest, hash);
}

/**
 * @param {Record<string, string>} left - Tree hashes.
 * @param {Record<string, string>} right - Tree hashes.
 * @returns {boolean} True when both maps have the same keys and digests.
 */
function sameHashes(left, right) {
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }
  return leftKeys.every((key, index) => key === rightKeys[index] && left[key] === right[key]);
}

/**
 * @param {string} skill - Skill directory name.
 * @param {Record<string, string>} files - Paths relative to the skill dir.
 * @returns {Record<string, string>} Paths relative to the agent root.
 */
function prefixHashes(skill, files) {
  /** @type {Record<string, string>} */
  const prefixed = {};
  for (const [relative, digest] of Object.entries(files)) {
    prefixed[`${skill}/${relative}`] = digest;
  }
  return prefixed;
}

/**
 * Sidecar path that does not clobber an existing ``.bak`` tree.
 *
 * @param {string} path - Dest or store path being swapped.
 * @returns {string} Unique backup path.
 */
function uniqueBackupPath(path) {
  return `${path}.bak.${randomUUID()}`;
}

/**
 * @param {string} path - File path.
 * @returns {Promise<boolean>} Whether the path exists.
 */
async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (isAbsentFsError(error)) {
      return false;
    }
    throw error;
  }
}

/**
 * @param {unknown} error - Caught rejection.
 * @returns {boolean} True when the code is ENOENT.
 */
function isAbsentFsError(error) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

/**
 * @param {unknown} error - Caught rejection.
 * @returns {boolean} True when rmdir should stop rather than fail the prune.
 */
function isPruneStopError(error) {
  if (!error || typeof error !== "object" || !("code" in error)) {
    return false;
  }
  return (
    error.code === "ENOENT" ||
    error.code === "ENOTEMPTY" ||
    error.code === "EEXIST" ||
    error.code === "ENOTDIR"
  );
}

/**
 * @param {unknown} error - Caught rejection.
 * @returns {boolean} True when rename crossed filesystems.
 */
function isCrossDeviceError(error) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "EXDEV");
}
