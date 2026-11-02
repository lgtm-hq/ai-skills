import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

import { CHECKOUT_ROOT } from "../lib/paths.ts";

test("gateway contains no authored JavaScript", () => {
  // Authored means tracked or new source; generator-owned vendor bake trees
  // contain upstream scripts and are ignored artifacts, like dist/node_modules.
  const result = spawnSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "--", "npm/ai-skills"],
    { cwd: CHECKOUT_ROOT, encoding: "utf8" },
  );
  expect(result.status).toBe(0);
  expect(
    result.stdout
      .split("\n")
      .filter(
        (path) =>
          /\.[cm]?js$/.test(path) &&
          !/^npm\/ai-skills\/(dist|node_modules)\//.test(path) &&
          existsSync(join(CHECKOUT_ROOT, path)),
      ),
  ).toEqual([]);
});
