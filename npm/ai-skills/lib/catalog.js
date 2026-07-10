import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const DATA_ROOT = new URL("../data/", import.meta.url);

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
 * @returns {Promise<{vendors: Array<{id: string, repo: string, sha: string, skillRoots: string[], license: string, homepage: string}>}>} Vendor registry.
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
  return readCatalog(`vendor-indexes/${vendorId}.json`);
}
