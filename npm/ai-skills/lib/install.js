import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import { mergeLockEntries, readLockfile, writeLockfile } from "./lockfile.js";
import { resolveScope } from "./options.js";
import { getPackageVersion } from "./package-version.js";
import { buildSkillsArguments, runSkills } from "./skills-runner.js";
import { createClackUi, KNOWN_AGENTS } from "./ui.js";

/**
 * Fill unset install selections through the terminal picker.
 *
 * Happy path asks for catalog source, skills (grouped multi-select for first-party),
 * and agents. Scope defaults to global, installs symlink (not copy), and uses
 * overwrite for the gateway fail-closed `--on-conflict` API without prompting —
 * upstream `skills` does not implement conflict policies yet.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Initial install options.
 * @param {ReturnType<typeof createClackUi>} [ui] - Injectable interactive UI.
 * @returns {Promise<typeof options>} Fully selected options.
 */
export async function completeInteractively(options, ui = createClackUi()) {
  ui.intro("ai-skills gateway");

  const bundles = await loadBundles();
  const vendors = await loadVendors();
  const packageVersion = getPackageVersion();
  const sourceChoices = [
    {
      value: "first-party",
      label: `lgtm-hq/ai-skills @ v${packageVersion}`,
    },
    ...vendors.vendors.map((vendor) => ({
      value: `vendor:${vendor.id}`,
      label: vendor.repo,
    })),
  ];

  const sourceValue = await cancelable(
    ui,
    ui.select({
      message: "Install from which catalog?",
      options: sourceChoices,
    }),
  );

  if (sourceValue === "first-party") {
    const skillGroups = buildFirstPartySkillGroups(bundles);
    options.skills = await cancelable(
      ui,
      ui.groupMultiselect({
        message: "Select skills to install",
        options: skillGroups,
        required: true,
      }),
    );
  } else {
    const vendorId = parseVendorSourceValue(sourceValue);
    const index = await loadVendorIndex(vendorId);
    options.vendor = vendorId;
    options.skills = await cancelable(
      ui,
      ui.multiselect({
        message: `Select skills from ${index.vendor.repo}`,
        options: index.skills.map((skill) => ({
          value: skill.name,
          label: skill.name,
        })),
        required: true,
      }),
    );
  }

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
  return options;
}

/**
 * Build grouped skill options for first-party interactive install.
 *
 * @param {{groups: Record<string, {name: string, skills: string[]}>, ungrouped: string[]}} bundles - Loaded bundle catalog.
 * @returns {Record<string, {value: string, label: string}[]>} Clack groupMultiselect options.
 */
function buildFirstPartySkillGroups(bundles) {
  const groups = Object.fromEntries(
    Object.values(bundles.groups).map((bundle) => [
      bundle.name,
      bundle.skills.map((skill) => ({ value: skill, label: skill })),
    ]),
  );
  if (bundles.ungrouped.length > 0) {
    groups.Other = bundles.ungrouped.map((skill) => ({ value: skill, label: skill }));
  }
  return groups;
}

/**
 * Parse a vendor catalog selection value.
 *
 * @param {string} value - Combined select value (`vendor:<id>`).
 * @returns {string} Vendor id.
 */
function parseVendorSourceValue(value) {
  const prefix = "vendor:";
  if (!value.startsWith(prefix)) {
    throw new Error(`Unknown catalog selection: ${value}`);
  }
  return value.slice(prefix.length);
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
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Install options.
 * @returns {Promise<void>} Resolves when installation completes.
 */
export async function installInteractively(options) {
  await install(await completeInteractively(options));
}
