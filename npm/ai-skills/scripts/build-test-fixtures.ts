import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { PACKAGE_ROOT } from "../lib/paths.ts";

// Build before test discovery: both the golden and runtime tests execute dist.
const result = spawnSync(process.execPath, ["run", "build"], {
  cwd: PACKAGE_ROOT,
  encoding: "utf8",
});
assert.equal(result.status, 0, result.stdout + result.stderr);
