import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PACKAGE_ROOT } from "../lib/paths.ts";

/** Verify an actual archive, in addition to Bun's dry-run listing. */
const root = await mkdtemp(join(tmpdir(), "ai-skills-pack-"));
try {
  const options = { cwd: PACKAGE_ROOT, encoding: "utf8" as const };
  const dryRun = spawnSync(process.execPath, ["pm", "pack", "--dry-run"], options);
  assert.equal(dryRun.status, 0, dryRun.stderr);
  const archive = join(root, "gateway.tgz");
  const packed = spawnSync(process.execPath, ["pm", "pack", "--filename", archive], options);
  assert.equal(packed.status, 0, packed.stderr);
  const listing = spawnSync("tar", ["-tzf", archive], { encoding: "utf8" });
  assert.equal(listing.status, 0, listing.stderr);
  const files = listing.stdout.trim().split("\n");
  assert(files.includes("package/dist/bin/skill.js"));
  assert(files.includes("package/dist/lib/cli.js"));
  assert(files.includes("package/data/bundles.json"));
  // Canonical upstream resources keep their original names and bytes.
  assert(
    !files.some((path) => !path.startsWith("package/data/plugins-baked/") && /\.tsx?$/.test(path)),
  );
  assert(!files.some((path) => /^package\/(test|scripts|bin|lib)\//.test(path)));
  const extracted = spawnSync("tar", ["-xzf", archive, "-C", root], { encoding: "utf8" });
  assert.equal(extracted.status, 0, extracted.stderr);
  const manifest: { bin: Record<string, string> } = JSON.parse(
    await readFile(join(root, "package/package.json"), "utf8"),
  );
  assert.deepEqual(manifest.bin, { skill: "dist/bin/skill.js", sk: "dist/bin/skill.js" });
  await symlink(join(PACKAGE_ROOT, "node_modules"), join(root, "package/node_modules"), "dir");
  const node = Bun.which("node");
  assert(node);
  await mkdir(join(root, "empty"));
  // The tarball resolves catalog/version without checkout paths or dependencies.
  const result = spawnSync(node, [join(root, "package/dist/bin/skill.js"), "vendors"], {
    cwd: join(root, "empty"),
    encoding: "utf8",
    env: { ...process.env, PATH: "", AI_SKILLS_NO_UPDATE_CHECK: "1", AI_SKILLS_RUNTIME_ROOT: "" },
  });
  assert.equal(result.status, 0, result.stderr);
  assert(result.stdout.includes("mattpocock\t"));
  console.log(
    `Pack content PASS: ${files.length} entries, emitted JS and data; no gateway sources/tests`,
  );
} finally {
  await rm(root, { force: true, recursive: true });
}
