import { existsSync } from "node:fs";
import { cp, mkdir, readdir, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { CHECKOUT_ROOT } from "../../paths.ts";

import { isSafePluginId } from "../../lockfile.ts";
import { CURSOR_HOST } from "./host.ts";

/**
 * Whether a Cursor plugin destination has any regular files.
 *
 * Empty leftover directories (clean remove, crash leftovers) must not count as
 * an unowned tree, or the next install refuses a dest the user already cleared.
 */
export async function cursorDestHasFiles(pluginDir: string): Promise<boolean> {
  return pathHasRegularFiles(pluginDir);
}

async function pathHasRegularFiles(dir: string): Promise<boolean> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
  for (const entry of entries) {
    if (entry.isFile()) {
      return true;
    }
    if (entry.isDirectory() && (await pathHasRegularFiles(join(dir, entry.name)))) {
      return true;
    }
  }
  return false;
}

/**
 * Directory that holds locally dropped Cursor plugins.
 */
export function cursorPluginsRoot(environment: {
  cwd?: string;
  home?: string;
  scope: "global" | "project";
}): string {
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const base = environment.scope === "project" ? cwd : home;
  const route = CURSOR_HOST.native;
  if (route?.kind !== "tree") {
    throw new Error("Cursor host definition has no tree route");
  }
  return join(base, route.pluginsDir);
}

/**
 * Keep only gateway-owned plugin-tree paths so untracked dest files stay
 * out of the lock (and therefore out of hash-verified remove).
 */
export function ownedPluginTreeFiles(
  files: Record<string, string>,
  skillNames: string[],
): Record<string, string> {
  const names = new Set(skillNames);
  const owned: Record<string, string> = {};
  for (const [relative, digest] of Object.entries(files)) {
    if (relative === PLUGIN_MANIFEST) {
      owned[relative] = digest;
      continue;
    }
    const match = /^skills\/([^/]+)\//.exec(relative);
    if (match && names.has(match[1]!)) {
      owned[relative] = digest;
    }
  }
  return owned;
}

/** Plugin manifest path inside a dropped tree. */
export const PLUGIN_MANIFEST = ".claude-plugin/plugin.json";

/**
 * Catalog root that contains ``skills/`` and the Claude marketplace adapter.
 *
 * Checks ``cwd`` first, then the git checkout that ships this gateway module
 * when running from a clone. Published npm installs have neither.
 */
export function findCatalogSourceRoot(cwd: string = process.cwd()): string | null {
  const packageRepoRoot = CHECKOUT_ROOT;
  for (const root of [cwd, packageRepoRoot]) {
    if (
      existsSync(join(root, "skills")) &&
      existsSync(join(root, ".claude-plugin", "marketplace.json"))
    ) {
      return root;
    }
  }
  return null;
}

/**
 * Reject a plugin id that is not a kebab-case folder name.
 *
 * @throws {Error} When the id could escape `destRoot`.
 */
export function assertSafePluginId(pluginId: string): void {
  if (!isSafePluginId(pluginId)) {
    throw new Error(`Refusing Cursor plugin id ${JSON.stringify(pluginId)}: must be kebab-case`);
  }
}

/**
 * Reject a skill directory name that could escape the catalog `skills/` tree.
 *
 * @throws {Error} When the name is not kebab-case.
 */
export function assertSafeSkillName(name: string): void {
  if (!isSafePluginId(name)) {
    throw new Error(`Refusing skill name ${JSON.stringify(name)}: must be kebab-case`);
  }
}

/**
 * Assemble a Cursor-local plugin tree from sliced marketplace metadata.
 *
 * Copies each listed skill directory and writes `.claude-plugin/plugin.json`.
 * Assembly happens in a sibling `.staging` directory. An existing destination
 * is never overwritten unless `replace` is true (this lock already owns the
 * plugin). Untracked files in an owned destination are copied into staging so
 * a swap cannot delete user data. When `commit` is false, a `.bak` of the
 * previous tree is left for the caller to discard after the lock write.
 */
export async function installCursorPlugin(args: {
  pluginId: string;
  description: string;
  version: string;
  skills: string[];
  sourceRoot: string;
  destRoot: string;
  replace?: boolean;
  commit?: boolean;
  copy?: typeof cp;
  makeDir?: typeof mkdir;
  remove?: typeof rm;
  move?: typeof rename;
  write?: typeof writeFile;
  progress?: { swapped?: boolean };
}): Promise<string> {
  const copy = args.copy ?? cp;
  const makeDir = args.makeDir ?? mkdir;
  const write = args.write ?? writeFile;
  const remove = args.remove ?? rm;
  const move = args.move ?? rename;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  const occupied = await cursorDestHasFiles(paths.pluginDir);
  if (occupied && !args.replace) {
    throw new Error(`Refusing to overwrite unowned Cursor plugin at ${paths.pluginDir}`);
  }
  if (existsSync(paths.pluginDir) && !occupied) {
    await remove(paths.pluginDir, { force: true, recursive: true });
  }
  const existed = occupied;

  await remove(paths.staging, { force: true, recursive: true });
  let swapped = false;
  try {
    await makeDir(paths.staging, { recursive: true });
    for (const name of args.skills) {
      assertSafeSkillName(name);
      const from = join(args.sourceRoot, "skills", name);
      const to = join(paths.staging, "skills", name);
      assertInsideRoot(join(args.sourceRoot, "skills"), from);
      assertInsideRoot(join(paths.staging, "skills"), to);
      await copy(from, to, { recursive: true });
    }
    const manifestDir = join(paths.staging, ".claude-plugin");
    await makeDir(manifestDir, { recursive: true });
    const manifest = {
      description: args.description,
      name: args.pluginId,
      version: args.version,
    };
    await write(join(manifestDir, "plugin.json"), `${JSON.stringify(manifest, null, 2)}\n`);
    if (existed) {
      await copyUntrackedFiles(paths.pluginDir, paths.staging, copy, makeDir);
    }
    if (existed) {
      await remove(paths.backup, { force: true, recursive: true });
      await move(paths.pluginDir, paths.backup);
      swapped = true;
      if (args.progress) {
        args.progress.swapped = true;
      }
    }
    await move(paths.staging, paths.pluginDir);
  } catch (error) {
    let restoreError;
    try {
      if (swapped) {
        await remove(paths.pluginDir, { force: true, recursive: true });
        await move(paths.backup, paths.pluginDir);
      }
      await remove(paths.staging, { force: true, recursive: true });
    } catch (failed) {
      restoreError = failed;
    }
    if (restoreError) {
      const original = error instanceof Error ? error.message : String(error);
      const restore = restoreError instanceof Error ? restoreError.message : String(restoreError);
      throw new Error(`${original} (Cursor restore also failed: ${restore})`);
    }
    throw error;
  }
  if (args.commit !== false) {
    await remove(paths.backup, { force: true, recursive: true });
  }
  return paths.pluginDir;
}

/**
 * Delete a Cursor-local plugin tree this operation created.
 *
 * User `remove` must not call this for an owned install: hash-whitelisted
 * deletes belong in `deleteVerifiedFiles`. Recursive removal is for rollback
 * of trees the current operation assembled.
 */
export async function removeCursorPlugin(args: {
  pluginId: string;
  destRoot: string;
  remove?: typeof rm;
}): Promise<void> {
  const remove = args.remove ?? rm;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  await remove(paths.pluginDir, { force: true, recursive: true });
  await remove(paths.staging, { force: true, recursive: true });
  await remove(paths.backup, { force: true, recursive: true });
}

/**
 * Restore the pre-swap Cursor tree after a later lock-write failure.
 */
export async function restoreCursorPluginInstall(args: {
  pluginId: string;
  destRoot: string;
  created?: boolean;
  swapped?: boolean;
  remove?: typeof rm;
  move?: typeof rename;
}): Promise<void> {
  const remove = args.remove ?? rm;
  const move = args.move ?? rename;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  if (args.swapped && existsSync(paths.backup)) {
    await remove(paths.pluginDir, { force: true, recursive: true });
    await move(paths.backup, paths.pluginDir);
  } else if (args.created) {
    await remove(paths.pluginDir, { force: true, recursive: true });
    await remove(paths.backup, { force: true, recursive: true });
  }
  await remove(paths.staging, { force: true, recursive: true });
}

/**
 * Discard the `.bak` sidecar after the gateway lock write succeeds.
 */
export async function discardCursorPluginBackup(args: {
  pluginId: string;
  destRoot: string;
  remove?: typeof rm;
}): Promise<void> {
  const remove = args.remove ?? rm;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  await remove(paths.backup, { force: true, recursive: true });
  await remove(paths.staging, { force: true, recursive: true });
}

function cursorPluginPaths(
  destRoot: string,
  pluginId: string,
): { backup: string; pluginDir: string; staging: string } {
  assertSafePluginId(pluginId);
  const pluginDir = join(destRoot, pluginId);
  assertInsideRoot(destRoot, pluginDir);
  return {
    backup: `${pluginDir}.bak`,
    pluginDir,
    staging: `${pluginDir}.staging`,
  };
}

/**
 * @throws {Error} When `candidate` escapes `root`.
 */
export function assertInsideRoot(root: string, candidate: string): void {
  const resolvedRoot = resolve(root);
  const resolvedCandidate = resolve(candidate);
  const prefix = resolvedRoot.endsWith(sep) ? resolvedRoot : `${resolvedRoot}${sep}`;
  if (resolvedCandidate !== resolvedRoot && !resolvedCandidate.startsWith(prefix)) {
    throw new Error(`Refusing to touch path outside Cursor plugin root: ${candidate}`);
  }
}

/**
 * Copy dest files that staging does not already contain so a swap keeps
 * untracked user data.
 */
async function copyUntrackedFiles(
  fromDir: string,
  toDir: string,
  copy: typeof cp,
  makeDir: typeof mkdir,
  relativePrefix: string = "",
): Promise<void> {
  let entries;
  try {
    entries = await readdir(fromDir, { withFileTypes: true });
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return;
    }
    throw error;
  }
  for (const entry of entries) {
    const relative = relativePrefix === "" ? entry.name : `${relativePrefix}/${entry.name}`;
    if (isCatalogOwnedPath(relative)) {
      continue;
    }
    const from = join(fromDir, entry.name);
    const to = join(toDir, entry.name);
    if (entry.isDirectory()) {
      await copyUntrackedFiles(from, to, copy, makeDir, relative);
      continue;
    }
    if (!existsSync(to)) {
      await makeDir(dirname(to), { recursive: true });
      await copy(from, to, { recursive: true });
    }
  }
}

/**
 * Whether a dest path belongs to the catalog skill tree.
 *
 * Staging already holds the new catalog copy of every retained skill, so no
 * dest file under `skills/` is user data — including files deleted upstream
 * inside a skill that is still in the plugin.
 */
function isCatalogOwnedPath(relative: string): boolean {
  return relative === "skills" || relative.startsWith("skills/");
}
