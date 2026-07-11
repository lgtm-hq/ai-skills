import { loadVendors } from "./catalog.js";
import { pruneMissingLockEntries, readLockfile, writeLockfile } from "./lockfile.js";
import { resolveScope } from "./options.js";
import { buildSkillsArguments, buildSkillsRemoveArguments, runSkills } from "./skills-runner.js";

/**
 * Refresh lock-managed skills using the current package tag or vendor registry pins.
 *
 * Entries absent from every tracked agent directory are pruned instead of reinstalled.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{isInstalled?: Parameters<typeof pruneMissingLockEntries>[1], now?: () => Date, readLock?: typeof readLockfile, run?: typeof runSkills, writeLock?: typeof writeLockfile}} [dependencies] - Injectable command dependencies.
 * @returns {Promise<{pruned: string[], updated: string[]}>} Updated and pruned skill names.
 */
export async function updateSkills(options, dependencies = {}) {
  const scope = resolveScope(options);
  const scopedOptions = {
    ...options,
    global: scope === "global",
    project: scope === "project",
  };
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const run = dependencies.run ?? runSkills;
  const now = dependencies.now ?? (() => new Date());
  const lock = await readLock(scope);
  const { lock: prunedLock, pruned } = await pruneMissingLockEntries(
    lock,
    dependencies.isInstalled,
  );
  const selected = selectSkills(prunedLock.skills, options.skills);
  const updated = Object.keys(selected);
  const { vendors } = await loadVendors();
  const sources = resolveSources(selected, vendors);
  for (const [source, names] of sources) {
    await run(
      buildSkillsArguments(
        {
          ...scopedOptions,
          copy: false,
          onConflict: "overwrite",
          skills: names,
        },
        source,
      ),
    );
  }
  const installedAt = now().toISOString();
  const skills = Object.fromEntries(
    Object.entries(prunedLock.skills).map(([name, entry]) => [
      name,
      updated.includes(name)
        ? {
            ...entry,
            installedAt,
            sha: sourceSha(entry.vendor, entry.sha, vendors),
          }
        : entry,
    ]),
  );
  await writeLock({
    ...prunedLock,
    gatewayVersion: process.env.npm_package_version ?? "0.0.0-dev",
    skills,
  });
  return { pruned, updated };
}

/**
 * Remove selected lock-managed skills through the upstream CLI and then unlock them.
 *
 * @param {{agents: string[], global: boolean, project: boolean, skills: string[], yes: boolean}} options - Validated command options.
 * @param {{readLock?: typeof readLockfile, run?: typeof runSkills, writeLock?: typeof writeLockfile}} [dependencies] - Injectable command dependencies.
 * @returns {Promise<string[]>} Removed skill names.
 */
export async function removeSkills(options, dependencies = {}) {
  const scope = resolveScope(options);
  const scopedOptions = {
    ...options,
    global: scope === "global",
    project: scope === "project",
  };
  const readLock = dependencies.readLock ?? readLockfile;
  const writeLock = dependencies.writeLock ?? writeLockfile;
  const run = dependencies.run ?? runSkills;
  const lock = await readLock(scope);
  const selected = Object.keys(selectSkills(lock.skills, options.skills));
  if (selected.length === 0) {
    return [];
  }
  await run(buildSkillsRemoveArguments(scopedOptions, selected));
  const skills = { ...lock.skills };
  selected.forEach((name) => delete skills[name]);
  await writeLock({
    ...lock,
    skills,
  });
  return selected;
}

/**
 * List lock-managed skills for the selected scope.
 *
 * @param {{global: boolean, project: boolean}} options - Validated command options.
 * @param {{readLock?: typeof readLockfile}} [dependencies] - Injectable command dependencies.
 * @returns {Promise<Array<{name: string} & import("./lockfile.js").LockEntry>>} Lock-managed entries.
 */
export async function listSkills(options, dependencies = {}) {
  const readLock = dependencies.readLock ?? readLockfile;
  const lock = await readLock(resolveScope(options));
  return Object.entries(lock.skills)
    .map(([name, entry]) => ({ name, ...entry }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/**
 * Select named entries, or every entry when no names were provided.
 *
 * @param {Record<string, import("./lockfile.js").LockEntry>} skills - Lock entries.
 * @param {string[]} names - Requested skill names.
 * @returns {Record<string, import("./lockfile.js").LockEntry>} Selected entries.
 * @throws {Error} When a requested skill is not lock-managed.
 */
function selectSkills(skills, names) {
  if (names.length === 0) {
    return skills;
  }
  return Object.fromEntries(
    names.map((name) => {
      if (!skills[name]) {
        throw new Error(`Skill is not managed by this gateway lockfile: ${name}`);
      }
      return [name, skills[name]];
    }),
  );
}

/**
 * Resolve updated source strings grouped by their lock entries.
 *
 * @param {Record<string, import("./lockfile.js").LockEntry>} skills - Selected lock entries.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {Map<string, string[]>} Source string to skill names.
 */
function resolveSources(skills, vendors) {
  const sources = new Map();
  for (const [name, entry] of Object.entries(skills)) {
    const source =
      entry.vendor === "lgtm-hq"
        ? `lgtm-hq/ai-skills@v${process.env.npm_package_version ?? "0.0.0-dev"}`
        : resolveVendorSource(entry, vendors);
    sources.set(source, [...(sources.get(source) ?? []), name]);
  }
  return sources;
}

/**
 * Resolve a vendor entry to its current registry pin.
 *
 * @param {import("./lockfile.js").LockEntry} entry - Lock entry.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {string} Pinned source.
 * @throws {Error} When a lock entry's vendor has been removed from the registry.
 */
function resolveVendorSource(entry, vendors) {
  const vendor = vendors.find((candidate) => candidate.id === entry.vendor);
  if (!vendor || vendor.repo !== entry.repo) {
    throw new Error(`Vendor is no longer available in the gateway registry: ${entry.vendor}`);
  }
  return `${vendor.repo}@${vendor.sha}`;
}

/**
 * Resolve the replacement SHA or first-party tag for a refreshed entry.
 *
 * @param {string} vendor - Vendor identifier.
 * @param {string} currentSha - Existing resolved SHA.
 * @param {Array<{id: string, repo: string, sha: string}>} vendors - Current vendor registry.
 * @returns {string} Updated SHA or tag.
 */
function sourceSha(vendor, currentSha, vendors) {
  if (vendor === "lgtm-hq") {
    return `v${process.env.npm_package_version ?? "0.0.0-dev"}`;
  }
  return vendors.find((candidate) => candidate.id === vendor)?.sha ?? currentSha;
}
