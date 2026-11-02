import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { CHECKOUT_ROOT, DATA_ROOT } from "./paths.ts";

const PLUGIN_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Read a bundled JSON catalog file.
 */
async function readCatalog<T>(fileName: string): Promise<T> {
  const contents = await readFile(join(DATA_ROOT, fileName), "utf8");
  return JSON.parse(contents);
}

/**
 * Load the first-party bundle catalog baked into the package.
 */
export function loadBundles(): Promise<{
  groups: Record<string, { name: string; description: string; skills: string[] }>;
}> {
  return readCatalog("bundles.json");
}

/**
 * Load all vendor records baked into the package.
 */
export function loadVendors(): Promise<{
  vendors: Array<{
    id: string;
    repo: string;
    sha: string;
    displayRef?: string;
    skillRoots: string[];
    license: string;
    homepage: string;
  }>;
}> {
  return readCatalog("vendors.json");
}

/**
 * Load one vendor's baked skill index.
 */
export function loadVendorIndex(vendorId: string): Promise<{
  skills: Array<{ name: string; path: string }>;
  vendor: { id: string; repo: string; sha: string; skillRoots: string[] };
}> {
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
 */
export function resolveBakedPluginsRoot(): string | null {
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
  const packaged = join(DATA_ROOT, "plugins-baked");
  const checkout = join(CHECKOUT_ROOT, "plugins-baked");
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
 */
export async function loadBakedPlugins(): Promise<{ plugins: BakedPlugin[] }> {
  const root = resolveBakedPluginsRoot();
  if (!root) {
    return { plugins: [] };
  }
  const marketplace = JSON.parse(
    await readFile(join(root, ".claude-plugin", "marketplace.json"), "utf8"),
  );
  const bakeLock = JSON.parse(await readFile(join(root, "BAKE.json"), "utf8"));

  const vendorByPlugin: Map<
    string,
    { id: string; repo: string; sha: string; displayRef?: string }
  > = new Map();
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

  const plugins: BakedPlugin[] = [];
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
 */
export async function loadBakedPlugin(pluginId: string): Promise<BakedPlugin | null> {
  if (!PLUGIN_ID_PATTERN.test(pluginId)) {
    throw new Error(`Invalid baked plugin identifier: ${pluginId}`);
  }
  const { plugins } = await loadBakedPlugins();
  return plugins.find((plugin) => plugin.id === pluginId) ?? null;
}

/**
 * Skill directory names under a baked plugin's `skills/` tree.
 */
async function listBakedSkillNames(pluginRoot: string): Promise<string[]> {
  const names: string[] = [];
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
 */
async function bakedPluginDescription(
  pluginRoot: string,
  entry: { description?: unknown },
  vendorId: string,
): Promise<string> {
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

/** One marketplace plugin baked from a vendor slice. */
export interface BakedPlugin {
  id: string;
  description: string;
  version: string;
  vendor: string;
  repo: string;
  sha: string;
  displayRef?: string;
  skills: string[];
  pluginRoot: string;
}
