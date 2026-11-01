import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const LIMIT = 1024 * 1024;
interface Capability {
  id: string;
  closure: string[];
  files: Record<string, string>;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid object");
  }
  return value as Record<string, unknown>;
}

function keys(value: Record<string, unknown>, expected: string[]): void {
  if (Object.keys(value).sort().join(",") !== expected.sort().join(",")) {
    throw new Error("invalid fields");
  }
}

function safePath(value: string): string {
  if (
    !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_.-]+)+$/.test(value) ||
    value.split("/").some((part) => part === "." || part === ".." || part.endsWith("."))
  ) {
    throw new Error("invalid path");
  }
  return value;
}

const digest = (value: Uint8Array): string => createHash("sha256").update(value).digest("hex");

// Deliberately supports only tiny regular-file USTAR fixtures, not general extraction.
function untar(archive: Buffer): Map<string, Buffer> {
  const output = new Map<string, Buffer>();
  let offset = 0;
  while (offset + 512 <= archive.length) {
    const header = archive.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) {
      if (archive.length - offset < 1024 || !archive.subarray(offset).every((b) => b === 0)) {
        throw new Error("invalid archive trailer");
      }
      return output;
    }
    const field = (start: number, end: number): string =>
      header.subarray(start, end).toString("ascii").replace(/\0.*$/s, "");
    const sizeText = field(124, 136).trim();
    const checksumText = field(148, 156).trim();
    if (!/^[0-7]+$/.test(sizeText) || !/^[0-7]+$/.test(checksumText)) {
      throw new Error("invalid archive number");
    }
    const checksum = header.reduce(
      (total, byte, index) => total + (index >= 148 && index < 156 ? 32 : byte),
      0,
    );
    const size = Number.parseInt(sizeText, 8);
    const name = safePath(field(0, 100));
    if (
      checksum !== Number.parseInt(checksumText, 8) ||
      field(257, 263) !== "ustar" ||
      field(345, 500) !== "" ||
      ![0, 48].includes(header[156] ?? -1) ||
      output.has(name) ||
      offset + 512 + size > archive.length
    ) {
      throw new Error("invalid archive inventory");
    }
    output.set(name, archive.subarray(offset + 512, offset + 512 + size));
    offset += 512 + Math.ceil(size / 512) * 512;
  }
  throw new Error("incomplete archive");
}

export async function install({
  fixture,
  home,
  exclude,
}: {
  fixture: string;
  home: string;
  exclude: string;
}): Promise<Record<string, string>> {
  const indexBytes = await readFile(join(fixture, "index.json"));
  const archive = await readFile(join(fixture, "artifact.tar"));
  if (indexBytes.length > LIMIT || archive.length > LIMIT) throw new Error("fixture too large");
  const index = record(JSON.parse(indexBytes.toString("utf8")) as unknown);
  keys(index, ["sha256", "capabilities"]);
  if (digest(archive) !== index.sha256) throw new Error("archive digest mismatch");
  if (!Array.isArray(index.capabilities) || index.capabilities.length === 0) {
    throw new Error("missing capabilities");
  }
  const ids = new Set<string>();
  const files = new Map<string, string>();
  const retained = new Set<string>();
  const capabilities: Capability[] = index.capabilities.map((raw: unknown) => {
    const cap = record(raw);
    keys(cap, ["id", "closure", "files"]);
    if (typeof cap.id !== "string" || !cap.id || ids.has(cap.id)) {
      throw new Error("invalid capability id");
    }
    ids.add(cap.id);
    if (!Array.isArray(cap.closure) || !cap.closure.every((x: unknown) => typeof x === "string")) {
      throw new Error("missing closure");
    }
    const inventory = record(cap.files);
    if (Object.keys(inventory).length === 0) throw new Error("missing files");
    const validated: Record<string, string> = {};
    for (const [path, hash] of Object.entries(inventory)) {
      safePath(path);
      if (files.has(path) || typeof hash !== "string" || !/^[0-9a-f]{64}$/.test(hash)) {
        throw new Error("invalid file inventory");
      }
      files.set(path, hash);
      validated[path] = hash;
      if (cap.id !== exclude) retained.add(path);
    }
    return { id: cap.id, closure: cap.closure as string[], files: validated };
  });
  if (!ids.has(exclude)) throw new Error("unknown exclusion");
  for (const cap of capabilities) {
    if (new Set(cap.closure).size !== cap.closure.length || cap.closure.some((x) => !ids.has(x))) {
      throw new Error("invalid closure");
    }
    if (cap.id !== exclude && cap.closure.includes(exclude)) {
      throw new Error("retained closure contains exclusion");
    }
  }
  const contents = untar(archive);
  if (contents.size !== files.size) throw new Error("incomplete archive");
  for (const [name, payload] of contents) {
    if (digest(payload) !== files.get(name)) throw new Error("file digest mismatch");
  }
  const output: Record<string, string> = {};
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const decoded = new Map([...contents].map(([name, payload]) => [name, decoder.decode(payload)]));
  for (const name of [...retained].sort()) {
    const content = decoded.get(name);
    if (content === undefined) throw new Error("incomplete archive");
    output[name] = content;
  }
  const target = join(home, ".spike-target");
  await mkdir(target);
  for (const [name, content] of Object.entries(output)) {
    const destination = join(target, name);
    await mkdir(join(destination, ".."), { recursive: true });
    await writeFile(destination, content);
  }
  return output;
}

if (import.meta.main) {
  try {
    const [, , fixture, exclude] = process.argv;
    const home = process.env.HOME;
    if (process.argv.length !== 4 || !fixture || !exclude || !home) {
      throw new Error("usage: prototype FIXTURE EXCLUDE (requires disposable HOME)");
    }
    console.log(JSON.stringify(await install({ fixture, home, exclude })));
  } catch (error: unknown) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
