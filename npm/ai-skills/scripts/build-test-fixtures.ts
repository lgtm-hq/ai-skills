import { afterAll } from "bun:test";
import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PACKAGE_ROOT } from "../lib/paths.ts";
import { STATE_DIR_ENV } from "../lib/journal/receipts.ts";

// Build before test discovery: both the golden and runtime tests execute dist.
const result = spawnSync(process.execPath, ["run", "build"], {
  cwd: PACKAGE_ROOT,
  encoding: "utf8",
});
assert.equal(result.status, 0, result.stdout + result.stderr);

// Tests that pass no explicit home must never write receipts, journals or the
// state lock under the real ~/.ai-skills: route machine-local state to a
// throwaway directory (child processes inherit it) and remove it on exit.
const stateDir = mkdtempSync(join(tmpdir(), "ai-skills-test-state-"));
process.env[STATE_DIR_ENV] = stateDir;
afterAll(() => {
  rmSync(stateDir, { force: true, recursive: true });
});
