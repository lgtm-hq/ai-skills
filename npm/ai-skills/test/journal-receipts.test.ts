import { describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { listSkills } from "../lib/gateway-commands.ts";
import { JOURNAL_VERSION } from "../lib/journal/journal.ts";
import {
  readInstallState,
  readReceipt,
  receiptPath,
  RECEIPT_VERSION,
  scopeStateDir,
  stateRoot,
} from "../lib/journal/receipts.ts";
import { recoverState } from "../lib/journal/recover.ts";
import {
  createWorld,
  deliveredTree,
  runWorldCommand,
  WORLD_PLUGIN,
} from "./fixtures/journal-world.ts";
import type { World } from "./fixtures/journal-world.ts";

async function withWorld(run: (world: World) => Promise<void>): Promise<void> {
  const world = await createWorld();
  try {
    await run(world);
  } finally {
    await rm(world.root, { force: true, recursive: true });
  }
}

const environment = (world: World) => ({ cwd: world.cwd, home: world.home });

/** A lock v2 file as earlier gateways wrote it into the repository. */
function legacyLock(world: World): string {
  return `${JSON.stringify(
    {
      gatewayVersion: "0.9.0",
      plugins: {
        "legacy-one": {
          agents: {
            codex: {
              files: { "legacy-one/SKILL.md": "abc" },
              projector: "explode",
              root: join(world.cwd, ".codex/skills"),
            },
          },
          installedAt: "2026-01-01T00:00:00.000Z",
          projector: "explode",
          repo: "lgtm-hq/ai-skills",
          sha: "v0.9.0",
          skills: ["legacy-one"],
          vendor: "lgtm-hq",
          version: "0.9.0",
        },
      },
      scope: "project",
      version: 2,
    },
    null,
    2,
  )}\n`;
}

describe("install receipts", () => {
  test("project receipts live outside the repository, keyed by its real path", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install");
      const key = createHash("sha256")
        .update(await realpath(world.cwd))
        .digest("hex");
      const expected = join(stateRoot(environment(world)), "projects", key, "receipt.json");
      expect(await receiptPath("project", environment(world))).toBe(expected);
      const receipt = JSON.parse(await readFile(expected, "utf8"));
      expect(receipt).toMatchObject({
        artifactDigest: null,
        generation: 1,
        root: await realpath(world.cwd),
        scope: "project",
        version: RECEIPT_VERSION,
      });
      expect(Object.keys(receipt.fingerprints.adapters).sort()).toEqual([
        "claude-cli",
        "cursor-drop",
        "skill-explode",
      ]);
      expect(receipt.fingerprints.policy).toBeNull();
      const skill = join(world.cwd, ".agents/skills/zeta-alpha/SKILL.md");
      expect(receipt.paths[skill]).toEqual({
        hash: createHash("sha256").update("# zeta-alpha v1\n").digest("hex"),
        owner: WORLD_PLUGIN,
        previousHash: null,
      });
      expect(receipt.registrations.map((item: { argv: string[] }) => item.argv[2])).toEqual([
        "marketplace",
        "install",
      ]);
      // Nothing machine-local lands in the repository.
      const repoFiles = Object.keys(await deliveredTree(world)).filter((path) =>
        path.startsWith("project/"),
      );
      expect(repoFiles.some((path) => /lock|receipt|journal|state/.test(path))).toBe(false);
      await expect(readFile(join(world.cwd, "ai-skills-lock.json"), "utf8")).rejects.toThrow(
        "ENOENT",
      );
      // A symlinked path to the same repository resolves to the same receipt.
      const alias = join(world.root, "alias");
      await symlink(world.cwd, alias);
      expect((await scopeStateDir("project", { cwd: alias, home: world.home })).dir).toBe(
        join(stateRoot(environment(world)), "projects", key),
      );
    });
  });

  test("refuses project state that would land inside the repository", async () => {
    await withWorld(async (world) => {
      // A home that is not a repository may hold its own project state.
      await expect(
        scopeStateDir("project", { cwd: world.home, home: world.home }),
      ).resolves.toMatchObject({ root: await realpath(world.home) });
      await mkdir(join(world.home, ".git"));
      for (const cwd of [world.home, join(world.home, "nested")]) {
        await mkdir(cwd, { recursive: true });
        await expect(scopeStateDir("project", { cwd, home: world.home })).rejects.toThrow(
          "so a receipt would land in it",
        );
      }
      await expect(runWorldCommand({ ...world, cwd: world.home }, "install")).rejects.toThrow(
        "so a receipt would land in it",
      );
    });
  });

  test("an unknown receipt version fails closed and is left untouched", async () => {
    await withWorld(async (world) => {
      const path = await receiptPath("project", environment(world));
      await mkdir(join(path, ".."), { recursive: true });
      const future = `${JSON.stringify({ generation: 9, version: 99 })}\n`;
      await writeFile(path, future);
      const before = await deliveredTree(world);
      await expect(runWorldCommand(world, "install")).rejects.toThrow(
        "Unsupported install receipt version 99",
      );
      await expect(readInstallState("project", environment(world))).rejects.toThrow(
        "Unsupported install receipt version 99",
      );
      expect(await readFile(path, "utf8")).toBe(future);
      expect(await deliveredTree(world)).toEqual(before);
    });
  });

  test("an unknown journal version fails closed and is left untouched", async () => {
    await withWorld(async (world) => {
      const dir = join(stateRoot(environment(world)), "journal", "20990101-000000000-future");
      await mkdir(dir, { recursive: true });
      const intent = `${JSON.stringify({ txn: "future", version: JOURNAL_VERSION + 1 })}\n`;
      await writeFile(join(dir, "intent.json"), intent);
      await writeFile(join(dir, "log.jsonl"), "");
      await expect(recoverState(environment(world))).rejects.toThrow(
        `Unsupported transaction journal version ${JOURNAL_VERSION + 1}`,
      );
      await expect(runWorldCommand(world, "install")).rejects.toThrow(
        "Unsupported transaction journal version",
      );
      expect(await readFile(join(dir, "intent.json"), "utf8")).toBe(intent);
      expect(await readReceipt("project", environment(world))).toBeNull();
    });
  });

  test("a corrupt log record (not the torn last line) fails closed", async () => {
    await withWorld(async (world) => {
      await runWorldCommand(world, "install", {
        journal: {
          afterOp: (index) => {
            if (index === 2) {
              throw new Error("stop here");
            }
          },
        },
      }).catch(() => undefined);
      // The failed install compensated and discarded its journal.
      expect(await readdir(join(stateRoot(environment(world)), "journal"))).toEqual([]);
      const dir = join(stateRoot(environment(world)), "journal", "20990101-000000000-broken");
      await mkdir(dir, { recursive: true });
      await writeFile(
        join(dir, "intent.json"),
        JSON.stringify({
          base: { generation: 0, txn: null },
          keepGenerations: 1,
          kind: "install",
          next: { plugins: {} },
          ops: [],
          planned: true,
          root: world.cwd,
          scope: "project",
          scopeDir: world.root,
          txn: "broken",
          version: JOURNAL_VERSION,
        }),
      );
      await writeFile(
        join(dir, "log.jsonl"),
        '{"phase":"begin","op":0}\nnot json\n{"phase":"done","op":0}\n',
      );
      await expect(recoverState(environment(world))).rejects.toThrow("Corrupt transaction log");
    });
  });

  test("lock v2 entries stay readable and the file is never mutated", async () => {
    await withWorld(async (world) => {
      const path = join(world.cwd, "ai-skills-lock.json");
      const legacy = legacyLock(world);
      await writeFile(path, legacy);
      const listed = await listSkills(
        { global: false, project: true },
        {
          lockEnvironment: environment(world),
        },
      );
      expect(listed.map((plugin) => plugin.name)).toEqual(["legacy-one"]);
      await runWorldCommand(world, "install");
      expect(await readFile(path, "utf8")).toBe(legacy);
      const state = await readInstallState("project", environment(world));
      expect(Object.keys(state.plugins).sort()).toEqual(["legacy-one", WORLD_PLUGIN]);
      const fingerprints = (await readReceipt("project", environment(world)))!.fingerprints;
      expect(Object.keys(fingerprints.adapters).length).toBeGreaterThan(0);
      await runWorldCommand(world, "remove");
      expect(await readFile(path, "utf8")).toBe(legacy);
      // Removing plugins keeps the recorded adapter fingerprints.
      expect((await readReceipt("project", environment(world)))!.fingerprints).toEqual(
        fingerprints,
      );
      expect(Object.keys((await readInstallState("project", environment(world))).plugins)).toEqual(
        [],
      );
    });
  });
});
