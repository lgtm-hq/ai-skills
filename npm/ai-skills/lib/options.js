/**
 * Minimum supported version of the upstream skills CLI.
 *
 * Keeping this value in the wrapper makes every invocation reproducible within
 * a compatible major version while allowing upstream patches.
 */
export const MINIMUM_SKILLS_VERSION = "0.16.0";

/**
 * Parse wrapper command-line arguments.
 *
 * @param {string[]} argv - Arguments after the executable name.
 * @returns {{command: string, options: {agents: string[], bundle: string | null, copy: boolean, global: boolean, project: boolean, yes: boolean, onConflict: string | null, skills: string[], vendor: string | null}}} Parsed command and options.
 * @throws {Error} When an option is malformed or unsupported.
 */
export function parseArguments(argv) {
  const commands = new Set(["install", "vendors"]);
  const command = commands.has(argv[0]) ? argv[0] : "install";
  const args = commands.has(argv[0]) ? argv.slice(1) : argv;
  const options = {
    agents: [],
    bundle: null,
    copy: false,
    global: false,
    project: false,
    yes: false,
    onConflict: null,
    skills: [],
    vendor: null,
  };

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    const value = args[index + 1];
    if (argument === "--global" || argument === "-g") {
      options.global = true;
    } else if (argument === "--project") {
      options.project = true;
    } else if (argument === "--yes" || argument === "-y") {
      options.yes = true;
    } else if (argument === "--copy") {
      options.copy = true;
    } else if (argument === "--agent" || argument === "-a") {
      if (!value) {
        throw new Error(`${argument} requires an agent name`);
      }
      options.agents.push(value);
      index += 1;
    } else if (argument === "--bundle" || argument === "--vendor") {
      if (!value) {
        throw new Error(`${argument} requires a value`);
      }
      options[argument.slice(2)] = value;
      index += 1;
    } else if (argument === "--skill") {
      if (!value) {
        throw new Error("--skill requires a skill name");
      }
      options.skills.push(value);
      index += 1;
    } else if (argument === "--on-conflict") {
      if (!["keep", "overwrite", "skip"].includes(value)) {
        throw new Error("--on-conflict must be keep, overwrite, or skip");
      }
      options.onConflict = value;
      index += 1;
    } else {
      throw new Error(`Unknown option: ${argument}`);
    }
  }

  if (options.global && options.project) {
    throw new Error("Choose only one scope: --global or --project");
  }
  if (command === "vendors" && args.length > 0) {
    throw new Error("vendors does not accept options");
  }
  return { command, options };
}

/**
 * Validate options that are unsafe to infer non-interactively.
 *
 * @param {{agents: string[], global: boolean, project: boolean, yes: boolean, onConflict: string | null, skills: string[], vendor: string | null, bundle: string | null}} options - Parsed install options.
 * @returns {void}
 * @throws {Error} When unattended use leaves a product decision ambiguous.
 */
export function validateUnattendedOptions(options) {
  if (!options.yes) {
    return;
  }
  if (!options.global && !options.project) {
    throw new Error("-y requires an explicit --global or --project scope");
  }
  if (options.agents.length === 0) {
    throw new Error("-y requires at least one -a/--agent");
  }
  if (!options.vendor && !options.bundle) {
    throw new Error("-y requires --vendor or --bundle");
  }
  if (options.skills.length === 0 && !options.bundle) {
    throw new Error("-y requires at least one --skill for a vendor");
  }
  if (!options.onConflict) {
    throw new Error("-y requires --on-conflict=keep, overwrite, or skip");
  }
}
