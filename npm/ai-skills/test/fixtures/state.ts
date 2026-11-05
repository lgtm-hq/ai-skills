import { afterAll } from "bun:test";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { readInstallState, receiptPath } from "../../lib/journal/receipts.ts";
import type { GatewayLock, LockEnvironment } from "../../lib/lockfile.ts";

/**
 * Installed state as gateway commands read it: the receipt once one is
 * committed, the legacy lock v2 file before that. Returned as parsed JSON,
 * like the lock files tests used to read.
 */
export async function readState(scope: "global" | "project", environment: LockEnvironment = {}) {
  const state: GatewayLock = await readInstallState(scope, environment);
  return JSON.parse(JSON.stringify(state));
}

/**
 * Seed a lock v2 file where earlier gateways wrote it (read-only input now).
 */
export async function writeLegacyLock(
  lock: GatewayLock | Record<string, unknown>,
  environment: { cwd?: string; home?: string } = {},
): Promise<void> {
  const scope = (lock as { scope?: string }).scope;
  const path =
    scope === "global"
      ? join(environment.home ?? homedir(), ".ai-skills", "lock.json")
      : join(environment.cwd ?? process.cwd(), "ai-skills-lock.json");
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(lock, null, 2)}\n`);
}

/**
 * Real one-file skill sources (`<name>/SKILL.md` = `# <name>\n`) for the explode lane.
 */
export async function skillSources(
  names: string[],
  root?: string,
): Promise<Record<string, string>> {
  let base = root;
  if (base === undefined) {
    const created = await mkdtemp(join(tmpdir(), "ai-skills-sources-"));
    afterAll(() => rm(created, { force: true, recursive: true }));
    base = created;
  }
  const sources: Record<string, string> = {};
  for (const name of names) {
    const dir = join(base, name);
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, "SKILL.md"), `# ${name}\n`);
    sources[name] = dir;
  }
  return sources;
}

/**
 * Edit committed plugin records in place (the receipt, or the legacy lock
 * before any commit), e.g. to make an install look like an older release.
 */
export async function editState(
  scope: "global" | "project",
  environment: LockEnvironment,
  edit: (plugins: GatewayLock["plugins"]) => void,
): Promise<void> {
  const receipt = await receiptPath(scope, environment);
  const legacy =
    scope === "global"
      ? join(environment.home ?? homedir(), ".ai-skills", "lock.json")
      : join(environment.cwd ?? process.cwd(), "ai-skills-lock.json");
  for (const path of [receipt, legacy]) {
    let document;
    try {
      document = JSON.parse(await readFile(path, "utf8"));
    } catch {
      continue;
    }
    edit(document.plugins);
    await writeFile(path, `${JSON.stringify(document, null, 2)}\n`);
    return;
  }
  throw new Error(`No ${scope} state to edit`);
}
