import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PACKAGE_ROOT } from "./paths.ts";

/**
 * Resolve the gateway package version for install pins and lock metadata.
 *
 * `bunx` / direct `node bin/skill.js` do not set `npm_package_version`, so
 * fall back to the on-disk `package.json` shipped in the published tarball.
 */
export function getPackageVersion(
  options: { env?: NodeJS.ProcessEnv; packageJsonPath?: string } = {},
): string {
  const env = options.env ?? process.env;
  if (env.npm_package_version) {
    return env.npm_package_version;
  }
  const packageJsonPath = options.packageJsonPath ?? join(PACKAGE_ROOT, "package.json");
  return JSON.parse(readFileSync(packageJsonPath, "utf8")).version;
}
