import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Resolve the gateway package version for install pins and lock metadata.
 *
 * `bunx` / direct `node bin/ai-skills.js` do not set `npm_package_version`, so
 * fall back to the on-disk `package.json` shipped in the published tarball.
 *
 * @param {{env?: NodeJS.ProcessEnv, packageJsonPath?: string}} [options] - Injectable paths/env for tests.
 * @returns {string} Semver package version.
 */
export function getPackageVersion(options = {}) {
  const env = options.env ?? process.env;
  if (env.npm_package_version) {
    return env.npm_package_version;
  }
  const packageJsonPath =
    options.packageJsonPath ?? join(dirname(fileURLToPath(import.meta.url)), "..", "package.json");
  return JSON.parse(readFileSync(packageJsonPath, "utf8")).version;
}
