import { access, rm } from "node:fs/promises";
import { join } from "node:path";

import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import {
  agentSkillsRoot,
  hashFile,
  LOCKFILE_VERSION,
  mergeLockEntries,
  PROJECTOR_EXPLODE,
  readLockfile,
  reconcileLock,
  writeLockfile,
} from "./lockfile.js";
import { resolveScope } from "./options.js";
import { getPackageVersion } from "./package-version.js";
import { buildSkillsArguments, runSkills } from "./skills-runner.js";
import {
  createClackUi,
  formatGatewayUpdateNotice,
  formatInstallCounts,
  formatInstalledSummary,
  formatSkillStatusSuffix,
  KNOWN_AGENTS,
  VENDOR_DRIFT_SUFFIX,
} from "./ui.js";
import { checkGatewayUpdate, checkSkillDrift, checkVendorDrift } from "./update-check.js";

/**
 * @typedef {{firstParty: string[], vendors: string[]}} InstallCart
 * Interactive plugin cart. Values are plugin ids (first-party bundle ids or vendor ids).
 */

/**
 * @typedef {{pluginId: string, vendor: string | null, skills: string[]}} InstallBatch
 * One upstream `skills add` invocation for a single plugin.
 */

/**
 * @typedef {{lock: {plugins: Record<string, import("./lockfile.js").PluginLockEntry>}, gatewayUpdate: {current: string, latest: string} | null, driftedVendors: Set<string>, driftedSkills: Set<string>}} WizardSignals
 * Installed-state and update signals surfaced by the install wizard.
 */

/**
 * @typedef {import("./update-check.js").UpdateCheckDependencies & {lockEnvironment?: Parameters<typeof readLockfile>[1]}} WizardDependencies
 * Injectable fetch/env/lockfile dependencies for the wizard's soft signals.
 */

/**
 * Fill unset install selections through the home/cart wizard.
 *
 * The wizard lists plugins (first-party groups + vendor plugins). Selection is
 * plugin-atomic: no per-skill expansion. Proceed asks for agents/scope once.
 * Scope defaults to global, installs symlink (not copy), and uses overwrite
 * for the gateway fail-closed `--on-conflict` API without prompting.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Initial install options.
 * @param {ReturnType<typeof createClackUi>} [ui] - Injectable interactive UI.
 * @param {WizardDependencies} [dependencies] - Injectable fetch/env/lockfile for the soft signals.
 * @returns {Promise<typeof options & {installBatches: InstallBatch[]}>} Shared options plus per-source install batches.
 */
export async function completeInteractively(options, ui = createClackUi(), dependencies = {}) {
  ui.intro("ai-skills gateway");

  // CLI already named a source/skills: honor it instead of discarding into an empty cart.
  if (options.vendor || options.bundle || options.skills.length > 0) {
    const installBatches = await batchesFromCliOptions(options);
    return finishInteractiveInstall(options, ui, installBatches);
  }

  const bundles = await loadBundles();
  const vendors = await loadVendors();
  const signals = await gatherWizardSignals(options, vendors, dependencies);
  if (signals.gatewayUpdate) {
    ui.note(formatGatewayUpdateNotice(signals.gatewayUpdate), "Update available");
  }
  const installedSummary = formatInstalledSummary(signals.lock);
  if (installedSummary) {
    ui.note(installedSummary, "Installed");
  }
  const selected = await cancelable(
    ui,
    ui.multiselect({
      message: "Install plugins",
      options: await buildPluginChecklist(bundles, vendors, signals),
      required: false,
    }),
  );
  const cart = partitionPluginSelection(selected);
  const installBatches = await batchesFromCart(cart);
  if (installBatches.length === 0) {
    throw new Error("Install cancelled");
  }

  return finishInteractiveInstall(options, ui, installBatches);
}

/**
 * Ask agents/scope/advanced once, then return shared options plus install batches.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Initial install options.
 * @param {ReturnType<typeof createClackUi>} ui - Interactive UI.
 * @param {InstallBatch[]} installBatches - Per-catalog install batches.
 * @returns {Promise<typeof options & {installBatches: InstallBatch[]}>} Shared options plus batches.
 */
async function finishInteractiveInstall(options, ui, installBatches) {
  options.bundle = null;
  options.vendor = null;
  options.skills = [];

  if (options.agents.length === 0) {
    const selected = await cancelable(
      ui,
      ui.multiselect({
        message: "Install into which agents?",
        options: [
          ...KNOWN_AGENTS,
          {
            value: "__detect__",
            label: "Detect installed agents (may target many tools)",
          },
        ],
        initialValues: KNOWN_AGENTS.map((agent) => agent.value),
        required: true,
      }),
    );
    if (selected.length === 1 && selected[0] === "__detect__") {
      options.agents = [];
      ui.note(
        "Leaving agents unset so the upstream skills CLI can detect targets.",
        "Agent detection",
      );
    } else {
      options.agents = selected.filter((agent) => agent !== "__detect__");
    }
  }

  if (!options.global && !options.project) {
    const scope = await cancelable(
      ui,
      ui.select({
        message: "Install scope",
        options: [
          { value: "global", label: "Global (user home — recommended)" },
          { value: "project", label: "Project (this repository)" },
        ],
        initialValue: "global",
      }),
    );
    options.global = scope === "global";
    options.project = scope === "project";
  }

  // Symlink is the default; only offer copy as an advanced opt-in.
  if (!options.copy) {
    const advanced = await cancelable(
      ui,
      ui.confirm({
        message: "Show advanced options (copy files instead of symlink)?",
        initialValue: false,
      }),
    );
    if (advanced) {
      options.copy = await cancelable(
        ui,
        ui.confirm({
          message: "Copy files into each agent instead of symlinking from ~/.agents/skills?",
          initialValue: false,
        }),
      );
    }
  }

  if (!options.onConflict) {
    // Gateway still requires an explicit policy for -y; interactive defaults to
    // overwrite so we do not ask a jargon question for a no-op upstream flag.
    options.onConflict = "overwrite";
  }

  ui.outro("Starting install…");
  return { ...options, installBatches };
}

/**
 * Gather installed-state and update signals for the wizard (all soft-fail).
 *
 * Network checks start first and run concurrently with the local lockfile read;
 * each self-resolves within its timeout so the wizard never blocks beyond it.
 * Any failure degrades to "no signal" — the prompt flow itself never breaks.
 *
 * @param {{global: boolean, project: boolean}} options - Install options (for scope).
 * @param {{vendors: Array<{id: string, repo: string, sha: string}>}} vendors - Vendor registry.
 * @param {WizardDependencies} dependencies - Injectable fetch/env/lockfile.
 * @returns {Promise<WizardSignals>} Merged signals, empty where checks were skipped or failed.
 */
async function gatherWizardSignals(options, vendors, dependencies) {
  const gatewayPromise = checkGatewayUpdate(dependencies);
  const vendorDriftPromise = checkVendorDrift(vendors.vendors, dependencies);
  const lock = await readWizardLock(options, dependencies.lockEnvironment);
  const [gatewayUpdate, driftedVendors] = await Promise.all([gatewayPromise, vendorDriftPromise]);
  return {
    lock,
    gatewayUpdate,
    driftedVendors,
    driftedSkills: checkSkillDrift(lock, { vendors: vendors.vendors }),
  };
}

/**
 * Read the lockfile state backing the wizard's installed/drift signals.
 *
 * With an explicit scope flag the matching lockfile is read alone. Before the
 * wizard has asked for scope (both flags unset) the user may still pick either
 * scope, so global and project lockfiles are merged — a skill installed in
 * either scope is marked installed, with project entries winning on conflict.
 * Each read soft-fails to empty: malformed lockfiles fail installs loudly
 * elsewhere, signals stay silent.
 *
 * @param {{global: boolean, project: boolean}} options - Install options (for scope).
 * @param {Parameters<typeof readLockfile>[1] | undefined} lockEnvironment - Injectable lockfile environment.
 * @returns {Promise<WizardSignals["lock"]>} Lock state for signals, empty on failure.
 */
async function readWizardLock(options, lockEnvironment) {
  const readScope = async (scope) => {
    try {
      return await readLockfile(scope, lockEnvironment);
    } catch {
      return {
        gatewayVersion: "",
        plugins: {},
        scope,
        version: LOCKFILE_VERSION,
      };
    }
  };
  if (options.global || options.project) {
    return readScope(resolveScope(options));
  }
  const [globalLock, projectLock] = await Promise.all([readScope("global"), readScope("project")]);
  return mergeLockEntries(globalLock, projectLock.plugins);
}

/**
 * Build a flat plugin checklist for interactive install.
 *
 * @param {{groups: Record<string, {id?: string, name: string, description: string, skills: string[]}>}} bundles - First-party plugin catalog.
 * @param {{vendors: Array<{id: string, repo: string, displayRef?: string}>}} vendors - Vendor registry.
 * @param {WizardSignals | {driftedVendors?: Set<string>, driftedSkills?: Set<string>, lock?: {plugins?: Record<string, import("./lockfile.js").PluginLockEntry>}}} [signals] - Installed/drift annotations.
 * @returns {Promise<{value: string, label: string}[]>} Clack multiselect options.
 */
export async function buildPluginChecklist(bundles, vendors, signals = {}) {
  const driftedVendors = signals.driftedVendors ?? new Set();
  const markers = buildPluginMarkers(signals);
  /** @type {{value: string, label: string}[]} */
  const options = Object.entries(bundles.groups).map(([pluginId, group]) => {
    const count = group.skills.length;
    const skillLabel = count === 1 ? "skill" : "skills";
    return {
      value: pluginId,
      label: `${group.name} — ${group.description} (${count} ${skillLabel})${markers.get(pluginId) ?? ""}`,
    };
  });
  for (const vendor of vendors.vendors) {
    const index = await loadVendorIndex(vendor.id);
    const count = index.skills.length;
    const skillLabel = count === 1 ? "skill" : "skills";
    const drift = driftedVendors.has(vendor.id) ? VENDOR_DRIFT_SUFFIX : "";
    options.push({
      value: `vendor:${vendor.id}`,
      label: `${vendorDisplayLabel(vendor)} — ${count} ${skillLabel}${drift}${markers.get(vendor.id) ?? ""}`,
    });
  }
  return options;
}

/**
 * Status suffixes keyed by plugin id.
 *
 * @param {{lock?: {plugins?: Record<string, import("./lockfile.js").PluginLockEntry>}, driftedSkills?: Set<string>}} signals - Wizard signals.
 * @returns {Map<string, string>} Plugin id to installed/drift suffix.
 */
function buildPluginMarkers(signals) {
  /** @type {Map<string, string>} */
  const markers = new Map();
  for (const [pluginId, entry] of Object.entries(signals.lock?.plugins ?? {})) {
    markers.set(
      pluginId,
      formatSkillStatusSuffix({
        entry,
        drifted: signals.driftedSkills?.has(pluginId) ?? false,
      }),
    );
  }
  return markers;
}

/**
 * Split checklist values into first-party plugin ids and vendor ids.
 *
 * @param {string[]} selected - Checklist values.
 * @returns {InstallCart} Partitioned plugin cart.
 */
export function partitionPluginSelection(selected) {
  /** @type {InstallCart} */
  const cart = { firstParty: [], vendors: [] };
  for (const value of selected) {
    if (value.startsWith("vendor:")) {
      cart.vendors.push(value.slice("vendor:".length));
    } else {
      cart.firstParty.push(value);
    }
  }
  return cart;
}

/**
 * Consumer-facing catalog pin for a vendor (never a SHA).
 *
 * @param {{repo: string, displayRef?: string}} vendor - Vendor record.
 * @returns {string} `owner/repo @ pin` label.
 */
export function vendorDisplayLabel(vendor) {
  const displayRef = typeof vendor.displayRef === "string" ? vendor.displayRef : undefined;
  const pin = displayRef?.trim() || "latest";
  return `${vendor.repo} @ ${pin}`;
}

/**
 * Count plugins currently in the cart.
 *
 * @param {InstallCart} cart - Plugin cart.
 * @returns {number} Total selected plugins.
 */
export function cartPluginCount(cart) {
  return cart.firstParty.length + cart.vendors.length;
}

/**
 * Convert a plugin cart into install batches (first-party first).
 *
 * @param {InstallCart} cart - Plugin cart.
 * @returns {Promise<InstallBatch[]>} One batch per selected plugin.
 */
export async function batchesFromCart(cart) {
  const bundles = await loadBundles();
  /** @type {InstallBatch[]} */
  const batches = [];
  for (const pluginId of cart.firstParty) {
    const bundle = bundles.groups[pluginId];
    if (!bundle) {
      throw new Error(`Unknown first-party plugin: ${pluginId}`);
    }
    batches.push({ pluginId, vendor: null, skills: [...bundle.skills] });
  }
  for (const vendorId of cart.vendors) {
    const index = await loadVendorIndex(vendorId);
    batches.push({
      pluginId: vendorId,
      vendor: vendorId,
      skills: index.skills.map((skill) => skill.name),
    });
  }
  return batches;
}

/**
 * Build install batches from CLI plugin flags.
 *
 * `--skill` names first-party plugins. `--bundle` is an alias for one
 * first-party plugin. `--vendor` installs that vendor plugin atomically.
 *
 * @param {{bundle: string | null, skills: string[], vendor: string | null}} options - Parsed install options.
 * @returns {Promise<InstallBatch[]>} One batch per selected plugin.
 */
export async function batchesFromCliOptions(options) {
  if (options.vendor && (options.bundle || options.skills.length > 0)) {
    throw new Error("Vendor installs are plugin-atomic; omit --skill and --bundle");
  }
  if (options.vendor) {
    const index = await loadVendorIndex(options.vendor);
    return [
      {
        pluginId: options.vendor,
        vendor: options.vendor,
        skills: index.skills.map((skill) => skill.name),
      },
    ];
  }
  if (options.bundle && options.skills.length > 0) {
    throw new Error("Choose plugins via --skill or --bundle, not both");
  }
  const pluginIds = options.bundle ? [options.bundle] : options.skills;
  if (pluginIds.length === 0) {
    throw new Error("Select at least one plugin via --skill or --bundle");
  }
  const bundles = await loadBundles();
  return pluginIds.map((pluginId) => {
    const bundle = bundles.groups[pluginId];
    if (!bundle) {
      throw new Error(`Unknown first-party plugin: ${pluginId}`);
    }
    return { pluginId, vendor: null, skills: [...bundle.skills] };
  });
}

/**
 * Derive a runtime category key from a vendor skill path (no hand-crafted maps).
 *
 * Matching follows the baker's skillRoots segment rules as used by the runtime
 * picker: each root segment may be a literal or a full-segment ``*`` wildcard
 * (other glob metacharacters are compared as literals). Wildcard captures become
 * the group (for example plugins slash-star slash skills maps to the plugin
 * folder). Literal roots use the first path segment under the root when the
 * skill is nested (skills/engineering/tdd maps to engineering); skills sitting
 * directly under the root stay uncategorized.
 *
 * @param {string} skillPath - POSIX skill directory from the vendor index.
 * @param {string[]} skillRoots - Vendor skillRoots globs.
 * @returns {string | null} Category key, or null when uncategorized / unmatched.
 */
export function vendorSkillGroupKey(skillPath, skillRoots) {
  const skillParts = posixParts(skillPath);
  for (const skillRoot of skillRoots) {
    const rootParts = posixParts(skillRoot);
    if (rootParts.length === 0 || skillParts.length <= rootParts.length) {
      continue;
    }
    /** @type {string[]} */
    const wildcards = [];
    let matched = true;
    for (let index = 0; index < rootParts.length; index += 1) {
      const rootPart = rootParts[index];
      const skillPart = skillParts[index];
      if (!posixPartMatches({ skillPart, pattern: rootPart })) {
        matched = false;
        break;
      }
      if (rootPart === "*") {
        wildcards.push(skillPart);
      }
    }
    if (!matched) {
      continue;
    }
    if (wildcards.length > 0) {
      return wildcards.join("/");
    }
    const relative = skillParts.slice(rootParts.length);
    if (relative.length >= 2) {
      return relative[0];
    }
    return null;
  }
  return null;
}

/**
 * Build vendor skill picker options, grouped when path categories exist.
 *
 * Uses `groupMultiselect` shape when two or more headings would appear (multiple
 * named groups, or one named group plus uncategorized). Otherwise returns a
 * flat multiselect option list.
 *
 * @param {Array<{name: string, path: string}>} skills - Vendor index skills.
 * @param {string[]} skillRoots - Vendor skillRoots globs.
 * @param {Map<string, string>} [markers] - Status suffixes keyed by skill name.
 * @returns {{mode: "grouped", options: Record<string, {value: string, label: string}[]>} | {mode: "flat", options: {value: string, label: string}[]}} Picker mode and options.
 */
export function buildVendorSkillPicker(skills, skillRoots, markers = new Map()) {
  /** @type {Map<string, {value: string, label: string}[]>} */
  const named = new Map();
  /** @type {{value: string, label: string}[]} */
  const other = [];
  const toOption = (skill) => ({
    value: skill.name,
    label: `${skill.name}${markers.get(skill.name) ?? ""}`,
  });

  for (const skill of skills) {
    const option = toOption(skill);
    const key = vendorSkillGroupKey(skill.path, skillRoots);
    if (key === null) {
      other.push(option);
      continue;
    }
    const existing = named.get(key);
    if (existing) {
      existing.push(option);
    } else {
      named.set(key, [option]);
    }
  }

  const namedKeys = [...named.keys()].sort((left, right) => {
    if (left < right) {
      return -1;
    }
    if (left > right) {
      return 1;
    }
    return 0;
  });
  if (namedKeys.length === 0 || (namedKeys.length === 1 && other.length === 0)) {
    return {
      mode: "flat",
      options: skills.map(toOption),
    };
  }

  /** @type {Record<string, {value: string, label: string}[]>} */
  const options = {};
  /** @type {Set<string>} */
  const usedHeadings = new Set(other.length > 0 ? ["Other"] : []);
  for (const key of namedKeys) {
    const heading = uniqueVendorGroupHeading({
      preferred: formatVendorGroupHeading(key),
      fallbackKey: key,
      used: usedHeadings,
    });
    options[heading] = named.get(key) ?? [];
  }
  if (other.length > 0) {
    options.Other = other;
  }
  return { mode: "grouped", options };
}

/**
 * Title-case a path-derived group key for Clack headings.
 *
 * @param {string} key - Raw folder key (for example in-progress or plugin-dev).
 * @returns {string} Display heading.
 */
export function formatVendorGroupHeading(key) {
  return key
    .split(/[-_/]/)
    .filter((part) => part.length > 0)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * Pick a Clack group heading that does not collide with an existing one.
 *
 * Reserves ``Other`` for uncategorized skills when that bucket is present.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.preferred - Title-cased heading.
 * @param {string} args.fallbackKey - Raw path key for disambiguation.
 * @param {Set<string>} args.used - Headings already assigned.
 * @returns {string} Unique heading (also recorded in ``used``).
 */
function uniqueVendorGroupHeading({ preferred, fallbackKey, used }) {
  let heading = preferred;
  if (used.has(heading)) {
    heading = `${preferred} (${fallbackKey})`;
  }
  let suffix = 2;
  while (used.has(heading)) {
    heading = `${preferred} (${fallbackKey} ${suffix})`;
    suffix += 1;
  }
  used.add(heading);
  return heading;
}

/**
 * Split a POSIX path into non-empty segments.
 *
 * @param {string} path - POSIX path.
 * @returns {string[]} Path segments.
 */
function posixParts(path) {
  return path.split("/").filter((part) => part.length > 0);
}

/**
 * Match one path segment against a skillRoots segment.
 *
 * Only full-segment ``*`` wildcards are supported (matches the registry usage
 * today). Other glob metacharacters are compared as literals.
 *
 * @param {object} args - Named arguments.
 * @param {string} args.skillPart - Skill path segment.
 * @param {string} args.pattern - Root segment (literal or ``*``).
 * @returns {boolean} Whether the segment matches.
 */
function posixPartMatches({ skillPart, pattern }) {
  return pattern === "*" || skillPart === pattern;
}

/**
 * Abort when Clack reports cancel (Ctrl+C / escape).
 *
 * @template T
 * @param {ReturnType<typeof createClackUi>} ui - UI adapter.
 * @param {Promise<T>} valuePromise - Pending prompt result.
 * @returns {Promise<Exclude<T, symbol>>} Resolved non-cancel value.
 */
async function cancelable(ui, valuePromise) {
  const value = await valuePromise;
  if (ui.isCancel(value)) {
    throw new Error("Install cancelled");
  }
  return /** @type {Exclude<T, symbol>} */ (value);
}

/**
 * Install a first-party bundle or SHA-pinned vendor skill.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Validated install options.
 * @param {(args: string[]) => Promise<void>} [run] - Injectable skills process runner.
 * @param {() => Date} [now] - Injectable clock.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable lockfile environment.
 * @returns {Promise<{alreadyPresent: number, installed: number, repaired: number}>} Install summary counts.
 */
export async function install(
  options,
  run = runSkills,
  now = () => new Date(),
  lockEnvironment = {},
) {
  lockEnvironment = lockEnvironment ?? {};
  if (options.onConflict && options.onConflict !== "overwrite") {
    throw new Error(
      `--on-conflict=${options.onConflict} is unsupported: upstream skills CLI has no conflict policy. Omit the flag, use overwrite, or remove the existing skill first.`,
    );
  }
  let source;
  let selectedOptions = options;
  let vendor;
  if (options.vendor) {
    const vendors = await loadVendors();
    vendor = vendors.vendors.find((item) => item.id === options.vendor);
    if (!vendor) {
      throw new Error(`Unknown vendor: ${options.vendor}`);
    }
    const index = await loadVendorIndex(vendor.id);
    const unknownSkill = options.skills.find(
      (skillName) => !index.skills.some((skill) => skill.name === skillName),
    );
    if (unknownSkill) {
      throw new Error(`Unknown skill for vendor ${vendor.id}: ${unknownSkill}`);
    }
    source = `${vendor.repo}@${vendor.sha}`;
  } else {
    if (options.bundle && options.skills.length === 0) {
      const bundles = await loadBundles();
      const bundle = bundles.groups[options.bundle];
      if (!bundle) {
        throw new Error(`Unknown first-party bundle: ${options.bundle}`);
      }
      selectedOptions = {
        ...options,
        skills: bundle.skills,
      };
    }
    const packageVersion = getPackageVersion();
    source = `lgtm-hq/ai-skills@v${packageVersion}`;
  }
  const scope = resolveScope(selectedOptions);
  const scopedOptions = {
    ...selectedOptions,
    global: scope === "global",
    project: scope === "project",
  };
  const lock = await readLockfile(scope, lockEnvironment);
  const pluginId = resolvePluginId(scopedOptions, vendor);
  const existing = lock.plugins[pluginId];
  const detectAgents = scopedOptions.agents.length === 0;
  const agentsToInstall = await agentsNeedingInstall(
    existing,
    scopedOptions.agents,
    scopedOptions.skills,
    lockEnvironment,
  );
  const alreadyPresent = detectAgents ? 0 : scopedOptions.agents.length - agentsToInstall.length;
  const repaired = detectAgents
    ? existing
      ? 1
      : 0
    : existing
      ? agentsToInstall.filter(
          (agent) =>
            existing.agents[agent] &&
            agentCoversSkills(existing.agents[agent], scopedOptions.skills),
        ).length
      : 0;
  const installed = detectAgents ? (existing ? 0 : 1) : agentsToInstall.length - repaired;
  if (!detectAgents && agentsToInstall.length === 0) {
    return { alreadyPresent, installed, repaired };
  }
  const agentsForRun = detectAgents ? [] : agentsToInstall;
  const rollbackAgents = detectAgents ? KNOWN_AGENTS.map((agent) => agent.value) : agentsToInstall;
  const preexisting = await snapshotExistingSkillDirs(
    scopedOptions,
    rollbackAgents,
    lockEnvironment,
  );
  try {
    await run(
      buildSkillsArguments(
        {
          ...scopedOptions,
          agents: agentsForRun,
        },
        source,
      ),
    );
    const agentsForLock = detectAgents
      ? await discoverInstalledAgents(scopedOptions, lockEnvironment)
      : agentsToInstall;
    if (agentsForLock.length === 0) {
      return { alreadyPresent: 0, installed: 0, repaired: 0 };
    }
    const entries = await createLockEntries(
      { ...scopedOptions, agents: agentsForLock },
      vendor,
      now,
      lockEnvironment,
      pluginId,
      detectAgents,
    );
    if (Object.keys(entries).length === 0) {
      return { alreadyPresent: 0, installed: 0, repaired: 0 };
    }
    try {
      await writeLockfile(mergeLockEntries(lock, entries), lockEnvironment);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(
        `Skills installed but gateway lock update failed (${detail}). ` +
          "Fix the lockfile path permissions and re-run install, or use adopt once available.",
      );
    }
    return { alreadyPresent, installed, repaired };
  } catch (error) {
    await rollbackNewSkillDirs(scopedOptions, rollbackAgents, preexisting, lockEnvironment);
    throw error;
  }
}

/**
 * Build lockfile entries for an installation that completed successfully.
 *
 * @param {{agents: string[], bundle: string | null, skills: string[], global: boolean, project: boolean}} options - Completed install options.
 * @param {{id: string, repo: string, sha: string} | undefined} vendor - Selected vendor, if any.
 * @param {() => Date} now - Clock for installation metadata.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable path/hash environment.
 * @param {string} pluginId - Plugin id to record.
 * @param {boolean} [onlyExistingFiles] - When true, omit missing SKILL.md paths instead of empty digests.
 * @returns {Promise<Record<string, import("./lockfile.js").PluginLockEntry>>} Entries keyed by plugin id.
 */
async function createLockEntries(
  options,
  vendor,
  now,
  lockEnvironment = {},
  pluginId,
  onlyExistingFiles = false,
) {
  lockEnvironment = lockEnvironment ?? {};
  const installedAt = now().toISOString();
  const scope = resolveScope(options);
  const packageVersion = getPackageVersion();
  const exists = lockEnvironment?.exists ?? pathExists;
  const agents = {};
  for (const agent of options.agents) {
    const root = agentSkillsRoot(scope, agent, lockEnvironment);
    const files = {};
    for (const name of options.skills) {
      const relative = `${name}/SKILL.md`;
      const absolute = join(root, relative);
      if (onlyExistingFiles && !(await exists(absolute))) {
        continue;
      }
      files[relative] = await hashTrackedFile(absolute, lockEnvironment);
    }
    if (Object.keys(files).length === 0) {
      continue;
    }
    agents[agent] = { files, root };
  }
  if (Object.keys(agents).length === 0) {
    return {};
  }
  const entry = {
    agents,
    installedAt,
    projector: PROJECTOR_EXPLODE,
    repo: vendor?.repo ?? "lgtm-hq/ai-skills",
    sha: vendor?.sha ?? `v${packageVersion}`,
    vendor: vendor?.id ?? "lgtm-hq",
    version: vendor?.sha ?? packageVersion,
  };
  return { [pluginId]: entry };
}

/**
 * Hash a tracked file, using an empty digest when the path is absent.
 *
 * @param {string} path - Absolute file path.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable hash.
 * @returns {Promise<string>} Hex digest, or empty string when missing.
 */
async function hashTrackedFile(path, lockEnvironment = {}) {
  const hash = lockEnvironment.hash ?? hashFile;
  try {
    return await hash(path);
  } catch {
    return "";
  }
}

/**
 * Plugin id for this install: bundle id, vendor skill name, or first skill.
 *
 * @param {{bundle: string | null, skills: string[]}} options - Install options.
 * @param {{id: string} | undefined} vendor - Selected vendor, if any.
 * @returns {string} Plugin id.
 */
function resolvePluginId(options, vendor) {
  if (options.bundle) {
    return options.bundle;
  }
  if (vendor) {
    return vendor.id;
  }
  return options.skills[0] ?? "plugin";
}

/**
 * Agents that are missing, modified, or missing requested skills for an existing plugin.
 *
 * @param {import("./lockfile.js").PluginLockEntry | undefined} existing - Current lock entry.
 * @param {string[]} requestedAgents - Agents requested for this install.
 * @param {string[]} requestedSkills - Skills requested for this install.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable fs.
 * @returns {Promise<string[]>} Agents that must be materialized.
 */
async function agentsNeedingInstall(existing, requestedAgents, requestedSkills, lockEnvironment) {
  if (!existing) {
    return requestedAgents;
  }
  const reconciliation = await reconcileLock(
    {
      gatewayVersion: "",
      plugins: { plugin: existing },
      scope: "project",
      version: LOCKFILE_VERSION,
    },
    lockEnvironment,
  );
  const healthy = new Set(
    reconciliation.present.filter((item) => item.pluginId === "plugin").map((item) => item.agent),
  );
  return requestedAgents.filter((agent) => {
    if (!healthy.has(agent)) {
      return true;
    }
    return !agentCoversSkills(existing.agents[agent], requestedSkills);
  });
}

/**
 * Whether an agent install already tracks every requested skill directory.
 *
 * @param {import("./lockfile.js").AgentInstall | undefined} install - Per-agent lock record.
 * @param {string[]} requestedSkills - Skills requested for this install.
 * @returns {boolean} True when every requested skill is already tracked.
 */
function agentCoversSkills(install, requestedSkills) {
  if (!install) {
    return false;
  }
  const tracked = new Set(
    Object.keys(install.files)
      .map((relative) => relative.split("/")[0])
      .filter(Boolean),
  );
  return requestedSkills.every((name) => tracked.has(name));
}

/**
 * Agents that actually received requested skills after an untargeted install.
 *
 * @param {{agents: string[], skills: string[], global: boolean, project: boolean}} options - Install options.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable fs.
 * @returns {Promise<string[]>} Detected agent ids.
 */
async function discoverInstalledAgents(options, lockEnvironment = {}) {
  const exists = lockEnvironment.exists ?? pathExists;
  const found = [];
  for (const { value: agent } of KNOWN_AGENTS) {
    const root = agentSkillsRoot(resolveScope(options), agent, lockEnvironment);
    let present = false;
    for (const name of options.skills) {
      if (await exists(join(root, name, "SKILL.md"))) {
        present = true;
        break;
      }
    }
    if (present) {
      found.push(agent);
    }
  }
  return found;
}

/**
 * Snapshot skill directories that already exist for the agents in this install.
 *
 * Used so a failed install can delete only the trees it created.
 *
 * @param {{skills: string[], global: boolean, project: boolean}} options - Install options.
 * @param {string[]} agents - Agents that may receive new skill directories.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable fs.
 * @returns {Promise<Set<string>>} Absolute skill directories present before the run.
 */
async function snapshotExistingSkillDirs(options, agents, lockEnvironment = {}) {
  const exists = lockEnvironment.exists ?? pathExists;
  /** @type {Set<string>} */
  const existing = new Set();
  for (const agent of agents) {
    const root = agentSkillsRoot(resolveScope(options), agent, lockEnvironment);
    for (const name of options.skills) {
      const dir = join(root, name);
      if (await exists(dir)) {
        existing.add(dir);
      }
    }
  }
  return existing;
}

/**
 * Remove skill directories created by a failed plugin install.
 *
 * Directories that existed before the run are left in place.
 *
 * @param {{skills: string[], global: boolean, project: boolean}} options - Install options.
 * @param {string[]} agents - Agents that may have received new skill directories.
 * @param {Set<string>} preexisting - Absolute skill directories present before the run.
 * @param {Parameters<typeof readLockfile>[1]} [lockEnvironment] - Injectable fs.
 * @returns {Promise<void>} Resolves when newly created trees are gone.
 */
async function rollbackNewSkillDirs(options, agents, preexisting, lockEnvironment = {}) {
  const exists = lockEnvironment.exists ?? pathExists;
  const remove = lockEnvironment.rm ?? rm;
  for (const agent of agents) {
    const root = agentSkillsRoot(resolveScope(options), agent, lockEnvironment);
    for (const name of options.skills) {
      const dir = join(root, name);
      if (preexisting.has(dir) || !(await exists(dir))) {
        continue;
      }
      await remove(dir, { force: true, recursive: true });
    }
  }
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

/**
 * Create an interactive installer session.
 *
 * Runs one upstream install per selected catalog so mixed first-party + vendor
 * picks complete in a single interactive session.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Install options.
 * @returns {Promise<void>} Resolves when installation completes.
 */
export async function installInteractively(options) {
  const completed = await completeInteractively(options);
  const finished = [];
  const totals = { alreadyPresent: 0, installed: 0, repaired: 0 };
  for (const batch of completed.installBatches) {
    try {
      const counts = await install({
        ...completed,
        bundle: batch.vendor ? null : batch.pluginId,
        vendor: batch.vendor,
        skills: batch.skills,
      });
      totals.alreadyPresent += counts.alreadyPresent;
      totals.installed += counts.installed;
      totals.repaired += counts.repaired;
      finished.push(batch.vendor ?? "first-party");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(
        `Install failed for "${batch.vendor ?? "first-party"}" after completing: ` +
          `${finished.length > 0 ? finished.join(", ") : "none"}. ${detail}`,
      );
    }
  }
  console.log(formatInstallCounts(totals));
}
