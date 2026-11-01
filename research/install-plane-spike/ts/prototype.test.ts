import { afterEach, beforeEach, expect, test, spyOn } from "bun:test";
import { cp, mkdtemp, readFile, rm, writeFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { install } from "./prototype";
import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";

let root: string;
let fixture: string;
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "spike-ts-"));
  fixture = join(root, "fixture");
  await cp(join(import.meta.dir, "../fixtures"), fixture, { recursive: true });
});

test.each(["index.json", "artifact.tar"])(
  "%s reads only its fixed budget before validation",
  async (filename) => {
    const limit = 1024 * 1024;
    const path = join(fixture, filename);
    const handle = await fs.open(path, "w");
    await handle.truncate(64 * limit);
    await handle.close();
    const originalOpen = fs.open;
    const verifyReads: (() => void)[] = [];
    const opened = spyOn(fs, "open").mockImplementation(
      async (...args: Parameters<typeof fs.open>) => {
        const input = await originalOpen(...args);
        if (args[0] === path) {
          const read = spyOn(input, "read");
          const closed = spyOn(input, "close");
          verifyReads.push(() => {
            expect(read).toHaveBeenCalledTimes(1);
            // FileHandle.read is overloaded; inspect the actual positional call.
            const [buffer, offset, length] = read.mock.calls[0] as unknown as [
              Uint8Array,
              number,
              number,
            ];
            expect(buffer.byteLength).toBe(limit + 1);
            expect(offset).toBe(0);
            expect(length).toBe(limit + 1);
            expect(closed).toHaveBeenCalledTimes(1);
          });
        }
        return input;
      },
    );
    try {
      await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow(
        "fixture too large",
      );
      expect(verifyReads).toHaveLength(1);
      for (const verify of verifyReads) verify();
      await expect(access(join(root, ".spike-target"))).rejects.toThrow();
    } finally {
      opened.mockRestore();
    }
  },
);
afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

test.each([
  { name: "a/" + "b".repeat(99), reason: "path length limit" },
  { name: "a/".repeat(16) + "b", reason: "path depth limit" },
  { name: "a/".repeat(5000) + "b", reason: "path length limit" },
  // Inclusive boundaries reach inventory checking, rather than path rejection.
  { name: "a/" + "b".repeat(98), reason: "incomplete archive" },
  { name: "a/".repeat(15) + "b", reason: "incomplete archive" },
])("path profile: $reason ($name)", async ({ name, reason }) => {
  const index = JSON.parse(await readFile(join(fixture, "index.json"), "utf8")) as {
    capabilities: { files: Record<string, string> }[];
  };
  const capability = index.capabilities[0];
  if (!capability) throw new Error("missing capability");
  capability.files[name] = "0".repeat(64);
  const raw = JSON.stringify(index);
  expect(Buffer.byteLength(raw)).toBeLessThan(1024 * 1024);
  await writeFile(join(fixture, "index.json"), raw);
  await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow(reason);
  await expect(access(join(root, ".spike-target"))).rejects.toThrow();
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
  const installed = await readFile(join(root, ".spike-target/keep/SKILL.md"));
  const index = JSON.parse(await readFile(join(fixture, "index.json"), "utf8")) as {
    capabilities: { id: string; files: Record<string, string> }[];
  };
  expect(installed.subarray(0, 3)).toEqual(Buffer.from([0xef, 0xbb, 0xbf]));
  const hash = index.capabilities.find((cap) => cap.id === "fixture:keep")?.files["keep/SKILL.md"];
  if (!hash) throw new Error("fixture missing digest");
  expect(createHash("sha256").update(installed).digest("hex")).toBe(hash);
});

test.each([
  "archive",
  "file",
  "closure",
  "missing-closure",
  "unknown-closure",
  "path",
  "duplicate",
  "case-file",
  "case-directory",
  "file-directory",
  "reserved-file",
  "reserved-directory",
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
  const first = index.capabilities[0];
  if (!first) throw new Error("fixture missing capability");
  if (mutation === "case-file") first.files["keep/skill.MD"] = "0".repeat(64);
  if (mutation === "case-directory") keep.files["KEEP/other.md"] = "0".repeat(64);
  if (mutation === "file-directory") keep.files["keep/SKILL.md/child"] = "0".repeat(64);
  if (mutation === "reserved-file") keep.files["keep/nUl.txt"] = "0".repeat(64);
  if (mutation === "reserved-directory") keep.files["COM1/child.md"] = "0".repeat(64);
  await writeFile(join(fixture, "index.json"), JSON.stringify(index));
  await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow();
  await expect(access(join(root, ".spike-target"))).rejects.toThrow();
});
