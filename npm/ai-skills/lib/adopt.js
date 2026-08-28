import { access, readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

import { loadVendors } from "./catalog.js";
import {
  AGENT_SKILL_PATHS,
  agentSkillsRoot,
  hashFile,
  mergeLockEntries,
  pluginAgentNames,
  pluginSkillNames,
  PROJECTOR_EXPLODE,
  readLockfile,
  refreshPluginFileHashes,
  writeLockfile,
} from "./lockfile.js";
import { resolveScope } from "./options.js";

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

  for (const [agent, relativePath] of Object.entries(AGENT_SKILL_PATHS)) {
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
 * @param {string} name - Skill name (also the explode plugin id).
 * @param {SkillsLockEntry} entry - Upstream lock entry.
 * @param {string[]} agents - Agents where the skill is installed.
 * @param {Array<{id: string, repo: string}>} vendors - Baked vendor registry.
 * @param {() => Date} now - Clock for installedAt.
 * @param {{cwd?: string, home?: string, scope?: "global" | "project"}} [environment] - Path environment for agent roots.
 * @returns {{entry: import("./lockfile.js").PluginLockEntry} | {ambiguous: string}} Mapped entry or ambiguity reason.
 */
export function mapSkillsLockEntry(
  name,
  entry,
  agents,
  vendors,
  now = () => new Date(),
  environment = {},
) {
  const repo = normalizeRepo(entry.sourceUrl ?? entry.source ?? "");
  if (!repo) {
    return { ambiguous: `${name}: skills-lock entry has no usable source/repo` };
  }
  const sha = normalizeSha(entry.ref);
  if (!sha) {
    return { ambiguous: `${name}: skills-lock entry has no commit/tag ref` };
  }
  if (repo.toLowerCase() === "lgtm-hq/ai-skills") {
    return {
      entry: explodePluginEntry({
        agents,
        environment,
        installedAt: now().toISOString(),
        name,
        repo: "lgtm-hq/ai-skills",
        sha,
        vendor: "lgtm-hq",
      }),
    };
  }
  const vendor = vendors.find((candidate) => candidate.repo.toLowerCase() === repo.toLowerCase());
  if (!vendor) {
    return {
      ambiguous: `${name}: source ${repo} is not in the gateway vendor registry`,
    };
  }
  return {
    entry: explodePluginEntry({
      agents,
      environment,
      installedAt: now().toISOString(),
      name,
      repo: vendor.repo,
      sha,
      vendor: vendor.id,
    }),
  };
}

/**
 * Build the adopt plan from disk installs and the stock skills lock.
 *
 * @param {import("./lockfile.js").GatewayLock} lock - Current gateway lock.
 * @param {Record<string, string[]>} installed - Skill name to agents.
 * @param {Record<string, SkillsLockEntry>} skillsLock - Upstream lock skills map.
 * @param {Array<{id: string, repo: string}>} vendors - Baked vendors.
 * @param {() => Date} [now] - Clock.
 * @param {{cwd?: string, home?: string}} [environment] - Path environment for agent roots.
 * @returns {AdoptPlan} Planned adopt/skip/ambiguous actions.
 */
export function planAdopt(
  lock,
  installed,
  skillsLock,
  vendors,
  now = () => new Date(),
  environment = {},
) {
  /** @type {AdoptPlan} */
  const plan = {
    adopt: {},
    alreadyTracked: [],
    ambiguous: [],
    skippedMissingLock: [],
  };
  const pathEnv = { ...environment, scope: lock.scope };
  const plugins = { ...lock.plugins };

  for (const [name, agents] of Object.entries(installed)) {
    const existingId = pluginIdTrackingSkill(plugins, name);
    if (existingId) {
      const existing = plugins[existingId];
      const merged = mergeSkillIntoPlugin(existing, name, agents, lock.scope, pathEnv);
      if (adoptEntryUnchanged(existing, merged)) {
        plan.alreadyTracked.push(name);
      } else {
        plan.adopt[existingId] = merged;
        plugins[existingId] = merged;
      }
      continue;
    }

    const stock = skillsLock[name];
    if (!stock) {
      plan.skippedMissingLock.push(name);
      plan.ambiguous.push(`${name}: installed on disk but absent from skills-lock.json`);
      continue;
    }

    const mapped = mapSkillsLockEntry(name, stock, agents, vendors, now, pathEnv);
    if ("ambiguous" in mapped) {
      plan.ambiguous.push(mapped.ambiguous);
      continue;
    }
    const pluginId = pluginIdForMappedEntry(name, mapped.entry);
    const existingPlugin = plugins[pluginId];
    const conflict = existingPlugin
      ? conflictingProvenanceReason(existingPlugin, mapped.entry, name, pluginId)
      : null;
    if (conflict) {
      plan.ambiguous.push(conflict);
      continue;
    }
    const next = existingPlugin
      ? mergeSkillIntoPlugin(existingPlugin, name, agents, lock.scope, pathEnv)
      : mapped.entry;
    plan.adopt[pluginId] = next;
    plugins[pluginId] = next;
  }

  return plan;
}

/**
 * Import pre-gateway installs into the gateway lock without reinstalling.
 *
 * @param {{agents: string[], global: boolean, project: boolean, yes: boolean}} options - Parsed adopt options.
 * @param {{
 *   confirm?: (summary: string) => Promise<boolean>,
 *   pathEnvironment?: {cwd?: string, home?: string},
 *   hash?: typeof hashFile,
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
  if (!options.global && !options.project) {
    throw new Error("adopt requires an explicit --global or --project scope");
  }
  const scope = resolveScope(options);
  const pathEnv = dependencies.pathEnvironment ?? {};
  const readLock = dependencies.readLock ?? ((target) => readLockfile(target, pathEnv));
  const writeLock = dependencies.writeLock ?? ((next) => writeLockfile(next, pathEnv));
  const readStock = dependencies.readSkillsLock ?? ((target) => readSkillsLock(target, pathEnv));
  const scanInstalled =
    dependencies.scanInstalled ?? ((target) => scanInstalledSkills(target, pathEnv));
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
  const plan = planAdopt(lock, filteredInstalled, stock.skills, vendors, now, pathEnv);
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

  const next = mergeLockEntries(lock, await hashAdoptedEntries(plan.adopt, dependencies.hash));
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
 * @typedef {{adopt: Record<string, import("./lockfile.js").PluginLockEntry>, alreadyTracked: string[], ambiguous: string[], skippedMissingLock: string[]}} AdoptPlan
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
      `  + ${name} <- ${entry.vendor}:${entry.repo}@${entry.sha} [${pluginAgentNames(entry).join(",")}]`,
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
 * Build a v2 explode-projector plugin entry for a scanned skill directory.
 *
 * @param {{
 *   agents: string[],
 *   environment: {cwd?: string, home?: string, scope?: "global" | "project"},
 *   installedAt: string,
 *   name: string,
 *   repo: string,
 *   sha: string,
 *   vendor: string,
 * }} options - Provenance and agent list.
 * @returns {import("./lockfile.js").PluginLockEntry} Plugin lock entry.
 */
function explodePluginEntry(options) {
  const scope = options.environment.scope ?? "project";
  const agents = Object.fromEntries(
    [...options.agents].sort().map((agent) => [
      agent,
      {
        files: { [`${options.name}/SKILL.md`]: "" },
        root: agentSkillsRoot(scope, agent, options.environment),
      },
    ]),
  );
  return {
    agents,
    installedAt: options.installedAt,
    projector: PROJECTOR_EXPLODE,
    repo: options.repo,
    sha: options.sha,
    vendor: options.vendor,
    version: options.sha.replace(/^v/, ""),
  };
}

/**
 * Plugin id that already tracks this exploded skill directory, if any.
 *
 * @param {Record<string, import("./lockfile.js").PluginLockEntry>} plugins - Lock or planned plugins.
 * @param {string} skillName - On-disk skill directory.
 * @returns {string | null} Owning plugin id.
 */
function pluginIdTrackingSkill(plugins, skillName) {
  if (plugins[skillName]) {
    return skillName;
  }
  for (const [pluginId, entry] of Object.entries(plugins)) {
    if (pluginSkillNames(entry).includes(skillName)) {
      return pluginId;
    }
  }
  return null;
}

/**
 * Lock key for a newly mapped explode skill.
 *
 * First-party skills stay keyed by directory name. Vendor skills share the vendor id.
 *
 * @param {string} skillName - On-disk skill directory.
 * @param {import("./lockfile.js").PluginLockEntry} entry - Mapped provenance.
 * @returns {string} Plugin id.
 */
function pluginIdForMappedEntry(skillName, entry) {
  return entry.vendor === "lgtm-hq" ? skillName : entry.vendor;
}

/**
 * Union a scanned skill directory onto an existing plugin entry.
 *
 * @param {import("./lockfile.js").PluginLockEntry} existing - Current lock entry.
 * @param {string} name - Skill directory name.
 * @param {string[]} agents - Newly scanned agents.
 * @param {"global" | "project"} scope - Lock scope.
 * @param {{cwd?: string, home?: string}} [environment] - Path environment for new agent roots.
 * @returns {import("./lockfile.js").PluginLockEntry} Entry with additional agents and files.
 */
function mergeSkillIntoPlugin(existing, name, agents, scope, environment = {}) {
  const relative = `${name}/SKILL.md`;
  const nextAgents = { ...existing.agents };
  for (const agent of agents) {
    const previous = nextAgents[agent];
    const root = agentSkillsRoot(scope, agent, environment);
    if (!previous) {
      nextAgents[agent] = {
        files: { [relative]: "" },
        root,
      };
      continue;
    }
    nextAgents[agent] = {
      ...previous,
      files: previous.files[relative] ? previous.files : { ...previous.files, [relative]: "" },
      root,
    };
  }
  return {
    ...existing,
    agents: nextAgents,
  };
}

/**
 * Whether a merge left plugin ownership and tracked files unchanged.
 *
 * @param {import("./lockfile.js").PluginLockEntry} existing - Entry before merge.
 * @param {import("./lockfile.js").PluginLockEntry} merged - Entry after merge.
 * @returns {boolean} True when agents and skill names are identical.
 */
function adoptEntryUnchanged(existing, merged) {
  const agents = pluginAgentNames(existing);
  if (
    agents.join(",") !== pluginAgentNames(merged).join(",") ||
    pluginSkillNames(existing).join(",") !== pluginSkillNames(merged).join(",")
  ) {
    return false;
  }
  return agents.every((agent) => existing.agents[agent].root === merged.agents[agent].root);
}

/**
 * Reason a mapped skill cannot share an existing vendor plugin.
 *
 * @param {import("./lockfile.js").PluginLockEntry} existing - Plugin already in the lock.
 * @param {import("./lockfile.js").PluginLockEntry} mapped - Newly mapped skills-lock entry.
 * @param {string} skillName - On-disk skill directory.
 * @param {string} pluginId - Vendor plugin id.
 * @returns {string | null} Ambiguity reason, or null when provenance matches.
 */
function conflictingProvenanceReason(existing, mapped, skillName, pluginId) {
  if (
    existing.projector === mapped.projector &&
    existing.repo === mapped.repo &&
    existing.sha === mapped.sha
  ) {
    return null;
  }
  return (
    `${skillName}: vendor ${pluginId} provenance ${existing.repo}@${existing.sha}` +
    ` (${existing.projector}) conflicts with ${mapped.repo}@${mapped.sha} (${mapped.projector})`
  );
}

/**
 * Fill empty adopt digests from disk before writing the gateway lock.
 *
 * @param {Record<string, import("./lockfile.js").PluginLockEntry>} entries - Planned adopt entries.
 * @param {typeof hashFile} [hash] - Injectable hasher.
 * @returns {Promise<Record<string, import("./lockfile.js").PluginLockEntry>>} Entries with refreshed hashes.
 */
async function hashAdoptedEntries(entries, hash = hashFile) {
  const hashed = {};
  for (const [pluginId, entry] of Object.entries(entries)) {
    hashed[pluginId] = await refreshPluginFileHashes(entry, hash);
  }
  return hashed;
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
