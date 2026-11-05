import { dirname, join, resolve } from "node:path";

import type { FsEntry, FsStat, ReadOnlyFs } from "../../lib/adapters/types.ts";

/** A file's text, or a symlink target. */
export type MemoryNode = string | { link: string };

const READ_METHODS = new Set(["lstat", "stat", "readdir", "readFile", "readlink", "realpath"]);

function absent(path: string): Error {
  return Object.assign(new Error(`ENOENT: ${path}`), { code: "ENOENT" });
}

/**
 * In-memory read-only filesystem for `plan()` purity tests.
 *
 * Keys are absolute paths; directories are implied by their descendants.
 * Every property other than the six read methods throws, so a plan that
 * tries anything else fails the test.
 */
export function memoryFs(nodes: Record<string, MemoryNode>): ReadOnlyFs {
  const files = new Map(Object.entries(nodes).map(([path, node]) => [resolve(path), node]));
  const isDir = (path: string) => {
    const prefix = `${resolve(path)}/`;
    return [...files.keys()].some((key) => key.startsWith(prefix));
  };
  const stat = (kind: "file" | "dir" | "link"): FsStat => ({
    isDirectory: () => kind === "dir",
    isFile: () => kind === "file",
    isSymbolicLink: () => kind === "link",
  });
  const lstat = async (path: string): Promise<FsStat> => {
    const node = files.get(resolve(path));
    if (node !== undefined) {
      return stat(typeof node === "string" ? "file" : "link");
    }
    if (isDir(path)) {
      return stat("dir");
    }
    throw absent(path);
  };
  const realpath = async (path: string, depth = 0): Promise<string> => {
    if (depth > 32) {
      throw Object.assign(new Error(`ELOOP: ${path}`), { code: "ELOOP" });
    }
    let current = "/";
    for (const part of resolve(path).split("/").filter(Boolean)) {
      current = join(current, part);
      const node = files.get(current);
      if (node !== undefined && typeof node !== "string") {
        current = await realpath(resolve(dirname(current), node.link), depth + 1);
      } else if (node === undefined && !isDir(current)) {
        throw absent(path);
      }
    }
    return current;
  };
  const view: ReadOnlyFs = {
    lstat,
    stat: async (path) => lstat(await realpath(path)),
    readdir: async (path): Promise<FsEntry[]> => {
      const base = resolve(path);
      if (!isDir(base)) {
        throw absent(path);
      }
      const names = new Set<string>();
      for (const key of files.keys()) {
        if (key.startsWith(`${base}/`)) {
          names.add(key.slice(base.length + 1).split("/")[0]!);
        }
      }
      return Promise.all(
        [...names].sort().map(async (name) => ({ name, ...(await lstat(join(base, name))) })),
      );
    },
    readFile: async (path) => {
      const node = files.get(await realpath(path));
      if (typeof node !== "string") {
        throw absent(path);
      }
      return new TextEncoder().encode(node);
    },
    readlink: async (path) => {
      const node = files.get(resolve(path));
      if (node === undefined || typeof node === "string") {
        throw Object.assign(new Error(`EINVAL: ${path}`), { code: "EINVAL" });
      }
      return node.link;
    },
    realpath: (path) => realpath(path),
  };
  return new Proxy(view, {
    get(target, property) {
      if (typeof property === "string" && !READ_METHODS.has(property)) {
        throw new Error(`plan() touched non-read filesystem method ${property}`);
      }
      return Reflect.get(target, property);
    },
  });
}
