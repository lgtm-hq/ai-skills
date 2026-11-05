import { isKnownHost } from "./adapters/hosts.ts";
import { PROJECTOR_EXPLODE, PROJECTOR_NATIVE } from "./lockfile.ts";

/**
 * Minimum supported version of the upstream skills CLI (npm package `skills`).
 *
 * Pin a real published 1.x floor so `bunx skills@^…` resolves. Upstream is on
 * the 1.x line (there is no 0.16.0). Caret allows compatible 1.x patches.
 */
export const MINIMUM_SKILLS_VERSION = "1.5.0";

/**
 * Artifact-consumption options evaluated only by the bundled Python engine.
 *
 * The launcher checks arity and command placement, then forwards them
 * verbatim; verification, filtering, denies and the profile live in
 * `src/ai_skills_engine/install/` (ADR 0008).
 */
const ENGINE_VALUE_OPTIONS = new Set(["--exclude", "--deny-origin", "--digest", "--artifacts"]);
const ENGINE_FLAG_OPTIONS = new Set(["--frozen", "--dry-run", "--json"]);
const ENGINE_INSTALL_ONLY = new Set(["--exclude", "--deny-origin"]);

/**
 * Parse wrapper command-line arguments.
 *
 * @throws {Error} When an option is malformed or unsupported.
 */
export function parseArguments(argv: string[]): {
  command: string;
  options: {
    engine: string[];
    agents: string[];
    bundle: string | null;
    copy: boolean;
    global: boolean;
    migrate: string | null;
    project: boolean;
    projector: "native" | "explode" | null;
    repair: boolean;
    yes: boolean;
    onConflict: string | null;
    skills: string[];
    unmanaged: boolean;
    vendor: string | null;
  };
} {
  const commands = new Set(["adopt", "doctor", "install", "list", "remove", "update", "vendors"]);
  const command = commands.has(argv[0]!) ? argv[0]! : "install";
  const args = commands.has(argv[0]!) ? argv.slice(1) : argv;
  const options: ReturnType<typeof parseArguments>["options"] = {
    agents: [],
    bundle: null,
    copy: false,
    engine: [],
    global: false,
    migrate: null,
    project: false,
    projector: null,
    repair: false,
    yes: false,
    onConflict: null,
    skills: [],
    unmanaged: false,
    vendor: null,
  };

  // Engine option names only; `options.engine` also holds their values.
  const engineNames: string[] = [];
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
    } else if (argument === "--unmanaged") {
      options.unmanaged = true;
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
      options[argument === "--bundle" ? "bundle" : "vendor"] = value;
      index += 1;
    } else if (argument === "--skill") {
      if (!value) {
        throw new Error("--skill requires a plugin id");
      }
      options.skills.push(value);
      index += 1;
    } else if (argument === "--projector") {
      if (value !== PROJECTOR_NATIVE && value !== PROJECTOR_EXPLODE) {
        throw new Error("--projector must be native or explode");
      }
      options.projector = value;
      index += 1;
    } else if (argument === "--on-conflict") {
      if (!["keep", "overwrite", "skip"].includes(value!)) {
        throw new Error("--on-conflict must be keep, overwrite, or skip");
      }
      options.onConflict = value!;
      index += 1;
    } else if (ENGINE_VALUE_OPTIONS.has(argument!)) {
      if (value === undefined || value === "") {
        throw new Error(`${argument} requires a value`);
      }
      options.engine.push(argument!, value);
      engineNames.push(argument!);
      index += 1;
    } else if (ENGINE_FLAG_OPTIONS.has(argument!)) {
      options.engine.push(argument!);
      engineNames.push(argument!);
    } else if (argument === "--repair") {
      options.repair = true;
    } else if (argument === "--migrate") {
      if (!value) {
        throw new Error("--migrate requires an agent name");
      }
      options.migrate = value;
      index += 1;
    } else {
      throw new Error(`Unknown option: ${argument}`);
    }
  }

  const unknownAgent = options.agents.find((agent) => !isKnownHost(agent));
  if (unknownAgent) {
    throw new Error(`Unknown agent: ${unknownAgent}`);
  }
  if (options.global && options.project) {
    throw new Error("Choose only one scope: --global or --project");
  }
  if (options.vendor && options.bundle) {
    throw new Error("Choose only one source: --vendor or --bundle");
  }
  // Judge placement on option names, never on values that look like options.
  const engineOption = engineNames[0];
  if (engineOption && command !== "install" && command !== "update") {
    throw new Error(`${engineOption} applies only to install and update`);
  }
  const installOnly = engineNames.find((name) => ENGINE_INSTALL_ONLY.has(name));
  if (installOnly && command !== "install") {
    throw new Error(`${installOnly} applies only to install; update replays the profile`);
  }
  if (options.unmanaged && command !== "install") {
    throw new Error("--unmanaged applies only to install");
  }
  if (options.unmanaged && options.engine.length > 0) {
    throw new Error(
      "--unmanaged hands off to the skills CLI; it cannot combine with engine options",
    );
  }
  if (command === "vendors" && args.length > 0) {
    throw new Error("vendors does not accept options");
  }
  if (options.vendor && options.projector === PROJECTOR_NATIVE) {
    throw new Error(
      "--projector native is first-party only; omit --vendor or use --projector explode",
    );
  }
  if (
    ["adopt", "doctor", "list", "remove", "update"].includes(command) &&
    (options.bundle || options.copy || options.onConflict || options.vendor || options.projector)
  ) {
    throw new Error(`${command} does not accept install source options`);
  }
  if (command === "adopt" && options.skills.length > 0) {
    throw new Error("adopt does not accept --skill; it imports installed skills");
  }
  if (command !== "doctor" && (options.repair || options.migrate)) {
    throw new Error("--repair and --migrate are doctor-only");
  }
  if (command === "doctor" && options.skills.length > 0) {
    throw new Error("doctor does not accept --skill");
  }
  if (options.migrate && !isKnownHost(options.migrate)) {
    throw new Error(`Unknown agent: ${options.migrate}`);
  }
  return { command, options };
}

/**
 * Validate options that are unsafe to infer non-interactively.
 *
 * @throws {Error} When unattended use leaves a product decision ambiguous.
 */
export function validateUnattendedOptions(options: {
  agents: string[];
  unmanaged?: boolean;
  global: boolean;
  project: boolean;
  yes: boolean;
  onConflict: string | null;
  skills: string[];
  vendor: string | null;
  bundle: string | null;
}): void {
  if (!options.yes) {
    return;
  }
  if (!options.global && !options.project) {
    throw new Error("-y requires an explicit --global or --project scope");
  }
  if (options.agents.length === 0 && !options.unmanaged) {
    throw new Error("-y requires at least one -a/--agent");
  }
  if (options.vendor && (options.bundle || options.skills.length > 0)) {
    throw new Error("Vendor installs are plugin-atomic; omit --skill and --bundle");
  }
  if (!options.vendor && !options.bundle && options.skills.length === 0) {
    throw new Error("-y requires --skill (plugin id), --bundle, or --vendor");
  }
  if (options.bundle && options.skills.length > 0) {
    throw new Error("Choose plugins via --skill or --bundle, not both");
  }
  // Upstream `skills` has no conflict policy. Accept omitted/`overwrite` only so
  // keep|skip cannot silently no-op under a fail-closed API.
  if (options.onConflict && options.onConflict !== "overwrite") {
    throw new Error(
      `--on-conflict=${options.onConflict} is unsupported: upstream skills CLI has no conflict policy. Omit the flag, use overwrite, or remove the existing skill first.`,
    );
  }
}

/**
 * Resolve the installation scope, defaulting to global.
 */
export function resolveScope(options: { global: boolean; project: boolean }): "global" | "project" {
  return options.project ? "project" : "global";
}

/**
 * Validate unattended scope (and optionally agent) selections for maintenance commands.
 *
 * @throws {Error} When unattended maintenance would infer a scope or agent.
 */
export function validateUnattendedCommandOptions(
  options: { agents: string[]; global: boolean; project: boolean; yes: boolean },
  rules: { requireAgents?: boolean } = {},
): void {
  if (!options.yes) {
    return;
  }
  if (!options.global && !options.project) {
    throw new Error("-y requires an explicit --global or --project scope");
  }
  if (rules.requireAgents !== false && options.agents.length === 0) {
    throw new Error("-y requires at least one -a/--agent");
  }
}
