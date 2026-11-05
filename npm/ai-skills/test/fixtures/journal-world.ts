import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  readlink,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { ExecResult } from "../../lib/adapters/shared/native-cli.ts";
import { removeSkills, updateSkills } from "../../lib/gateway-commands.ts";
import { install } from "../../lib/install.ts";
import type { JournalHooks } from "../../lib/journal/recover.ts";

/** A throwaway machine: home, project, catalog and a fake host CLI registry. */
export interface World {
  root: string;
  home: string;
  cwd: string;
  catalog: string;
  registry: string;
}

/** Skills of the first-party test plugin (not a real catalog bundle). */
export const WORLD_SKILLS = ["zeta-alpha", "zeta-beta"];

/** Plugin id `install` derives from `WORLD_SKILLS`. */
export const WORLD_PLUGIN = "zeta-alpha";

/** Hosts the multi-adapter install delivers to, one per lane. */
export const WORLD_AGENTS = ["claude-code", "codex", "cursor"];

/** Per-host delivery for the multi-adapter install (no probing). */
export const WORLD_CAPABILITIES: Record<string, "native" | "explode"> = {
  "claude-code": "native",
  codex: "explode",
  cursor: "native",
};

/**
 * Create a world with version `v1` of the catalog.
 */
export async function createWorld(): Promise<World> {
  // Canonical path, so the CLI's process.cwd() matches the recorded roots.
  const root = await realpath(await mkdtemp(join(tmpdir(), "ai-skills-journal-")));
  const world = {
    catalog: join(root, "catalog"),
    cwd: join(root, "project"),
    home: join(root, "home"),
    registry: join(root, "host-registry.json"),
    root,
  };
  await mkdir(world.cwd, { recursive: true });
  await mkdir(world.home, { recursive: true });
  await writeCatalog(world, "v1");
  await writeFile(world.registry, `${JSON.stringify({ marketplaces: [], plugins: [] })}\n`);
  return world;
}

/**
 * Write catalog content for a version: `v2` changes bytes, adds a nested
 * file and an executable script, and drops one file.
 */
export async function writeCatalog(world: World, version: "v1" | "v2"): Promise<void> {
  await rm(world.catalog, { force: true, recursive: true });
  await mkdir(join(world.catalog, ".claude-plugin"), { recursive: true });
  await writeFile(
    join(world.catalog, ".claude-plugin", "marketplace.json"),
    `${JSON.stringify({ name: "ai-skills", plugins: [] })}\n`,
  );
  for (const skill of WORLD_SKILLS) {
    const dir = join(world.catalog, "skills", skill);
    await mkdir(join(dir, "docs"), { recursive: true });
    await writeFile(join(dir, "SKILL.md"), `# ${skill} ${version}\n`);
    if (version === "v1") {
      await writeFile(join(dir, "docs", "old.md"), `old ${skill}\n`);
    } else {
      await writeFile(join(dir, "docs", "new.md"), `new ${skill}\n`);
      await writeFile(join(dir, "run.sh"), "#!/bin/sh\necho hi\n");
      await chmod(join(dir, "run.sh"), 0o755);
    }
  }
}

/**
 * Fake host CLI whose registry persists in a file, so a killed process's
 * registrations are visible to the next one.
 */
export function fakeHostExec(
  registryPath: string,
  calls: string[][] = [],
): (command: string, args: string[]) => Promise<ExecResult> {
  return async (command, args) => {
    calls.push([command, ...args]);
    const registry = JSON.parse(await readFile(registryPath, "utf8")) as {
      marketplaces: string[];
      plugins: string[];
    };
    const save = () => writeFile(registryPath, `${JSON.stringify(registry)}\n`);
    const [, action, target, extra] = args;
    if (args[0] === "plugin" && action === "marketplace" && target === "add") {
      const key = `${command}:${extra}`;
      if (registry.marketplaces.includes(key)) {
        return { status: 0, stderr: "", stdout: "Marketplace already exists" };
      }
      registry.marketplaces.push(key);
      await save();
      return { status: 0, stderr: "", stdout: "added" };
    }
    if (args[0] === "plugin" && action === "install") {
      const key = `${command}:${target}`;
      if (registry.plugins.includes(key)) {
        return { status: 0, stderr: "", stdout: "Plugin already installed" };
      }
      registry.plugins.push(key);
      await save();
      return { status: 0, stderr: "", stdout: "installed" };
    }
    if (args[0] === "plugin" && action === "uninstall") {
      const key = `${command}:${target}`;
      if (!registry.plugins.includes(key)) {
        return { status: 1, stderr: "Plugin not found", stdout: "" };
      }
      registry.plugins = registry.plugins.filter((item) => item !== key);
      await save();
      return { status: 0, stderr: "", stdout: "uninstalled" };
    }
    return { status: 1, stderr: `unexpected ${command} ${args.join(" ")}`, stdout: "" };
  };
}

/** Registered plugins in the fake host registry. */
export async function hostPlugins(world: World): Promise<string[]> {
  return (JSON.parse(await readFile(world.registry, "utf8")) as { plugins: string[] }).plugins;
}

/**
 * Every file, directory and symlink under `root` with content, mode or target,
 * keyed by relative path. Missing roots snapshot as empty.
 */
export async function snapshotTree(root: string, prefix = ""): Promise<Record<string, string>> {
  const tree: Record<string, string> = {};
  let entries;
  try {
    entries = await readdir(join(root, prefix), { withFileTypes: true });
  } catch {
    return tree;
  }
  for (const entry of entries.sort((left, right) => (left.name < right.name ? -1 : 1))) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolute = join(root, relative);
    if (entry.isSymbolicLink()) {
      tree[relative] = `-> ${await readlink(absolute)}`;
    } else if (entry.isDirectory()) {
      tree[relative] = "<dir>";
      Object.assign(tree, await snapshotTree(root, relative));
    } else {
      const mode = (await lstat(absolute)).mode & 0o777;
      tree[relative] = `${mode.toString(8)} ${await readFile(absolute, "utf8")}`;
    }
  }
  return tree;
}

/** Install-visible paths of a world (state, journal and the fake registry excluded). */
export async function deliveredTree(world: World): Promise<Record<string, string>> {
  const tree: Record<string, string> = {};
  for (const [label, root] of [
    ["home", world.home],
    ["project", world.cwd],
  ] as const) {
    for (const [path, value] of Object.entries(await snapshotTree(root))) {
      if (
        path === ".ai-skills" ||
        path === ".ai-skills/state" ||
        path.startsWith(".ai-skills/state/")
      ) {
        continue;
      }
      tree[`${label}/${path}`] = value;
    }
  }
  return tree;
}

/** Paths left by an interrupted op or the old staging/backup engines. */
export function orphanPaths(tree: Record<string, string>): string[] {
  return Object.keys(tree).filter((path) =>
    /\.aiskills-[^/]*\.(tmp|rm)$|\.staging|\.bak(\.|$)|\.tmp\.[0-9a-f-]{36}$/.test(path),
  );
}

/**
 * Run `install`, `update` or `remove` for the world's plugin (project scope,
 * one lane per adapter, fake host CLI).
 */
export async function runWorldCommand(
  world: World,
  command: "install" | "remove" | "update",
  options: {
    journal?: JournalHooks;
    keepGenerations?: number;
    warn?: (message: string) => void;
    calls?: string[][];
  } = {},
): Promise<void> {
  const environment = { cwd: world.cwd, home: world.home };
  const exec = fakeHostExec(world.registry, options.calls);
  const sourceSkills = Object.fromEntries(
    WORLD_SKILLS.map((skill) => [skill, join(world.catalog, "skills", skill)]),
  );
  const warn = options.warn ?? (() => {});
  const keepGenerations = options.keepGenerations ?? null;
  if (command === "install") {
    await install(
      {
        agents: WORLD_AGENTS,
        bundle: null,
        copy: false,
        global: false,
        keepGenerations,
        onConflict: null,
        project: true,
        skills: WORLD_SKILLS,
        vendor: null,
        yes: true,
      },
      async () => {
        throw new Error("skills CLI must not run");
      },
      () => new Date("2026-11-05T00:00:00.000Z"),
      environment,
      {
        exec,
        hostCapabilities: WORLD_CAPABILITIES,
        ...(options.journal ? { journal: options.journal } : {}),
        sourceRoot: world.catalog,
        sourceSkills,
        warn,
      },
    );
    return;
  }
  const scope = {
    agents: [],
    global: false,
    keepGenerations,
    project: true,
    skills: [],
    yes: true,
  };
  if (command === "update") {
    await updateSkills(scope, {
      exec,
      ...(options.journal ? { journal: options.journal } : {}),
      lockEnvironment: environment,
      now: () => new Date("2026-11-05T01:00:00.000Z"),
      sourceRoot: world.catalog,
      sourceSkills,
      warn,
    });
    return;
  }
  await removeSkills(scope, {
    exec,
    ...(options.journal ? { journal: options.journal } : {}),
    lockEnvironment: environment,
    warn,
  });
}
