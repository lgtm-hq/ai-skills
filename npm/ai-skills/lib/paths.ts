import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Find the package by identity, independently of source/dist depth or cwd. */
export function findPackageRoot(moduleUrl: string = import.meta.url): string {
  let current = dirname(fileURLToPath(moduleUrl));
  for (;;) {
    const manifest = join(current, "package.json");
    if (existsSync(manifest)) {
      const parsed: { name?: string } = JSON.parse(readFileSync(manifest, "utf8"));
      if (parsed.name === "@lgtm-hq/ai-skills") {
        return current;
      }
    }
    const parent = dirname(current);
    if (parent === current) {
      throw new Error("Cannot locate @lgtm-hq/ai-skills package.json");
    }
    current = parent;
  }
}

export const PACKAGE_ROOT = findPackageRoot();
export const DATA_ROOT = join(PACKAGE_ROOT, "data");
export const CHECKOUT_ROOT = resolve(PACKAGE_ROOT, "../..");
