import { createHash, randomUUID } from "node:crypto";
import {
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readdir,
  rename,
  rm,
  rmdir,
  symlink,
  unlink,
} from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

import { hashFile, hashLockEntryPath, hashTree, isSafePluginId } from "../../lockfile.ts";
import { nodeReadOnlyFs } from "../fs.ts";
import type { ReadOnlyFs } from "../types.ts";

/** Recursive copy that keeps relative symlink targets as written. */
const EXPLODE_COPY_OPTIONS = { recursive: true, verbatimSymlinks: true };

/**
 * ADR-0005 class 1: identical dest skip is a log line, with no ownership claim.
 */
export function warnSkippedExplodeDests(
  skipped: Array<{ agent: string; dest: string; skill: string }>,
  warn: (message: string) => void = (message) => console.warn(message),
): void {
  for (const item of skipped) {
    warn(
      `skipped identical explode dest ${item.dest} (not claiming ${item.skill} on ${item.agent})`,
    );
  }
}

/**
 * Resolve first-party skill directories from a catalog root.
 */
export function resolveExplodeSourceSkills(
  skills: string[],
  extras: {
    sourceRoot?: string | null;
    sourceSkills?: Record<string, string>;
  } = {},
  catalogRoot: string | null = null,
): Record<string, string> | null {
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

  const sourceSkills: Record<string, string> = {};
  for (const name of skills) {
    sourceSkills[name] = join(root, "skills", name);
  }
  return sourceSkills;
}

/**
 * Managed store that exploded dests symlink to (``~/.agents/skills``).
 */
export function defaultStoreRoot(
  scope: "global" | "project",
  environment: { cwd?: string; home?: string } = {},
): string {
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  return join(root, ".agents", "skills");
}

/**
 * Whether existing dest skills are real directories (``--copy``), not store
 * symlinks. Any real dest directory selects copy mode for that agent so an
 * update cannot rewrite ``--copy`` installs into store symlinks.
 */
export async function destUsesCopyMaterialization(
  destRoot: string,
  skillNames: string[],
): Promise<boolean> {
  for (const name of skillNames) {
    try {
      const info = await lstat(join(destRoot, name));
      if (info.isDirectory()) {
        return true;
      }
    } catch (error) {
      if (isAbsentFsError(error)) {
        continue;
      }
      throw error;
    }
  }
  return false;
}

/**
 * Stage a whole-plugin explode, reject dest collisions, then commit atomically.
 *
 * Dest trees that already match the staged bytes are skipped and not claimed.
 * Different dest content hard-errors before any dest write. Source trees may
 * not contain escaping symlinks. ``failAfter`` injects a failure after staging
 * (``"stage"``) or after the first dest commit (``"commit"``).
 */
export async function explodePlugin(args: {
  agents: ExplodeAgent[];
  skills: string[];
  sourceSkills: Record<string, string>;
  copy?: boolean;
  storeRoot?: string;
  retainStoreSkills?: Set<string>;
  destRoots?: string[];
  keepBackups?: boolean;
  failAfter?: "stage" | "commit";
  hash?: (path: string) => Promise<string>;
  copyFn?: typeof cp;
  makeDir?: typeof mkdir;
  move?: typeof rename;
  remove?: typeof rm;
  link?: typeof symlink;
}): Promise<ExplodeResult> {
  const copyFn = args.copyFn ?? cp;
  const makeDir = args.makeDir ?? mkdir;
  const move = args.move ?? rename;
  const remove = args.remove ?? rm;
  const link = args.link ?? symlink;
  const hash = args.hash ?? hashFile;
  const copy = Boolean(args.copy);
  const keepBackups = Boolean(args.keepBackups);
  const storeRoot = args.storeRoot;
  const needsStore = args.agents.some((agent) => !(agent.copy ?? copy));

  if (needsStore && !storeRoot) {
    throw new Error("explodePlugin requires storeRoot unless copy is true");
  }

  const staging = await mkdtemp(join(tmpdir(), "ai-skills-explode-"));

  const createdDests: string[] = [];

  const swappedDests: Array<{ backup: string; dest: string }> = [];

  const createdStores: string[] = [];

  const swappedStores: Array<{ backup: string; storeDir: string }> = [];

  const writtenStores: Set<string> = new Set();

  const stagingSidecars: string[] = [];
  const trackStaging = (path: string) => {
    stagingSidecars.push(path);
  };
  try {
    const stagedSkills: Record<string, string> = {};

    const stagedHashes: Record<string, Record<string, string>> = {};
    for (const name of args.skills) {
      assertSafeSkillName(name);
      const source = args.sourceSkills[name];
      if (!source) {
        throw new Error(`Missing explode source for skill ${JSON.stringify(name)}`);
      }
      const dest = join(staging, name);
      assertInsideRoot(staging, dest);
      await assertSafeSourceTree(source);
      await copyFn(source, dest, EXPLODE_COPY_OPTIONS);
      stagedSkills[name] = dest;
      stagedHashes[name] = await hashTree(dest, hash);
    }

    const plans = await planExplodeCommits({
      agents: args.agents,
      copy,
      destRoots: args.destRoots ?? [],
      hash,
      retainStoreSkills: args.retainStoreSkills ?? new Set(),
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
      if (plan.copy) {
        await commitCopiedSkill({
          copyFn,
          dest: plan.dest,
          makeDir,
          move,
          remove,
          staged: plan.staged,
          trackStaging,
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
            trackStaging,
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
    for (const sidecar of stagingSidecars) {
      try {
        await remove(sidecar, { force: true, recursive: true });
      } catch (failed) {
        rollbackErrors.push(failed);
      }
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
 * Decide an explode transaction without writing: the same validation and
 * collision rules ``explodePlugin`` applies, hashed from the source trees
 * (staging is a verbatim copy, so the hashes are identical). Reads only
 * through ``fs``.
 */
export async function planExplode(args: {
  agents: ExplodeAgent[];
  skills: string[];
  sourceSkills: Record<string, string>;
  copy?: boolean;
  storeRoot?: string;
  retainStoreSkills?: Set<string>;
  destRoots?: string[];
  fs?: ReadOnlyFs;
}): Promise<ExplodeDecisions> {
  const fs = args.fs ?? nodeReadOnlyFs;
  const hash = async (path: string) =>
    createHash("sha256")
      .update(await fs.readFile(path))
      .digest("hex");
  const copy = Boolean(args.copy);
  if (args.agents.some((agent) => !(agent.copy ?? copy)) && !args.storeRoot) {
    throw new Error("explodePlugin requires storeRoot unless copy is true");
  }
  const stagedSkills: Record<string, string> = {};
  const stagedHashes: Record<string, Record<string, string>> = {};
  for (const name of args.skills) {
    assertSafeSkillName(name);
    const source = args.sourceSkills[name];
    if (!source) {
      throw new Error(`Missing explode source for skill ${JSON.stringify(name)}`);
    }
    await assertSafeSourceTree(source, fs);
    stagedSkills[name] = source;
    stagedHashes[name] = await hashTree(source, hash, fs);
  }
  return planExplodeCommits({
    agents: args.agents,
    copy,
    destRoots: args.destRoots ?? [],
    fs,
    hash,
    retainStoreSkills: args.retainStoreSkills ?? new Set(),
    stagedHashes,
    stagedSkills,
    storeRoot: args.storeRoot,
  });
}

/**
 * Discard dest/store ``.bak`` trees after the gateway lock write succeeds.
 */
export async function discardExplodeBackups(
  result: Partial<Pick<ExplodeResult, "swappedDests" | "swappedStores">>,
  io: { remove?: typeof rm } = {},
): Promise<void> {
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
 */
export async function restoreExplodeInstall(
  result: Partial<
    Pick<ExplodeResult, "createdDests" | "createdStores" | "swappedDests" | "swappedStores">
  >,
  io: { move?: typeof rename; remove?: typeof rm } = {},
): Promise<void> {
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
      await mkdir(dirname(item.dest), { recursive: true });
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
 * Copy a dest path to a unique sidecar so a later lock-write failure can restore it.
 */
export async function snapshotDestPath(
  dest: string,
  io: { copy?: typeof cp } = {},
): Promise<{ backup: string; dest: string } | null> {
  const copyFn = io.copy ?? cp;
  const backup = uniqueBackupPath(dest);
  try {
    await copyFn(dest, backup, EXPLODE_COPY_OPTIONS);
  } catch (error) {
    if (isAbsentFsError(error)) {
      return null;
    }
    throw error;
  }
  return { backup, dest };
}

/**
 * Hash-verified delete of owned exploded files, leaving modified paths.
 *
 * Empty directory trees under each touched skill dir are pruned recursively,
 * then empty ancestors up to the agent root.
 */
export async function removeExplodedFiles(args: {
  pluginId: string;
  files: Array<{ absolute?: string; digest: string; relative: string; root: string }>;
  hash?: (path: string) => Promise<string>;
  removeFile?: typeof unlink;
  removeDir?: typeof rmdir;
  readDir?: (dir: string) => Promise<import("node:fs").Dirent[]>;
  warn?: (message: string) => void;
}): Promise<{ modified: string[]; removed: string[] }> {
  const hash = args.hash ?? hashFile;
  const removeFile = args.removeFile ?? unlink;
  const removeDir = args.removeDir ?? rmdir;
  const readDir = args.readDir ?? ((dir) => readdir(dir, { withFileTypes: true }));
  const warn = args.warn ?? ((message) => console.warn(message));

  const modified: string[] = [];

  const removed: string[] = [];

  const groups: Map<string, { files: typeof args.files; root: string }> = new Map();
  for (const file of args.files) {
    const skillName = file.relative.split("/")[0] ?? "";
    const skillDir = skillName ? join(file.root, skillName) : file.root;
    const group = groups.get(skillDir) ?? { files: [], root: file.root };
    group.files.push(file);
    groups.set(skillDir, group);
  }

  const skillDirs: Map<string, string> = new Map();
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
        const current = await hashExplodePath(absolute, hash);
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
 */
export async function destSkillIsSymlink(skillDir: string): Promise<boolean> {
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
 */
export async function unlinkDestSkillSymlink(
  skillDir: string,
  removeFile: typeof unlink = unlink,
): Promise<boolean> {
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
 */
async function unlinkDestSkillIfUnmodified(
  skillDir: string,
  group: { files: Array<{ digest: string; relative: string; root: string }>; root: string },
  args: { pluginId: string },
  hash: (path: string) => Promise<string>,
  removeFile: typeof unlink,
  warn: (message: string) => void,
  modified: string[],
  removed: string[],
): Promise<boolean> {
  try {
    const info = await lstat(skillDir);
    if (!info.isSymbolicLink()) {
      return false;
    }
    if (await danglingSymlink(skillDir)) {
      await removeFile(skillDir);
      for (const file of group.files) {
        removed.push(file.relative);
      }
      return true;
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
      const current = await hashExplodePath(absolute, hash);
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
 */
export async function pruneEmptyDirTrees(
  start: string,
  stopAt: string,
  io: {
    readDir: (dir: string) => Promise<import("node:fs").Dirent[]>;
    removeDir: typeof rmdir;
  },
): Promise<boolean> {
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
 */
export async function pruneEmptyAncestors(
  start: string,
  root: string,
  removeDir: typeof rmdir,
): Promise<void> {
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
 * @throws {Error} When the relative path escapes the root.
 */
export function resolveTrackedPath(root: string, relative: string): string {
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
 * @throws {Error} When the name is not kebab-case.
 */
export function assertSafeSkillName(name: string): void {
  if (!isSafePluginId(name)) {
    throw new Error(`Refusing skill name ${JSON.stringify(name)}: must be kebab-case`);
  }
}

/**
 * @throws {Error} When ``candidate`` escapes ``root``.
 */
export function assertInsideRoot(root: string, candidate: string): void {
  const resolvedRoot = resolve(root);
  const resolvedCandidate = resolve(candidate);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  if (resolvedCandidate !== resolvedRoot && !resolvedCandidate.startsWith(prefix)) {
    throw new Error(`Refusing to touch path outside explode root: ${candidate}`);
  }
}

async function checkpoint(
  failAfter: "stage" | "commit" | undefined,
  name: "stage" | "commit",
): Promise<void> {
  if (failAfter === name) {
    throw new Error(`injected failure: ${name}`);
  }
}

async function planExplodeCommits(args: {
  agents: ExplodeAgent[];
  copy: boolean;
  destRoots: string[];
  fs?: ReadOnlyFs;
  hash: (path: string) => Promise<string>;
  retainStoreSkills: Set<string>;
  stagedHashes: Record<string, Record<string, string>>;
  stagedSkills: Record<string, string>;
  storeRoot: string | undefined;
}): Promise<ExplodeDecisions> {
  const fs = args.fs ?? nodeReadOnlyFs;
  const claimed: Record<string, Record<string, string>> = {};

  const skipped: Array<{ agent: string; dest: string; skill: string }> = [];

  const toWrite: Array<{
    agent: string;
    copy: boolean;
    dest: string;
    replace: boolean;
    skill: string;
    staged: string;
    storeDir: string;
  }> = [];

  const transactionDests: Record<string, string[]> = {};
  for (const agent of args.agents) {
    for (const skill of Object.keys(args.stagedSkills)) {
      (transactionDests[skill] ??= []).push(join(agent.root, skill));
    }
  }
  for (const agent of args.agents) {
    claimed[agent.id] = {};
    const owned = agent.replace ?? new Set();
    const copy = Boolean(agent.copy ?? args.copy);
    for (const [skill, staged] of Object.entries(args.stagedSkills)) {
      const dest = join(agent.root, skill);
      assertInsideRoot(agent.root, dest);
      const storeDir = args.storeRoot ? join(args.storeRoot, skill) : dest;
      if (!copy && args.storeRoot) {
        assertInsideRoot(args.storeRoot, storeDir);
      }
      const storePlan = () =>
        planStoreReplacement({
          copy,
          destRoots: args.destRoots,
          fs,
          hash: args.hash,
          retainStoreSkills: args.retainStoreSkills,
          skill,
          skipDests: transactionDests[skill] ?? [],
          stagedHashes: args.stagedHashes,
          storeDir,
          storeRoot: args.storeRoot,
        });
      if (await pathExists(dest, fs)) {
        const existing = await hashExistingTree(dest, args.hash, fs);
        const isEmpty = Object.keys(existing).length === 0;
        if (!isEmpty && owned.has(skill)) {
          const storeReplace = await storePlan();
          toWrite.push({
            agent: agent.id,
            copy,
            dest,
            replace: copy || storeReplace,
            skill,
            staged,
            storeDir,
          });
          Object.assign(claimed[agent.id]!, prefixHashes(skill, args.stagedHashes[skill]!));
          continue;
        }
        if (!isEmpty && sameHashes(existing, args.stagedHashes[skill]!)) {
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
      const storeReplace = await storePlan();
      toWrite.push({
        agent: agent.id,
        copy,
        dest,
        replace: owned.has(skill) ? copy || storeReplace : storeReplace,
        skill,
        staged,
        storeDir,
      });
      Object.assign(claimed[agent.id]!, prefixHashes(skill, args.stagedHashes[skill]!));
    }
    if (Object.keys(claimed[agent.id]!).length === 0) {
      delete claimed[agent.id];
    }
  }
  return { claimed, skipped, toWrite };
}

/**
 * Whether the managed store must be replaced for this skill.
 *
 * Identical leftover stores are reused. Empty stores and true residue
 * (no other explode plugin, no dest symlink outside this transaction) are
 * replaced. A live consumer of different content is a hard error, including
 * owned updates that would rewrite a shared store.
 */
async function planStoreReplacement(args: {
  copy: boolean;
  destRoots: string[];
  fs: ReadOnlyFs;
  hash: (path: string) => Promise<string>;
  retainStoreSkills: Set<string>;
  skill: string;
  skipDests: string[];
  stagedHashes: Record<string, Record<string, string>>;
  storeDir: string;
  storeRoot: string | undefined;
}): Promise<boolean> {
  if (args.copy || !args.storeRoot || !(await pathExists(args.storeDir, args.fs))) {
    return false;
  }
  const storeHashes = await hashExistingTree(args.storeDir, args.hash, args.fs);
  if (Object.keys(storeHashes).length === 0) {
    return true;
  }
  if (sameHashes(storeHashes, args.stagedHashes[args.skill]!)) {
    return false;
  }
  if (args.retainStoreSkills.has(args.skill)) {
    throw new Error(
      `Explode collision at ${args.storeDir}: existing store content differs from incoming ${args.skill}`,
    );
  }
  const consumers = await destsSymlinkedToStore(
    args.storeDir,
    args.skill,
    args.destRoots,
    args.skipDests,
    args.fs,
  );
  if (consumers.length > 0) {
    throw new Error(
      `Explode collision at ${args.storeDir}: existing store content differs from incoming ` +
        `${args.skill} (also linked from ${consumers.join(", ")})`,
    );
  }
  return true;
}

/**
 * Dest skill symlinks (other than this transaction) that resolve to ``storeDir``.
 *
 * Scans known agent layouts plus caller-supplied dest roots. Dest trees that
 * are neither in ``destRoots`` nor recorded in the lock are not discovered.
 */
async function destsSymlinkedToStore(
  storeDir: string,
  skill: string,
  destRoots: string[],
  skipDests: string[],
  fs: ReadOnlyFs,
): Promise<string[]> {
  let resolvedStore;
  try {
    resolvedStore = await fs.realpath(storeDir);
  } catch (error) {
    if (isAbsentFsError(error)) {
      return [];
    }
    throw error;
  }
  const skipped = new Set((skipDests ?? []).map((path) => resolve(path)));

  const hits: string[] = [];
  for (const root of destRoots) {
    const candidate = join(root, skill);
    if (skipped.has(resolve(candidate))) {
      continue;
    }
    try {
      const info = await fs.lstat(candidate);
      if (!info.isSymbolicLink()) {
        continue;
      }
      const target = await fs.realpath(candidate);
      if (target === resolvedStore) {
        hits.push(candidate);
      }
    } catch (error) {
      if (isAbsentFsError(error)) {
        continue;
      }
      throw error;
    }
  }
  return hits;
}

async function commitCopiedSkill(args: {
  copyFn: typeof cp;
  dest: string;
  makeDir: typeof mkdir;
  move: typeof rename;
  remove: typeof rm;
  staged: string;
  trackStaging: (path: string) => void;
}): Promise<void> {
  await args.remove(args.dest, { force: true, recursive: true });
  await args.makeDir(dirname(args.dest), { recursive: true });
  const destStage = `${args.dest}.staging.${randomUUID()}`;
  args.trackStaging(destStage);
  await args.copyFn(args.staged, destStage, EXPLODE_COPY_OPTIONS);
  try {
    await args.move(destStage, args.dest);
  } catch (error) {
    if (!isCrossDeviceError(error)) {
      await args.remove(destStage, { force: true, recursive: true });
      throw error;
    }
    await args.copyFn(destStage, args.dest, EXPLODE_COPY_OPTIONS);
    await args.remove(destStage, { force: true, recursive: true });
  }
}

async function commitStoreSkill(args: {
  copyFn: typeof cp;
  makeDir: typeof mkdir;
  move: typeof rename;
  remove: typeof rm;
  replace: boolean;
  staged: string;
  storeDir: string;
  trackStaging: (path: string) => void;
}): Promise<boolean> {
  const existed = await pathExists(args.storeDir);
  if (existed && !args.replace) {
    return false;
  }
  await args.makeDir(dirname(args.storeDir), { recursive: true });
  const storeStage = `${args.storeDir}.staging.${randomUUID()}`;
  args.trackStaging(storeStage);
  await args.copyFn(args.staged, storeStage, EXPLODE_COPY_OPTIONS);
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
    await args.copyFn(storeStage, args.storeDir, EXPLODE_COPY_OPTIONS);
    await args.remove(storeStage, { force: true, recursive: true });
  }
  return !existed;
}

/**
 * Reject source trees that contain symlinks escaping the skill root.
 */
async function assertSafeSourceTree(root: string, fs: ReadOnlyFs = nodeReadOnlyFs): Promise<void> {
  const resolvedRoot = await fs.realpath(root);
  await walkRejectingEscapes(resolvedRoot, resolvedRoot, fs);
}

async function walkRejectingEscapes(
  dir: string,
  root: string,
  fs: ReadOnlyFs,
  visiting: Set<string> = new Set(),
): Promise<void> {
  const resolvedDir = await fs.realpath(dir);
  if (visiting.has(resolvedDir)) {
    throw new Error(`Refusing cyclic symlink in explode source: ${dir}`);
  }
  visiting.add(resolvedDir);
  try {
    const entries = await fs.readdir(resolvedDir);
    for (const entry of entries) {
      const absolute = join(resolvedDir, entry.name);
      if (entry.isSymbolicLink()) {
        let target;
        try {
          target = await fs.realpath(absolute);
        } catch (error) {
          if (isAbsentFsError(error)) {
            throw new Error(`Refusing dangling symlink in explode source: ${absolute}`);
          }
          throw error;
        }
        assertInsideRoot(root, target);
        const info = await fs.lstat(target);
        if (info.isDirectory()) {
          await walkRejectingEscapes(target, root, fs, visiting);
        }
        continue;
      }
      if (entry.isDirectory()) {
        await walkRejectingEscapes(absolute, root, fs, visiting);
      }
    }
  } finally {
    visiting.delete(resolvedDir);
  }
}

/**
 * Hash an existing dest, following dest-root symlinks for content compare.
 * Dangling dest or store symlinks hash as empty so explode can replace them
 * instead of throwing ENOENT from ``realpath``.
 */
async function hashExistingTree(
  dest: string,
  hash: (path: string) => Promise<string>,
  fs: ReadOnlyFs = nodeReadOnlyFs,
): Promise<Record<string, string>> {
  const info = await fs.lstat(dest);
  if (info.isFile()) {
    return { ".": await hash(dest) };
  }
  if (info.isSymbolicLink()) {
    if (await danglingSymlink(dest, fs)) {
      return {};
    }
    const target = await fs.realpath(dest);
    const targetInfo = await fs.lstat(target);
    if (targetInfo.isFile()) {
      return { ".": await hash(dest) };
    }
    return hashTree(target, hash, fs);
  }
  return hashTree(dest, hash, fs);
}

/**
 * True when ``path`` is a symlink whose target cannot be resolved.
 */
async function danglingSymlink(path: string, fs: ReadOnlyFs = nodeReadOnlyFs): Promise<boolean> {
  try {
    await fs.realpath(path);
    return false;
  } catch (error) {
    if (isAbsentFsError(error)) {
      return true;
    }
    throw error;
  }
}

/**
 * Hash a dest path the same way ``walkHashTree`` records lock digests.
 * In-tree dest-dir symlinks use ``symlink:<target>``; files hash through.
 */
async function hashExplodePath(
  path: string,
  hash: (path: string) => Promise<string>,
): Promise<string> {
  try {
    return await hashLockEntryPath(path, hash);
  } catch (error) {
    if (!isAbsentFsError(error)) {
      throw error;
    }
  }
  return hash(path);
}

function sameHashes(left: Record<string, string>, right: Record<string, string>): boolean {
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }
  return leftKeys.every((key, index) => key === rightKeys[index] && left[key] === right[key]);
}

function prefixHashes(skill: string, files: Record<string, string>): Record<string, string> {
  const prefixed: Record<string, string> = {};
  for (const [relative, digest] of Object.entries(files)) {
    prefixed[`${skill}/${relative}`] = digest;
  }
  return prefixed;
}

/**
 * Sidecar path that does not clobber an existing ``.bak`` tree.
 */
function uniqueBackupPath(path: string): string {
  return `${path}.bak.${randomUUID()}`;
}

async function pathExists(path: string, fs: ReadOnlyFs = nodeReadOnlyFs): Promise<boolean> {
  try {
    await fs.lstat(path);
    return true;
  } catch (error) {
    if (isAbsentFsError(error)) {
      return false;
    }
    throw error;
  }
}

function isAbsentFsError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

function isPruneStopError(error: unknown): boolean {
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

function isCrossDeviceError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "EXDEV");
}

/** Commit decisions shared by the engine and the adapter plan. */
export interface ExplodeDecisions {
  claimed: Record<string, Record<string, string>>;
  skipped: Array<{ agent: string; dest: string; skill: string }>;
  toWrite: Array<{
    agent: string;
    copy: boolean;
    dest: string;
    replace: boolean;
    skill: string;
    staged: string;
    storeDir: string;
  }>;
}

/** Agent id plus the exploded skills directory root. ``replace`` is the set of
 * skill names this agent already owns in the lock (not skipped dests).
 * ``copy`` overrides the call-level copy flag so ``--copy`` dests stay
 * directories on update instead of becoming store symlinks. */
export interface ExplodeAgent {
  copy?: boolean;
  id: string;
  replace?: Set<string>;
  root: string;
}

/** Files this plugin owns after a successful commit. Skipped dests are
 * byte-identical and must not be recorded in the lock. Callers that pass
 * ``keepBackups`` must discard dest/store ``.bak`` trees after the lock write. */
export interface ExplodeResult {
  claimed: Record<string, Record<string, string>>;
  createdDests: string[];
  createdStores: string[];
  skipped: Array<{ agent: string; skill: string; dest: string }>;
  swappedDests: Array<{ backup: string; dest: string }>;
  swappedStores: Array<{ backup: string; storeDir: string }>;
}
