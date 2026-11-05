import { describe, expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { runDoctor } from "../lib/doctor.ts";
import { recoverState } from "../lib/journal/recover.ts";
import { readReceipt, scopeStateDir, stateRoot } from "../lib/journal/receipts.ts";
import { PACKAGE_ROOT } from "../lib/paths.ts";
import {
  createWorld,
  deliveredTree,
  fakeHostExec,
  hostPlugins,
  orphanPaths,
  WORLD_PLUGIN,
  writeCatalog,
} from "./fixtures/journal-world.ts";
import type { World } from "./fixtures/journal-world.ts";

const CHILD = join(PACKAGE_ROOT, "test/fixtures/journal-child.ts");
const HOST_PLUGIN = `claude:${WORLD_PLUGIN}@ai-skills`;

/** Run one gateway command in a child; `crashAt` SIGKILLs it after or inside that op. */
function runChild(
  world: World,
  command: string,
  crashAt?: number,
  phase: "after" | "during" = "after",
): Promise<{ code: number | null; signal: NodeJS.Signals | null; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      [
        CHILD,
        JSON.stringify(world),
        command,
        ...(crashAt === undefined ? [] : [String(crashAt), phase]),
      ],
      {
        env: { ...process.env, AI_SKILLS_NO_UPDATE_CHECK: "1" },
        stdio: ["ignore", "ignore", "pipe"],
      },
    );
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code, signal) => resolve({ code, signal, stderr }));
  });
}

async function withWorld<T>(run: (world: World) => Promise<T>): Promise<T> {
  const world = await createWorld();
  try {
    return await run(world);
  } finally {
    await rm(world.root, { force: true, recursive: true });
  }
}

const environment = (world: World) => ({ cwd: world.cwd, home: world.home });

/** Ops the committed generation applied, read from its archived journal. */
async function committedOpCount(world: World): Promise<number> {
  const receipt = await readReceipt("project", environment(world));
  const { dir } = await scopeStateDir("project", environment(world));
  const intent = JSON.parse(
    await readFile(join(dir, "generations", String(receipt!.generation), "intent.json"), "utf8"),
  );
  return intent.ops.length;
}

/** Make the installed plugin look like an older release so update refreshes it. */
async function ageInstalledPlugin(world: World): Promise<void> {
  const { dir } = await scopeStateDir("project", environment(world));
  const path = join(dir, "receipt.json");
  const receipt = JSON.parse(await readFile(path, "utf8"));
  receipt.plugins[WORLD_PLUGIN].version = "0.0.0-old";
  receipt.plugins[WORLD_PLUGIN].sha = "v0.0.0-old";
  await writeFile(path, `${JSON.stringify(receipt, null, 2)}\n`);
}

/** Converged state after the next command's recovery. */
async function observe(world: World) {
  const receipt = await readReceipt("project", environment(world));
  const observed = {
    generation: receipt?.generation ?? 0,
    hostPlugins: await hostPlugins(world),
    journal: await readdir(join(stateRoot(environment(world)), "journal")).catch(() => []),
    plugin: receipt?.plugins[WORLD_PLUGIN]
      ? { ...receipt.plugins[WORLD_PLUGIN], installedAt: "" }
      : null,
    tree: await deliveredTree(world),
  };
  // Worlds differ only by their temporary root.
  return JSON.parse(JSON.stringify(observed).replaceAll(world.root, "<root>")) as typeof observed;
}

/** Run a crash at every op index in parallel batches. */
async function forEachIndex(count: number, run: (index: number) => Promise<void>): Promise<void> {
  const width = 6;
  for (let start = 0; start < count; start += width) {
    const batch = [];
    for (let index = start; index < Math.min(count, start + width); index += 1) {
      batch.push(run(index));
    }
    await Promise.all(batch);
  }
}

describe("crash injection", () => {
  for (const phase of ["after", "during"] as const) {
    const when = phase === "after" ? "after" : "in the middle of";

    test(`an install killed ${when} every op converges on the next command`, async () => {
      const reference = await withWorld(async (world) => {
        const before = await observe(world);
        const result = await runChild(world, "install");
        expect(result.stderr).toBe("");
        expect(result.code).toBe(0);
        return { after: await observe(world), before, ops: await committedOpCount(world) };
      });
      expect(reference.ops).toBeGreaterThan(20);
      expect(reference.after.hostPlugins).toEqual([HOST_PLUGIN]);
      await forEachIndex(reference.ops, (index) =>
        withWorld(async (world) => {
          const crashed = await runChild(world, "install", index, phase);
          expect(crashed.signal).toBe("SIGKILL");
          const lines = await recoverState(environment(world), {
            exec: fakeHostExec(world.registry),
          });
          expect(lines.some((line) => line.includes("rolled-forward"))).toBe(true);
          const state = await observe(world);
          expect(orphanPaths(state.tree)).toEqual([]);
          expect(state.journal).toEqual([]);
          expect(state).toEqual(state.generation === 0 ? reference.before : reference.after);
        }),
      );
    }, 180_000);

    test(`an update killed ${when} every op converges on the next command`, async () => {
      const prepare = async (world: World) => {
        expect((await runChild(world, "install")).code).toBe(0);
        await ageInstalledPlugin(world);
        await writeCatalog(world, "v2");
      };
      const reference = await withWorld(async (world) => {
        await prepare(world);
        const before = await observe(world);
        const result = await runChild(world, "update");
        expect(result.stderr).toBe("");
        expect(result.code).toBe(0);
        return { after: await observe(world), before, ops: await committedOpCount(world) };
      });
      expect(reference.after.generation).toBe(2);
      expect(reference.after.tree).not.toEqual(reference.before.tree);
      await forEachIndex(reference.ops, (index) =>
        withWorld(async (world) => {
          await prepare(world);
          const crashed = await runChild(world, "update", index, phase);
          expect(crashed.signal).toBe("SIGKILL");
          await recoverState(environment(world), { exec: fakeHostExec(world.registry) });
          const state = await observe(world);
          expect(orphanPaths(state.tree)).toEqual([]);
          expect(state.journal).toEqual([]);
          expect(state).toEqual(state.generation === 1 ? reference.before : reference.after);
          expect(state.hostPlugins).toEqual([HOST_PLUGIN]);
        }),
      );
    }, 240_000);
  }

  test("doctor --repair finishes an interrupted install and reports it", async () => {
    await withWorld(async (world) => {
      const reference = await withWorld(async (clean) => {
        await runChild(clean, "install");
        return observe(clean);
      });
      const crashed = await runChild(world, "install", 5);
      expect(crashed.signal).toBe("SIGKILL");
      const lines: string[] = [];
      await runDoctor(
        { agents: ["codex"], global: false, migrate: null, project: true, repair: true, yes: true },
        {
          exec: fakeHostExec(world.registry),
          home: world.home,
          lockEnvironment: environment(world),
          log: (line) => lines.push(line),
          warn: () => {},
        },
      );
      expect(lines).toContainEqual(
        expect.stringMatching(/^recovery\t\S+\trolled-forward\tinstall generation 1$/),
      );
      expect(lines).toContain(`plugin\t${WORLD_PLUGIN}\tcodex\texplode\t`);
      const state = await observe(world);
      expect(state.journal).toEqual([]);
      // Doctor also records its host probe cache; everything else matches.
      const { "home/.ai-skills/doctor.json": cache, ...tree } = state.tree;
      expect(cache).toContain('"codex"');
      expect({ ...state, tree }).toEqual(reference);
    });
  }, 30_000);

  test("a crash whose remaining preconditions changed compensates to the old generation", async () => {
    await withWorld(async (world) => {
      const before = await observe(world);
      const crashed = await runChild(world, "install", 3);
      expect(crashed.signal).toBe("SIGKILL");
      // A user file appears where the interrupted install was about to write.
      const journalRoot = join(stateRoot(environment(world)), "journal");
      const [pendingTxn] = await readdir(journalRoot);
      const intent = JSON.parse(
        await readFile(join(journalRoot, pendingTxn!, "intent.json"), "utf8"),
      );
      const candidates = intent.ops
        .slice(4)
        .filter(
          (item: { op: { kind: string }; expect?: string | null }) =>
            item.op.kind === "write-file" && item.expect === null,
        )
        .map((item: { op: { path: string } }) => item.op.path) as string[];
      const pending = candidates[0];
      expect(pending).toBeDefined();
      await mkdir(dirname(pending!), { recursive: true });
      await writeFile(pending!, "user content\n");
      const lines = await recoverState(environment(world), { exec: fakeHostExec(world.registry) });
      expect(lines.some((line) => line.includes("cannot-roll-forward"))).toBe(true);
      expect(lines.some((line) => line.includes("compensated"))).toBe(true);
      const state = await observe(world);
      expect(state.generation).toBe(0);
      expect(state.hostPlugins).toEqual([]);
      expect(state.journal).toEqual([]);
      expect(orphanPaths(state.tree)).toEqual([]);
      const userKey = labelled(world, pending!);
      expect(state.tree[userKey]).toBe("644 user content\n");
      // Only the user's file and the directories holding it remain.
      for (const path of Object.keys(state.tree).filter((key) => !(key in before.tree))) {
        expect({ path, kept: userKey === path || userKey.startsWith(`${path}/`) }).toEqual({
          path,
          kept: true,
        });
      }
    });
  }, 30_000);
});

function labelled(world: World, path: string): string {
  return path.startsWith(world.home)
    ? `home${path.slice(world.home.length)}`
    : `project${path.slice(world.cwd.length)}`;
}
