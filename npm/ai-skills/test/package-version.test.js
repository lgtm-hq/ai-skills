import { describe, expect, test } from "bun:test";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { getPackageVersion } from "../lib/package-version.js";

describe("getPackageVersion", () => {
  test("prefers npm_package_version when set", () => {
    expect(getPackageVersion({ env: { npm_package_version: "9.9.9" } })).toBe("9.9.9");
  });

  test("reads package.json when env is unset", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-version-"));
    try {
      const packageJsonPath = join(cwd, "package.json");
      await writeFile(packageJsonPath, JSON.stringify({ version: "1.2.3" }));
      expect(getPackageVersion({ env: {}, packageJsonPath })).toBe("1.2.3");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });
});
