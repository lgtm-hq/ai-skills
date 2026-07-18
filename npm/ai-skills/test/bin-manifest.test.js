import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageJsonPath = join(dirname(fileURLToPath(import.meta.url)), "..", "package.json");
const manifest = JSON.parse(readFileSync(packageJsonPath, "utf8"));

describe("package.json bin manifest", () => {
  test("exposes exactly skill and sk pointing at the same file", () => {
    expect(manifest.bin).toEqual({
      skill: "bin/skill.js",
      sk: "bin/skill.js",
    });
  });

  test("does not ship an ai-skills or skills binary", () => {
    expect(manifest.bin).not.toHaveProperty("ai-skills");
    expect(manifest.bin).not.toHaveProperty("skills");
  });
});
