import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import { mergeLockEntries, readLockfile, writeLockfile } from "./lockfile.js";
import { resolveScope } from "./options.js";
import { getPackageVersion } from "./package-version.js";
import { buildSkillsArguments, runSkills } from "./skills-runner.js";
import {
  createClackUi,
  formatGatewayUpdateNotice,
  formatInstalledSummary,
  formatSkillStatusSuffix,
  KNOWN_AGENTS,
  VENDOR_DRIFT_SUFFIX,
} from "./ui.js";
import { checkGatewayUpdate, checkSkillDrift, checkVendorDrift } from "./update-check.js";

/**
 * @typedef {{firstParty: string[], vendors: Record<string, string[]>}} InstallCart
 * Interactive skill cart keyed by catalog source.
 */

/**
 * @typedef {{vendor: string | null, skills: string[]}} InstallBatch
 * One upstream `skills add` invocation (single source).
 */

/**
 * @typedef {{lock: {skills: Record<string, import("./lockfile.js").LockEntry>}, gatewayUpdate: {current: string, latest: string} | null, driftedVendors: Set<string>, driftedSkills: Set<string>}} WizardSignals
 * Installed-state and update signals surfaced by the install wizard.
 */

/**
 * @typedef {import("./update-check.js").UpdateCheckDependencies & {lockEnvironment?: Parameters<typeof readLockfile>[1]}} WizardDependencies
 * Injectable fetch/env/lockfile dependencies for the wizard's soft signals.
 */

/**
 * Fill unset install selections through the home/cart wizard.
 *
 * Home lists catalogs to browse; selections accumulate in a cart. Proceed asks
 * for agents/scope once, then returns install batches. Scope defaults to global,
 * installs symlink (not copy), and uses overwrite for the gateway fail-closed
 * `--on-conflict` API without prompting.
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
  /** @type {InstallCart} */
  const cart = { firstParty: [], vendors: {} };

  while (true) {
    const action = await cancelable(
      ui,
      ui.select({
        message: "Install skills",
        options: buildHomeOptions(cart, vendors, signals),
      }),
    );

    if (action === "cancel") {
      throw new Error("Install cancelled");
    }
    if (action === "proceed") {
      break;
    }
    if (action === "browse:first-party") {
      cart.firstParty = await cancelable(
        ui,
        ui.groupMultiselect({
          message: `Skills from lgtm-hq/ai-skills @ v${getPackageVersion()}`,
          options: buildFirstPartySkillGroups(bundles, buildSkillMarkers(signals, null)),
          initialValues: cart.firstParty,
          required: false,
        }),
      );
      continue;
    }
    if (action.startsWith("browse:vendor:")) {
      const vendorId = action.slice("browse:vendor:".length);
      const index = await loadVendorIndex(vendorId);
      // Prefer registry record so displayRef survives (baked indexes omit it).
      const vendor = vendors.vendors.find((entry) => entry.id === vendorId) ?? index.vendor;
      const skillRoots = index.vendor.skillRoots ?? vendor.skillRoots ?? [];
      const picker = buildVendorSkillPicker(
        index.skills,
        skillRoots,
        buildSkillMarkers(signals, vendorId),
      );
      const message = `Skills from ${vendorDisplayLabel(vendor)}`;
      const initialValues = cart.vendors[vendorId] ?? [];
      cart.vendors[vendorId] = await cancelable(
        ui,
        picker.mode === "grouped"
          ? ui.groupMultiselect({
              message,
              options: picker.options,
              initialValues,
              required: false,
            })
          : ui.multiselect({
              message,
              options: picker.options,
              initialValues,
              required: false,
            }),
      );
      continue;
    }
    throw new Error(`Unknown home action: ${action}`);
  }

  const installBatches = batchesFromCart(cart);
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
  /** @type {WizardSignals["lock"]} */
  let lock = { skills: {} };
  try {
    lock = await readLockfile(resolveScope(options), dependencies.lockEnvironment);
  } catch {
    // Malformed lockfiles fail installs loudly elsewhere; signals stay silent.
  }
  const [gatewayUpdate, driftedVendors] = await Promise.all([gatewayPromise, vendorDriftPromise]);
  return {
    lock,
    gatewayUpdate,
    driftedVendors,
    driftedSkills: checkSkillDrift(lock, { vendors: vendors.vendors }),
  };
}

/**
 * Compute browse-row status suffixes for skills installed from one catalog.
 *
 * @param {WizardSignals} signals - Wizard signals.
 * @param {string | null} vendorId - Vendor being browsed, or null for first-party.
 * @returns {Map<string, string>} Skill name to label suffix.
 */
function buildSkillMarkers(signals, vendorId) {
  /** @type {Map<string, string>} */
  const markers = new Map();
  const catalogVendor = vendorId ?? "lgtm-hq";
  for (const [name, entry] of Object.entries(signals.lock.skills)) {
    if (entry.vendor !== catalogVendor) {
      continue;
    }
    markers.set(name, formatSkillStatusSuffix({ entry, drifted: signals.driftedSkills.has(name) }));
  }
  return markers;
}

/**
 * Build home-screen options for the install wizard.
 *
 * @param {InstallCart} cart - Current skill cart.
 * @param {{vendors: Array<{id: string, repo: string, displayRef?: string}>}} vendors - Vendor registry.
 * @param {{driftedVendors?: Set<string>}} [signals] - Wizard signals (vendor drift annotations).
 * @returns {{value: string, label: string}[]} Clack select options.
 */
export function buildHomeOptions(cart, vendors, signals = {}) {
  const driftedVendors = signals.driftedVendors ?? new Set();
  const options = [
    {
      value: "browse:first-party",
      label: `Browse lgtm-hq/ai-skills @ v${getPackageVersion()}`,
    },
    ...vendors.vendors.map((vendor) => ({
      value: `browse:vendor:${vendor.id}`,
      label: `Browse ${vendorDisplayLabel(vendor)}${
        driftedVendors.has(vendor.id) ? VENDOR_DRIFT_SUFFIX : ""
      }`,
    })),
  ];
  const total = cartSkillCount(cart);
  if (total > 0) {
    options.push({
      value: "proceed",
      label: `Proceed with install (${total} skill${total === 1 ? "" : "s"})`,
    });
  }
  options.push({ value: "cancel", label: "Cancel" });
  return options;
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
 * Count skills currently in the cart.
 *
 * @param {InstallCart} cart - Skill cart.
 * @returns {number} Total selected skills.
 */
export function cartSkillCount(cart) {
  return (
    cart.firstParty.length +
    Object.values(cart.vendors).reduce((sum, skills) => sum + skills.length, 0)
  );
}

/**
 * Convert a cart into install batches (first-party first).
 *
 * @param {InstallCart} cart - Skill cart.
 * @returns {InstallBatch[]} Non-empty batches only.
 */
export function batchesFromCart(cart) {
  /** @type {InstallBatch[]} */
  const batches = [];
  if (cart.firstParty.length > 0) {
    batches.push({ vendor: null, skills: [...cart.firstParty] });
  }
  for (const [vendorId, skills] of Object.entries(cart.vendors)) {
    if (skills.length > 0) {
      batches.push({ vendor: vendorId, skills: [...skills] });
    }
  }
  return batches;
}

/**
 * Build install batches from CLI source flags (interactive, without -y).
 *
 * @param {{bundle: string | null, skills: string[], vendor: string | null}} options - Parsed install options.
 * @returns {Promise<InstallBatch[]>} One batch for the CLI-selected source.
 */
export async function batchesFromCliOptions(options) {
  if (options.vendor) {
    if (options.skills.length === 0) {
      throw new Error(
        "Interactive install with --vendor requires --skill, or omit both to browse catalogs",
      );
    }
    return [{ vendor: options.vendor, skills: [...options.skills] }];
  }
  if (options.bundle) {
    const bundles = await loadBundles();
    const bundle = bundles.groups[options.bundle];
    if (!bundle) {
      throw new Error(`Unknown first-party bundle: ${options.bundle}`);
    }
    const skills = options.skills.length > 0 ? options.skills : bundle.skills;
    return [{ vendor: null, skills: [...skills] }];
  }
  return [{ vendor: null, skills: [...options.skills] }];
}

/**
 * Build grouped skill options for first-party interactive install.
 *
 * @param {{groups: Record<string, {name: string, skills: string[]}>, ungrouped: string[]}} bundles - Loaded bundle catalog.
 * @param {Map<string, string>} [markers] - Status suffixes keyed by skill name.
 * @returns {Record<string, {value: string, label: string}[]>} Clack groupMultiselect options.
 */
function buildFirstPartySkillGroups(bundles, markers = new Map()) {
  const toOption = (skill) => ({ value: skill, label: `${skill}${markers.get(skill) ?? ""}` });
  const groups = Object.fromEntries(
    Object.values(bundles.groups).map((bundle) => [bundle.name, bundle.skills.map(toOption)]),
  );
  if (bundles.ungrouped.length > 0) {
    groups.Other = bundles.ungrouped.map(toOption);
  }
  return groups;
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
 * @returns {Promise<void>} Resolves when the skills CLI succeeds.
 */
export async function install(options, run = runSkills, now = () => new Date(), lockEnvironment) {
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
  // Validate/read the lock before mutating agent skill dirs so a malformed lock
  // fails closed instead of leaving an unlocked install behind.
  const lock = await readLockfile(scope, lockEnvironment);
  const entries = await createLockEntries(scopedOptions, vendor, now);
  await run(buildSkillsArguments(scopedOptions, source));
  try {
    await writeLockfile(mergeLockEntries(lock, entries), lockEnvironment);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Skills installed but gateway lock update failed (${detail}). ` +
        "Fix the lockfile path permissions and re-run install, or use adopt once available.",
    );
  }
}

/**
 * Build lockfile entries for an installation that completed successfully.
 *
 * @param {{agents: string[], skills: string[]}} options - Completed install options.
 * @param {{id: string, repo: string, sha: string} | undefined} vendor - Selected vendor, if any.
 * @param {() => Date} now - Clock for installation metadata.
 * @returns {Promise<Record<string, import("./lockfile.js").LockEntry>>} Entries keyed by skill name.
 */
async function createLockEntries(options, vendor, now) {
  const installedAt = now().toISOString();
  if (!vendor) {
    return Object.fromEntries(
      options.skills.map((name) => [
        name,
        {
          agents: options.agents,
          installedAt,
          repo: "lgtm-hq/ai-skills",
          sha: `v${getPackageVersion()}`,
          skillPath: `skills/${name}/SKILL.md`,
          vendor: "lgtm-hq",
        },
      ]),
    );
  }
  const index = await loadVendorIndex(vendor.id);
  const paths = new Map(index.skills.map((skill) => [skill.name, skill.path]));
  return Object.fromEntries(
    options.skills.map((name) => {
      const path = paths.get(name);
      if (!path) {
        throw new Error(`Unknown ${vendor.id} skill: ${name}`);
      }
      return [
        name,
        {
          agents: options.agents,
          installedAt,
          repo: vendor.repo,
          sha: vendor.sha,
          skillPath: `${path}/SKILL.md`,
          vendor: vendor.id,
        },
      ];
    }),
  );
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
  for (const batch of completed.installBatches) {
    try {
      await install({
        ...completed,
        bundle: null,
        vendor: batch.vendor,
        skills: batch.skills,
      });
      finished.push(batch.vendor ?? "first-party");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(
        `Install failed for "${batch.vendor ?? "first-party"}" after completing: ` +
          `${finished.length > 0 ? finished.join(", ") : "none"}. ${detail}`,
      );
    }
  }
}
