import { describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { readdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { PACKAGE_ROOT } from "../lib/paths.ts";
import { STATE_DIR_ENV, stateRoot } from "../lib/journal/receipts.ts";

import { parseArguments } from "../lib/options.ts";
import { readReceipt, scopeStateDir } from "../lib/journal/receipts.ts";
import { rollbackGeneration } from "../lib/journal/rollback.ts";
import {
  createWorld,
  deliveredTree,
  fakeHostExec,
  hostPlugins,
  runWorldCommand,
  WORLD_PLUGIN,
  writeCatalog,
} from "./fixtures/journal-world.ts";
import type { World } from "./fixtures/journal-world.ts";

const HOST_PLUGIN = `claude:${WORLD_PLUGIN}@ai-skills`;

async function withWorld(run: (world: World) => Promise<void>): Promise<void> {
  const world = await createWorld();
  try {
    await run(world);
  } finally {
    await rm(world.root, { force: true, recursive: true });
  }
}

const environment = (world: World) => ({ cwd: world.cwd, home: world.home });

const rollback = (world: World, options: { dryRun?: boolean; keepGenerations?: number } = {}) =>
  rollbackGeneration({
    env: environment(world),
    exec: fakeHostExec(world.registry),
    report: () => {},
    scope: "project",
    ...options,
  });

/** Make the installed plugin an older release and publish catalog v2. */
async function ageAndPublishV2(world: World): Promise<void> {
  const { dir } = await scopeStateDir("project", environment(world));
  const path = join(dir, "receipt.json");
  const receipt = JSON.parse(await readFile(path, "utf8"));
  receipt.plugins[WORLD_PLUGIN].version = "0.0.0-old";
  receipt.plugins[WORLD_PLUGIN].sha = "v0.0.0-old";
  await writeFile(path, `${JSON.stringify(receipt, null, 2)}\n`);
  await writeCatalog(world, "v2");
}

/** Install v1, then update to v2 (the update is the generation to undo). */
async function installThenUpdate(world: World, keepGenerations?: number): Promise<void> {
  await runWorldCommand(world, "install", { keepGenerations });
  await ageAndPublishV2(world);
  await runWorldCommand(world, "update", { keepGenerations });
}

describe("rollback", () => {
  test("restores the previous generation byte for byte", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install");
      const v1 = await deliveredTree(world);
      const { dir } = await scopeStateDir("project", environment(world));
      await ageAndPublishV2(world);
      const aged = (await readReceipt("project", environment(world)))!.plugins;
      await runWorldCommand(world, "update");
      const v2 = await deliveredTree(world);
      expect(v2).not.toEqual(v1);
      expect(v2["project/.agents/skills/zeta-alpha/run.sh"]).toStartWith("755 ");

      const result = await rollback(world);

      expect(result).toMatchObject({ from: 2, kept: [], remaining: [], to: 1 });
      expect(await deliveredTree(world)).toEqual(v1);
      const restored = await readReceipt("project", environment(world));
      expect(restored?.generation).toBe(1);
      expect(restored?.plugins).toEqual(aged);
      expect(await hostPlugins(world)).toEqual([HOST_PLUGIN]);
      expect(await readdir(join(dir, "generations"))).toEqual([]);
    });
  });

  test("keeps and reports files edited locally since the update", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install");
      const v1 = await deliveredTree(world);
      await ageAndPublishV2(world);
      await runWorldCommand(world, "update");
      const edited = join(world.cwd, ".agents/skills/zeta-beta/SKILL.md");
      const added = join(world.cwd, ".agents/skills/zeta-beta/run.sh");
      await writeFile(edited, "# my local notes\n");
      await writeFile(added, "#!/bin/sh\necho mine\n");

      const result = await rollback(world);

      expect(result.kept).toEqual([
        `${added} (edited locally since generation 2)`,
        `${edited} (edited locally since generation 2)`,
      ]);
      const restored = await deliveredTree(world);
      expect(restored["project/.agents/skills/zeta-beta/SKILL.md"]).toBe("644 # my local notes\n");
      expect(restored["project/.agents/skills/zeta-beta/run.sh"]).toBe(
        "755 #!/bin/sh\necho mine\n",
      );
      // Everything else is the previous generation.
      const untouched = (tree: Record<string, string>) =>
        Object.fromEntries(
          Object.entries(tree).filter(
            ([path]) => !path.startsWith("project/.agents/skills/zeta-beta"),
          ),
        );
      expect(untouched(restored)).toEqual(untouched(v1));
      expect((await readReceipt("project", environment(world)))?.generation).toBe(1);
    });
  });

  test("dry run prints the compensating plan and changes nothing", async () => {
    await withWorld(async (world) => {
      await installThenUpdate(world);
      const before = await deliveredTree(world);
      const receipt = await readReceipt("project", environment(world));

      const result = await rollback(world, { dryRun: true });

      const lines = result.text.split("\n");
      expect(lines[0]).toBe("rollback\tproject\tgeneration 2 -> 1");
      expect(lines).toContain(
        "op\tremove-owned\t./.agents/skills/zeta-alpha/run.sh\texpect:" +
          receipt!.paths[join(world.cwd, ".agents/skills/zeta-alpha/run.sh")]!.hash,
      );
      expect(
        lines.some((line) =>
          line.startsWith("op\twrite-file\t./.agents/skills/zeta-alpha/SKILL.md"),
        ),
      ).toBe(true);
      expect(await deliveredTree(world)).toEqual(before);
      expect(await readReceipt("project", environment(world))).toEqual(receipt);
    });
  });

  test("keeps one previous generation by default and more on request", async () => {
    await withWorld(async (world) => {
      await installThenUpdate(world);
      await rollback(world);
      await expect(rollback(world)).rejects.toThrow(
        "Cannot roll back generation 1: its preimages are no longer kept",
      );
    });
    await withWorld(async (world) => {
      const initial = await deliveredTree(world);
      await installThenUpdate(world, 2);
      await rollback(world, { keepGenerations: 2 });
      await rollback(world, { keepGenerations: 2 });
      expect(await deliveredTree(world)).toEqual(initial);
      // Generation 1 created the host registration, so undoing it unregisters it.
      expect(await hostPlugins(world)).toEqual([]);
      expect((await readReceipt("project", environment(world)))?.generation).toBe(0);
      await expect(rollback(world)).rejects.toThrow("Nothing to roll back");
    });
  });

  test("never uninstalls a host plugin the receipt did not create", async () => {
    await withWorld(async (world) => {
      await writeFile(
        world.registry,
        `${JSON.stringify({ marketplaces: [], plugins: [HOST_PLUGIN] })}\n`,
      );
      await runWorldCommand(world, "install");
      const receipt = await readReceipt("project", environment(world));
      expect(receipt?.registrations.map((item) => item.argv[2])).toEqual(["marketplace"]);
      const result = await rollback(world);
      expect(result.ops.some((item) => item.op.kind === "host-exec")).toBe(false);
      expect(await hostPlugins(world)).toEqual([HOST_PLUGIN]);
      expect(result.remaining).toEqual([expect.stringContaining("plugin marketplace add")]);
    });
  });

  test("compensation after a failure leaves a pre-existing host plugin alone", async () => {
    await withWorld(async (world) => {
      await writeFile(
        world.registry,
        `${JSON.stringify({ marketplaces: [], plugins: [HOST_PLUGIN] })}\n`,
      );
      const calls: string[][] = [];
      await expect(
        runWorldCommand(world, "install", { calls, journal: { failBeforeCommit: true } }),
      ).rejects.toThrow("injected failure before commit");
      expect(calls.some((call) => call.includes("uninstall"))).toBe(false);
      expect(await hostPlugins(world)).toEqual([HOST_PLUGIN]);
    });
    await withWorld(async (world) => {
      const calls: string[][] = [];
      await expect(
        runWorldCommand(world, "install", { calls, journal: { failBeforeCommit: true } }),
      ).rejects.toThrow("still in effect after rollback");
      // The plugin this transaction installed is uninstalled; nothing else is.
      expect(calls.filter((call) => call.includes("uninstall"))).toEqual([
        ["claude", "plugin", "uninstall", `${WORLD_PLUGIN}@ai-skills`],
      ]);
      expect(await hostPlugins(world)).toEqual([]);
      expect(await deliveredTree(world)).toEqual({});
    });
  });

  test("rolling back a remove puts the removed plugin back", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install");
      const installed = await deliveredTree(world);
      await runWorldCommand(world, "remove");
      expect(await hostPlugins(world)).toEqual([]);
      await rollback(world);
      const restored = await deliveredTree(world);
      expect(restored).toEqual(installed);
      expect(await hostPlugins(world)).toEqual([HOST_PLUGIN]);
      expect(Object.keys((await readReceipt("project", environment(world)))!.plugins)).toEqual([
        WORLD_PLUGIN,
      ]);
    });
  });
});

describe("sk rollback", () => {
  /** Run the CLI in the world's project with its state root. */
  const sk = (world: World, args: string[]) =>
    spawnSync(process.execPath, [join(PACKAGE_ROOT, "test/fixtures/run-cli.ts"), ...args], {
      cwd: world.cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        AI_SKILLS_NO_UPDATE_CHECK: "1",
        // Keep the runtime's transpiler cache out of the fixture home.
        BUN_RUNTIME_TRANSPILER_CACHE_PATH: "0",
        HOME: world.home,
        [STATE_DIR_ENV]: stateRoot(environment(world)),
      },
    });

  test("prints the plan with --dry-run, then restores the previous generation", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install");
      const v1 = await deliveredTree(world);
      await ageAndPublishV2(world);
      const { dir } = await scopeStateDir("project", environment(world));
      await runWorldCommand(world, "update");

      const dry = sk(world, ["rollback", "--project", "--dry-run"]);
      expect(dry.stderr).toBe("");
      expect(dry.status).toBe(0);
      expect(dry.stdout).toStartWith("rollback\tproject\tgeneration 2 -> 1\n");
      expect(dry.stdout).toContain("op\twrite-file\t./.agents/skills/zeta-alpha/SKILL.md\t");
      expect((await readReceipt("project", environment(world)))?.generation).toBe(2);

      const applied = sk(world, ["rollback", "--project", "-y"]);
      expect(applied.stderr).toBe("");
      expect(applied.status).toBe(0);
      expect(applied.stdout).toEndWith("rolled back\tgeneration 2 -> 1\n");
      expect(await deliveredTree(world)).toEqual(v1);
      expect(await readdir(join(dir, "generations"))).toEqual([]);

      const again = sk(world, ["rollback", "--project"]);
      expect(again.status).toBe(1);
      expect(again.stderr).toContain("its preimages are no longer kept");
    });
  });
});

describe("rollback arguments", () => {
  test("parses scope, dry run and generation retention", () => {
    const parsed = parseArguments([
      "rollback",
      "--project",
      "--dry-run",
      "--keep-generations",
      "2",
    ]);
    expect(parsed.command).toBe("rollback");
    expect(parsed.options).toMatchObject({
      dryRun: true,
      engine: [],
      keepGenerations: 2,
      project: true,
    });
    expect(parseArguments(["install", "--dry-run"]).options).toMatchObject({
      dryRun: false,
      engine: ["--dry-run"],
    });
    expect(parseArguments(["update", "--keep-generations", "0"]).options.keepGenerations).toBe(0);
  });

  test("rejects options rollback cannot honor", () => {
    expect(() => parseArguments(["rollback", "-a", "codex"])).toThrow(
      "rollback restores a whole scope",
    );
    expect(() => parseArguments(["rollback", "--skill", "lint"])).toThrow(
      "rollback restores a whole scope",
    );
    expect(() => parseArguments(["rollback", "--bundle", "review"])).toThrow(
      "rollback does not accept install source options",
    );
    expect(() => parseArguments(["list", "--keep-generations", "1"])).toThrow(
      "--keep-generations applies only to install, update, remove and rollback",
    );
    expect(() => parseArguments(["update", "--keep-generations", "-1"])).toThrow(
      "--keep-generations requires a non-negative integer",
    );
    expect(() => parseArguments(["rollback", "--frozen"])).toThrow("--frozen applies only to");
  });
});
