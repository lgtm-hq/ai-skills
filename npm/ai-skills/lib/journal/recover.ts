import { readdir, rename, rm } from "node:fs/promises";
import { join, sep } from "node:path";

import type { Scope } from "../adapters/types.ts";
import { readLockfile } from "../lockfile.ts";
import type { GatewayLock, LockEnvironment, PluginLockEntry } from "../lockfile.ts";
import { getPackageVersion } from "../package-version.ts";
import { fsyncPath, isCode, mkdirDurable, writeDurable } from "./durable.ts";
import {
  acquireStateLock,
  currentHash,
  JournalTxn,
  PlanApplyError,
  preHash,
  resultHash,
} from "./journal.ts";
import type { ApplyHooks, JournalOp, NextState, OpOrigin, TxnKind } from "./journal.ts";
import { readReceipt, readReceiptFile, receiptView, scopeStateDir, stateRoot } from "./receipts.ts";
import type { HostRegistration, OwnedPath, Receipt } from "./receipts.ts";

/** Generations whose preimages are kept for `rollback` by default. */
export const DEFAULT_KEEP_GENERATIONS = 1;

/** Test and tuning hooks commands accept for their transaction. */
export type JournalHooks = Omit<ApplyHooks, "exec"> & {
  failBeforeCommit?: boolean;
  lockWaitMs?: number;
};

/** Options shared by every state session. */
export interface SessionOptions {
  scope: Scope;
  env?: LockEnvironment;
  /** Host runner and io for recovery and the transaction. */
  hooks?: ApplyHooks;
  lockWaitMs?: number;
  /** Recovery and lock notices (default: stderr). */
  report?: (line: string) => void;
}

/** An op with the plugin/lane it belongs to and the roots it must stay inside. */
export interface PlannedOp {
  op: JournalOp;
  origin: OpOrigin;
  roots: string[];
}

/** Run-time removals and host steps a transaction journals as it goes. */
export interface DynamicOps {
  /**
   * Remove a file or symlink like `unlink` (an absent path throws `ENOENT`),
   * journaling its preimage first.
   */
  removeFile(path: string): Promise<void>;
  /** Remove an empty directory like `rmdir` (a non-empty one throws). */
  removeDir(path: string): Promise<void>;
  /** Run a host step; resolves to whether it changed host state. */
  exec(op: Extract<JournalOp, { kind: "host-exec" }>, origin: OpOrigin): Promise<boolean>;
}

/** What `transact` commits. */
export interface TransactArgs {
  kind: TxnKind;
  ops: PlannedOp[];
  next: NextState;
  /** Owner and roots for dynamic removals. */
  dynamicOrigin?: { origin: OpOrigin; roots: string[] };
  dynamic?: (ops: DynamicOps) => Promise<void>;
  hooks?: ApplyHooks & { failBeforeCommit?: boolean };
  keepGenerations?: number | null;
  rollbackOf?: number;
}

/** A locked view of one scope's installed state. */
export interface StateSession {
  scope: Scope;
  env: LockEnvironment;
  /** Installed plugins: the receipt's, or the legacy lock v2's when none exists. */
  view: GatewayLock;
  receipt: Receipt | null;
  scopeDir: string;
  root: string;
  transact(args: TransactArgs): Promise<Receipt>;
}

/**
 * Run `run` holding the state lock, after recovering interrupted transactions.
 *
 * Every mutating command goes through here: it takes the exclusive lock,
 * resumes or compensates any journal left by a crash, then reads the scope's
 * installed state. The lock is released when `run` settles.
 *
 * @throws {Error} When the lock stays busy, or recovery cannot converge (the
 *   message names the journal kept for inspection).
 */
export async function withStateSession<T>(
  options: SessionOptions,
  run: (session: StateSession) => Promise<T>,
): Promise<T> {
  const env = options.env ?? {};
  const report = options.report ?? ((line: string) => console.warn(line));
  const release = await acquireStateLock(join(stateRoot(env), "lock"), {
    onStale: (holder) =>
      report(
        holder
          ? `recovered a stale state lock left by pid ${holder.pid} (started ${holder.startedAt})`
          : "recovered a torn state lock",
      ),
    ...(options.lockWaitMs === undefined ? {} : { waitMs: options.lockWaitMs }),
  });
  try {
    await recoverPending(env, options.hooks ?? {}, report);
    const { dir, root } = await scopeStateDir(options.scope, env);
    const receipt = await readReceipt(options.scope, env);
    const view = receipt ? receiptView(receipt) : await readLockfile(options.scope, env);
    const session: StateSession = {
      env,
      receipt,
      root,
      scope: options.scope,
      scopeDir: dir,
      transact: (args) =>
        transact(session, { ...args, hooks: { ...options.hooks, ...args.hooks } }, report),
      view,
    };
    return await run(session);
  } finally {
    await release();
  }
}

/**
 * Take the lock and run recovery only (`sk doctor --repair`).
 *
 * @returns Report lines for every transaction recovered.
 */
export async function recoverState(
  env: LockEnvironment = {},
  hooks: ApplyHooks = {},
  options: { lockWaitMs?: number } = {},
): Promise<string[]> {
  const lines: string[] = [];
  const release = await acquireStateLock(join(stateRoot(env), "lock"), {
    onStale: () => lines.push("recovery\tlock\tstale lock recovered"),
    ...(options.lockWaitMs === undefined ? {} : { waitMs: options.lockWaitMs }),
  });
  try {
    await recoverPending(env, hooks, (line) => lines.push(line));
  } finally {
    await release();
  }
  return lines;
}

/**
 * Resume or compensate every transaction left in the journal.
 *
 * A committed transaction (its id is the scope receipt's) is archived. An
 * incomplete one rolls forward when its plan is fully recorded and every
 * remaining precondition still holds; otherwise it is compensated from its
 * preimages. When compensation cannot finish, recovery stops and names the
 * journal; it never guesses. Must run under the state lock.
 *
 * @throws {Error} On an unreadable or unknown-version journal, or incomplete compensation.
 */
export async function recoverPending(
  env: LockEnvironment,
  hooks: ApplyHooks,
  report: (line: string) => void,
): Promise<void> {
  const journalRoot = join(stateRoot(env), "journal");
  let names: string[];
  try {
    names = (await readdir(journalRoot)).sort();
  } catch (error) {
    if (isCode(error, "ENOENT")) {
      return;
    }
    throw error;
  }
  for (const name of names) {
    const dir = join(journalRoot, name);
    if (name.endsWith(".tmp")) {
      // Never published: no op ran, so there is nothing to undo.
      await rm(dir, { force: true, recursive: true });
      report(`recovery\t${name}\tdiscarded\tunpublished transaction`);
      continue;
    }
    const txn = await JournalTxn.load(dir);
    const receipt = await readReceiptFile(
      join(txn.intent.scopeDir, "receipt.json"),
      txn.intent.scope,
    );
    if (receipt?.txn === txn.id) {
      await archive(txn, receipt);
      report(`recovery\t${txn.id}\tcommitted\tarchived the committed transaction`);
      continue;
    }
    if (!txn.isCompensating && sameBase(receipt, txn.intent.base)) {
      const blocker = await txn.rollForwardBlocker();
      if (blocker === null) {
        try {
          await txn.applyFrom(txn.nextPending(), hooks);
          const committed = await commit(txn, report);
          report(
            `recovery\t${txn.id}\trolled-forward\t${txn.intent.kind} generation ${committed.generation}`,
          );
          continue;
        } catch (error) {
          report(`recovery\t${txn.id}\troll-forward-failed\t${message(error)}`);
        }
      } else {
        report(`recovery\t${txn.id}\tcannot-roll-forward\t${blocker}`);
      }
    }
    const result = await txn.compensate(hooks);
    for (const kept of result.kept) {
      report(`recovery\t${txn.id}\tkept\t${kept}`);
    }
    for (const remaining of result.remaining) {
      report(`recovery\t${txn.id}\tremaining\t${remaining}`);
    }
    if (result.failures.length > 0) {
      throw new Error(
        `Recovery stopped: transaction ${txn.id} could not be compensated ` +
          `(${result.failures.join("; ")}). Its journal is kept at ${txn.dir}; fix the cause ` +
          "and re-run, or inspect it before removing it by hand.",
      );
    }
    await txn.discard();
    report(`recovery\t${txn.id}\tcompensated\t${txn.intent.kind} undone; previous generation kept`);
  }
}

/**
 * Open, apply and commit one transaction in a session.
 */
async function transact(
  session: StateSession,
  args: TransactArgs,
  report: (line: string) => void,
): Promise<Receipt> {
  const hooks = args.hooks ?? {};
  const txn = await JournalTxn.open({
    base: { generation: session.receipt?.generation ?? 0, txn: session.receipt?.txn ?? null },
    baseState: { plugins: session.view.plugins, receipt: session.receipt },
    journalRoot: join(stateRoot(session.env), "journal"),
    keepGenerations: args.keepGenerations ?? DEFAULT_KEEP_GENERATIONS,
    kind: args.kind,
    next: args.next,
    ops: args.ops,
    planned: args.dynamic === undefined,
    root: session.root,
    scope: session.scope,
    scopeDir: session.scopeDir,
    ...(args.rollbackOf === undefined ? {} : { rollbackOf: args.rollbackOf }),
  });
  try {
    await txn.applyFrom(0, hooks);
    if (args.dynamic) {
      await args.dynamic(dynamicOps(txn, args.dynamicOrigin, hooks));
    }
    if (hooks.failBeforeCommit) {
      throw new Error("injected failure before commit");
    }
  } catch (error) {
    const result = await txn.compensate(hooks);
    const original = message(error);
    if (result.failures.length > 0) {
      throw new PlanApplyError(
        `${original} (rollback also failed: ${result.failures.join("; ")}; the journal is ` +
          `kept at ${txn.dir} and the next command retries recovery)`,
        result.remaining,
        result.kept,
      );
    }
    await txn.discard();
    for (const kept of result.kept) {
      report(`kept ${kept}`);
    }
    throw new PlanApplyError(
      result.remaining.length > 0
        ? `${original} (still in effect after rollback: ${result.remaining.join("; ")})`
        : original,
      result.remaining,
      result.kept,
    );
  }
  return commit(txn, report);
}

/**
 * Commit: replace the receipt atomically, then archive the journal.
 *
 * Archiving happens after the commit point; if it fails, the journal stays
 * and the next recovery archives it.
 */
async function commit(txn: JournalTxn, report: (line: string) => void): Promise<Receipt> {
  const base = await txn.baseState();
  const receipt = buildReceipt(txn, base.receipt);
  await writeDurable(
    join(txn.intent.scopeDir, "receipt.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
  );
  try {
    await archive(txn, receipt);
  } catch (error) {
    report(
      `warning: committed generation ${receipt.generation} but could not archive its journal ` +
        `${txn.dir} (${message(error)}); the next command finishes it`,
    );
  }
  return receipt;
}

/**
 * Move a committed journal to the scope's generations (or drop a rollback's),
 * then prune generations beyond the retention count.
 */
async function archive(txn: JournalTxn, receipt: Receipt): Promise<void> {
  const generations = join(txn.intent.scopeDir, "generations");
  if (txn.intent.kind === "rollback") {
    if (txn.intent.rollbackOf !== undefined) {
      await rm(join(generations, String(txn.intent.rollbackOf)), { force: true, recursive: true });
    }
    await txn.discard();
  } else {
    await mkdirDurable(generations);
    const target = join(generations, String(receipt.generation));
    await rm(target, { force: true, recursive: true });
    await rename(txn.dir, target);
    await fsyncPath(generations);
    await fsyncPath(join(txn.dir, ".."));
  }
  await pruneGenerations(generations, receipt.generation, txn.intent.keepGenerations);
}

/**
 * Keep the newest `keep` generations up to `current`; drop older and orphaned ones.
 */
export async function pruneGenerations(dir: string, current: number, keep: number): Promise<void> {
  let names: string[];
  try {
    names = await readdir(dir);
  } catch (error) {
    if (isCode(error, "ENOENT")) {
      return;
    }
    throw error;
  }
  for (const name of names) {
    const generation = Number(name);
    if (!/^\d+$/.test(name) || generation > current || generation <= current - keep) {
      await rm(join(dir, name), { force: true, recursive: true });
    }
  }
}

/**
 * The receipt a transaction commits: the base receipt plus every done op.
 */
export function buildReceipt(txn: JournalTxn, base: Receipt | null): Receipt {
  const intent = txn.intent;
  const committedAt = new Date().toISOString();
  if (intent.kind === "rollback" && intent.next.restore) {
    return { ...intent.next.restore, committedAt, txn: intent.txn };
  }
  const paths: Record<string, OwnedPath> = { ...base?.paths };
  let registrations: HostRegistration[] = [...(base?.registrations ?? [])];
  for (const { index, item } of txn.doneOps()) {
    const op = item.op;
    const progress = txn.opAt(index).progress!;
    switch (op.kind) {
      case "write-file":
      case "symlink": {
        const pre = progress.begin?.pre;
        paths[op.path] = {
          hash: resultHash(op)!,
          owner: item.origin.owner,
          previousHash: pre ? preHash(pre) : null,
        };
        break;
      }
      case "remove-owned": {
        for (const key of Object.keys(paths)) {
          if (key === op.path || key.startsWith(`${op.path}${sep}`)) {
            delete paths[key];
          }
        }
        break;
      }
      case "host-exec": {
        if (op.tolerateAlreadyAbsent) {
          registrations = registrations.filter(
            (registration) => !sameArgv(registration.compensate, op.argv),
          );
        } else if (progress.done?.effective && !progress.done.uncertain) {
          registrations = registrations.filter(
            (registration) => !sameArgv(registration.argv, op.argv),
          );
          registrations.push({
            argv: op.argv,
            compensate: op.compensate,
            owner: item.origin.owner,
            txn: intent.txn,
          });
        }
        break;
      }
      default:
        break;
    }
  }
  const owners = new Set(Object.keys(intent.next.plugins));
  return {
    aliases: base?.aliases ?? {},
    artifactDigest: intent.next.artifactDigest,
    committedAt,
    configKeys: Object.fromEntries(
      Object.entries(base?.configKeys ?? {}).filter(([, value]) => owners.has(value.owner)),
    ),
    fingerprints: {
      adapters: { ...base?.fingerprints.adapters, ...intent.next.fingerprints.adapters },
      policy: intent.next.fingerprints.policy,
    },
    gatewayVersion: getPackageVersion(),
    generation: intent.base.generation + 1,
    paths: Object.fromEntries(Object.entries(paths).filter(([, value]) => owners.has(value.owner))),
    plugins: intent.next.plugins,
    registrations: registrations.filter((registration) => owners.has(registration.owner)),
    root: intent.root,
    scope: intent.scope,
    txn: intent.txn,
    version: 1,
  };
}

/**
 * The receipt to restore when undoing a generation: its base receipt, or a
 * generation-0 receipt holding the plugins read before the first commit.
 */
export function restoreReceipt(
  base: { receipt: Receipt | null; plugins: Record<string, PluginLockEntry> },
  intent: { scope: Scope; root: string },
): Receipt {
  if (base.receipt) {
    return base.receipt;
  }
  return {
    aliases: {},
    artifactDigest: null,
    committedAt: new Date(0).toISOString(),
    configKeys: {},
    fingerprints: { adapters: {}, policy: null },
    gatewayVersion: getPackageVersion(),
    generation: 0,
    paths: {},
    plugins: base.plugins,
    registrations: [],
    root: intent.root,
    scope: intent.scope,
    txn: "",
    version: 1,
  };
}

function dynamicOps(
  txn: JournalTxn,
  owner: TransactArgs["dynamicOrigin"],
  hooks: ApplyHooks,
): DynamicOps {
  const origin = owner?.origin ?? { adapter: "gateway", host: "", owner: "" };
  const roots = owner?.roots ?? [];
  return {
    async removeFile(path) {
      const hash = await currentHash(path);
      if (hash === null) {
        throw Object.assign(new Error(`ENOENT: no such file or directory, unlink '${path}'`), {
          code: "ENOENT",
        });
      }
      if (hash.startsWith("tree:")) {
        throw Object.assign(
          new Error(`EISDIR: illegal operation on a directory, unlink '${path}'`),
          {
            code: "EISDIR",
          },
        );
      }
      await txn.applyDynamic(
        { expectHash: hash, kind: "remove-owned", path },
        origin,
        roots,
        hooks,
      );
    },
    async removeDir(path) {
      const done = await txn.applyDynamic({ kind: "rmdir", path }, origin, roots, hooks);
      if (done.kept) {
        throw Object.assign(new Error(`ENOTEMPTY: directory not removed, rmdir '${path}'`), {
          code: "ENOTEMPTY",
        });
      }
    },
    async exec(op, opOrigin) {
      const done = await txn.applyDynamic(op, opOrigin, [], hooks);
      return Boolean(done.effective);
    },
  };
}

function sameBase(
  receipt: Receipt | null,
  base: { generation: number; txn: string | null },
): boolean {
  return (receipt?.generation ?? 0) === base.generation && (receipt?.txn ?? null) === base.txn;
}

function sameArgv(left: string[] | null, right: string[]): boolean {
  return (
    left !== null && left.length === right.length && left.every((item, at) => item === right[at])
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
