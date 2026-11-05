import { randomUUID } from "node:crypto";
import { chmod, mkdir, open, rename, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

/**
 * Flush a file or directory to stable storage.
 *
 * Directories are flushed so a rename or create inside them survives power
 * loss. Windows cannot open a directory for flushing (`fs.fsyncSync` maps to
 * `FlushFileBuffers` on files only), so a directory flush that the platform
 * refuses there is skipped; every other failure propagates.
 */
export async function fsyncPath(path: string): Promise<void> {
  let handle;
  try {
    handle = await open(path, "r");
  } catch (error) {
    if (process.platform === "win32" && isCode(error, "EISDIR", "EPERM", "EACCES")) {
      return;
    }
    throw error;
  }
  try {
    await handle.sync();
  } catch (error) {
    if (!(process.platform === "win32" && isCode(error, "EPERM", "EINVAL"))) {
      throw error;
    }
  } finally {
    await handle.close();
  }
}

/**
 * Create a directory (and parents) and flush every level the call created.
 */
export async function mkdirDurable(
  path: string,
  sync: (path: string) => Promise<void> = fsyncPath,
): Promise<void> {
  await syncCreatedDirs(path, await mkdir(path, { recursive: true }), sync);
}

/**
 * Flush the directory entries `mkdir -p path` added: `created` is the topmost
 * directory it made (or undefined when nothing was new). Each new level's
 * entry lives in its parent, so every parent from `dirname(created)` down to
 * `dirname(path)` is flushed, and `path` itself so its own (empty) listing is.
 */
export async function syncCreatedDirs(
  path: string,
  created: string | undefined,
  sync: (path: string) => Promise<void> = fsyncPath,
): Promise<void> {
  if (!created) {
    return;
  }
  const levels: string[] = [];
  for (let current = resolve(path); ; current = dirname(current)) {
    levels.unshift(current);
    if (current === resolve(created) || current === dirname(current)) {
      break;
    }
  }
  await sync(dirname(levels[0]!));
  for (const level of levels) {
    await sync(level);
  }
}

/**
 * Replace `path` atomically with `content`: write a sibling temp file, flush
 * it, rename it over the target and flush the directory.
 *
 * The temp file is removed when any step fails, so a failed replace leaves
 * neither a partial target nor a stray temp file.
 */
export async function writeDurable(
  path: string,
  content: Uint8Array | string,
  mode?: number,
): Promise<void> {
  const directory = dirname(path);
  await mkdirDurable(directory);
  const temporary = join(directory, `.${randomUUID()}.tmp`);
  try {
    const handle = await open(temporary, "wx", mode ?? 0o644);
    try {
      await handle.writeFile(content);
      await handle.sync();
    } finally {
      await handle.close();
    }
    if (mode !== undefined) {
      await chmod(temporary, mode);
    }
    await rename(temporary, path);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
  await fsyncPath(directory);
}

/**
 * Append one line to a log file, then flush the file and its directory
 * before returning, so the record survives power loss.
 */
export async function appendDurable(path: string, line: string): Promise<void> {
  const handle = await open(path, "a");
  try {
    await handle.appendFile(`${line}\n`);
    await handle.sync();
  } finally {
    await handle.close();
  }
  await fsyncPath(dirname(path));
}

/**
 * Whether an error carries one of the given `code` values.
 */
export function isCode(error: unknown, ...codes: string[]): boolean {
  return Boolean(
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string" &&
    codes.includes(error.code),
  );
}
