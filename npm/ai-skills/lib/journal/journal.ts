import { randomUUID } from "node:crypto";
import {
  chmod,
  link,
  lstat,
  mkdir,
  open,
  readFile,
  readlink,
  rename,
  rm,
  rmdir,
  stat,
  symlink,
  unlink,
  writeFile,
} from "node:fs/promises";
import { hostname } from "node:os";
import { dirname, join, relative, resolve, sep } from "node:path";

import { nodeReadOnlyFs, ownedPathHash, sha256, walkTree } from "../adapters/fs.ts";
import {
  detail,
  isAlreadyAbsent,
  isAlreadyPresent,
  spawnExec,
} from "../adapters/shared/native-cli.ts";
import type { ExecResult } from "../adapters/shared/native-cli.ts";
import type { Op, Scope, WriteFileOp } from "../adapters/types.ts";
import type { PluginLockEntry } from "../lockfile.ts";
import { appendDurable, fsyncPath, isCode, mkdirDurable, writeDurable } from "./durable.ts";
import { isRecord, parseReceipt } from "./receipts.ts";
import type { Receipt } from "./receipts.ts";

/** Journal schema version this gateway reads and writes. */
export const JOURNAL_VERSION = 1;

/** Mutating commands that open a transaction. */
export type TxnKind = "adopt" | "install" | "remove" | "rollback" | "update";

/** Remove an empty directory; a non-empty or missing one is kept, not an error. */
export interface RmdirOp {
  kind: "rmdir";
  path: string;
}

/** Every operation a journal applies: the adapter ops plus `rmdir`. */
export type JournalOp = Op | RmdirOp;

/** Who an op belongs to: the plugin it installs and the lane that planned it. */
export interface OpOrigin {
  owner: string;
  adapter: string;
  host: string;
}

/** An op as the intent stores it: write-file bytes live in `post/<sha256>`. */
export type StoredOp = Exclude<JournalOp, WriteFileOp> | Omit<WriteFileOp, "content">;

/** One op of a transaction. */
export interface TxnOp {
  origin: OpOrigin;
  op: StoredOp;
  /** Declared roots the op must stay inside (no symlinked directory on the way). */
  roots: string[];
  /**
   * Content hash the path had when the transaction opened (`null`: absent).
   * Set only for the first op touching a path; roll-forward requires it to still hold.
   */
  expect?: string | null;
}

/** What a committed transaction makes current. */
export interface NextState {
  plugins: Record<string, PluginLockEntry>;
  artifactDigest: string | null;
  fingerprints: Receipt["fingerprints"];
  /** Rollback only: the receipt to restore (generation 0 when none existed). */
  restore?: Receipt;
}

/** `intent.json`: the composed plan and the preconditions it was planned under. */
export interface Intent {
  version: typeof JOURNAL_VERSION;
  txn: string;
  kind: TxnKind;
  scope: Scope;
  /** Directory holding the scope's receipt and generations. */
  scopeDir: string;
  /** Real path of the scope root (project root or home). */
  root: string;
  createdAt: string;
  pid: number;
  hostname: string;
  /** Receipt the transaction was planned against (generation 0: none). */
  base: { generation: number; txn: string | null };
  /** True when `ops` is the whole sequence; dynamic ops make recovery compensate only. */
  planned: boolean;
  ops: TxnOp[];
  next: NextState;
  keepGenerations: number;
  /** Rollback only: the generation being undone. */
  rollbackOf?: number;
}

/** State of a path before an op touched it. */
export type Preimage =
  | { kind: "absent" }
  | { kind: "file"; hash: string; mode: number }
  | { kind: "symlink"; target: string }
  | { kind: "tree"; hash: string; manifest: string };

/** One `log.jsonl` record. */
export type LogRecord =
  | { phase: "begin"; op: number; pre?: Preimage; missing?: string[]; dynamic?: TxnOp }
  | { phase: "done"; op: number; effective?: boolean; uncertain?: boolean; kept?: boolean }
  | { phase: "failed"; op: number; error: string }
  | { phase: "compensate" }
  | { phase: "compensated" };

/** Filesystem writes an op performs; injectable for failure tests. */
export interface JournalIo {
  chmod: typeof chmod;
  mkdir: typeof mkdir;
  rename: typeof rename;
  rm: typeof rm;
  rmdir: typeof rmdir;
  symlink: typeof symlink;
  unlink: typeof unlink;
  writeFile: typeof writeFile;
}

/** Host CLI runner. */
export type ExecFn = (command: string, args: string[]) => Promise<ExecResult>;

/** Hooks a transaction applies with: host runner, io and the op-index injectors. */
export interface ApplyHooks {
  exec?: ExecFn;
  io?: Partial<JournalIo>;
  /** Throw before applying the op at this index (tests). */
  failBeforeOp?: number;
  /** Called after the op at this index is durably done (crash-injection tests). */
  afterOp?: (index: number) => void | Promise<void>;
  /**
   * Called inside an op, after its begin record is durable and before its
   * effect completes (crash-injection tests): after the staging file is
   * written, after a removed path is moved aside, after a host command ran.
   */
  duringOp?: (index: number) => void | Promise<void>;
}

/** Outcome of compensating a transaction. */
export interface CompensationReport {
  /** Paths left alone because they changed since the transaction touched them. */
  kept: string[];
  /** Host effects that remain (irreversible or of unknown outcome). */
  remaining: string[];
  /** Compensation steps that failed; non-empty means recovery is incomplete. */
  failures: string[];
}

/** Tree preimage manifest stored as a content-addressed object. */
interface TreeManifest {
  mode: number;
  entries: Array<{
    relative: string;
    kind: "dir" | "file" | "symlink";
    mode?: number;
    hash?: string;
    target?: string;
  }>;
}

/** Thrown when an op fails; carries host effects compensation could not undo. */
export class PlanApplyError extends Error {
  readonly remaining: string[];
  readonly kept: string[];

  constructor(message: string, remaining: string[], kept: string[] = []) {
    super(message);
    this.name = "PlanApplyError";
    this.remaining = remaining;
    this.kept = kept;
  }
}

/** Per-op progress read back from the log. */
interface OpProgress {
  begin?: Extract<LogRecord, { phase: "begin" }>;
  done?: Extract<LogRecord, { phase: "done" }>;
  failed?: boolean;
}

/**
 * One durable transaction: `intent.json`, an append-only `log.jsonl` and
 * content-addressed `pre/` (preimages) and `post/` (bytes to write) objects.
 *
 * Every op is write-ahead: its `begin` record and preimage are flushed before
 * it runs and `done` is flushed after. Undo is computed from the log and the
 * current filesystem, never from memory, so the same code compensates a
 * failure in process, after a crash, and for `sk rollback`.
 */
export class JournalTxn {
  readonly dir: string;
  readonly intent: Intent;
  private progress: Map<number, OpProgress> = new Map();
  private ops: TxnOp[];
  private compensating = false;
  private dynamicSeen = false;
  private failedSeen = false;

  private constructor(dir: string, intent: Intent, records: LogRecord[]) {
    this.dir = dir;
    this.intent = intent;
    this.ops = [...intent.ops];
    for (const record of records) {
      this.track(record);
    }
  }

  /**
   * Create a transaction directory and publish its intent atomically.
   *
   * The directory is assembled under a temporary name and renamed into
   * `journalRoot`, so recovery never sees a transaction without its intent;
   * a failure removes the temporary directory.
   */
  static async open(args: {
    journalRoot: string;
    kind: TxnKind;
    scope: Scope;
    scopeDir: string;
    root: string;
    base: Intent["base"];
    baseState: { receipt: Receipt | null; plugins: Record<string, PluginLockEntry> };
    ops: Array<{ op: JournalOp; origin: OpOrigin; roots: string[] }>;
    planned: boolean;
    next: NextState;
    keepGenerations: number;
    rollbackOf?: number;
  }): Promise<JournalTxn> {
    const txn = newTxnId();
    const staging = join(args.journalRoot, `${txn}.tmp`);
    const dir = join(args.journalRoot, txn);
    await mkdirDurable(args.journalRoot);
    try {
      await mkdir(join(staging, "pre"), { recursive: true });
      await mkdir(join(staging, "post"), { recursive: true });
      const stored: TxnOp[] = [];
      const expectations = await openingExpectations(args.ops.map((item) => item.op));
      for (const [index, item] of args.ops.entries()) {
        if (item.op.kind === "write-file") {
          await putObject(join(staging, "post"), item.op.content, item.op.hash);
        }
        stored.push({
          op: storeOp(item.op),
          origin: item.origin,
          roots: item.roots,
          ...(expectations[index] === undefined ? {} : { expect: expectations[index] }),
        });
      }
      const intent: Intent = {
        base: args.base,
        createdAt: new Date().toISOString(),
        hostname: hostname(),
        keepGenerations: args.keepGenerations,
        kind: args.kind,
        next: args.next,
        ops: stored,
        pid: process.pid,
        planned: args.planned,
        root: args.root,
        scope: args.scope,
        scopeDir: args.scopeDir,
        txn,
        version: JOURNAL_VERSION,
        ...(args.rollbackOf === undefined ? {} : { rollbackOf: args.rollbackOf }),
      };
      await writeDurable(join(staging, "base.json"), `${JSON.stringify(args.baseState)}\n`);
      await writeDurable(join(staging, "intent.json"), `${JSON.stringify(intent, null, 2)}\n`);
      await writeDurable(join(staging, "log.jsonl"), "");
      await fsyncPath(join(staging, "pre"));
      await fsyncPath(join(staging, "post"));
      await rename(staging, dir);
      await fsyncPath(args.journalRoot);
      return new JournalTxn(dir, intent, []);
    } catch (error) {
      await rm(staging, { force: true, recursive: true });
      throw error;
    }
  }

  /**
   * Load a transaction directory for recovery or rollback.
   *
   * @throws {Error} When the intent or a log record has an unknown version or
   *   shape (fail closed: an unreadable journal is never guessed at).
   */
  static async load(dir: string): Promise<JournalTxn> {
    let intent: unknown;
    try {
      intent = JSON.parse(await readFile(join(dir, "intent.json"), "utf8"));
    } catch (error) {
      throw new Error(`Unreadable transaction journal ${dir}: ${message(error)}`);
    }
    if (!isRecord(intent) || intent.version !== JOURNAL_VERSION) {
      throw new Error(
        `Unsupported transaction journal version ${JSON.stringify(
          isRecord(intent) ? intent.version : undefined,
        )} at ${dir}; this gateway reads version ${JOURNAL_VERSION}. Upgrade ` +
          "@lgtm-hq/ai-skills; the journal was left untouched.",
      );
    }
    if (!isIntent(intent)) {
      throw new Error(`Invalid transaction journal intent at ${dir}`);
    }
    const records: LogRecord[] = [];
    const text = await readFile(join(dir, "log.jsonl"), "utf8");
    const lines = text.split("\n");
    for (const [index, line] of lines.entries()) {
      if (line === "") {
        continue;
      }
      let record: unknown;
      try {
        record = JSON.parse(line);
      } catch {
        // Only the final line can be torn by a crash mid-append; it never
        // completed, so the op it describes is treated as not begun/done.
        if (index === lines.length - 1 || lines.slice(index + 1).every((rest) => rest === "")) {
          continue;
        }
        throw new Error(`Corrupt transaction log at ${dir} (line ${index + 1})`);
      }
      if (!isLogRecord(record)) {
        throw new Error(`Invalid transaction log record at ${dir} (line ${index + 1})`);
      }
      records.push(record);
    }
    return new JournalTxn(dir, intent, records);
  }

  get id(): string {
    return this.intent.txn;
  }

  /** Whether compensation has started (the decision is sticky across crashes). */
  get isCompensating(): boolean {
    return this.compensating;
  }

  /** Number of ops the transaction knows about (planned plus dynamic). */
  get opCount(): number {
    return this.ops.length;
  }

  /** Whether any op ran outside the planned sequence or failed. */
  get hasUnplannedProgress(): boolean {
    return this.dynamicSeen || this.failedSeen;
  }

  /** Ops whose `done` record is durable. */
  doneOps(): Array<{ index: number; item: TxnOp; record: OpProgress }> {
    const done = [];
    for (const [index, item] of this.ops.entries()) {
      const record = this.progress.get(index);
      if (item && record?.done) {
        done.push({ index, item, record });
      }
    }
    return done;
  }

  /** The base state stored when the transaction opened. */
  async baseState(): Promise<{
    receipt: Receipt | null;
    plugins: Record<string, PluginLockEntry>;
  }> {
    const parsed: unknown = JSON.parse(await readFile(join(this.dir, "base.json"), "utf8"));
    if (!isRecord(parsed) || !isRecord(parsed.plugins)) {
      throw new Error(`Invalid transaction base state at ${this.dir}`);
    }
    const receipt =
      parsed.receipt === null || parsed.receipt === undefined
        ? null
        : parseReceipt(JSON.stringify(parsed.receipt), join(this.dir, "base.json"));
    return { plugins: parsed.plugins as Record<string, PluginLockEntry>, receipt };
  }

  /** Index of the first op that is not durably done. */
  nextPending(): number {
    let index = 0;
    while (index < this.ops.length && this.progress.get(index)?.done) {
      index += 1;
    }
    return index;
  }

  /**
   * Apply every planned op from `start`, in order.
   *
   * @throws {Error} On the first failing op; the caller compensates.
   */
  async applyFrom(start: number, hooks: ApplyHooks = {}): Promise<void> {
    for (let index = start; index < this.intent.ops.length; index += 1) {
      if (this.progress.get(index)?.done) {
        continue;
      }
      if (hooks.failBeforeOp === index) {
        throw new Error(`injected failure before op ${index} (${this.ops[index]!.op.kind})`);
      }
      await this.applyAt(index, hooks, Boolean(this.progress.get(index)?.begin));
      await hooks.afterOp?.(index);
    }
  }

  /**
   * Append and apply one op decided at run time (removals, uninstalls).
   *
   * A transaction with dynamic ops can only compensate after a crash.
   *
   * @returns The op's `done` record.
   */
  async applyDynamic(
    op: JournalOp,
    origin: OpOrigin,
    roots: string[],
    hooks: ApplyHooks = {},
  ): Promise<Extract<LogRecord, { phase: "done" }>> {
    const index = this.ops.length;
    const item: TxnOp = { op: storeOp(op), origin, roots };
    this.ops.push(item);
    this.dynamicSeen = true;
    if (op.kind === "write-file") {
      await putObject(join(this.dir, "post"), op.content, op.hash);
    }
    if (hooks.failBeforeOp === index) {
      throw new Error(`injected failure before op ${index} (${op.kind})`);
    }
    await this.applyAt(index, hooks, false, item);
    await hooks.afterOp?.(index);
    return this.progress.get(index)!.done!;
  }

  /**
   * Check whether the remaining plan can still be applied (roll forward).
   *
   * Requires a fully planned transaction that never failed or compensated,
   * every done op's result still on disk, the in-flight op in its before or
   * after state, and every pending op's opening hash unchanged.
   *
   * @returns null when roll-forward is safe, else the reason it is not.
   */
  async rollForwardBlocker(): Promise<string | null> {
    if (!this.intent.planned || this.hasUnplannedProgress) {
      return "the transaction ran ops decided at run time or an op failed";
    }
    if (this.compensating) {
      return "compensation already started";
    }
    const lastDone = new Map<string, number>();
    for (const { index, item } of this.doneOps()) {
      if (item.op.kind !== "host-exec") {
        lastDone.set(resolve(item.op.path), index);
      }
    }
    for (const index of lastDone.values()) {
      const op = this.ops[index]!.op;
      if (!(await resultHolds(op))) {
        return `${describe(op)} no longer holds`;
      }
    }
    for (let index = this.nextPending(); index < this.ops.length; index += 1) {
      const item = this.ops[index]!;
      const progress = this.progress.get(index);
      if (progress?.done) {
        continue;
      }
      if (progress?.begin) {
        if (!(await inFlightResumable(item.op, progress.begin.pre, this.tempPaths(index)))) {
          return `${describe(item.op)} was interrupted and its path changed since`;
        }
        continue;
      }
      if (item.expect !== undefined && (await currentHash(pathOf(item.op))) !== item.expect) {
        return `${pathOf(item.op)} changed since the transaction was planned`;
      }
    }
    return null;
  }

  /**
   * Undo every begun op in reverse, from the log and the current filesystem.
   *
   * Paths whose content no longer matches what the transaction wrote (or
   * removed) are kept and reported. Host effects are compensated only when
   * this transaction's `done` record says it made them. Idempotent: running
   * it again after a crash converges.
   */
  async compensate(hooks: ApplyHooks = {}): Promise<CompensationReport> {
    if (!this.compensating) {
      await this.append({ phase: "compensate" });
    }
    const report: CompensationReport = { failures: [], kept: [], remaining: [] };
    const indices = [...this.progress.keys()].filter((index) => this.progress.get(index)?.begin);
    indices.sort((left, right) => right - left);
    for (const index of indices) {
      try {
        await this.compensateAt(index, hooks, report);
      } catch (error) {
        report.failures.push(`${describe(this.ops[index]!.op)}: ${message(error)}`);
      }
    }
    if (report.failures.length === 0) {
      await this.append({ phase: "compensated" });
    }
    return report;
  }

  /**
   * Remove the transaction directory (after compensation or an archive copy).
   */
  async discard(): Promise<void> {
    await rm(this.dir, { force: true, recursive: true });
    await fsyncPath(dirname(this.dir)).catch(() => undefined);
  }

  /** Read a content-addressed object written by this transaction. */
  async readObject(kind: "pre" | "post", hash: string): Promise<Uint8Array> {
    const content = new Uint8Array(await readFile(join(this.dir, kind, hash)));
    if (sha256(content) !== hash) {
      throw new Error(`Journal object ${kind}/${hash} in ${this.dir} is corrupt`);
    }
    return content;
  }

  /** Read a tree preimage manifest. */
  async readManifest(hash: string): Promise<TreeManifest> {
    const parsed: unknown = JSON.parse(
      new TextDecoder().decode(await this.readObject("pre", hash)),
    );
    if (!isRecord(parsed) || typeof parsed.mode !== "number" || !Array.isArray(parsed.entries)) {
      throw new Error(`Invalid tree preimage ${hash} in ${this.dir}`);
    }
    return parsed as unknown as TreeManifest;
  }

  /** The op at an index, with its log progress. */
  opAt(index: number): { item: TxnOp; progress: OpProgress | undefined } {
    return { item: this.ops[index]!, progress: this.progress.get(index) };
  }

  /** Every op index that has a `begin` record, ascending. */
  begunIndices(): number[] {
    return [...this.progress.keys()]
      .filter((index) => this.progress.get(index)?.begin)
      .sort((left, right) => left - right);
  }

  private track(record: LogRecord): void {
    if (record.phase === "compensate") {
      this.compensating = true;
      return;
    }
    if (record.phase === "compensated") {
      return;
    }
    const progress = this.progress.get(record.op) ?? {};
    if (record.phase === "begin") {
      if (record.dynamic) {
        this.ops[record.op] = record.dynamic;
        this.dynamicSeen = true;
      }
      // The first begin carries the preimage; a resumed op logs another.
      progress.begin ??= record;
    } else if (record.phase === "done") {
      progress.done = record;
    } else {
      progress.failed = true;
      this.failedSeen = true;
    }
    this.progress.set(record.op, progress);
  }

  private async append(record: LogRecord): Promise<void> {
    await appendDurable(join(this.dir, "log.jsonl"), JSON.stringify(record));
    this.track(record);
  }

  private tempPaths(index: number): { staging: string; trash: string } {
    const path = pathOf(this.ops[index]!.op);
    const tag = `${this.id.slice(-8)}-${index}`;
    return { staging: `${path}.aiskills-${tag}.tmp`, trash: `${path}.aiskills-${tag}.rm` };
  }

  private async content(index: number, op: StoredOp): Promise<Uint8Array> {
    if (op.kind !== "write-file") {
      throw new Error(`op ${index} has no content`);
    }
    return this.readObject("post", op.hash);
  }

  private async applyAt(
    index: number,
    hooks: ApplyHooks,
    resume: boolean,
    dynamic?: TxnOp,
  ): Promise<void> {
    const item = this.ops[index]!;
    const io = withDefaults(hooks.io);
    const exec = hooks.exec ?? spawnExec;
    const { staging, trash } = this.tempPaths(index);
    const begin = (fields: Omit<Extract<LogRecord, { phase: "begin" }>, "phase" | "op">) =>
      this.append({ phase: "begin", op: index, ...fields, ...(dynamic ? { dynamic } : {}) });
    const done = (fields: Omit<Extract<LogRecord, { phase: "done" }>, "phase" | "op"> = {}) =>
      this.append({ phase: "done", op: index, ...fields });
    try {
      const op = item.op;
      if (op.kind !== "host-exec") {
        await assertInsideRoots(op.path, op.kind, item.roots);
      }
      switch (op.kind) {
        case "mkdir": {
          await begin({ missing: await missingDirs(op.path) });
          await hooks.duringOp?.(index);
          await makeDirectory(op.path, io);
          await done();
          return;
        }
        case "write-file": {
          const info = await lstatOrNull(op.path);
          if (info && !info.isFile()) {
            throw new Error(`Refusing to overwrite a non-file with write-file: ${op.path}`);
          }
          const content = await this.content(index, op);
          await begin({
            missing: await missingDirs(dirname(op.path)),
            pre: await this.capture(op.path),
          });
          await makeDirectory(dirname(op.path), io);
          try {
            await io.writeFile(staging, content);
            await fsyncPath(staging);
            if (op.mode !== undefined) {
              await io.chmod(staging, op.mode);
            }
            await hooks.duringOp?.(index);
            await io.rename(staging, op.path);
          } catch (error) {
            // A failed write (ENOSPC, EIO) or rename must not leave the staging file.
            await io.rm(staging, { force: true });
            throw error;
          }
          await fsyncPath(dirname(op.path));
          await done();
          return;
        }
        case "symlink": {
          const info = await lstatOrNull(op.path);
          if (info) {
            if (resume && info.isSymbolicLink() && (await readlink(op.path)) === op.target) {
              await done();
              return;
            }
            throw new Error(`Refusing to replace existing path with a symlink: ${op.path}`);
          }
          await begin({ missing: await missingDirs(dirname(op.path)) });
          await hooks.duringOp?.(index);
          await makeDirectory(dirname(op.path), io);
          await io.symlink(op.target, op.path);
          await fsyncPath(dirname(op.path));
          await done();
          return;
        }
        case "remove-owned": {
          if (resume && !(await lstatOrNull(op.path))) {
            // Interrupted after the rename: finish deleting the moved-aside copy.
            await io.rm(trash, { force: true, recursive: true });
            await done();
            return;
          }
          const current = await currentHash(op.path);
          if (current === null) {
            throw new Error(`Refusing to remove ${op.path}: it is no longer present`);
          }
          if (current !== op.expectHash) {
            throw new Error(`Refusing to remove ${op.path}: content changed since the plan`);
          }
          await begin({ pre: await this.capture(op.path) });
          await io.rename(op.path, trash);
          await fsyncPath(dirname(op.path));
          await hooks.duringOp?.(index);
          await io.rm(trash, { force: true, recursive: true });
          await done();
          return;
        }
        case "rmdir": {
          await begin({});
          await hooks.duringOp?.(index);
          try {
            await io.rmdir(op.path);
          } catch (error) {
            if (!isCode(error, "ENOTEMPTY", "EEXIST", "ENOENT", "ENOTDIR")) {
              throw error;
            }
            await done({ kept: true });
            return;
          }
          await fsyncPath(dirname(op.path));
          await done();
          return;
        }
        case "host-exec": {
          await begin({});
          const [command, ...args] = op.argv;
          const result = await exec(command!, args);
          const tolerated =
            (op.tolerateAlreadyPresent === true && isAlreadyPresent(result)) ||
            (op.tolerateAlreadyAbsent === true && isAlreadyAbsent(result));
          if (result.status !== 0 && !tolerated) {
            throw new Error(`${commandLabel(op.argv)} failed: ${detail(result)}`);
          }
          await hooks.duringOp?.(index);
          // A resumed op cannot tell an effect it made before the crash from
          // one that was already there: it is never recorded as created.
          await done({
            effective: !tolerated,
            ...(resume && tolerated ? { uncertain: true } : {}),
          });
          return;
        }
      }
    } catch (error) {
      await this.append({ phase: "failed", op: index, error: message(error) }).catch(
        () => undefined,
      );
      throw error;
    }
  }

  private async compensateAt(
    index: number,
    hooks: ApplyHooks,
    report: CompensationReport,
  ): Promise<void> {
    const { item, progress } = this.opAt(index);
    const begin = progress!.begin!;
    const op = item.op;
    const io = withDefaults(hooks.io);
    const { staging, trash } = this.tempPaths(index);
    switch (op.kind) {
      case "mkdir": {
        await removeCreatedDirs(begin.missing ?? [], io, report);
        return;
      }
      case "write-file": {
        await io.rm(staging, { force: true });
        const pre = begin.pre ?? { kind: "absent" };
        const current = await currentHash(op.path);
        if (current === op.hash && pre.kind === "file" && pre.hash === op.hash) {
          // Same bytes rewritten: only the permission bits may differ.
          await chmodQuiet(op.path, pre.mode, io);
        } else if (current === op.hash) {
          await this.restore(pre, op.path, staging, io);
        } else if (!matchesPreimage(current, pre)) {
          report.kept.push(`${op.path} (changed since the transaction wrote it)`);
        }
        await removeCreatedDirs(begin.missing ?? [], io, report);
        return;
      }
      case "symlink": {
        const info = await lstatOrNull(op.path);
        if (info?.isSymbolicLink() && (await readlink(op.path)) === op.target) {
          await io.unlink(op.path);
        } else if (info) {
          report.kept.push(`${op.path} (replaced since the transaction linked it)`);
        }
        await removeCreatedDirs(begin.missing ?? [], io, report);
        return;
      }
      case "remove-owned": {
        const pre = begin.pre;
        if (!pre || pre.kind === "absent") {
          return;
        }
        const current = await currentHash(op.path);
        if (current !== null) {
          if (current !== preHash(pre)) {
            report.kept.push(`${op.path} (occupied since the transaction removed it)`);
            if (await lstatOrNull(trash)) {
              report.kept.push(`${trash} (previous content of ${op.path})`);
            }
            return;
          }
          await io.rm(trash, { force: true, recursive: true });
          return;
        }
        if ((await lstatOrNull(trash)) && (await currentHash(trash)) === preHash(pre)) {
          await io.rename(trash, op.path);
          await fsyncPath(dirname(op.path));
          return;
        }
        await this.restore(pre, op.path, staging, io);
        await io.rm(trash, { force: true, recursive: true });
        return;
      }
      case "rmdir": {
        if (progress?.done?.kept) {
          return;
        }
        if (!(await lstatOrNull(op.path))) {
          await makeDirectory(op.path, io);
        }
        return;
      }
      case "host-exec": {
        const exec = hooks.exec ?? spawnExec;
        if (!progress?.done) {
          if (!progress?.failed) {
            report.remaining.push(
              `${op.argv.join(" ")} (interrupted; outcome unknown, so it is not undone)`,
            );
          }
          return;
        }
        if (!progress.done.effective) {
          return;
        }
        if (op.compensate === null) {
          report.remaining.push(`${op.argv.join(" ")} (${op.step})`);
          return;
        }
        const [command, ...args] = op.compensate;
        const undone = await exec(command!, args);
        const settled = op.tolerateAlreadyAbsent
          ? isAlreadyPresent(undone)
          : isAlreadyAbsent(undone);
        if (undone.status !== 0 && !settled) {
          throw new Error(`${commandLabel(op.compensate)} failed: ${detail(undone)}`);
        }
        return;
      }
    }
  }

  /**
   * Record a path's current state as a preimage, storing its bytes.
   */
  private async capture(path: string): Promise<Preimage> {
    const info = await lstatOrNull(path);
    const objects = join(this.dir, "pre");
    if (!info) {
      return { kind: "absent" };
    }
    if (info.isSymbolicLink()) {
      return { kind: "symlink", target: await readlink(path) };
    }
    if (info.isFile()) {
      const content = new Uint8Array(await readFile(path));
      const hash = sha256(content);
      await putObject(objects, content, hash);
      return { hash, kind: "file", mode: info.mode & 0o777 };
    }
    const manifest: TreeManifest = { entries: [], mode: info.mode & 0o777 };
    for (const entry of await walkTree(nodeReadOnlyFs, path)) {
      const absolute = join(path, entry.relative);
      if (entry.kind === "file") {
        const content = new Uint8Array(await readFile(absolute));
        const hash = sha256(content);
        await putObject(objects, content, hash);
        manifest.entries.push({
          hash,
          kind: "file",
          mode: entry.mode ?? 0o644,
          relative: entry.relative,
        });
      } else if (entry.kind === "symlink") {
        manifest.entries.push({ kind: "symlink", relative: entry.relative, target: entry.target! });
      } else {
        const mode = (await stat(absolute)).mode & 0o777;
        manifest.entries.push({ kind: "dir", mode, relative: entry.relative });
      }
    }
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const manifestHash = sha256(bytes);
    await putObject(objects, bytes, manifestHash);
    return {
      hash: await ownedPathHash(nodeReadOnlyFs, path),
      kind: "tree",
      manifest: manifestHash,
    };
  }

  /**
   * Put a preimage back at `path`, building it at `staging` and renaming it
   * into place so an interrupted restore never leaves a partial tree.
   */
  private async restore(
    pre: Preimage,
    path: string,
    staging: string,
    io: JournalIo,
  ): Promise<void> {
    if (pre.kind === "absent") {
      await io.rm(path, { force: true });
      return;
    }
    await io.rm(staging, { force: true, recursive: true });
    await makeDirectory(dirname(path), io);
    try {
      if (pre.kind === "file") {
        await io.writeFile(staging, await this.readObject("pre", pre.hash));
        await fsyncPath(staging);
        await io.chmod(staging, pre.mode);
      } else if (pre.kind === "symlink") {
        await io.symlink(pre.target, staging);
      } else {
        const manifest = await this.readManifest(pre.manifest);
        await io.mkdir(staging, { recursive: true });
        for (const entry of manifest.entries) {
          const target = join(staging, entry.relative);
          if (entry.kind === "dir") {
            await io.mkdir(target, { recursive: true });
          } else if (entry.kind === "symlink") {
            await io.symlink(entry.target!, target);
          } else {
            await io.writeFile(target, await this.readObject("pre", entry.hash!));
            await io.chmod(target, entry.mode ?? 0o644);
          }
        }
        for (const entry of manifest.entries) {
          if (entry.kind === "dir" && entry.mode !== undefined) {
            await io.chmod(join(staging, entry.relative), entry.mode);
          }
        }
        await io.chmod(staging, manifest.mode);
      }
      await io.rename(staging, path);
    } catch (error) {
      await io.rm(staging, { force: true, recursive: true });
      throw error;
    }
    await fsyncPath(dirname(path));
  }
}

/**
 * New transaction id: sortable timestamp plus random suffix.
 */
export function newTxnId(): string {
  const stamp = new Date().toISOString().replace(/[-:.]/g, "").replace("T", "-").replace("Z", "");
  return `${stamp}-${randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

/**
 * Hash identifying a path's content the way `remove-owned` checks it, or
 * null when the path is absent.
 */
export async function currentHash(path: string): Promise<string | null> {
  try {
    return await ownedPathHash(nodeReadOnlyFs, path);
  } catch (error) {
    if (isCode(error, "ENOENT", "ENOTDIR")) {
      return null;
    }
    throw error;
  }
}

/**
 * Hash a preimage would have on disk.
 */
export function preHash(pre: Preimage): string | null {
  switch (pre.kind) {
    case "absent":
      return null;
    case "file":
    case "tree":
      return pre.hash;
    case "symlink":
      return sha256(`symlink:${pre.target}`);
  }
}

/**
 * Hash a write-file or symlink op leaves at its path.
 */
export function resultHash(op: StoredOp): string | null {
  if (op.kind === "write-file") {
    return op.hash;
  }
  if (op.kind === "symlink") {
    return sha256(`symlink:${op.target}`);
  }
  return null;
}

/**
 * Path an op acts on (`host-exec` has none).
 */
export function pathOf(op: StoredOp | JournalOp): string {
  return op.kind === "host-exec" ? "" : op.path;
}

/**
 * Human label for an op in reports.
 */
export function describe(op: StoredOp | JournalOp): string {
  return op.kind === "host-exec" ? `host-exec ${op.argv.join(" ")}` : `${op.kind} ${op.path}`;
}

/**
 * Refuse a path outside its declared roots or reached through a symlinked
 * directory inside one.
 *
 * @throws {Error} Naming the escaping path or the symlinked directory.
 */
export async function assertInsideRoots(
  path: string,
  kind: string,
  roots: string[],
): Promise<void> {
  const resolved = resolve(path);
  const root = roots
    .map((candidate) => resolve(candidate))
    .find((candidate) => resolved === candidate || resolved.startsWith(withSep(candidate)));
  if (root === undefined || path.includes("\0")) {
    throw new Error(`Refusing ${kind} outside the plan's declared roots: ${path}`);
  }
  if (resolved === root) {
    return;
  }
  const parts = relative(root, dirname(resolved)).split(sep).filter(Boolean);
  let current = root;
  for (const part of parts) {
    current = join(current, part);
    const info = await lstatOrNull(current);
    if (!info) {
      break;
    }
    if (info.isSymbolicLink()) {
      throw new Error(`Refusing ${kind} through a symlinked directory: ${current}`);
    }
  }
}

/**
 * Hashes each op's path had when the transaction opened, for the first op
 * that touches a path (later ops depend on earlier ones, not on the disk).
 */
async function openingExpectations(ops: JournalOp[]): Promise<Array<string | null | undefined>> {
  const touched = new Set<string>();
  const touchedAncestors = new Set<string>();
  const expectations: Array<string | null | undefined> = [];
  for (const op of ops) {
    if (op.kind === "host-exec") {
      expectations.push(undefined);
      continue;
    }
    const path = resolve(op.path);
    let related = touched.has(path) || touchedAncestors.has(path);
    for (
      let parent = dirname(path);
      !related && parent !== dirname(parent);
      parent = dirname(parent)
    ) {
      related = touched.has(parent);
    }
    const tracked = op.kind === "write-file" || op.kind === "symlink";
    expectations.push(tracked && !related ? await currentHash(path) : undefined);
    if (op.kind === "mkdir") {
      // Creating a parent does not change what a later write expects to replace.
      continue;
    }
    touched.add(path);
    for (let parent = dirname(path); parent !== dirname(parent); parent = dirname(parent)) {
      touchedAncestors.add(parent);
    }
  }
  return expectations;
}

/**
 * Whether a done op's effect is still on disk.
 */
async function resultHolds(op: StoredOp): Promise<boolean> {
  switch (op.kind) {
    case "mkdir":
      return Boolean((await lstatOrNull(op.path))?.isDirectory());
    case "write-file":
    case "symlink":
      return (await currentHash(op.path)) === resultHash(op);
    case "remove-owned":
      return (await lstatOrNull(op.path)) === null;
    case "rmdir":
    case "host-exec":
      return true;
  }
}

/**
 * Whether an op interrupted mid-flight left its path in its before or after state.
 */
async function inFlightResumable(
  op: StoredOp,
  pre: Preimage | undefined,
  temp: { staging: string; trash: string },
): Promise<boolean> {
  switch (op.kind) {
    case "write-file": {
      const current = await currentHash(op.path);
      return current === op.hash || matchesPreimage(current, pre ?? { kind: "absent" });
    }
    case "symlink": {
      const current = await currentHash(op.path);
      return current === null || current === resultHash(op);
    }
    case "remove-owned": {
      const current = await currentHash(op.path);
      if (current === null) {
        return true;
      }
      return current === op.expectHash && !(await lstatOrNull(temp.trash));
    }
    case "host-exec":
      return op.tolerateAlreadyPresent === true || op.tolerateAlreadyAbsent === true;
    case "mkdir":
    case "rmdir":
      return true;
  }
}

function matchesPreimage(current: string | null, pre: Preimage): boolean {
  return current === preHash(pre);
}

async function removeCreatedDirs(
  missing: string[],
  io: JournalIo,
  report: CompensationReport,
): Promise<void> {
  // `missing` runs topmost first; remove deepest first.
  for (const dir of [...missing].reverse()) {
    try {
      await io.rmdir(dir);
    } catch (error) {
      if (isCode(error, "ENOENT")) {
        continue;
      }
      if (isCode(error, "ENOTEMPTY", "EEXIST")) {
        report.kept.push(`${dir} (directory holds content the transaction did not create)`);
        return;
      }
      throw error;
    }
  }
}

/**
 * Directories `mkdir -p path` would create, topmost first.
 */
async function missingDirs(path: string): Promise<string[]> {
  const missing: string[] = [];
  let current = resolve(path);
  while (!(await lstatOrNull(current))) {
    missing.unshift(current);
    const parent = dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  return missing;
}

async function makeDirectory(path: string, io: JournalIo): Promise<void> {
  const created = await io.mkdir(path, { recursive: true });
  if (created) {
    await fsyncPath(dirname(created));
  }
}

async function chmodQuiet(path: string, mode: number, io: JournalIo): Promise<void> {
  const info = await lstatOrNull(path);
  if (info?.isFile() && (info.mode & 0o777) !== mode) {
    await io.chmod(path, mode);
  }
}

/**
 * Store an object under its sha256 unless it is already present.
 */
async function putObject(dir: string, content: Uint8Array, hash: string): Promise<void> {
  if (sha256(content) !== hash) {
    throw new Error(`Refusing to journal content whose sha256 is not ${hash}`);
  }
  const path = join(dir, hash);
  if (await lstatOrNull(path)) {
    return;
  }
  await writeDurable(path, content);
}

function storeOp(op: JournalOp): StoredOp {
  if (op.kind !== "write-file") {
    return op;
  }
  const { content: _content, ...rest } = op;
  return rest;
}

async function lstatOrNull(path: string) {
  try {
    return await lstat(path);
  } catch (error) {
    if (isCode(error, "ENOENT", "ENOTDIR")) {
      return null;
    }
    throw error;
  }
}

function withDefaults(io: Partial<JournalIo> = {}): JournalIo {
  return { chmod, mkdir, rename, rm, rmdir, symlink, unlink, writeFile, ...io };
}

function withSep(path: string): string {
  return path.endsWith(sep) ? path : `${path}${sep}`;
}

/**
 * Human command prefix for errors: leading lowercase words of `argv`.
 */
export function commandLabel(argv: string[]): string {
  const words: string[] = [];
  for (const word of argv) {
    if (!/^[a-z][a-z-]*$/.test(word)) {
      break;
    }
    words.push(word);
  }
  return words.join(" ");
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isStoredOp(value: unknown): value is StoredOp {
  if (!isRecord(value) || typeof value.kind !== "string") {
    return false;
  }
  switch (value.kind) {
    case "mkdir":
    case "rmdir":
      return typeof value.path === "string";
    case "write-file":
      return (
        typeof value.path === "string" &&
        typeof value.hash === "string" &&
        (value.mode === undefined || typeof value.mode === "number")
      );
    case "symlink":
      return typeof value.path === "string" && typeof value.target === "string";
    case "remove-owned":
      return typeof value.path === "string" && typeof value.expectHash === "string";
    case "host-exec":
      return (
        typeof value.step === "string" &&
        isStringArray(value.argv) &&
        value.argv.length > 0 &&
        (value.compensate === null ||
          (isStringArray(value.compensate) && value.compensate.length > 0))
      );
    default:
      return false;
  }
}

function isTxnOp(value: unknown): value is TxnOp {
  return (
    isRecord(value) &&
    isStoredOp(value.op) &&
    isRecord(value.origin) &&
    typeof value.origin.owner === "string" &&
    typeof value.origin.adapter === "string" &&
    typeof value.origin.host === "string" &&
    isStringArray(value.roots) &&
    (value.expect === undefined || value.expect === null || typeof value.expect === "string")
  );
}

function isPreimage(value: unknown): value is Preimage {
  if (!isRecord(value)) {
    return false;
  }
  switch (value.kind) {
    case "absent":
      return true;
    case "file":
      return typeof value.hash === "string" && typeof value.mode === "number";
    case "symlink":
      return typeof value.target === "string";
    case "tree":
      return typeof value.hash === "string" && typeof value.manifest === "string";
    default:
      return false;
  }
}

function isLogRecord(value: unknown): value is LogRecord {
  if (!isRecord(value)) {
    return false;
  }
  if (value.phase === "compensate" || value.phase === "compensated") {
    return true;
  }
  if (!Number.isInteger(value.op) || (value.op as number) < 0) {
    return false;
  }
  switch (value.phase) {
    case "begin":
      return (
        (value.pre === undefined || isPreimage(value.pre)) &&
        (value.missing === undefined || isStringArray(value.missing)) &&
        (value.dynamic === undefined || isTxnOp(value.dynamic))
      );
    case "done":
      return true;
    case "failed":
      return typeof value.error === "string";
    default:
      return false;
  }
}

function isIntent(value: Record<string, unknown>): value is Intent & Record<string, unknown> {
  return (
    typeof value.txn === "string" &&
    ["adopt", "install", "remove", "rollback", "update"].includes(value.kind as string) &&
    (value.scope === "global" || value.scope === "project") &&
    typeof value.scopeDir === "string" &&
    typeof value.root === "string" &&
    isRecord(value.base) &&
    Number.isInteger(value.base.generation) &&
    (value.base.txn === null || typeof value.base.txn === "string") &&
    typeof value.planned === "boolean" &&
    Array.isArray(value.ops) &&
    value.ops.every(isTxnOp) &&
    isRecord(value.next) &&
    isRecord(value.next.plugins) &&
    Number.isInteger(value.keepGenerations) &&
    (value.next.restore === undefined || isRecord(value.next.restore))
  );
}

export type { ExecResult };

/** Contents of the state lock file. */
export interface LockHolder {
  pid: number;
  hostname: string;
  startedAt: string;
  token: string;
}

/** Thrown when another live process holds the state lock past the wait budget. */
export class StateLockBusyError extends Error {
  readonly holder: LockHolder | null;
  readonly path: string;

  constructor(path: string, holder: LockHolder | null) {
    super(
      holder
        ? `Another ai-skills command holds the state lock ${path} (pid ${holder.pid} on ` +
            `${holder.hostname}, since ${holder.startedAt}). Wait for it to finish and re-run; ` +
            "if that process is gone on another host, delete the lock file."
        : `The state lock ${path} is held and its holder could not be read. Wait and re-run; ` +
            "if no ai-skills command is running, delete the lock file.",
    );
    this.name = "StateLockBusyError";
    this.holder = holder;
    this.path = path;
  }
}

/** Default time a command waits for another one to release the state lock. */
export const DEFAULT_LOCK_WAIT_MS = 15_000;

/** An unreadable lock this old is a crash between create and write. */
const TORN_LOCK_MS = 30_000;

/**
 * Take the exclusive state lock (`O_EXCL` create) and return its release.
 *
 * The lock records pid, hostname and start time. A lock held by a dead pid
 * on this host is stale and is recovered; a live holder (or one on another
 * host, whose liveness cannot be checked) blocks until `waitMs` elapses, then
 * the call fails naming the holder.
 *
 * @throws {StateLockBusyError} When the lock stays held past `waitMs`.
 */
export async function acquireStateLock(
  path: string,
  options: { waitMs?: number; onStale?: (holder: LockHolder | null) => void } = {},
): Promise<() => Promise<void>> {
  const waitMs = options.waitMs ?? DEFAULT_LOCK_WAIT_MS;
  const started = Date.now();
  await mkdirDurable(dirname(path));
  const holder: LockHolder = {
    hostname: hostname(),
    pid: process.pid,
    startedAt: new Date().toISOString(),
    token: randomUUID(),
  };
  for (;;) {
    try {
      const handle = await open(path, "wx", 0o644);
      try {
        await handle.writeFile(`${JSON.stringify(holder)}\n`);
        await handle.sync();
      } finally {
        await handle.close();
      }
      await fsyncPath(dirname(path));
      return () => releaseStateLock(path, holder.token);
    } catch (error) {
      if (!isCode(error, "EEXIST")) {
        throw error;
      }
    }
    const current = await readLockHolder(path);
    if (current === undefined) {
      continue;
    }
    if (await isStaleLock(path, current)) {
      options.onStale?.(current);
      await breakLock(path, current);
      continue;
    }
    if (Date.now() - started >= waitMs) {
      throw new StateLockBusyError(path, current);
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 50));
  }
}

/**
 * Read the lock holder: `undefined` when the lock vanished, null when unreadable.
 */
export async function readLockHolder(path: string): Promise<LockHolder | null | undefined> {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if (isCode(error, "ENOENT")) {
      return undefined;
    }
    throw error;
  }
  try {
    const parsed: unknown = JSON.parse(text);
    if (
      isRecord(parsed) &&
      Number.isInteger(parsed.pid) &&
      typeof parsed.hostname === "string" &&
      typeof parsed.startedAt === "string" &&
      typeof parsed.token === "string"
    ) {
      return parsed as unknown as LockHolder;
    }
  } catch {
    // Fall through: a torn write.
  }
  return null;
}

async function isStaleLock(path: string, holder: LockHolder | null): Promise<boolean> {
  if (holder === null) {
    try {
      return Date.now() - (await stat(path)).mtimeMs > TORN_LOCK_MS;
    } catch (error) {
      if (isCode(error, "ENOENT")) {
        return false;
      }
      throw error;
    }
  }
  return holder.hostname === hostname() && !pidAlive(holder.pid);
}

/**
 * Whether a pid names a live process on this host.
 */
export function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return !isCode(error, "ESRCH");
  }
}

async function breakLock(path: string, judged: LockHolder | null): Promise<void> {
  // Move it aside, then check it is the lock judged stale: a competing
  // recoverer may already have replaced it with a fresh one, which is put back.
  const aside = `${path}.stale-${randomUUID()}`;
  try {
    await rename(path, aside);
  } catch (error) {
    if (isCode(error, "ENOENT")) {
      return;
    }
    throw error;
  }
  const moved = await readLockHolder(aside);
  if (judged !== null && moved?.token !== judged.token) {
    await link(aside, path).catch((error: unknown) => {
      if (!isCode(error, "EEXIST")) {
        throw error;
      }
    });
  }
  await rm(aside, { force: true });
}

async function releaseStateLock(path: string, token: string): Promise<void> {
  const current = await readLockHolder(path);
  if (current && current.token === token) {
    await unlink(path).catch((error: unknown) => {
      if (!isCode(error, "ENOENT")) {
        throw error;
      }
    });
  }
}
