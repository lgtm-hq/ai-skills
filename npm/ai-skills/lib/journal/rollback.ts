import { homedir } from "node:os";
import { dirname, join } from "node:path";

import type { Scope } from "../adapters/types.ts";
import type { LockEnvironment } from "../lockfile.ts";
import { currentHash, JournalTxn, preHash, resultHash } from "./journal.ts";
import type { ApplyHooks, JournalOp, Preimage } from "./journal.ts";
import { readReceipt, scopeStateDir } from "./receipts.ts";
import type { Receipt } from "./receipts.ts";
import { restoreReceipt, withStateSession } from "./recover.ts";
import type { JournalHooks, PlannedOp } from "./recover.ts";

/** Options for `rollbackGeneration`. */
export interface RollbackOptions {
  scope: Scope;
  env?: LockEnvironment;
  /** Print the compensating plan only: no lock, no recovery, no writes. */
  dryRun?: boolean;
  keepGenerations?: number | null;
  exec?: ApplyHooks["exec"];
  journal?: JournalHooks;
  report?: (line: string) => void;
}

/** What a rollback did (or, for a dry run, would do). */
export interface RollbackResult {
  /** Generation undone. */
  from: number;
  /** Generation now current. */
  to: number;
  ops: PlannedOp[];
  /** Paths left as they are because they changed since the generation was applied. */
  kept: string[];
  /** Host effects the rollback cannot undo. */
  remaining: string[];
  /** Deterministic report (the dry-run output). */
  text: string;
}

/**
 * Restore the previous generation of a scope (`sk rollback`).
 *
 * The compensating plan is computed from the current generation's journal:
 * files it wrote are restored from their preimages byte for byte (or removed
 * when they were new), paths it removed are put back, and host registrations
 * it created are unregistered. A path edited since the update, or one the
 * generation does not own, is kept and reported. The plan runs as its own
 * journaled transaction, so an interrupted rollback converges too.
 *
 * @throws {Error} When the scope has no generation to roll back, or its
 *   preimages were pruned (`--keep-generations`).
 */
export async function rollbackGeneration(options: RollbackOptions): Promise<RollbackResult> {
  const env = options.env ?? {};
  if (options.dryRun) {
    const receipt = await readReceipt(options.scope, env);
    return planRollback(options.scope, env, receipt);
  }
  return withStateSession(
    {
      env,
      hooks: options.exec ? { exec: options.exec } : {},
      scope: options.scope,
      ...(options.report ? { report: options.report } : {}),
      ...(options.journal?.lockWaitMs === undefined
        ? {}
        : { lockWaitMs: options.journal.lockWaitMs }),
    },
    async (session) => {
      const result = await planRollback(options.scope, env, session.receipt);
      const generation = await loadGeneration(session.scopeDir, session.receipt!);
      const restore = restoreReceipt(await generation.baseState(), {
        root: session.root,
        scope: session.scope,
      });
      await session.transact({
        hooks: options.journal,
        keepGenerations: options.keepGenerations,
        kind: "rollback",
        next: {
          artifactDigest: restore.artifactDigest,
          fingerprints: restore.fingerprints,
          plugins: restore.plugins,
          restore,
        },
        ops: result.ops,
        rollbackOf: result.from,
      });
      return result;
    },
  );
}

/**
 * Compensating plan for the scope's current generation.
 *
 * @throws {Error} When there is nothing to roll back.
 */
async function planRollback(
  scope: Scope,
  env: LockEnvironment,
  receipt: Receipt | null,
): Promise<RollbackResult> {
  if (!receipt || receipt.generation === 0) {
    throw new Error(`Nothing to roll back: no ${scope} generation has been committed`);
  }
  const { dir } = await scopeStateDir(scope, env);
  const txn = await loadGeneration(dir, receipt);
  const ops: PlannedOp[] = [];
  const kept: string[] = [];
  const remaining: string[] = [];
  const simulated = new Map<string, string | null>();
  const occupied = new Set<string>();
  const label = `generation ${receipt.generation}`;
  const state = async (path: string) =>
    simulated.has(path) ? simulated.get(path)! : currentHash(path);
  const keep = (path: string, why: string) => {
    kept.push(`${path} (${why})`);
    for (let parent = dirname(path); parent !== dirname(parent); parent = dirname(parent)) {
      occupied.add(parent);
    }
  };
  const removeCreated = (missing: string[] | undefined, origin: PlannedOp) => {
    for (const created of [...(missing ?? [])].reverse()) {
      if (occupied.has(created)) {
        return;
      }
      // Confined to exactly the directory the generation recorded creating.
      ops.push({ ...origin, op: { kind: "rmdir", path: created }, roots: [created] });
      simulated.set(created, null);
    }
  };
  for (const index of txn.begunIndices().reverse()) {
    const { item, progress } = txn.opAt(index);
    if (!progress?.done || !progress.begin) {
      continue;
    }
    const op = item.op;
    const begin = progress.begin;
    const base: PlannedOp = {
      op: { kind: "rmdir", path: "" },
      origin: item.origin,
      roots: item.roots,
    };
    const push = (next: JournalOp) => ops.push({ ...base, op: next });
    /** Ops that put a preimage back at `path` (a tree around kept content). */
    const restore = async (pre: Exclude<Preimage, { kind: "absent" }>, path: string) => {
      if (pre.kind === "file") {
        const content = await txn.readObject("pre", pre.hash);
        push({ content, hash: pre.hash, kind: "write-file", mode: pre.mode, path: path });
      } else if (pre.kind === "symlink") {
        push({ kind: "symlink", path: path, target: pre.target });
      } else {
        const manifest = await txn.readManifest(pre.manifest);
        push({ kind: "mkdir", path: path });
        for (const entry of manifest.entries) {
          const entryPath = join(path, entry.relative);
          if (entry.kind === "dir") {
            push({ kind: "mkdir", path: entryPath });
            continue;
          }
          // Under a merge, a path still holding kept content is left alone.
          if ((await state(entryPath)) !== null) {
            continue;
          }
          if (entry.kind === "symlink") {
            push({ kind: "symlink", path: entryPath, target: entry.target! });
          } else {
            const content = await txn.readObject("pre", entry.hash!);
            push({
              content,
              hash: entry.hash!,
              kind: "write-file",
              mode: entry.mode ?? 0o644,
              path: entryPath,
            });
          }
        }
      }
    };
    switch (op.kind) {
      case "write-file":
      case "symlink": {
        const pre = begin.pre ?? { kind: "absent" };
        const current = await state(op.path);
        if (current === resultHash(op)) {
          if (pre.kind === "file") {
            const content = await txn.readObject("pre", pre.hash);
            push({ content, hash: pre.hash, kind: "write-file", mode: pre.mode, path: op.path });
          } else {
            push({ expectHash: current!, kind: "remove-owned", path: op.path });
            // Executor ops replace only files or absent paths today; restore
            // any other preimage kind the same way a removal is restored.
            if (pre.kind !== "absent") {
              await restore(pre, op.path);
            }
          }
          simulated.set(op.path, preHash(pre));
        } else if (current !== preHash(pre) && current !== null) {
          keep(op.path, `edited locally since ${label}`);
        }
        removeCreated(begin.missing, base);
        break;
      }
      case "mkdir": {
        removeCreated(begin.missing, base);
        break;
      }
      case "remove-owned": {
        const pre = begin.pre;
        if (!pre || pre.kind === "absent") {
          break;
        }
        const current = await state(op.path);
        if (current === preHash(pre)) {
          break;
        }
        // A directory still holding locally edited files is restored around them.
        const merge = current !== null && pre.kind === "tree" && occupied.has(op.path);
        if (current !== null && !merge) {
          keep(op.path, `occupied since ${label} removed it`);
          break;
        }
        await restore(pre, op.path);
        if (merge) {
          break;
        }
        simulated.set(op.path, preHash(pre));
        break;
      }
      case "rmdir": {
        if (!progress.done.kept && (await state(op.path)) === null) {
          push({ kind: "mkdir", path: op.path });
        }
        break;
      }
      case "host-exec": {
        if (!progress.done.effective) {
          break;
        }
        if (op.compensate === null) {
          remaining.push(`${op.argv.join(" ")} (${op.step}; irreversible)`);
          break;
        }
        if (op.tolerateAlreadyAbsent) {
          // Undo an unregistration by registering again.
          push({
            argv: op.compensate,
            compensate: op.argv,
            kind: "host-exec",
            step: "rollback",
            tolerateAlreadyPresent: true,
          });
          break;
        }
        const created = receipt.registrations.some((registration) =>
          sameArgv(registration.argv, op.argv),
        );
        if (!created) {
          // Never undo a registration the receipt does not record as created.
          remaining.push(`${op.argv.join(" ")} (not recorded as created by ${label}; left as is)`);
          break;
        }
        push({
          argv: op.compensate,
          compensate: op.argv,
          kind: "host-exec",
          step: "rollback",
          tolerateAlreadyAbsent: true,
        });
        break;
      }
    }
  }
  const to = txn.intent.base.generation;
  return {
    from: receipt.generation,
    kept,
    ops,
    remaining,
    text: formatRollback(scope, receipt.generation, to, ops, kept, remaining, env),
    to,
  };
}

/**
 * Load the journal kept for the receipt's generation.
 *
 * @throws {Error} When it was pruned or belongs to a different history.
 */
async function loadGeneration(scopeDir: string, receipt: Receipt): Promise<JournalTxn> {
  const dir = join(scopeDir, "generations", String(receipt.generation));
  let txn;
  try {
    txn = await JournalTxn.load(dir);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Unreadable transaction journal")) {
      throw new Error(
        `Cannot roll back generation ${receipt.generation}: its preimages are no longer kept ` +
          "(raise --keep-generations to retain more history)",
      );
    }
    throw error;
  }
  if (txn.intent.kind === "rollback" || txn.intent.base.generation !== receipt.generation - 1) {
    throw new Error(
      `Generation ${receipt.generation} journal at ${dir} does not match the receipt`,
    );
  }
  return txn;
}

function formatRollback(
  scope: Scope,
  from: number,
  to: number,
  ops: PlannedOp[],
  kept: string[],
  remaining: string[],
  env: LockEnvironment,
): string {
  const show = (path: string) => displayPath(path, env);
  const lines = [`rollback\t${scope}\tgeneration ${from} -> ${to}`];
  for (const { op } of ops) {
    switch (op.kind) {
      case "write-file":
        lines.push(`op\twrite-file\t${show(op.path)}\tsha256:${op.hash}`);
        break;
      case "remove-owned":
        lines.push(`op\tremove-owned\t${show(op.path)}\texpect:${op.expectHash}`);
        break;
      case "symlink":
        lines.push(`op\tsymlink\t${show(op.path)}\t-> ${show(op.target)}`);
        break;
      case "mkdir":
      case "rmdir":
        lines.push(`op\t${op.kind}\t${show(op.path)}`);
        break;
      case "host-exec":
        lines.push(`op\thost-exec\t${op.argv.map(show).join(" ")}`);
        break;
    }
  }
  for (const item of kept) {
    lines.push(`kept\t${show(item)}`);
  }
  for (const item of remaining) {
    lines.push(`remaining\t${item}`);
  }
  if (ops.length === 0) {
    lines.push("nothing to change on disk");
  }
  return lines.join("\n");
}

function displayPath(path: string, env: LockEnvironment): string {
  const cwd = env.cwd ?? process.cwd();
  const home = env.home ?? homedir();
  for (const [base, label] of [
    [cwd, "."],
    [home, "~"],
  ] as const) {
    if (path === base) {
      return label;
    }
    if (path.startsWith(`${base}/`)) {
      return `${label}${path.slice(base.length)}`;
    }
  }
  return path;
}

function sameArgv(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, at) => item === right[at]);
}
