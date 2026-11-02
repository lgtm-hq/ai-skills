import { createHash } from "node:crypto";
import { mkdir, mkdtemp, open, readdir, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import "./network-control";

const LIMIT = 1024 * 1024;
const PATH_LIMIT = 100; // ASCII bytes/characters; tiny USTAR name field.
const PATH_DEPTH = 16;
const JSON_DEPTH = 64;
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
  // Bound work before regex, split, or retaining directory prefixes.
  if (value.length > PATH_LIMIT) throw new Error("path length limit");
  let separators = 0;
  for (const character of value) {
    if (character === "/" && ++separators >= PATH_DEPTH) throw new Error("path depth limit");
  }
  if (
    !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_.-]+)+$/.test(value) ||
    value
      .split("/")
      .some(
        (part) =>
          part === "." ||
          part === ".." ||
          part.endsWith(".") ||
          /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i.test(part),
      )
  ) {
    throw new Error("invalid path");
  }
  return value;
}

const digest = (value: Uint8Array): string => createHash("sha256").update(value).digest("hex");

// Deliberately supports only tiny regular-file USTAR fixtures, not general extraction.
function untar(archive: Buffer): Map<string, Buffer> {
  if (archive.length % 512 !== 0) throw new Error("invalid archive length");
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
    if (header.some((byte) => byte >= 0x80)) throw new Error("non-ASCII archive header");
    const field = (start: number, end: number): string => {
      const bytes = header.subarray(start, end);
      const terminator = bytes.indexOf(0);
      if (terminator !== -1 && bytes.subarray(terminator).some((byte) => byte !== 0)) {
        throw new Error("nonzero bytes after archive string terminator");
      }
      return bytes.subarray(0, terminator === -1 ? bytes.length : terminator).toString("ascii");
    };
    const octal = (start: number, end: number): number => {
      const text = header.subarray(start, end).toString("ascii");
      // Empty numbers (including size) are outside this fixture profile.
      if (!/^ *[0-7]+[ \0]*$/.test(text)) throw new Error("invalid archive number");
      return Number.parseInt(text, 8);
    };
    for (const [start, end] of [
      [100, 108],
      [108, 116],
      [116, 124],
      [136, 148],
    ] as const) {
      octal(start, end);
    }
    field(157, 257);
    field(265, 297);
    field(297, 329);
    const checksum = header.reduce(
      (total, byte, index) => total + (index >= 148 && index < 156 ? 32 : byte),
      0,
    );
    const size = octal(124, 136);
    const name = safePath(field(0, 100));
    if (
      checksum !== octal(148, 156) ||
      !header.subarray(257, 263).equals(Buffer.from("ustar\0")) ||
      header.subarray(345, 512).some((byte) => byte !== 0) ||
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

function parseIndex(raw: string): unknown {
  // Scan JSON strings/containers before native parsing discards duplicate keys.
  // JSON.parse still validates the complete grammar; it decodes key escapes here.
  const containers: (Set<string> | null)[] = [];
  const stringToken = /"(?:[^"\\]|\\.)*"/y;
  for (let offset = 0; offset < raw.length; offset++) {
    const char = raw[offset];
    if (char === '"') {
      stringToken.lastIndex = offset;
      const token = stringToken.exec(raw)?.[0];
      if (token === undefined) throw new SyntaxError("invalid index JSON");
      let next = offset + token.length;
      while (/\s/.test(raw[next] ?? "") && next < raw.length) next++;
      const keys = containers.at(-1);
      if (keys && raw[next] === ":") {
        const key = JSON.parse(token) as string;
        if (keys.has(key)) throw new Error("duplicate index key");
        keys.add(key);
      }
      offset += token.length - 1;
    } else if (char === "{" || char === "[") {
      containers.push(char === "{" ? new Set<string>() : null);
      if (containers.length > JSON_DEPTH) throw new Error("index nesting too deep");
    } else if (char === "}" || char === "]") {
      containers.pop();
    }
  }
  return JSON.parse(raw) as unknown;
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
  const indexBytes = await readFixture(join(fixture, "index.json"));
  const archive = await readFixture(join(fixture, "artifact.tar"));
  const index = record(
    parseIndex(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(indexBytes)),
  );
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
  const identities = new Map<string, string>();
  for (const name of files.keys()) {
    const parts = name.split("/");
    for (let count = 1; count <= parts.length; count++) {
      const path = parts.slice(0, count).join("/");
      const key = path.toLowerCase();
      const identity = `${count === parts.length ? "file" : "directory"}:${path}`;
      if (identities.has(key) && identities.get(key) !== identity) {
        throw new Error("portable path collision");
      }
      identities.set(key, identity);
    }
  }
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
  const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  const decoded = new Map([...contents].map(([name, payload]) => [name, decoder.decode(payload)]));
  for (const name of [...retained].sort()) {
    const content = decoded.get(name);
    if (content === undefined) throw new Error("incomplete archive");
    output[name] = content;
  }
  const target = join(home, ".spike-target");
  const staging = await mkdtemp(join(home, ".spike-stage-"));
  let ownsTarget = false;
  let isPublished = false;
  const failures: unknown[] = [];
  try {
    for (const [name, content] of Object.entries(output)) {
      const destination = join(staging, name);
      await mkdir(join(destination, ".."), { recursive: true });
      await writeFile(destination, content);
    }
    // Reserve without replacing an existing target; publish only completed writes.
    // Roll back only our reservation on publication failure (also on Windows).
    await mkdir(target);
    ownsTarget = true;
    for (const child of await readdir(staging)) {
      await rename(join(staging, child), join(target, child));
    }
    isPublished = true;
  } catch (error: unknown) {
    failures.push(error);
    if (ownsTarget) {
      try {
        await rm(target, { recursive: true });
      } catch (cleanupError: unknown) {
        failures.push(cleanupError);
      }
    }
  }
  try {
    await rm(staging, { recursive: true });
  } catch (cleanupError: unknown) {
    if (isPublished) {
      // Publication is the commit point; leftover staging is a cleanup warning.
      console.warn("Installation completed; staging cleanup failed:", cleanupError);
    } else {
      failures.push(cleanupError);
    }
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) {
    const details = failures
      .map((error) => (error instanceof Error ? error.message : String(error)))
      .join("; ");
    throw new AggregateError(failures, `Installation failed; cleanup also failed: ${details}`, {
      cause: failures[0],
    });
  }
  return output;
}

async function readFixture(path: string): Promise<Buffer> {
  const handle = await open(path, "r");
  try {
    const buffer = Buffer.alloc(LIMIT + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(buffer, offset, buffer.length - offset, null);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    if (offset > LIMIT) throw new Error("fixture too large");
    return buffer.subarray(0, offset);
  } finally {
    await handle.close();
  }
}

if (
  import.meta.main &&
  !(process.argv.length === 3 && process.argv[2] === "--spike-network-control")
) {
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
