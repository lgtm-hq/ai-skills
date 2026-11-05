import { randomUUID } from "node:crypto";
import { mkdir, rename, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";

import { existsNoFollow, isAbsent, nodeReadOnlyFs, ownedPathHash, sha256 } from "./fs.ts";
import { detail, isAlreadyAbsent, isAlreadyPresent, spawnExec } from "./shared/native-cli.ts";
import type { ExecResult } from "./shared/native-cli.ts";
import type { AdapterPlan, Op, ReadOnlyFs, VerifyResult } from "./types.ts";

/** Filesystem writes the executor performs; injectable for failure tests. */
export interface ExecuteIo {
  mkdir: typeof mkdir;
  writeFile: typeof writeFile;
  rename: typeof rename;
  rm: typeof rm;
  symlink: typeof symlink;
  unlink: typeof unlink;
}

/** Options for `applyPlan`. */
export interface ExecuteOptions {
  exec?: (command: string, args: string[]) => Promise<ExecResult>;
  fs?: ReadOnlyFs;
  io?: Partial<ExecuteIo>;
  /** Inject a failure before applying the op at this index (tests, #580). */
  failBeforeOp?: number;
}

/**
 * Applied plan whose undo log is still held in memory.
 *
 * `commit()` discards backups once the caller has recorded ownership (the
 * gateway lock write); `rollback()` undoes every applied op in reverse.
 * Effects that cannot be undone are listed in `irreversible`.
 */
export interface Transaction {
  applied: number;
  irreversible: string[];
  commit(): Promise<void>;
  rollback(): Promise<void>;
}

/**
 * Error from a failed apply, carrying effects recovery could not undo.
 */
export class PlanApplyError extends Error {
  readonly remaining: string[];

  constructor(message: string, remaining: string[]) {
    super(message);
    this.name = "PlanApplyError";
    this.remaining = remaining;
  }
}

/**
 * Apply a plan's ops in order with in-memory undo.
 *
 * Every path is checked against the plan's declared roots before the first
 * write; a path outside them, or one reached through a symlinked directory
 * inside a root, refuses the whole plan. On failure, applied ops are undone in
 * reverse and the original error is rethrown (with any undo failures appended).
 *
 * @throws {Error} When a path escapes the roots, a `remove-owned` hash differs,
 *   or an op fails.
 */
export async function applyPlan(
  plan: AdapterPlan,
  options: ExecuteOptions = {},
): Promise<Transaction> {
  const fs = options.fs ?? nodeReadOnlyFs;
  const io: ExecuteIo = {
    mkdir,
    rename,
    rm,
    symlink,
    unlink,
    writeFile,
    ...options.io,
  };
  const exec = options.exec ?? spawnExec;
  await assertOpsInsideRoots(plan, fs);

  const undo: Array<() => Promise<void>> = [];
  const backups: string[] = [];
  const irreversible: string[] = [];
  let applied = 0;
  const rollback = async (): Promise<string[]> => {
    const failures: string[] = [];
    while (undo.length > 0) {
      const step = undo.pop()!;
      try {
        await step();
      } catch (error) {
        failures.push(error instanceof Error ? error.message : String(error));
      }
    }
    return failures;
  };
  try {
    for (const [index, op] of plan.ops.entries()) {
      if (options.failBeforeOp === index) {
        throw new Error(`injected failure before op ${index} (${op.kind})`);
      }
      await applyOp(op, { backups, exec, fs, io, irreversible, undo });
      applied += 1;
    }
  } catch (error) {
    const failures = await rollback();
    const original = error instanceof Error ? error.message : String(error);
    const message =
      failures.length > 0 ? `${original} (rollback also failed: ${failures.join("; ")})` : original;
    throw new PlanApplyError(message, [...irreversible]);
  }
  return {
    applied,
    irreversible: [...irreversible],
    async commit() {
      undo.length = 0;
      for (const backup of backups.splice(0)) {
        await io.rm(backup, { force: true, recursive: true });
      }
    },
    async rollback() {
      const failures = await rollback();
      for (const backup of backups.splice(0)) {
        await io.rm(backup, { force: true, recursive: true });
      }
      if (failures.length > 0) {
        throw new Error(failures.join("; "));
      }
    },
  };
}

/**
 * Check what `plan` promised against the filesystem after apply.
 *
 * Host registries are not queried; host-exec effects are reported unverified.
 */
export async function verifyPlanOps(
  plan: AdapterPlan,
  fs: ReadOnlyFs = nodeReadOnlyFs,
): Promise<VerifyResult> {
  const problems: string[] = [];
  const unverified: string[] = [];
  const final = new Map<string, Op>();
  for (const op of plan.ops) {
    if (op.kind === "host-exec") {
      unverified.push(`${op.argv.join(" ")} (host registry not queried)`);
    } else {
      final.set(resolve(op.path), op);
    }
  }
  for (const [path, op] of final) {
    try {
      if (op.kind === "write-file") {
        if (sha256(await fs.readFile(path)) !== op.hash) {
          problems.push(`content differs: ${path}`);
        }
      } else if (op.kind === "symlink") {
        if ((await fs.readlink(path)) !== op.target) {
          problems.push(`symlink differs: ${path}`);
        }
      } else if (op.kind === "mkdir") {
        if (!(await fs.stat(path)).isDirectory()) {
          problems.push(`not a directory: ${path}`);
        }
      } else if (await existsNoFollow(fs, path)) {
        problems.push(`still present: ${path}`);
      }
    } catch (error) {
      if (!isAbsent(error)) {
        throw error;
      }
      if (op.kind !== "remove-owned") {
        problems.push(`missing: ${path}`);
      }
    }
  }
  return { ok: problems.length === 0, problems, unverified };
}

async function applyOp(
  op: Op,
  context: {
    backups: string[];
    exec: NonNullable<ExecuteOptions["exec"]>;
    fs: ReadOnlyFs;
    io: ExecuteIo;
    irreversible: string[];
    undo: Array<() => Promise<void>>;
  },
): Promise<void> {
  const { fs, io, undo } = context;
  switch (op.kind) {
    case "mkdir": {
      await makeDirectory(op.path, io, undo);
      return;
    }
    case "write-file": {
      await makeDirectory(dirname(op.path), io, undo);
      const previous = await snapshotFile(op.path, fs);
      const staging = `${op.path}.tmp.${randomUUID()}`;
      try {
        await io.writeFile(staging, op.content);
        await io.rename(staging, op.path);
      } catch (error) {
        // A failed write (ENOSPC, EIO) or rename must not leave the staging file.
        await io.rm(staging, { force: true });
        throw error;
      }
      undo.push(async () => {
        if (previous === null) {
          await io.rm(op.path, { force: true });
        } else {
          await io.writeFile(op.path, previous);
        }
      });
      return;
    }
    case "symlink": {
      if (await existsNoFollow(fs, op.path)) {
        throw new Error(`Refusing to replace existing path with a symlink: ${op.path}`);
      }
      await makeDirectory(dirname(op.path), io, undo);
      await io.symlink(op.target, op.path);
      undo.push(() => io.unlink(op.path));
      return;
    }
    case "remove-owned": {
      let current;
      try {
        current = await ownedPathHash(fs, op.path);
      } catch (error) {
        if (isAbsent(error)) {
          throw new Error(`Refusing to remove ${op.path}: it is no longer present`);
        }
        throw error;
      }
      if (current !== op.expectHash) {
        throw new Error(`Refusing to remove ${op.path}: content changed since the plan`);
      }
      const backup = `${op.path}.bak.${randomUUID()}`;
      await io.rename(op.path, backup);
      context.backups.push(backup);
      undo.push(async () => {
        await io.rm(op.path, { force: true, recursive: true });
        await io.rename(backup, op.path);
        const at = context.backups.indexOf(backup);
        if (at >= 0) {
          context.backups.splice(at, 1);
        }
      });
      return;
    }
    case "host-exec": {
      const [command, ...args] = op.argv;
      const label = commandLabel(op.argv);
      const result = await context.exec(command!, args);
      const present = isAlreadyPresent(result);
      if (result.status !== 0 && !(op.tolerateAlreadyPresent && present)) {
        throw new Error(`${label} failed: ${detail(result)}`);
      }
      if (op.tolerateAlreadyPresent && present) {
        return;
      }
      if (op.compensate === null) {
        context.irreversible.push(`${op.argv.join(" ")} (${op.step})`);
        return;
      }
      const compensate = op.compensate;
      undo.push(async () => {
        const [undoCommand, ...undoArgs] = compensate;
        const undone = await context.exec(undoCommand!, undoArgs);
        if (undone.status !== 0 && !isAlreadyAbsent(undone)) {
          throw new Error(`${commandLabel(compensate)} failed: ${detail(undone)}`);
        }
      });
      return;
    }
  }
}

/**
 * Create a directory and record the topmost directory this call created.
 */
async function makeDirectory(
  path: string,
  io: ExecuteIo,
  undo: Array<() => Promise<void>>,
): Promise<void> {
  const created = await io.mkdir(path, { recursive: true });
  if (created) {
    undo.push(() => io.rm(created, { force: true, recursive: true }));
  }
}

/**
 * Previous bytes of a regular file, or null when absent.
 *
 * @throws {Error} When the path is a directory or symlink (plans must remove those first).
 */
async function snapshotFile(path: string, fs: ReadOnlyFs): Promise<Uint8Array | null> {
  let info;
  try {
    info = await fs.lstat(path);
  } catch (error) {
    if (isAbsent(error)) {
      return null;
    }
    throw error;
  }
  if (!info.isFile()) {
    throw new Error(`Refusing to overwrite a non-file with write-file: ${path}`);
  }
  return fs.readFile(path);
}

/**
 * Human command prefix for errors: leading lowercase words of `argv`.
 */
function commandLabel(argv: string[]): string {
  const words: string[] = [];
  for (const word of argv) {
    if (!/^[a-z][a-z-]*$/.test(word)) {
      break;
    }
    words.push(word);
  }
  return words.join(" ");
}

/**
 * Refuse a plan when any path op leaves its declared roots.
 *
 * @throws {Error} Naming the first escaping path.
 */
async function assertOpsInsideRoots(plan: AdapterPlan, fs: ReadOnlyFs): Promise<void> {
  const roots = plan.roots.map((root) => resolve(root));
  for (const op of plan.ops) {
    if (op.kind === "host-exec") {
      continue;
    }
    const path = resolve(op.path);
    const root = roots.find(
      (candidate) => path === candidate || path.startsWith(withSep(candidate)),
    );
    if (root === undefined || op.path.includes("\0")) {
      throw new Error(`Refusing ${op.kind} outside the plan's declared roots: ${op.path}`);
    }
    // A symlinked directory between the root and the path would redirect the write.
    const parts = relative(root, dirname(path)).split(sep).filter(Boolean);
    let current = root;
    for (const part of parts) {
      current = join(current, part);
      let info;
      try {
        info = await fs.lstat(current);
      } catch (error) {
        if (isAbsent(error)) {
          break;
        }
        throw error;
      }
      if (info.isSymbolicLink()) {
        throw new Error(`Refusing ${op.kind} through a symlinked directory: ${current}`);
      }
    }
  }
}

function withSep(path: string): string {
  return path.endsWith(sep) ? path : `${path}${sep}`;
}
