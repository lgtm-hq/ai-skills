import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

import { PACKAGE_ROOT } from "../lib/paths.ts";

// Captured at fb3468e613584c2a7ec2aa337ffcda70a196ef63 before conversion.
// Only the ephemeral fixture-home prefix is normalized; lock bytes stay intact.
for (const mode of ["source", "dist"]) {
  test(`legacy CLI golden parity (${mode})`, () => {
    const result = spawnSync(
      process.execPath,
      [join(PACKAGE_ROOT, "scripts/golden-scenario.ts"), PACKAGE_ROOT, mode],
      { encoding: "utf8", env: { ...process.env, AI_SKILLS_NO_UPDATE_CHECK: "1" } },
    );
    expect(result.stderr).toBe("");
    expect(result.status).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual(
      JSON.parse(readFileSync(join(PACKAGE_ROOT, "test/fixtures/legacy-golden.json"), "utf8")),
    );
  });
}
