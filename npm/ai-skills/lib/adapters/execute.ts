import { resolve } from "node:path";

import { JournalTxn, PlanApplyError, assertInsideRoots } from "../journal/journal.ts";
import type { ApplyHooks, ExecFn, JournalIo } from "../journal/journal.ts";
import type { PlannedOp } from "../journal/recover.ts";
import { existsNoFollow, isAbsent, nodeReadOnlyFs, sha256 } from "./fs.ts";
import type { AdapterPlan, Op, ReadOnlyFs, VerifyResult } from "./types.ts";

export { PlanApplyError };

/** Filesystem writes the executor performs; injectable for failure tests. */
export type ExecuteIo = JournalIo;

/** Options for `applyPlan`. */
export interface ExecuteOptions {
  exec?: ExecFn;
  io?: Partial<ExecuteIo>;
  /** Inject a failure before applying the op at this index. */
  failBeforeOp?: number;
  /** Called after the op at this index is durably done (crash injection). */
  afterOp?: ApplyHooks["afterOp"];
  /** Directory that holds the transaction journal. */
  journalRoot: string;
}

/**
 * An applied plan whose journal is still open.
 *
 * `commit()` discards the journal once the caller has recorded ownership;
 * `rollback()` compensates every applied op from the journal. Effects that
 * cannot be undone are listed in `irreversible`.
 */
export interface Transaction {
  applied: number;
  irreversible: string[];
  commit(): Promise<void>;
  rollback(): Promise<void>;
}

/**
 * Journal ops for composed plans, in application order, each tagged with its
 * plan's owner and declared roots.
 */
export function planOps(plans: AdapterPlan[]): PlannedOp[] {
  return plans.flatMap((plan) =>
    plan.ops.map((op) => ({
      op,
      origin: { adapter: plan.adapter, host: plan.host, owner: plan.pluginId },
      roots: plan.roots,
    })),
  );
}

/**
 * Refuse plans when any path op leaves its plan's declared roots or passes
 * through a symlinked directory inside one, before anything is written.
 *
 * @throws {Error} Naming the first escaping path.
 */
export async function assertPlansInsideRoots(plans: AdapterPlan[]): Promise<void> {
  for (const plan of plans) {
    for (const op of plan.ops) {
      if (op.kind !== "host-exec") {
        await assertInsideRoots(op.path, op.kind, plan.roots);
      }
    }
  }
}

/**
 * Apply one plan through a standalone journaled transaction.
 *
 * Every op is write-ahead journaled under `options.journalRoot` (preimages
 * included); the plan is refused before its first write when a path escapes
 * the declared roots. On failure the journal compensates the applied ops in
 * reverse and the original error is rethrown (with any compensation failure
 * appended; the journal is then kept). Gateway commands use state sessions
 * (`withStateSession`), which commit a receipt instead.
 *
 * @throws {PlanApplyError} When an op fails.
 */
export async function applyPlan(plan: AdapterPlan, options: ExecuteOptions): Promise<Transaction> {
  await assertPlansInsideRoots([plan]);
  const txn = await JournalTxn.open({
    base: { generation: 0, txn: null },
    baseState: { plugins: {}, receipt: null },
    journalRoot: options.journalRoot,
    keepGenerations: 0,
    kind: "install",
    next: { artifactDigest: null, fingerprints: { adapters: {}, policy: null }, plugins: {} },
    ops: planOps([plan]),
    planned: true,
    root: options.journalRoot,
    scope: plan.scope,
    scopeDir: options.journalRoot,
  });
  const hooks: ApplyHooks = {
    ...(options.exec ? { exec: options.exec } : {}),
    ...(options.io ? { io: options.io } : {}),
    ...(options.failBeforeOp === undefined ? {} : { failBeforeOp: options.failBeforeOp }),
    ...(options.afterOp ? { afterOp: options.afterOp } : {}),
  };
  try {
    await txn.applyFrom(0, hooks);
  } catch (error) {
    const result = await txn.compensate(hooks);
    const original = error instanceof Error ? error.message : String(error);
    if (result.failures.length > 0) {
      throw new PlanApplyError(
        `${original} (rollback also failed: ${result.failures.join("; ")}; journal kept at ${txn.dir})`,
        result.remaining,
        result.kept,
      );
    }
    await txn.discard();
    throw new PlanApplyError(original, result.remaining, result.kept);
  }
  const irreversible = txn
    .doneOps()
    .flatMap(({ item, record }) =>
      item.op.kind === "host-exec" && item.op.compensate === null && record.done?.effective
        ? [`${item.op.argv.join(" ")} (${item.op.step})`]
        : [],
    );
  return {
    applied: txn.doneOps().length,
    irreversible,
    commit: () => txn.discard(),
    async rollback() {
      const result = await txn.compensate(hooks);
      if (result.failures.length > 0) {
        throw new Error(`${result.failures.join("; ")} (journal kept at ${txn.dir})`);
      }
      await txn.discard();
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
