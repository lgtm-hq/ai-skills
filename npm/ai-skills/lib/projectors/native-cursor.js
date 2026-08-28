import { existsSync } from "node:fs";
import { cp, mkdir, readdir, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { isSafePluginId } from "../lockfile.js";

/**
 * Whether a Cursor plugin destination has any regular files.
 *
 * Empty leftover directories (clean remove, crash leftovers) must not count as
 * an unowned tree, or the next install refuses a dest the user already cleared.
 *
 * @param {string} pluginDir - Absolute plugin destination.
 * @returns {Promise<boolean>} True when at least one regular file exists.
 */
export async function cursorDestHasFiles(pluginDir) {
  return pathHasRegularFiles(pluginDir);
}

/**
 * @param {string} dir - Directory to walk.
 * @returns {Promise<boolean>} True when a regular file exists under `dir`.
 */
async function pathHasRegularFiles(dir) {
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
 *
 * @param {{cwd?: string, home?: string, scope: "global" | "project"}} environment - Scope and path roots.
 * @returns {string} Absolute `plugins/local` directory.
 */
export function cursorPluginsRoot(environment) {
  const home = environment.home ?? homedir();
  const cwd = environment.cwd ?? process.cwd();
  const base = environment.scope === "project" ? cwd : home;
  return join(base, ".cursor", "plugins", "local");
}

/**
 * Catalog root that contains ``skills/`` and the Claude marketplace adapter.
 *
 * Checks ``cwd`` first, then the git checkout that ships this gateway module
 * when running from a clone. Published npm installs have neither.
 *
 * @param {string} [cwd] - Working directory to probe first.
 * @returns {string | null} Absolute catalog root, or null when absent.
 */
export function findCatalogSourceRoot(cwd = process.cwd()) {
  const packageRepoRoot = fileURLToPath(new URL("../../../../", import.meta.url));
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
 * @param {string} pluginId - Candidate destination folder name.
 * @returns {void}
 * @throws {Error} When the id could escape `destRoot`.
 */
export function assertSafePluginId(pluginId) {
  if (!isSafePluginId(pluginId)) {
    throw new Error(`Refusing Cursor plugin id ${JSON.stringify(pluginId)}: must be kebab-case`);
  }
}

/**
 * Reject a skill directory name that could escape the catalog `skills/` tree.
 *
 * @param {string} name - Candidate skill directory name.
 * @returns {void}
 * @throws {Error} When the name is not kebab-case.
 */
function assertSafeSkillName(name) {
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
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id (destination folder name).
 * @param {string} args.description - Plugin description for plugin.json.
 * @param {string} args.version - Plugin version for plugin.json.
 * @param {string[]} args.skills - Skill directory names to copy.
 * @param {string} args.sourceRoot - Catalog root that contains `skills/<name>/`.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {boolean} [args.replace=false] - Overwrite a destination this lock owns.
 * @param {boolean} [args.commit=true] - Discard `.bak` after a successful swap.
 * @param {typeof cp} [args.copy] - Injectable recursive copy.
 * @param {typeof mkdir} [args.makeDir] - Injectable mkdir.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @param {typeof rename} [args.move] - Injectable rename used for the swap.
 * @param {typeof writeFile} [args.write] - Injectable writer.
 * @param {{swapped?: boolean}} [args.progress] - Set `swapped` after dest moves to `.bak`.
 * @returns {Promise<string>} Absolute plugin directory.
 */
export async function installCursorPlugin(args) {
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
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @returns {Promise<void>} Resolves when the tree is gone.
 */
export async function removeCursorPlugin(args) {
  const remove = args.remove ?? rm;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  await remove(paths.pluginDir, { force: true, recursive: true });
  await remove(paths.staging, { force: true, recursive: true });
  await remove(paths.backup, { force: true, recursive: true });
}

/**
 * Restore the pre-swap Cursor tree after a later lock-write failure.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {boolean} [args.created=false] - Whether this operation created dest.
 * @param {boolean} [args.swapped=false] - Whether this operation moved dest to `.bak`.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @param {typeof rename} [args.move] - Injectable rename.
 * @returns {Promise<void>} Resolves when dest matches the pre-install tree.
 */
export async function restoreCursorPluginInstall(args) {
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
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @returns {Promise<void>} Resolves when sidecars are gone.
 */
export async function discardCursorPluginBackup(args) {
  const remove = args.remove ?? rm;
  const paths = cursorPluginPaths(args.destRoot, args.pluginId);
  await remove(paths.backup, { force: true, recursive: true });
  await remove(paths.staging, { force: true, recursive: true });
}

/**
 * @param {string} destRoot - `plugins/local` directory.
 * @param {string} pluginId - Plugin id.
 * @returns {{backup: string, pluginDir: string, staging: string}} Resolved paths.
 */
function cursorPluginPaths(destRoot, pluginId) {
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
 * @param {string} root - Directory that must contain `candidate`.
 * @param {string} candidate - Path joined from `root`.
 * @returns {void}
 * @throws {Error} When `candidate` escapes `root`.
 */
function assertInsideRoot(root, candidate) {
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
 *
 * @param {string} fromDir - Existing plugin directory.
 * @param {string} toDir - Staging directory.
 * @param {typeof cp} copy - Recursive copy.
 * @param {typeof mkdir} makeDir - mkdir for parent paths.
 * @param {string} [relativePrefix] - POSIX path from the plugin root.
 * @returns {Promise<void>} Resolves when untracked files are copied.
 */
async function copyUntrackedFiles(fromDir, toDir, copy, makeDir, relativePrefix = "") {
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
 *
 * @param {string} relative - POSIX path from the plugin root.
 * @returns {boolean} True when the path must not be preserved as user data.
 */
function isCatalogOwnedPath(relative) {
  return relative === "skills" || relative.startsWith("skills/");
}
