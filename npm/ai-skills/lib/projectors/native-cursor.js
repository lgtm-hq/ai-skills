import { existsSync } from "node:fs";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

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
  const packageRepoRoot = fileURLToPath(new URL("../../../", import.meta.url));
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
 * Assemble a Cursor-local plugin tree from sliced marketplace metadata.
 *
 * Copies each listed skill directory and writes `.claude-plugin/plugin.json`.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id (destination folder name).
 * @param {string} args.description - Plugin description for plugin.json.
 * @param {string} args.version - Plugin version for plugin.json.
 * @param {string[]} args.skills - Skill directory names to copy.
 * @param {string} args.sourceRoot - Catalog root that contains `skills/<name>/`.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {typeof cp} [args.copy] - Injectable recursive copy.
 * @param {typeof mkdir} [args.makeDir] - Injectable mkdir.
 * @param {typeof rm} [args.remove] - Injectable rm used to replace an existing tree.
 * @param {typeof writeFile} [args.write] - Injectable writer.
 * @returns {Promise<string>} Absolute plugin directory.
 */
export async function installCursorPlugin(args) {
  const copy = args.copy ?? cp;
  const makeDir = args.makeDir ?? mkdir;
  const write = args.write ?? writeFile;
  const remove = args.remove ?? rm;
  const pluginDir = join(args.destRoot, args.pluginId);
  await remove(pluginDir, { force: true, recursive: true });
  await makeDir(pluginDir, { recursive: true });
  for (const name of args.skills) {
    const from = join(args.sourceRoot, "skills", name);
    const to = join(pluginDir, "skills", name);
    await copy(from, to, { recursive: true });
  }
  const manifestDir = join(pluginDir, ".claude-plugin");
  await makeDir(manifestDir, { recursive: true });
  const manifest = {
    description: args.description,
    name: args.pluginId,
    version: args.version,
  };
  await write(join(manifestDir, "plugin.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  return pluginDir;
}

/**
 * Delete a Cursor-local plugin tree.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.pluginId - Plugin id.
 * @param {string} args.destRoot - `plugins/local` directory.
 * @param {typeof rm} [args.remove] - Injectable rm.
 * @returns {Promise<void>} Resolves when the tree is gone.
 */
export async function removeCursorPlugin(args) {
  const remove = args.remove ?? rm;
  await remove(join(args.destRoot, args.pluginId), { force: true, recursive: true });
}
