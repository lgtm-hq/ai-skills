import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { getPackageVersion } from "./package-version.js";

const LOCKFILE_VERSION = 1;

const AGENT_SKILL_PATHS = {
  "claude-code": ".claude/skills",
  cursor: ".cursor/skills",
};

/**
 * Resolve the gateway lockfile path for an installation scope.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string}} [environment] - Injectable path environment.
 * @returns {string} Absolute lockfile path.
 */
export function getLockfilePath(scope, environment = {}) {
  const cwd = environment.cwd ?? process.cwd();
  const home = environment.home ?? homedir();
  return scope === "global"
    ? join(home, ".ai-skills", "lock.json")
    : join(cwd, "ai-skills-lock.json");
}

/**
 * Read a gateway lockfile, returning an empty lock when it does not exist.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string, read?: typeof readFile}} [environment] - Injectable file environment.
 * @returns {Promise<{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}>} Parsed lockfile.
 * @throws {Error} When a present lockfile is malformed or mismatched to its scope.
 */
export async function readLockfile(scope, environment = {}) {
  const read = environment.read ?? readFile;
  const path = getLockfilePath(scope, environment);
  try {
    const lock = JSON.parse(await read(path, "utf8"));
    if (
      lock.version !== LOCKFILE_VERSION ||
      lock.scope !== scope ||
      typeof lock.skills !== "object"
    ) {
      throw new Error(`Invalid gateway lockfile: ${path}`);
    }
    return lock;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return createLockfile(scope);
    }
    throw error;
  }
}

/**
 * Write a gateway lockfile atomically.
 *
 * @param {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}} lock - Lockfile contents.
 * @param {{cwd?: string, home?: string, mkdir?: typeof mkdir, rename?: typeof rename, write?: typeof writeFile}} [environment] - Injectable file environment.
 * @returns {Promise<void>} Resolves after persisting the lockfile.
 */
export async function writeLockfile(lock, environment = {}) {
  const path = getLockfilePath(lock.scope, environment);
  const makeDirectory = environment.mkdir ?? mkdir;
  const move = environment.rename ?? rename;
  const write = environment.write ?? writeFile;
  await makeDirectory(dirname(path), { recursive: true });
  const temporaryPath = `${path}.tmp`;
  await write(temporaryPath, `${JSON.stringify(lock, null, 2)}\n`, "utf8");
  await move(temporaryPath, path);
}

/**
 * Merge installed skills into a lockfile without discarding tracked agents.
 *
 * @param {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}} lock - Existing lockfile.
 * @param {Record<string, LockEntry>} entries - Newly installed skill records.
 * @returns {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}} Updated lockfile.
 */
export function mergeLockEntries(lock, entries) {
  const skills = { ...lock.skills };
  for (const [name, entry] of Object.entries(entries)) {
    const existing = skills[name];
    skills[name] = {
      ...entry,
      agents: [...new Set([...(existing?.agents ?? []), ...entry.agents])].sort(),
    };
  }
  return {
    ...lock,
    skills,
  };
}

/**
 * Remove lock entries whose skill is absent from every tracked agent directory.
 *
 * @param {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}} lock - Existing lockfile.
 * @param {(name: string, entry: LockEntry, scope: "global" | "project") => Promise<boolean>} isInstalled - Disk presence check.
 * @returns {Promise<{lock: typeof lock, pruned: string[]}>} Updated lockfile and removed skill names.
 */
export async function pruneMissingLockEntries(lock, isInstalled = isSkillInstalled) {
  const skills = {};
  const pruned = [];
  for (const [name, entry] of Object.entries(lock.skills)) {
    if (await isInstalled(name, entry, lock.scope)) {
      skills[name] = entry;
    } else {
      pruned.push(name);
    }
  }
  return {
    lock: {
      ...lock,
      skills,
    },
    pruned,
  };
}

/**
 * Check whether a skill exists in at least one known tracked agent directory.
 *
 * Unknown agent layouts are retained because their absence cannot be established
 * safely from the gateway.
 *
 * @param {string} name - Skill name.
 * @param {LockEntry} entry - Lockfile entry.
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string, exists?: (path: string) => Promise<boolean>}} [environment] - Injectable file environment.
 * @returns {Promise<boolean>} Whether the skill remains installed.
 */
export async function isSkillInstalled(name, entry, scope, environment = {}) {
  if (entry.agents.some((agent) => !AGENT_SKILL_PATHS[agent])) {
    return true;
  }
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  const exists = environment.exists ?? pathExists;
  const locations = entry.agents.map((agent) =>
    join(root, AGENT_SKILL_PATHS[agent], name, "SKILL.md"),
  );
  return (await Promise.all(locations.map((location) => exists(location)))).some(Boolean);
}

/**
 * @typedef {{agents: string[], installedAt: string, repo: string, sha: string, skillPath: string, vendor: string}} LockEntry
 */

/**
 * Create an empty version-one lockfile.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @returns {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, LockEntry>, version: number}} Empty lockfile.
 */
function createLockfile(scope) {
  return {
    gatewayVersion: getPackageVersion(),
    scope,
    skills: {},
    version: LOCKFILE_VERSION,
  };
}

/**
 * Test whether a path exists.
 *
 * @param {string} path - File path.
 * @returns {Promise<boolean>} Whether the path exists.
 */
async function pathExists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}
