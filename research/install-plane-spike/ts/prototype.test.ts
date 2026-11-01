import { afterEach, beforeEach, expect, test } from "bun:test";
import { cp, mkdtemp, readFile, rm, writeFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { install } from "./prototype";

let root: string;
let fixture: string;
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "spike-ts-"));
  fixture = join(root, "fixture");
  await cp(join(import.meta.dir, "../fixtures"), fixture, { recursive: true });
});
afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

test("shared golden fixture is materialized after set subtraction", async () => {
  const expected = JSON.parse(
    await readFile(join(fixture, "expected-output.json"), "utf8"),
  ) as Record<string, string>;
  expect(await install({ fixture, home: root, exclude: "fixture:drop" })).toEqual(expected);
  expect(await readFile(join(root, ".spike-target/keep/SKILL.md"), "utf8")).toEqual(
    String(expected["keep/SKILL.md"]),
  );
  await expect(access(join(root, ".spike-target/drop"))).rejects.toThrow();
});

test.each([
  "archive",
  "file",
  "closure",
  "missing-closure",
  "unknown-closure",
  "path",
  "duplicate",
])("%s fails before writes", async (mutation) => {
  const index = JSON.parse(await readFile(join(fixture, "index.json"), "utf8")) as {
    sha256: string;
    capabilities: { id: string; closure?: string[]; files: Record<string, string> }[];
  };
  const keep = index.capabilities.find((cap) => cap.id === "fixture:keep");
  if (!keep) throw new Error("fixture missing keep");
  if (mutation === "archive") index.sha256 = "0".repeat(64);
  if (mutation === "file") keep.files["keep/SKILL.md"] = "0".repeat(64);
  if (mutation === "closure") keep.closure = ["fixture:drop"];
  if (mutation === "missing-closure") delete keep.closure;
  if (mutation === "unknown-closure") keep.closure = ["fixture:missing"];
  if (mutation === "path") keep.files = { "../escape": "0".repeat(64) };
  if (mutation === "duplicate") index.capabilities.push(keep);
  await writeFile(join(fixture, "index.json"), JSON.stringify(index));
  await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow();
  await expect(access(join(root, ".spike-target"))).rejects.toThrow();
});
