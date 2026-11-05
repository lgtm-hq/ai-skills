import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

import type { AdapterId, Scope } from "../adapters/types.ts";
import { arePluginEntriesValid, LOCKFILE_VERSION, readLockfile } from "../lockfile.ts";
import type { GatewayLock, LockEnvironment, PluginLockEntry } from "../lockfile.ts";
import { isCode, writeDurable } from "./durable.ts";

/** Receipt schema version this gateway reads and writes. */
export const RECEIPT_VERSION = 1;

/**
 * Environment variable that relocates the machine-local state root when no
 * explicit home is passed (sandboxes and the test suite).
 */
export const STATE_DIR_ENV = "AI_SKILLS_STATE_DIR";

/** Where state paths are resolved from. */
export interface StateEnvironment {
  cwd?: string;
  home?: string;
}

/** A path the gateway owns, with the hash it installed and the one it replaced. */
export interface OwnedPath {
  hash: string;
  previousHash: string | null;
  owner: string;
}

/** A host CLI registration this gateway created (not one it found present). */
export interface HostRegistration {
  owner: string;
  argv: string[];
  /** Argv that undoes the registration; null when the step is irreversible. */
  compensate: string[] | null;
  txn: string;
}

/**
 * Machine-local install receipt for one scope (ADR 0010).
 *
 * The receipt is the commit point of every transaction: replacing it
 * atomically is what makes a generation current.
 */
export interface Receipt {
  version: typeof RECEIPT_VERSION;
  generation: number;
  scope: Scope;
  /** Real path of the project root (project scope) or the home directory. */
  root: string;
  /** Transaction that wrote this receipt. */
  txn: string;
  committedAt: string;
  gatewayVersion: string;
  /** Digest of the installed artifact; null until artifacts are delivered (#386). */
  artifactDigest: string | null;
  fingerprints: {
    adapters: Partial<Record<AdapterId, string>>;
    /** No delivery policy is evaluated yet (#582); null until one is. */
    policy: string | null;
  };
  paths: Record<string, OwnedPath>;
  /** Configuration keys owned by key; no adapter writes configuration yet. */
  configKeys: Record<string, { owner: string; hash: string }>;
  registrations: HostRegistration[];
  aliases: Record<string, string>;
  /** Per-plugin install records (the facts lock v2 used to hold). */
  plugins: Record<string, PluginLockEntry>;
}

/**
 * Root of all machine-local state: `~/.ai-skills/state`.
 */
export function stateRoot(environment: StateEnvironment = {}): string {
  if (environment.home !== undefined) {
    return join(environment.home, ".ai-skills", "state");
  }
  const override = process.env[STATE_DIR_ENV];
  return override ? resolve(override) : join(homedir(), ".ai-skills", "state");
}

/**
 * Directory holding one scope's receipt and generations.
 *
 * Project scope is keyed by the sha256 of the project root's real path, so
 * nothing machine-local is written into the repository.
 *
 * @throws {Error} When the project root does not exist, or when the state
 *   root would lie inside the git repository holding the project.
 */
export async function scopeStateDir(
  scope: Scope,
  environment: StateEnvironment = {},
): Promise<{ dir: string; root: string }> {
  const state = stateRoot(environment);
  if (scope === "global") {
    const home = environment.home ?? homedir();
    return { dir: join(state, "user"), root: await realpathOrSelf(home) };
  }
  const project = await realpath(environment.cwd ?? process.cwd());
  const realState = await realpathOrSelf(state);
  const repository = await enclosingRepository(project);
  if (repository !== null && isInside(realState, repository)) {
    throw new Error(
      `Refusing project-scope state: the state directory ${state} lies inside the ` +
        `repository ${repository}, so a receipt would land in it. Set ${STATE_DIR_ENV} ` +
        "to a directory outside the repository.",
    );
  }
  return { dir: join(state, "projects", projectKey(project)), root: project };
}

/**
 * Receipt key for a project root's real path.
 */
export function projectKey(realProjectRoot: string): string {
  return createHash("sha256").update(realProjectRoot).digest("hex");
}

/**
 * Path of a scope's receipt.
 */
export async function receiptPath(
  scope: Scope,
  environment: StateEnvironment = {},
): Promise<string> {
  return join((await scopeStateDir(scope, environment)).dir, "receipt.json");
}

/**
 * Read a scope's receipt, or null when none has been committed.
 *
 * @throws {Error} When the receipt has an unknown version or is malformed
 *   (fail closed: an unreadable receipt never reads as "nothing installed").
 */
export async function readReceipt(
  scope: Scope,
  environment: StateEnvironment = {},
): Promise<Receipt | null> {
  let path;
  try {
    path = await receiptPath(scope, environment);
  } catch (error) {
    // A project directory that does not exist has never committed a receipt.
    if (isCode(error, "ENOENT", "ENOTDIR")) {
      return null;
    }
    throw error;
  }
  return readReceiptFile(path, scope);
}

/**
 * Read the receipt at `path`, or null when it does not exist.
 *
 * @throws {Error} When the receipt is unknown-version or malformed.
 */
export async function readReceiptFile(path: string, scope?: Scope): Promise<Receipt | null> {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if (isCode(error, "ENOENT")) {
      return null;
    }
    throw error;
  }
  return parseReceipt(text, path, scope);
}

/**
 * Parse and validate receipt text.
 *
 * @throws {Error} On an unknown version, a scope mismatch or a malformed field.
 */
export function parseReceipt(text: string, path: string, scope?: Scope): Receipt {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`Invalid install receipt (not JSON): ${path}`);
  }
  if (!isRecord(value)) {
    throw new Error(`Invalid install receipt: ${path}`);
  }
  if (value.version !== RECEIPT_VERSION) {
    throw new Error(
      `Unsupported install receipt version ${JSON.stringify(value.version)} at ${path}; ` +
        `this gateway reads version ${RECEIPT_VERSION}. Upgrade @lgtm-hq/ai-skills.`,
    );
  }
  if (!isValidReceipt(value) || (scope !== undefined && value.scope !== scope)) {
    throw new Error(`Invalid install receipt: ${path}`);
  }
  return value;
}

/**
 * Replace a scope's receipt atomically (the transaction commit point).
 */
export async function writeReceipt(
  receipt: Receipt,
  environment: StateEnvironment = {},
): Promise<void> {
  await writeDurable(
    await receiptPath(receipt.scope, environment),
    `${JSON.stringify(receipt, null, 2)}\n`,
  );
}

/**
 * Installed state for a scope as the gateway reads it.
 *
 * A committed receipt is authoritative. Without one, an existing lock v2 file
 * is read (never written: #586 converts it) so earlier installs stay visible;
 * the first commit copies its entries into the receipt.
 *
 * @throws {Error} When the receipt or the legacy lock is invalid.
 */
export async function readInstallState(
  scope: Scope,
  environment: LockEnvironment = {},
): Promise<GatewayLock> {
  const receipt = await readReceipt(scope, environment);
  if (receipt) {
    return receiptView(receipt);
  }
  return readLockfile(scope, environment);
}

/**
 * Gateway-lock shaped view of a receipt for code that reads plugin entries.
 */
export function receiptView(receipt: Receipt): GatewayLock {
  return {
    gatewayVersion: receipt.gatewayVersion,
    plugins: receipt.plugins,
    scope: receipt.scope,
    version: LOCKFILE_VERSION,
  };
}

function isValidReceipt(
  value: Record<string, unknown>,
): value is Receipt & Record<string, unknown> {
  return (
    Number.isInteger(value.generation) &&
    (value.generation as number) >= 0 &&
    (value.scope === "global" || value.scope === "project") &&
    typeof value.root === "string" &&
    typeof value.txn === "string" &&
    typeof value.committedAt === "string" &&
    typeof value.gatewayVersion === "string" &&
    (value.artifactDigest === null || typeof value.artifactDigest === "string") &&
    isRecord(value.fingerprints) &&
    isRecord(value.fingerprints.adapters) &&
    Object.values(value.fingerprints.adapters).every((item) => typeof item === "string") &&
    (value.fingerprints.policy === null || typeof value.fingerprints.policy === "string") &&
    isRecord(value.paths) &&
    Object.values(value.paths).every(isOwnedPath) &&
    isRecord(value.configKeys) &&
    Object.values(value.configKeys).every(
      (item) => isRecord(item) && typeof item.owner === "string" && typeof item.hash === "string",
    ) &&
    Array.isArray(value.registrations) &&
    value.registrations.every(isRegistration) &&
    isRecord(value.aliases) &&
    Object.values(value.aliases).every((item) => typeof item === "string") &&
    isRecord(value.plugins) &&
    arePluginEntriesValid(value.plugins)
  );
}

function isOwnedPath(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.hash === "string" &&
    (value.previousHash === null || typeof value.previousHash === "string") &&
    typeof value.owner === "string"
  );
}

function isRegistration(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.owner === "string" &&
    typeof value.txn === "string" &&
    isArgv(value.argv) &&
    (value.compensate === null || isArgv(value.compensate))
  );
}

function isArgv(value: unknown): boolean {
  return (
    Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string")
  );
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Real path of `path`, resolving the longest existing prefix when the tail
 * does not exist yet.
 */
async function realpathOrSelf(path: string): Promise<string> {
  const absolute = resolve(path);
  try {
    return await realpath(absolute);
  } catch (error) {
    if (!isCode(error, "ENOENT", "ENOTDIR")) {
      throw error;
    }
  }
  const parent = dirname(absolute);
  if (parent === absolute) {
    return absolute;
  }
  return join(await realpathOrSelf(parent), basename(absolute));
}

/**
 * Root of the git work tree containing `path` (a `.git` entry), or null.
 */
async function enclosingRepository(path: string): Promise<string | null> {
  let current = path;
  for (;;) {
    try {
      await lstat(join(current, ".git"));
      return current;
    } catch (error) {
      if (!isCode(error, "ENOENT", "ENOTDIR")) {
        throw error;
      }
    }
    const parent = dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

function isInside(candidate: string, root: string): boolean {
  const offset = relative(root, candidate);
  return (
    offset === "" || (offset !== ".." && !offset.startsWith(`..${sep}`) && !isAbsolute(offset))
  );
}
