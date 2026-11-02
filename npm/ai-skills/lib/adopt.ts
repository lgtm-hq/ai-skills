import { access, readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

import { loadVendors } from "./catalog.ts";
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
} from "./lockfile.ts";
import { resolveScope } from "./options.ts";

/**
 * Resolve the stock upstream skills lock path for a scope.
 *
 * Upstream only writes a project-local `skills-lock.json`. Global adopt still
 * scans agent skill directories under `$HOME`.
 */
export function getSkillsLockPath(
  scope: "global" | "project",
  environment: { cwd?: string } = {},
): string | null {
  if (scope === "global") {
    return null;
  }
  return join(environment.cwd ?? process.cwd(), "skills-lock.json");
}

/**
 * Read the stock skills lock when present.
 */
export async function readSkillsLock(
  scope: "global" | "project",
  environment: { cwd?: string; read?: typeof readFile } = {},
): Promise<{ version: number; skills: Record<string, SkillsLockEntry> }> {
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
 */
export async function scanInstalledSkills(
  scope: "global" | "project",
  environment: {
    cwd?: string;
    home?: string;
    readdir?: typeof readdir;
    exists?: (path: string) => Promise<boolean>;
  } = {},
): Promise<Record<string, string[]>> {
  const root =
    scope === "global" ? (environment.home ?? homedir()) : (environment.cwd ?? process.cwd());
  const listDirectory = environment.readdir ?? readdir;
  const exists = environment.exists ?? pathExists;

  const installed: Record<string, Set<string>> = {};

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
      installed[entry.name]!.add(agent);
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
 */
export function mapSkillsLockEntry(
  name: string,
  entry: SkillsLockEntry,
  agents: string[],
  vendors: Array<{ id: string; repo: string }>,
  now: () => Date = () => new Date(),
  environment: { cwd?: string; home?: string; scope?: "global" | "project" } = {},
): { entry: import("./lockfile.ts").PluginLockEntry } | { ambiguous: string } {
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
 */
export function planAdopt(
  lock: import("./lockfile.ts").GatewayLock,
  installed: Record<string, string[]>,
  skillsLock: Record<string, SkillsLockEntry>,
  vendors: Array<{ id: string; repo: string }>,
  now: () => Date = () => new Date(),
  environment: { cwd?: string; home?: string } = {},
): AdoptPlan {
  const plan: AdoptPlan = {
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
      const merged = mergeSkillIntoPlugin(existing!, name, agents, lock.scope, pathEnv);
      if (adoptEntryUnchanged(existing!, merged)) {
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
 */
export async function adoptSkills(
  options: { agents: string[]; global: boolean; project: boolean; yes: boolean },
  dependencies: {
    confirm?: (summary: string) => Promise<boolean>;
    pathEnvironment?: { cwd?: string; home?: string };
    hash?: typeof hashFile;
    loadVendors?: () => Promise<{ vendors: { id: string; repo: string }[] }>;
    now?: () => Date;
    readLock?: typeof readLockfile;
    readSkillsLock?: typeof readSkillsLock;
    scanInstalled?: typeof scanInstalledSkills;
    writeLock?: typeof writeLockfile;
    write?: (line: string) => void;
  } = {},
): Promise<AdoptResult> {
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
 * Restrict scanned installs to selected agents when provided.
 */
function filterAgents(
  installed: Record<string, string[]>,
  agents: string[],
): Record<string, string[]> {
  if (agents.length === 0) {
    return installed;
  }
  const allowed = new Set(agents);

  const filtered: Record<string, string[]> = {};
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
 */
function formatAdoptSummary(plan: AdoptPlan): string {
  const lines = [
    `Adopt plan: ${Object.keys(plan.adopt).length} to import, ${plan.alreadyTracked.length} already tracked, ${plan.ambiguous.length} ambiguous/skipped.`,
  ];
  for (const name of Object.keys(plan.adopt).sort()) {
    const entry = plan.adopt[name];
    lines.push(
      `  + ${name} <- ${entry!.vendor}:${entry!.repo}@${entry!.sha} [${pluginAgentNames(entry!).join(",")}]`,
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
 */
function normalizeRepo(source: string): string | null {
  const trimmed = source.trim().replace(/\.git$/, "");
  if (!trimmed) {
    return null;
  }
  const github = trimmed.match(/github\.com[/:]([^/]+\/[^/]+)$/i);
  if (github) {
    return github[1]!;
  }
  if (/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(trimmed)) {
    return trimmed;
  }
  return null;
}

/**
 * Accept a commit SHA or keep a non-empty ref tag.
 */
function normalizeSha(ref: string | undefined): string | null {
  if (typeof ref !== "string" || !ref.trim()) {
    return null;
  }
  return ref.trim();
}

/**
 * Build a v2 explode-projector plugin entry for a scanned skill directory.
 */
function explodePluginEntry(options: {
  agents: string[];
  environment: { cwd?: string; home?: string; scope?: "global" | "project" };
  installedAt: string;
  name: string;
  repo: string;
  sha: string;
  vendor: string;
}): import("./lockfile.ts").PluginLockEntry {
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
 */
function pluginIdTrackingSkill(
  plugins: Record<string, import("./lockfile.ts").PluginLockEntry>,
  skillName: string,
): string | null {
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
 */
function pluginIdForMappedEntry(
  skillName: string,
  entry: import("./lockfile.ts").PluginLockEntry,
): string {
  return entry.vendor === "lgtm-hq" ? skillName : entry.vendor;
}

/**
 * Union a scanned skill directory onto an existing plugin entry.
 */
function mergeSkillIntoPlugin(
  existing: import("./lockfile.ts").PluginLockEntry,
  name: string,
  agents: string[],
  scope: "global" | "project",
  environment: { cwd?: string; home?: string } = {},
): import("./lockfile.ts").PluginLockEntry {
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
 */
function adoptEntryUnchanged(
  existing: import("./lockfile.ts").PluginLockEntry,
  merged: import("./lockfile.ts").PluginLockEntry,
): boolean {
  const agents = pluginAgentNames(existing);
  if (
    agents.join(",") !== pluginAgentNames(merged).join(",") ||
    pluginSkillNames(existing).join(",") !== pluginSkillNames(merged).join(",")
  ) {
    return false;
  }
  return agents.every((agent) => existing.agents[agent]!.root === merged.agents[agent]!.root);
}

/**
 * Reason a mapped skill cannot share an existing vendor plugin.
 */
function conflictingProvenanceReason(
  existing: import("./lockfile.ts").PluginLockEntry,
  mapped: import("./lockfile.ts").PluginLockEntry,
  skillName: string,
  pluginId: string,
): string | null {
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
 */
async function hashAdoptedEntries(
  entries: Record<string, import("./lockfile.ts").PluginLockEntry>,
  hash: typeof hashFile = hashFile,
): Promise<Record<string, import("./lockfile.ts").PluginLockEntry>> {
  const hashed: Record<string, import("./lockfile.ts").PluginLockEntry> = {};
  for (const [pluginId, entry] of Object.entries(entries)) {
    hashed[pluginId] = await refreshPluginFileHashes(entry, hash);
  }
  return hashed;
}

/**
 * Test whether a path exists.
 */
async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

export interface SkillsLockEntry {
  source?: string;
  sourceUrl?: string;
  sourceType?: string;
  ref?: string;
  skillPath?: string;
}

export interface AdoptPlan {
  adopt: Record<string, import("./lockfile.ts").PluginLockEntry>;
  alreadyTracked: string[];
  ambiguous: string[];
  skippedMissingLock: string[];
}

export interface AdoptResult {
  adopted: string[];
  alreadyTracked: string[];
  ambiguous: string[];
  skippedMissingLock: string[];
  wrote: boolean;
}
