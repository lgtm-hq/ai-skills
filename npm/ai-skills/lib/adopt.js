import { access, readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

import { loadVendors } from "./catalog.js";
import { mergeLockEntries, readLockfile, writeLockfile } from "./lockfile.js";
import { resolveScope } from "./options.js";

/**
 * Agent skill directory layouts known to the gateway.
 *
 * Keep this aligned with `lockfile.js` so adopt and prune agree on presence.
 */
export const ADOPT_AGENT_SKILL_PATHS = {
  "claude-code": ".claude/skills",
  cursor: ".cursor/skills",
};

/**
 * Resolve the stock upstream skills lock path for a scope.
 *
 * Upstream only writes a project-local `skills-lock.json`. Global adopt still
 * scans agent skill directories under `$HOME`.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string}} [environment] - Injectable path environment.
 * @returns {string | null} Absolute skills-lock path, or null for global.
 */
export function getSkillsLockPath(scope, environment = {}) {
  if (scope === "global") {
    return null;
  }
  return join(environment.cwd ?? process.cwd(), "skills-lock.json");
}

/**
 * Read the stock skills lock when present.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, read?: typeof readFile}} [environment] - Injectable file environment.
 * @returns {Promise<{version: number, skills: Record<string, SkillsLockEntry>}>} Parsed lock or empty.
 */
export async function readSkillsLock(scope, environment = {}) {
  const path = getSkillsLockPath(scope, environment);
  if (!path) {
    return { version: 1, skills: {} };
  }
  const read = environment.read ?? readFile;
  try {
    const parsed = JSON.parse(await read(path, "utf8"));
    if (typeof parsed?.version !== "number" || typeof parsed.skills !== "object") {
      throw new Error(`Invalid skills-lock.json: ${path}`);
    }
    return parsed;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return { version: 1, skills: {} };
    }
    throw error;
  }
}

/**
 * Scan known agent skill directories for installed skill names.
 *
 * @param {"global" | "project"} scope - Installation scope.
 * @param {{cwd?: string, home?: string, readdir?: typeof readdir, exists?: (path: string) => Promise<boolean>}} [environment] - Injectable file environment.
 * @returns {Promise<Record<string, string[]>>} Skill name to sorted agent ids.
 */
export async function scanInstalledSkills(scope, environment = {}) {
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  const listDirectory = environment.readdir ?? readdir;
  const exists = environment.exists ?? pathExists;
  /** @type {Record<string, Set<string>>} */
  const installed = {};

  for (const [agent, relativePath] of Object.entries(ADOPT_AGENT_SKILL_PATHS)) {
    const skillsRoot = join(root, relativePath);
    let entries = [];
    try {
      entries = await listDirectory(skillsRoot, { withFileTypes: true });
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") {
        continue;
      }
      throw error;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }
      if (!(await exists(join(skillsRoot, entry.name, "SKILL.md")))) {
        continue;
      }
      installed[entry.name] ??= new Set();
      installed[entry.name].add(agent);
    }
  }

  return Object.fromEntries(
    Object.entries(installed)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, agents]) => [name, [...agents].sort()]),
  );
}

/**
 * Map a stock skills-lock entry into gateway lock provenance.
 *
 * @param {string} name - Skill name.
 * @param {SkillsLockEntry} entry - Upstream lock entry.
 * @param {string[]} agents - Agents where the skill is installed.
 * @param {Array<{id: string, repo: string}>} vendors - Baked vendor registry.
 * @param {() => Date} now - Clock for installedAt.
 * @returns {{entry: import("./lockfile.js").LockEntry} | {ambiguous: string}} Mapped entry or ambiguity reason.
 */
export function mapSkillsLockEntry(name, entry, agents, vendors, now = () => new Date()) {
  const repo = normalizeRepo(entry.sourceUrl ?? entry.source ?? "");
  if (!repo) {
    return { ambiguous: `${name}: skills-lock entry has no usable source/repo` };
  }
  const sha = normalizeSha(entry.ref);
  if (!sha) {
    return { ambiguous: `${name}: skills-lock entry has no commit/tag ref` };
  }
  const vendor =
    vendors.find((candidate) => candidate.repo.toLowerCase() === repo.toLowerCase())?.id ??
    (repo === "lgtm-hq/ai-skills" ? "lgtm-hq" : "external");
  return {
    entry: {
      agents: [...agents].sort(),
      installedAt: now().toISOString(),
      repo,
      sha,
      skillPath: normalizeSkillPath(name, entry.skillPath),
      vendor,
    },
  };
}

/**
 * Build the adopt plan from disk installs and the stock skills lock.
 *
 * @param {{gatewayVersion: string, scope: "global" | "project", skills: Record<string, import("./lockfile.js").LockEntry>, version: number}} lock - Current gateway lock.
 * @param {Record<string, string[]>} installed - Skill name to agents.
 * @param {Record<string, SkillsLockEntry>} skillsLock - Upstream lock skills map.
 * @param {Array<{id: string, repo: string}>} vendors - Baked vendors.
 * @param {() => Date} [now] - Clock.
 * @returns {AdoptPlan} Planned adopt/skip/ambiguous actions.
 */
export function planAdopt(lock, installed, skillsLock, vendors, now = () => new Date()) {
  /** @type {AdoptPlan} */
  const plan = {
    adopt: {},
    alreadyTracked: [],
    ambiguous: [],
    skippedMissingLock: [],
  };

  for (const [name, agents] of Object.entries(installed)) {
    const existing = lock.skills[name];
    if (existing) {
      const mergedAgents = [...new Set([...existing.agents, ...agents])].sort();
      if (mergedAgents.join(",") !== existing.agents.join(",")) {
        plan.adopt[name] = {
          ...existing,
          agents: mergedAgents,
        };
      } else {
        plan.alreadyTracked.push(name);
      }
      continue;
    }

    const stock = skillsLock[name];
    if (!stock) {
      plan.skippedMissingLock.push(name);
      plan.ambiguous.push(`${name}: installed on disk but absent from skills-lock.json`);
      continue;
    }

    const mapped = mapSkillsLockEntry(name, stock, agents, vendors, now);
    if ("ambiguous" in mapped) {
      plan.ambiguous.push(mapped.ambiguous);
      continue;
    }
    plan.adopt[name] = mapped.entry;
  }

  return plan;
}

/**
 * Import pre-gateway installs into the gateway lock without reinstalling.
 *
 * @param {{agents: string[], global: boolean, project: boolean, yes: boolean}} options - Parsed adopt options.
 * @param {{
 *   confirm?: (summary: string) => Promise<boolean>,
 *   loadVendors?: typeof loadVendors,
 *   now?: () => Date,
 *   readLock?: typeof readLockfile,
 *   readSkillsLock?: typeof readSkillsLock,
 *   scanInstalled?: typeof scanInstalledSkills,
 *   writeLock?: typeof writeLockfile,
 *   write?: (line: string) => void,
 * }} [dependencies] - Injectable collaborators.
 * @returns {Promise<AdoptResult>} Summary of adopt actions.
 */
export async function adoptSkills(options, dependencies = {}) {
  const scope = resolveScope(options);
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const readStock = dependencies.readSkillsLock ?? readSkillsLock;
  const scanInstalled = dependencies.scanInstalled ?? scanInstalledSkills;
  const loadVendorCatalog = dependencies.loadVendors ?? loadVendors;
  const now = dependencies.now ?? (() => new Date());
  const write = dependencies.write ?? ((line) => stdout.write(`${line}\n`));
  const confirm =
    dependencies.confirm ??
    (async (summary) => {
      const prompt = createInterface({ input: stdin, output: stdout });
      try {
        write(summary);
        const answer = (await prompt.question("Write gateway lock updates? [y/N] "))
          .trim()
          .toLowerCase();
        return answer === "y" || answer === "yes";
      } finally {
        prompt.close();
      }
    });

  const lock = await readLock(scope);
  const stock = await readStock(scope);
  const installed = await scanInstalled(scope);
  const filteredInstalled = filterAgents(installed, options.agents);
  const { vendors } = await loadVendorCatalog();
  const plan = planAdopt(lock, filteredInstalled, stock.skills, vendors, now);
  const summary = formatAdoptSummary(plan);

  if (Object.keys(plan.adopt).length === 0) {
    write(summary);
    return {
      adopted: [],
      alreadyTracked: plan.alreadyTracked,
      ambiguous: plan.ambiguous,
      skippedMissingLock: plan.skippedMissingLock,
      wrote: false,
    };
  }

  if (!options.yes) {
    const accepted = await confirm(summary);
    if (!accepted) {
      write("Adopt cancelled; gateway lock unchanged.");
      return {
        adopted: [],
        alreadyTracked: plan.alreadyTracked,
        ambiguous: plan.ambiguous,
        skippedMissingLock: plan.skippedMissingLock,
        wrote: false,
      };
    }
  } else {
    write(summary);
  }

  const next = mergeLockEntries(lock, plan.adopt);
  await writeLock(next);
  return {
    adopted: Object.keys(plan.adopt).sort(),
    alreadyTracked: plan.alreadyTracked,
    ambiguous: plan.ambiguous,
    skippedMissingLock: plan.skippedMissingLock,
    wrote: true,
  };
}

/**
 * @typedef {{source?: string, sourceUrl?: string, sourceType?: string, ref?: string, skillPath?: string}} SkillsLockEntry
 * @typedef {{adopt: Record<string, import("./lockfile.js").LockEntry>, alreadyTracked: string[], ambiguous: string[], skippedMissingLock: string[]}} AdoptPlan
 * @typedef {{adopted: string[], alreadyTracked: string[], ambiguous: string[], skippedMissingLock: string[], wrote: boolean}} AdoptResult
 */

/**
 * Restrict scanned installs to selected agents when provided.
 *
 * @param {Record<string, string[]>} installed - Skill name to agents.
 * @param {string[]} agents - Optional agent filter.
 * @returns {Record<string, string[]>} Filtered map.
 */
function filterAgents(installed, agents) {
  if (agents.length === 0) {
    return installed;
  }
  const allowed = new Set(agents);
  /** @type {Record<string, string[]>} */
  const filtered = {};
  for (const [name, found] of Object.entries(installed)) {
    const matched = found.filter((agent) => allowed.has(agent));
    if (matched.length > 0) {
      filtered[name] = matched;
    }
  }
  return filtered;
}

/**
 * Render a human-readable adopt summary.
 *
 * @param {AdoptPlan} plan - Planned actions.
 * @returns {string} Multi-line summary.
 */
function formatAdoptSummary(plan) {
  const lines = [
    `Adopt plan: ${Object.keys(plan.adopt).length} to import, ${plan.alreadyTracked.length} already tracked, ${plan.ambiguous.length} ambiguous/skipped.`,
  ];
  for (const name of Object.keys(plan.adopt).sort()) {
    const entry = plan.adopt[name];
    lines.push(
      `  + ${name} <- ${entry.vendor}:${entry.repo}@${entry.sha} [${entry.agents.join(",")}]`,
    );
  }
  for (const name of plan.alreadyTracked) {
    lines.push(`  = ${name} (already in gateway lock)`);
  }
  for (const reason of plan.ambiguous) {
    lines.push(`  ? ${reason}`);
  }
  return lines.join("\n");
}

/**
 * Normalize a GitHub-ish source into owner/name.
 *
 * @param {string} source - Upstream source or URL.
 * @returns {string | null} owner/name or null.
 */
function normalizeRepo(source) {
  const trimmed = source.trim().replace(/\.git$/, "");
  if (!trimmed) {
    return null;
  }
  const github = trimmed.match(/github\.com[/:]([^/]+\/[^/]+)$/i);
  if (github) {
    return github[1];
  }
  if (/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(trimmed)) {
    return trimmed;
  }
  return null;
}

/**
 * Accept a commit SHA or keep a non-empty ref tag.
 *
 * @param {string | undefined} ref - Upstream ref.
 * @returns {string | null} Usable pin.
 */
function normalizeSha(ref) {
  if (typeof ref !== "string" || !ref.trim()) {
    return null;
  }
  return ref.trim();
}

/**
 * Normalize a skill path to `.../SKILL.md`.
 *
 * @param {string} name - Skill name.
 * @param {string | undefined} skillPath - Upstream path.
 * @returns {string} Gateway skillPath.
 */
function normalizeSkillPath(name, skillPath) {
  if (!skillPath) {
    return `skills/${name}/SKILL.md`;
  }
  const normalized = skillPath.replace(/\\/g, "/").replace(/\/+$/, "");
  if (normalized.endsWith("SKILL.md")) {
    return normalized;
  }
  return `${normalized}/SKILL.md`;
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
