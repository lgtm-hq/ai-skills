import { afterEach, beforeEach, expect, test, spyOn } from "bun:test";
import { cp, mkdtemp, readFile, rm, writeFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { install } from "./prototype";
import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";

let root: string;
let fixture: string;

const duplicateCases = JSON.parse(
  await readFile(join(import.meta.dir, "../invalid-index-keys.json"), "utf8"),
) as { key: string; previous: string }[];
for (const { key, previous } of duplicateCases) {
  test.each([false, true])(`duplicate ${key} (escaped=%s) is rejected`, async (escaped) => {
    const path = join(fixture, "index.json");
    const repeated = escaped
      ? `\\u${key.charCodeAt(0).toString(16).padStart(4, "0")}${key.slice(1)}`
      : key;
    const raw = (await readFile(path, "utf8")).replace(
      `"${key}":`,
      `"${key}": ${previous}, "${repeated}":`,
    );
    await writeFile(path, raw);
    await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow(
      "duplicate index key",
    );
    await expect(access(join(root, ".spike-target"))).rejects.toThrow();
  });
}

test.each(["mkdir", "write"])("%s failure cleans output and permits retry", async (failure) => {
  const home = join(root, "home");
  await fs.mkdir(home);
  const originalMkdir = fs.mkdir;
  const originalWrite = fs.writeFile;
  // The forwarding wrapper preserves mkdir overloads on non-failure paths.
  const injected =
    failure === "mkdir"
      ? spyOn(fs, "mkdir").mockImplementation((async (...args: Parameters<typeof fs.mkdir>) => {
          if (String(args[0]).includes("keep")) throw new Error("injected output failure");
          return originalMkdir(...args);
        }) as typeof fs.mkdir)
      : spyOn(fs, "writeFile").mockImplementation(
          async (...args: Parameters<typeof fs.writeFile>) => {
            if (String(args[0]).includes("SKILL.md")) {
              await originalWrite(args[0], "partial bytes before failure");
              throw new Error("injected output failure");
            }
            return originalWrite(...args);
          },
        );
  try {
    await expect(install({ fixture, home, exclude: "fixture:drop" })).rejects.toThrow(
      "injected output failure",
    );
    expect(await fs.readdir(home)).toEqual([]);
  } finally {
    injected.mockRestore();
  }
  const expected = JSON.parse(
    await readFile(join(fixture, "expected-output.json"), "utf8"),
  ) as Record<string, string>;
  expect(await install({ fixture, home, exclude: "fixture:drop" })).toEqual(expected);
  expect(await fs.readdir(home)).toEqual([".spike-target"]);
});

test.each([false, true])("existing target is preserved (occupied=%s)", async (occupied) => {
  const target = join(root, ".spike-target");
  await fs.mkdir(target);
  if (occupied) await writeFile(join(target, "owned"), "preserve me");
  await expect(install({ fixture, home: root, exclude: "fixture:drop" })).rejects.toThrow();
  expect((await fs.readdir(root)).sort()).toEqual([".spike-target", "fixture"]);
  expect(await fs.readdir(target)).toEqual(occupied ? ["owned"] : []);
  if (occupied) expect(await readFile(join(target, "owned"), "utf8")).toBe("preserve me");
});

test("staging cleanup failure after publication preserves successful installation", async () => {
  const originalRm = fs.rm;
  const cleanupError = new Error("injected staging cleanup failure");
  const removed = spyOn(fs, "rm").mockImplementation(async (...args: Parameters<typeof fs.rm>) => {
    if (String(args[0]).includes(".spike-stage-")) throw cleanupError;
    return originalRm(...args);
  });
  const warning = spyOn(console, "warn").mockImplementation(() => {});
  try {
    const expected = JSON.parse(
      await readFile(join(fixture, "expected-output.json"), "utf8"),
    ) as Record<string, string>;
    expect(await install({ fixture, home: root, exclude: "fixture:drop" })).toEqual(expected);
    for (const [name, content] of Object.entries(expected)) {
      expect(await readFile(join(root, ".spike-target", name), "utf8")).toBe(content);
    }
    expect(warning).toHaveBeenCalledWith(
      "Installation completed; staging cleanup failed:",
      cleanupError,
    );
    expect((await fs.readdir(root)).some((name) => name.startsWith(".spike-stage-"))).toBe(true);
  } finally {
    removed.mockRestore();
    warning.mockRestore();
  }
});

test("prepublication cleanup failure retains original error and permits retry", async () => {
  const originalRm = fs.rm;
  const publicationError = new Error("injected publication failure");
  const cleanupError = new Error("injected staging cleanup failure");
  const renamed = spyOn(fs, "rename").mockRejectedValue(publicationError);
  const removed = spyOn(fs, "rm").mockImplementation(async (...args: Parameters<typeof fs.rm>) => {
    if (String(args[0]).includes(".spike-stage-")) throw cleanupError;
    return originalRm(...args);
  });
  try {
    const failure = await install({ fixture, home: root, exclude: "fixture:drop" }).catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(AggregateError);
    if (!(failure instanceof AggregateError)) throw new Error("expected combined errors");
    expect(failure.cause).toBe(publicationError);
    expect(failure.errors).toEqual([publicationError, cleanupError]);
    expect(failure.message).toContain(publicationError.message);
    expect(failure.message).toContain(cleanupError.message);
    await expect(access(join(root, ".spike-target"))).rejects.toThrow();
  } finally {
    renamed.mockRestore();
    removed.mockRestore();
  }
  const expected = JSON.parse(
    await readFile(join(fixture, "expected-output.json"), "utf8"),
  ) as Record<string, string>;
  expect(await install({ fixture, home: root, exclude: "fixture:drop" })).toEqual(expected);
});
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
