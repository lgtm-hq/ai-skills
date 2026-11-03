import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, parse } from "node:path";

import { CHECKOUT_ROOT } from "../lib/paths.ts";

function isAuthoredJavaScript(path: string): boolean {
  return (
    /\.[cm]?js$/.test(path) &&
    // Existing .gitignore policy: emitted gateway code, dependencies and bakes.
    !/^npm\/ai-skills\/(dist|node_modules|runtime-staging)\//.test(path) &&
    !/^(plugins-baked|npm\/ai-skills\/data\/plugins-baked)\//.test(path)
  );
}

test.each(["js", "mjs", "cjs"])(
  "maintained fixtures cannot introduce authored .%s",
  (extension) => {
    expect(isAuthoredJavaScript(`tests/fixtures/manifest/runner.${extension}`)).toBe(true);
  },
);

test.each([
  "npm/ai-skills/dist/bin/skill.js",
  "npm/ai-skills/node_modules/example/index.js",
  "npm/ai-skills/runtime-staging/launcher.js",
  "plugins-baked/example/script.js",
  "npm/ai-skills/data/plugins-baked/example/script.js",
  "tests/fixtures/manifest/renovate/upstream.ts.txt",
])("generated artifacts and upstream byte snapshots retain their policy: %s", (path) => {
  expect(isAuthoredJavaScript(path)).toBe(false);
});

test("repository contains no authored JavaScript", () => {
  // Authored means tracked or new source; generator-owned vendor bake trees
  // contain upstream scripts and are ignored artifacts, like dist/node_modules.
  const result = spawnSync("git", ["ls-files", "--cached", "--others", "--exclude-standard"], {
    cwd: CHECKOUT_ROOT,
    encoding: "utf8",
  });
  expect(result.status).toBe(0);
  expect(
    result.stdout
      .split("\n")
      .filter((path) => isAuthoredJavaScript(path) && existsSync(join(CHECKOUT_ROOT, path))),
  ).toEqual([]);
});

test.each(["valid", "unchecked-index", "missing-types"])(
  "the actual fixture typecheck fails closed: %s",
  (control) => {
    const scratch = mkdtempSync(join(tmpdir(), "manifest-fixture-types-"));
    const gateway = join(CHECKOUT_ROOT, "npm/ai-skills");
    try {
      const probe = join(scratch, "probe.ts");
      writeFileSync(
        probe,
        control === "unchecked-index"
          ? "export {}; const values: string[] = []; values[0].toUpperCase();\n"
          : "export {};\n",
      );
      const config = join(scratch, "tsconfig.json");
      writeFileSync(
        config,
        JSON.stringify({
          extends: join(gateway, "tsconfig.fixtures.json"),
          compilerOptions: {
            rootDir: parse(CHECKOUT_ROOT).root,
            types: [
              control === "missing-types"
                ? "missing-manifest-runtime-types"
                : join(gateway, "node_modules/bun-types"),
            ],
          },
          include: [join(CHECKOUT_ROOT, "tests/fixtures/manifest/*.ts"), probe],
        }),
      );
      const result = spawnSync("bunx", ["--no-install", "tsc", "--noEmit", "-p", config], {
        cwd: gateway,
        encoding: "utf8",
        timeout: 30_000,
      });
      expect(result.error).toBeUndefined();
      expect(result.status, result.stdout + result.stderr).toBe(control === "valid" ? 0 : 1);
      if (control === "unchecked-index") expect(result.stdout).toContain("possibly 'undefined'");
      if (control === "missing-types")
        expect(result.stdout).toContain("Cannot find type definition file");
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);
