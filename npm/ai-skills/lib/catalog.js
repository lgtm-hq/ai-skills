import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DATA_ROOT = new URL("../data/", import.meta.url);
const PLUGIN_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * @typedef {{
 *   id: string,
 *   description: string,
 *   version: string,
 *   vendor: string,
 *   repo: string,
 *   sha: string,
 *   displayRef?: string,
 *   skills: string[],
 *   pluginRoot: string,
 * }} BakedPlugin
 * One marketplace plugin baked from a vendor slice.
 */

/**
 * Read a bundled JSON catalog file.
 *
 * @template T
 * @param {string} fileName - Relative file name below the package data directory.
 * @returns {Promise<T>} Parsed catalog data.
 */
async function readCatalog(fileName) {
  const contents = await readFile(fileURLToPath(new URL(fileName, DATA_ROOT)), "utf8");
  return JSON.parse(contents);
}

/**
 * Load the first-party bundle catalog baked into the package.
 *
 * @returns {Promise<{groups: Record<string, {name: string, description: string, skills: string[]}>}>} Bundle catalog.
 */
export function loadBundles() {
  return readCatalog("bundles.json");
}

/**
 * Load all vendor records baked into the package.
 *
 * @returns {Promise<{vendors: Array<{id: string, repo: string, sha: string, displayRef?: string, skillRoots: string[], license: string, homepage: string}>}>} Vendor registry.
 */
export function loadVendors() {
  return readCatalog("vendors.json");
}

/**
 * Load one vendor's baked skill index.
 *
 * @param {string} vendorId - Registry vendor identifier.
 * @returns {Promise<{skills: Array<{name: string, path: string}>, vendor: {id: string, repo: string, sha: string, skillRoots: string[]}}>} Vendor skill index.
 */
export function loadVendorIndex(vendorId) {
  if (!PLUGIN_ID_PATTERN.test(vendorId)) {
    throw new Error(`Invalid vendor identifier: ${vendorId}`);
  }
  return readCatalog(`vendor-indexes/${vendorId}.json`);
}

/**
 * Directory that holds bake output (marketplace + plugin trees).
 *
 * Prefers an explicit ``AI_SKILLS_PLUGINS_BAKED`` override (tests). When that
 * env is set, a missing or incomplete tree is treated as absent (no
 * fall-through to the packaged or checkout bake). Otherwise uses the copy
 * shipped inside the npm package, then the repository checkout when running
 * from a clone after a local bake.
 *
 * @returns {string | null} Absolute `plugins-baked` root, or null when absent.
 */
export function resolveBakedPluginsRoot() {
  const override = process.env.AI_SKILLS_PLUGINS_BAKED;
  if (typeof override === "string" && override.trim()) {
    const root = override.trim();
    if (
      existsSync(join(root, ".claude-plugin", "marketplace.json")) &&
      existsSync(join(root, "BAKE.json"))
    ) {
      return root;
    }
    return null;
  }
  const packaged = fileURLToPath(new URL("plugins-baked/", DATA_ROOT));
  const checkout = fileURLToPath(new URL("../../../plugins-baked/", import.meta.url));
  for (const root of [packaged, checkout]) {
    if (
      existsSync(join(root, ".claude-plugin", "marketplace.json")) &&
      existsSync(join(root, "BAKE.json"))
    ) {
      return root;
    }
  }
  return null;
}

/**
 * Load baked vendor plugins from the marketplace and bake lock.
 *
 * @returns {Promise<{plugins: BakedPlugin[]}>} Baked plugins in marketplace order.
 */
export async function loadBakedPlugins() {
  const root = resolveBakedPluginsRoot();
  if (!root) {
    return { plugins: [] };
  }
  const marketplace = JSON.parse(
    await readFile(join(root, ".claude-plugin", "marketplace.json"), "utf8"),
  );
  const bakeLock = JSON.parse(await readFile(join(root, "BAKE.json"), "utf8"));
  /** @type {Map<string, {id: string, repo: string, sha: string, displayRef?: string}>} */
  const vendorByPlugin = new Map();
  for (const vendor of bakeLock.vendors ?? []) {
    if (!vendor || typeof vendor !== "object" || typeof vendor.id !== "string") {
      continue;
    }
    for (const plugin of vendor.plugins ?? []) {
      if (plugin && typeof plugin === "object" && typeof plugin.id === "string") {
        vendorByPlugin.set(plugin.id, vendor);
      }
    }
  }
  /** @type {BakedPlugin[]} */
  const plugins = [];
  for (const entry of marketplace.plugins ?? []) {
    if (!entry || typeof entry !== "object" || typeof entry.name !== "string") {
      throw new Error("Baked marketplace plugin is missing a name");
    }
    const id = entry.name;
    if (!PLUGIN_ID_PATTERN.test(id)) {
      throw new Error(`Invalid baked plugin identifier: ${id}`);
    }
    const vendor = vendorByPlugin.get(id);
    if (!vendor) {
      throw new Error(`Baked plugin missing bake lock vendor: ${id}`);
    }
    if (typeof vendor.repo !== "string" || typeof vendor.sha !== "string") {
      throw new Error(`Baked plugin lock vendor is malformed: ${id}`);
    }
    const pluginRoot = join(root, id);
    const skills = await listBakedSkillNames(pluginRoot);
    const description = await bakedPluginDescription(pluginRoot, entry, vendor.id);
    plugins.push({
      id,
      description,
      version: typeof entry.version === "string" ? entry.version : "",
      vendor: vendor.id,
      repo: vendor.repo,
      sha: vendor.sha,
      displayRef: vendor.displayRef,
      skills,
      pluginRoot,
    });
  }
  return { plugins };
}

/**
 * Load one baked plugin by id.
 *
 * @param {string} pluginId - Marketplace plugin identifier.
 * @returns {Promise<BakedPlugin | null>} Matching plugin, or null when unknown.
 */
export async function loadBakedPlugin(pluginId) {
  if (!PLUGIN_ID_PATTERN.test(pluginId)) {
    throw new Error(`Invalid baked plugin identifier: ${pluginId}`);
  }
  const { plugins } = await loadBakedPlugins();
  return plugins.find((plugin) => plugin.id === pluginId) ?? null;
}

/**
 * Skill directory names under a baked plugin's `skills/` tree.
 *
 * @param {string} pluginRoot - Absolute baked plugin directory.
 * @returns {Promise<string[]>} Sorted skill directory names.
 */
async function listBakedSkillNames(pluginRoot) {
  /** @type {string[]} */
  const names = [];
  let entries;
  try {
    entries = await readdir(join(pluginRoot, "skills"), { withFileTypes: true });
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      throw new Error(`Baked plugin missing skills directory: ${pluginRoot}`);
    }
    throw error;
  }
  for (const entry of entries) {
    if (entry.isDirectory() && PLUGIN_ID_PATTERN.test(entry.name)) {
      names.push(entry.name);
    }
  }
  names.sort();
  return names;
}

/**
 * Prefer the stamped plugin.json description so list/detail show provenance.
 *
 * @param {string} pluginRoot - Absolute baked plugin directory.
 * @param {{description?: unknown}} entry - Marketplace plugin row.
 * @param {string} vendorId - Registry vendor identifier.
 * @returns {Promise<string>} Description including bake provenance.
 */
async function bakedPluginDescription(pluginRoot, entry, vendorId) {
  try {
    const manifest = JSON.parse(await readFile(join(pluginRoot, "plugin.json"), "utf8"));
    if (manifest && typeof manifest.description === "string" && manifest.description.trim()) {
      return manifest.description;
    }
  } catch (error) {
    if (!(error && typeof error === "object" && "code" in error && error.code === "ENOENT")) {
      throw error;
    }
  }
  const description = typeof entry.description === "string" ? entry.description.trim() : "";
  const base = description || pluginRoot;
  const suffix = `[baked from vendor '${vendorId}']`;
  return base.includes(suffix) ? base : `${base} ${suffix}`;
}
