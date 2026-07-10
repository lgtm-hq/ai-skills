import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

import { loadBundles, loadVendorIndex, loadVendors } from "./catalog.js";
import { mergeLockEntries, readLockfile, writeLockfile } from "./lockfile.js";
import { resolveScope } from "./options.js";
import { buildSkillsArguments, runSkills } from "./skills-runner.js";

/**
 * Prompt for a numbered item.
 *
 * @template T
 * @param {string} label - Prompt heading.
 * @param {T[]} items - Selectable values.
 * @param {(item: T) => string} describe - Human-readable item formatter.
 * @param {{question: (query: string) => Promise<string>}} prompt - Interactive prompt.
 * @returns {Promise<T>} Selected value.
 */
async function choose(label, items, describe, prompt) {
  stdout.write(`${label}\n`);
  items.forEach((item, index) => stdout.write(`  ${index + 1}. ${describe(item)}\n`));
  const response = await prompt.question("> ");
  const selection = Number.parseInt(response, 10) - 1;
  if (!Number.isInteger(selection) || !items[selection]) {
    throw new Error("Choose a listed number");
  }
  return items[selection];
}

/**
 * Fill unset install selections through the terminal picker.
 *
 * @param {{agents: string[], bundle: string | null, copy: boolean, global: boolean, onConflict: string | null, project: boolean, skills: string[], vendor: string | null, yes: boolean}} options - Initial install options.
 * @param {{question: (query: string) => Promise<string>}} prompt - Interactive prompt.
 * @returns {Promise<typeof options>} Fully selected options.
 */
export async function completeInteractively(options, prompt) {
  const bundles = await loadBundles();
  const vendors = await loadVendors();
  const source = await choose(
    "Choose a first-party bundle or vendor catalog:",
    [
      ...Object.entries(bundles.groups).map(([id, bundle]) => ({
        id,
        kind: "bundle",
        label: `${bundle.name} — ${bundle.description}`,
      })),
      ...vendors.vendors.map((vendor) => ({
        id: vendor.id,
        kind: "vendor",
        label: `${vendor.repo} @ ${vendor.sha.slice(0, 12)}`,
      })),
    ],
    (item) => item.label,
    prompt,
  );

  if (source.kind === "bundle") {
    const bundle = bundles.groups[source.id];
    options.bundle = source.id;
    options.skills = bundle.skills;
  } else {
    const index = await loadVendorIndex(source.id);
    const skill = await choose(
      `Choose a skill from ${index.vendor.repo}:`,
      index.skills,
      (item) => item.name,
      prompt,
    );
    options.vendor = source.id;
    options.skills = [skill.name];
  }

  if (options.agents.length === 0) {
    const agents = await prompt.question(
      "Agent(s), comma-separated (blank lets skills CLI detect): ",
    );
    options.agents = agents
      .split(",")
      .map((agent) => agent.trim())
      .filter(Boolean);
  }
  if (!options.copy) {
    options.copy = (await prompt.question("Copy files instead of symlink? [y/N] "))
      .trim()
      .toLowerCase()
      .startsWith("y");
  }
  if (!options.onConflict) {
    options.onConflict = await choose(
      "When an installed skill conflicts:",
      ["keep", "overwrite", "skip"],
      (item) => item,
      prompt,
    );
  }
  return options;
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
    const packageVersion = process.env.npm_package_version ?? "0.0.0-dev";
    source = `lgtm-hq/ai-skills@v${packageVersion}`;
  }
  await run(buildSkillsArguments(selectedOptions, source));
  const scope = resolveScope(selectedOptions);
  const lock = await readLockfile(scope, lockEnvironment);
  await writeLockfile(
    mergeLockEntries(lock, await createLockEntries(selectedOptions, vendor, now)),
    lockEnvironment,
  );
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
          sha: `v${process.env.npm_package_version ?? "0.0.0-dev"}`,
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
  const prompt = createInterface({ input: stdin, output: stdout });
  try {
    await install(await completeInteractively(options, prompt));
  } finally {
    prompt.close();
  }
}
