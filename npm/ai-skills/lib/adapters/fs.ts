import { createHash } from "node:crypto";
import { lstat, readFile, readdir, readlink, realpath, stat } from "node:fs/promises";
import { join } from "node:path";

import type { FsEntry, Op, ReadOnlyFs } from "./types.ts";

/**
 * Read-only view of the real filesystem; the default for `plan()`.
 */
export const nodeReadOnlyFs: ReadOnlyFs = Object.freeze({
  lstat: (path: string) => lstat(path),
  stat: (path: string) => stat(path),
  readdir: (path: string): Promise<FsEntry[]> => readdir(path, { withFileTypes: true }),
  readFile: async (path: string): Promise<Uint8Array> => new Uint8Array(await readFile(path)),
  readlink: (path: string) => readlink(path),
  realpath: (path: string) => realpath(path),
});

/**
 * sha256 of bytes or text, hex.
 */
export function sha256(content: Uint8Array | string): string {
  return createHash("sha256").update(content).digest("hex");
}

/**
 * Whether an fs error means the path is absent.
 */
export function isAbsent(error: unknown): boolean {
  return Boolean(
    error &&
    typeof error === "object" &&
    "code" in error &&
    (error.code === "ENOENT" || error.code === "ENOTDIR"),
  );
}

/**
 * Whether `path` exists without following a final symlink.
 */
export async function existsNoFollow(fs: ReadOnlyFs, path: string): Promise<boolean> {
  try {
    await fs.lstat(path);
    return true;
  } catch (error) {
    if (isAbsent(error)) {
      return false;
    }
    throw error;
  }
}

/** One entry of a walked tree, POSIX-relative to its root. */
export interface TreeEntry {
  relative: string;
  kind: "dir" | "file" | "symlink";
  target?: string;
  /** Permission bits of a file (`mode & 0o777`), when the view reports them. */
  mode?: number;
}

/**
 * Walk a tree without following symlinks, sorted for deterministic plans.
 */
export async function walkTree(fs: ReadOnlyFs, root: string, prefix = ""): Promise<TreeEntry[]> {
  let entries: FsEntry[];
  try {
    entries = await fs.readdir(prefix ? join(root, prefix) : root);
  } catch (error) {
    if (isAbsent(error)) {
      return [];
    }
    throw error;
  }
  const sorted = [...entries].sort((left, right) => compareText(left.name, right.name));
  const walked: TreeEntry[] = [];
  for (const entry of sorted) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isSymbolicLink()) {
      walked.push({
        kind: "symlink",
        relative,
        target: await fs.readlink(join(root, relative)),
      });
    } else if (entry.isDirectory()) {
      walked.push({ kind: "dir", relative });
      walked.push(...(await walkTree(fs, root, relative)));
    } else if (entry.isFile()) {
      const { mode } = await fs.lstat(join(root, relative));
      walked.push(
        mode === undefined
          ? { kind: "file", relative }
          : { kind: "file", mode: mode & 0o777, relative },
      );
    }
  }
  return walked;
}

/**
 * Hash a path the way the executor checks `remove-owned`: file bytes,
 * `symlink:<target>` for links (as the gateway lock does), or a canonical
 * digest of a directory's walked entries.
 */
export async function ownedPathHash(fs: ReadOnlyFs, path: string): Promise<string> {
  const info = await fs.lstat(path);
  if (info.isSymbolicLink()) {
    return sha256(`symlink:${await fs.readlink(path)}`);
  }
  if (info.isFile()) {
    return sha256(await fs.readFile(path));
  }
  const lines: string[] = [];
  for (const entry of await walkTree(fs, path)) {
    const absolute = join(path, entry.relative);
    if (entry.kind === "file") {
      lines.push(`file\t${entry.relative}\t${sha256(await fs.readFile(absolute))}`);
    } else if (entry.kind === "symlink") {
      lines.push(`symlink\t${entry.relative}\t${entry.target}`);
    } else {
      lines.push(`dir\t${entry.relative}`);
    }
  }
  return `tree:${sha256(lines.join("\n"))}`;
}

/**
 * Ops that reproduce `source` at `dest`, keeping symlink targets verbatim.
 */
export async function copyTreeOps(fs: ReadOnlyFs, source: string, dest: string): Promise<Op[]> {
  const ops: Op[] = [{ kind: "mkdir", path: dest }];
  for (const entry of await walkTree(fs, source)) {
    const path = join(dest, entry.relative);
    if (entry.kind === "dir") {
      ops.push({ kind: "mkdir", path });
    } else if (entry.kind === "symlink") {
      ops.push({ kind: "symlink", path, target: entry.target! });
    } else {
      const content = await fs.readFile(join(source, entry.relative));
      // Keep the source mode so executable skill scripts stay executable,
      // as the engine's recursive copy does.
      ops.push({
        kind: "write-file",
        path,
        content,
        hash: sha256(content),
        ...(entry.mode === undefined ? {} : { mode: entry.mode }),
      });
    }
  }
  return ops;
}

/**
 * Bytes of a JSON document as the gateway writes it (2-space, trailing newline).
 */
export function jsonBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(`${JSON.stringify(value, null, 2)}\n`);
}

/**
 * Locale-independent string order.
 */
export function compareText(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  return left > right ? 1 : 0;
}
