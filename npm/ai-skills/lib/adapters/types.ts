/**
 * Destination adapter contract (ADR 0010).
 *
 * An adapter turns a kept set into an inspectable plan of reversible
 * operations for one host. Core install code talks only to this contract and
 * the registry; host knowledge lives in the adapter and host definitions under
 * `lib/adapters/<host>/`.
 */

/** Adapter identifiers registered by the gateway. */
export type AdapterId = "claude-cli" | "copilot-cli" | "cursor-drop" | "skill-explode";

/** Host identifier; validated against the registered host definitions. */
export type HostId = string;

/** Capability role (ADR 0009). Only `skill` is delivered before #583. */
export type Role =
  | "skill"
  | "instruction"
  | "specialist"
  | "workflow"
  | "lifecycle"
  | "integration";

/**
 * Delivery mode. Stays the v1 projector vocabulary until #581 introduces
 * `native-plugin | user-explode | repo-materialize`; the field already exists
 * so that change does not alter this interface.
 */
export type Mode = "native" | "explode";

/** Install scope. */
export type Scope = "global" | "project";

/** Parity cell state (ADR 0009). */
export type CellState =
  | "supported"
  | "partial"
  | "unverified"
  | "platform-unavailable"
  | "policy-blocked"
  | "source-unportable"
  | "adapter-missing";

/** What an adapter can promise when a later step fails. */
export type RecoveryGuarantee = "reversible" | "compensating" | "irreversible";

/** Every operation kind a plan may contain. */
export const OP_KINDS = ["mkdir", "write-file", "symlink", "remove-owned", "host-exec"] as const;

/** Operation kind. */
export type OpKind = (typeof OP_KINDS)[number];

/** Create a directory (and missing parents) inside a declared root. */
export interface MkdirOp {
  kind: "mkdir";
  path: string;
}

/** Write a file's bytes inside a declared root, replacing any previous file. */
export interface WriteFileOp {
  kind: "write-file";
  path: string;
  content: Uint8Array;
  /** sha256 of `content`, hex. */
  hash: string;
}

/** Create a symlink inside a declared root. */
export interface SymlinkOp {
  kind: "symlink";
  path: string;
  target: string;
}

/**
 * Remove a path the gateway owns. The executor refuses when the current
 * owned hash (see `ownedPathHash`) differs from `expectHash`.
 */
export interface RemoveOwnedOp {
  kind: "remove-owned";
  path: string;
  expectHash: string;
}

/**
 * Run a host CLI. `compensate` undoes the effect; `null` means the effect is
 * irreversible and `disclosure` names the declared irreversible step.
 */
export interface HostExecOp {
  kind: "host-exec";
  /** Declared host-exec step this op instantiates (see `HostExecStep`). */
  step: string;
  argv: string[];
  compensate: string[] | null;
  /** Treat "already present" output as success that needs no compensation. */
  tolerateAlreadyPresent?: boolean;
}

/** One operation in an adapter plan. */
export type Op = MkdirOp | WriteFileOp | SymlinkOp | RemoveOwnedOp | HostExecOp;

/**
 * A host-exec step an adapter may emit, declared up front so the registry can
 * reject uncompensated effects that are not disclosed as irreversible.
 */
export interface HostExecStep {
  id: string;
  compensated: boolean;
  /** Required when `compensated` is false: what remains after recovery. */
  irreversible?: string;
}

/** A behavior that differs from the contract, recorded as data (#584 fixes). */
export interface Deviation {
  id: string;
  detail: string;
  issue: string;
}

/** Support request: one host × role × mode × scope cell. */
export interface SupportRequest {
  host: HostId;
  role: Role;
  mode: Mode;
  scope: Scope;
  /** Whether a locally rendered, filtered artifact is available to install from. */
  localSource: boolean;
}

/** Support report for one cell (ADR 0009 vocabulary). */
export interface SupportReport {
  adapter: AdapterId;
  host: HostId;
  role: Role;
  mode: Mode;
  scope: Scope;
  /** Whether this adapter can plan the request at all. */
  route: "available" | "unavailable";
  /** Parity claim. Never upgraded without evidence. */
  state: CellState;
  lostFields: string[];
  deviations: Deviation[];
  reason: string | null;
}

/** One skill in the kept set, with its local source directory. */
export interface KeptSkill {
  name: string;
  source: string;
}

/** Filtered capabilities this install delivers (first-party or baked vendor). */
export interface KeptSet {
  pluginId: string;
  version: string;
  description: string;
  skills: KeptSkill[];
}

/** Read-only filesystem view handed to `plan()`. It has no write methods. */
export interface ReadOnlyFs {
  lstat(path: string): Promise<FsStat>;
  stat(path: string): Promise<FsStat>;
  readdir(path: string): Promise<FsEntry[]>;
  readFile(path: string): Promise<Uint8Array>;
  readlink(path: string): Promise<string>;
  realpath(path: string): Promise<string>;
}

/** Subset of `fs.Stats` adapters read. */
export interface FsStat {
  isFile(): boolean;
  isDirectory(): boolean;
  isSymbolicLink(): boolean;
}

/** Subset of `fs.Dirent` adapters read. */
export interface FsEntry extends FsStat {
  name: string;
}

/** Everything `plan()` may read. */
export interface PlanInput {
  host: HostId;
  role: Role;
  mode: Mode;
  scope: Scope;
  kept: KeptSet;
  env: { home: string; cwd: string };
  fs: ReadOnlyFs;
  /** Skill names this lock already owns for the host (owned replace). */
  owned: string[];
  /** Adapter-specific knobs that do not change the interface. */
  options?: {
    copy?: boolean;
    destRoots?: string[];
    /** Tree drop: this lock already owns the destination. */
    replace?: boolean;
    retainStoreSkills?: string[];
    storeRoot?: string;
  };
}

/** A composed, inspectable plan. */
export interface AdapterPlan {
  adapter: AdapterId;
  host: HostId;
  role: Role;
  mode: Mode;
  scope: Scope;
  pluginId: string;
  recovery: RecoveryGuarantee;
  /** Every path op must resolve inside one of these. */
  roots: string[];
  ops: Op[];
  support: SupportReport;
  /** Informational lines (skipped identical dests and similar). */
  notes: string[];
}

/** Environment for `verify()`. */
export interface VerifyEnv {
  fs: ReadOnlyFs;
}

/** Post-apply verification. */
export interface VerifyResult {
  ok: boolean;
  problems: string[];
  /** Effects verify cannot observe (host registries). */
  unverified: string[];
}

/**
 * Host definition: the host table entries that used to live in core
 * (`AGENT_SKILL_PATHS`, `KNOWN_AGENTS`, `CLI_BY_AGENT`, projector defaults).
 */
export interface HostDefinition {
  id: HostId;
  /** Interactive label. */
  label: string;
  /** Exploded skills directory, relative to home (global) or cwd (project). */
  skillDir: string;
  /** Projector used when neither the lock nor doctor decides. */
  defaultMode: Mode;
  /** Native route, or null for explode-only hosts. */
  native: NativeRoute | null;
}

/** How a host receives a native plugin. */
export type NativeRoute =
  | {
      kind: "cli";
      adapter: AdapterId;
      /** Host CLI binary. */
      binary: string;
      /**
       * Known deviation (#584): the host's `marketplace add` drops a trailing
       * `@<tag>` from the source.
       */
      stripSourceTag?: boolean;
    }
  | {
      kind: "tree";
      adapter: AdapterId;
      /** Local plugins directory, relative to home (global) or cwd (project). */
      pluginsDir: string;
      /** Binary whose `--version` keys the doctor cache. */
      versionBinary: string;
    };

/** The adapter contract. */
export interface DestinationAdapter {
  readonly id: AdapterId;
  readonly hosts: readonly HostId[];
  readonly mode: Mode;
  /** Op kinds `plan()` may emit. */
  readonly opKinds: readonly OpKind[];
  /** Declared host-exec steps; required when `opKinds` has `host-exec`. */
  readonly hostExec: readonly HostExecStep[];
  readonly recovery: RecoveryGuarantee;
  support(request: SupportRequest): SupportReport;
  /** Pure: reads through `input.fs` only, never writes or executes. */
  plan(input: PlanInput): Promise<AdapterPlan>;
  verify(plan: AdapterPlan, env: VerifyEnv): Promise<VerifyResult>;
}
