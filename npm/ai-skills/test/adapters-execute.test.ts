import { describe, expect, test } from "bun:test";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  readlink,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { cursorDropAdapter } from "../lib/adapters/cursor/drop-adapter.ts";
import { installCursorPlugin } from "../lib/adapters/cursor/drop.ts";
import { applyPlan, PlanApplyError, verifyPlanOps } from "../lib/adapters/execute.ts";
import { nodeReadOnlyFs, ownedPathHash, sha256 } from "../lib/adapters/fs.ts";
import { skillExplodeAdapter } from "../lib/adapters/shared/skill-explode-adapter.ts";
import { explodePlugin } from "../lib/adapters/shared/skill-explode.ts";
import type { AdapterPlan, Op } from "../lib/adapters/types.ts";
import { memoryFs } from "./fixtures/memory-fs.ts";

const text = (value: string) => new TextEncoder().encode(value);
const write = (path: string, value: string): Op => ({
  content: text(value),
  hash: sha256(value),
  kind: "write-file",
  path,
});

/** Every directory, file and symlink under `root`, with content or target. */
async function snapshot(root: string, prefix = ""): Promise<Record<string, string>> {
  const tree: Record<string, string> = {};
  for (const entry of await readdir(join(root, prefix), { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolute = join(root, relative);
    if (entry.isSymbolicLink()) {
      tree[relative] = `-> ${(await readlink(absolute)).replaceAll(root, "<root>")}`;
    } else if (entry.isDirectory()) {
      tree[relative] = "<dir>";
      Object.assign(tree, await snapshot(root, relative));
    } else {
      tree[relative] = await readFile(absolute, "utf8");
    }
  }
  return tree;
}

const filesOnly = (tree: Record<string, string>) =>
  Object.fromEntries(Object.entries(tree).filter(([, value]) => value !== "<dir>"));

function plan(root: string, ops: Op[], roots: string[] = [root]): AdapterPlan {
  return {
    adapter: "skill-explode",
    host: "codex",
    mode: "explode",
    notes: [],
    ops,
    pluginId: "review",
    recovery: "reversible",
    role: "skill",
    roots,
    scope: "global",
    support: skillExplodeAdapter.support({
      host: "codex",
      localSource: true,
      mode: "explode",
      role: "skill",
      scope: "global",
    }),
  };
}

async function withRoot(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(join(tmpdir(), "ai-skills-execute-"));
  try {
    await run(root);
  } finally {
    await rm(root, { force: true, recursive: true });
  }
}

/** A prior tree plus a plan touching every op kind except host-exec. */
async function seededPlan(root: string): Promise<AdapterPlan> {
  await mkdir(join(root, "dest/old"), { recursive: true });
  await writeFile(join(root, "dest/old/SKILL.md"), "old\n");
  await writeFile(join(root, "dest/keep.md"), "before\n");
  await writeFile(join(root, "untracked.md"), "mine\n");
  return plan(root, [
    {
      expectHash: await ownedPathHash(nodeReadOnlyFs, join(root, "dest/old")),
      kind: "remove-owned",
      path: join(root, "dest/old"),
    },
    { kind: "mkdir", path: join(root, "store/lint/docs") },
    write(join(root, "store/lint/SKILL.md"), "# lint\n"),
    write(join(root, "dest/keep.md"), "after\n"),
    { kind: "symlink", path: join(root, "dest/lint"), target: join(root, "store/lint") },
    write(join(root, "new/deep/file.md"), "deep\n"),
  ]);
}

describe("plan executor", () => {
  test("an injected failure before each op restores the prior tree", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      const before = await snapshot(root);
      for (let index = 0; index < prepared.ops.length; index += 1) {
        await expect(applyPlan(prepared, { failBeforeOp: index })).rejects.toThrow(
          `injected failure before op ${index}`,
        );
        expect(await snapshot(root)).toEqual(before);
      }
    });
  });

  test("a failure inside an op restores the prior tree", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      const before = await snapshot(root);
      let writes = 0;
      await expect(
        applyPlan(prepared, {
          io: {
            writeFile: (async (...args: Parameters<typeof writeFile>) => {
              writes += 1;
              if (writes === 2) {
                throw new Error("ENOSPC: disk full");
              }
              return writeFile(...args);
            }) as typeof writeFile,
          },
        }),
      ).rejects.toThrow("ENOSPC");
      expect(await snapshot(root)).toEqual(before);
    });
  });

  test("removes the staging file when writing it fails", async () => {
    await withRoot(async (root) => {
      // The directory pre-exists so undoing mkdir cannot sweep the staging file away.
      await mkdir(join(root, "dest"));
      const target = join(root, "dest/new.md");
      await expect(
        applyPlan(plan(root, [write(target, "new\n")]), {
          // Empty read view: the target does not exist yet.
          fs: memoryFs({}),
          io: {
            writeFile: (async (path: Parameters<typeof writeFile>[0]) => {
              // Partial write, then the disk fills up.
              await writeFile(path, "partial");
              throw Object.assign(new Error("ENOSPC: no space left on device"), {
                code: "ENOSPC",
              });
            }) as typeof writeFile,
          },
        }),
      ).rejects.toThrow("ENOSPC");
      expect(await snapshot(root)).toEqual({ dest: "<dir>" });
    });
  });

  test("applies, verifies, and either commits or rolls back on request", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      const before = await snapshot(root);
      const transaction = await applyPlan(prepared);
      expect(transaction.applied).toBe(prepared.ops.length);
      expect(await verifyPlanOps(prepared)).toEqual({ ok: true, problems: [], unverified: [] });
      const applied = await snapshot(root);
      expect(applied["dest/keep.md"]).toBe("after\n");
      expect(applied["dest/lint"]).toBe("-> <root>/store/lint");
      expect(Object.keys(applied).some((path) => path.includes(".bak."))).toBe(true);
      await transaction.rollback();
      expect(await snapshot(root)).toEqual(before);

      const again = await applyPlan(await seededPlan(root));
      await again.commit();
      const committed = await snapshot(root);
      expect(Object.keys(committed).some((path) => path.includes(".bak."))).toBe(false);
      expect(committed["dest/old"]).toBeUndefined();
      expect(committed["untracked.md"]).toBe("mine\n");
    });
  });

  test("verify reports drift after apply", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      await (await applyPlan(prepared)).commit();
      await writeFile(join(root, "dest/keep.md"), "tampered\n");
      await mkdir(join(root, "dest/old"));
      const result = await verifyPlanOps(prepared);
      expect(result.ok).toBe(false);
      expect(result.problems).toEqual([
        `still present: ${join(root, "dest/old")}`,
        `content differs: ${join(root, "dest/keep.md")}`,
      ]);
    });
  });

  test("refuses every op when one path leaves the declared roots", async () => {
    await withRoot(async (root) => {
      await mkdir(join(root, "inside"));
      const before = await snapshot(root);
      await expect(
        applyPlan(
          plan(
            root,
            [write(join(root, "inside/a.md"), "a\n"), write(join(root, "outside.md"), "b\n")],
            [join(root, "inside")],
          ),
        ),
      ).rejects.toThrow("outside the plan's declared roots");
      await expect(
        applyPlan(
          plan(root, [write(join(root, "inside/../escape.md"), "x\n")], [join(root, "inside")]),
        ),
      ).rejects.toThrow("outside the plan's declared roots");
      expect(await snapshot(root)).toEqual(before);
    });
  });

  test("refuses writes through a symlinked directory inside a root", async () => {
    await withRoot(async (root) => {
      await mkdir(join(root, "elsewhere"));
      await mkdir(join(root, "inside"));
      await symlink(join(root, "elsewhere"), join(root, "inside/link"));
      await expect(
        applyPlan(
          plan(root, [write(join(root, "inside/link/a.md"), "a\n")], [join(root, "inside")]),
        ),
      ).rejects.toThrow("through a symlinked directory");
      expect(await readdir(join(root, "elsewhere"))).toEqual([]);
    });
  });

  test("refuses to remove an owned path whose content changed since the plan", async () => {
    await withRoot(async (root) => {
      await writeFile(join(root, "owned.md"), "planned\n");
      const expectHash = await ownedPathHash(nodeReadOnlyFs, join(root, "owned.md"));
      await writeFile(join(root, "owned.md"), "edited by the user\n");
      await expect(
        applyPlan(
          plan(root, [
            write(join(root, "first.md"), "1\n"),
            { expectHash, kind: "remove-owned", path: join(root, "owned.md") },
          ]),
        ),
      ).rejects.toThrow("content changed since the plan");
      expect(await snapshot(root)).toEqual({ "owned.md": "edited by the user\n" });
    });
  });

  test("refuses to replace an existing path with a symlink or a directory with a file", async () => {
    await withRoot(async (root) => {
      await mkdir(join(root, "dir"));
      await writeFile(join(root, "file.md"), "x\n");
      await expect(
        applyPlan(plan(root, [{ kind: "symlink", path: join(root, "file.md"), target: "x" }])),
      ).rejects.toThrow("Refusing to replace existing path");
      await expect(applyPlan(plan(root, [write(join(root, "dir"), "x\n")]))).rejects.toThrow(
        "non-file",
      );
      await expect(
        applyPlan(
          plan(root, [{ expectHash: "x", kind: "remove-owned", path: join(root, "absent.md") }]),
        ),
      ).rejects.toThrow("no longer present");
    });
  });
});

describe("host-exec ops", () => {
  const install: Op = {
    argv: ["claude", "plugin", "install", "review@ai-skills"],
    compensate: ["claude", "plugin", "uninstall", "review@ai-skills"],
    kind: "host-exec",
    step: "plugin-install",
    tolerateAlreadyPresent: true,
  };
  const register: Op = {
    argv: ["claude", "plugin", "marketplace", "add", "/envelope"],
    compensate: null,
    kind: "host-exec",
    step: "marketplace-add",
    tolerateAlreadyPresent: true,
  };

  test("compensates on a later failure and reports what stays", async () => {
    await withRoot(async (root) => {
      const calls: string[][] = [];
      await expect(
        applyPlan(plan(root, [register, install, write(join(root, "x.md"), "x\n")]), {
          exec: async (command, args) => {
            calls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "ok" };
          },
          failBeforeOp: 2,
        }),
      ).rejects.toBeInstanceOf(PlanApplyError);
      expect(calls).toEqual([
        register.argv,
        install.argv,
        ["claude", "plugin", "uninstall", "review@ai-skills"],
      ]);
    });
  });

  test("does not compensate an already-present plugin and lists irreversible steps", async () => {
    await withRoot(async (root) => {
      const calls: string[][] = [];
      let caught: PlanApplyError | undefined;
      try {
        await applyPlan(plan(root, [register, install, write(join(root, "x.md"), "x\n")]), {
          exec: async (command, args) => {
            calls.push([command, ...args]);
            return args.includes("install")
              ? { status: 1, stderr: "already installed", stdout: "" }
              : { status: 0, stderr: "", stdout: "" };
          },
          failBeforeOp: 2,
        });
      } catch (error) {
        caught = error as PlanApplyError;
      }
      expect(calls.some((argv) => argv.includes("uninstall"))).toBe(false);
      expect(caught?.remaining).toEqual([
        "claude plugin marketplace add /envelope (marketplace-add)",
      ]);
    });
  });

  test("surfaces host failures and failed compensation", async () => {
    await withRoot(async (root) => {
      await expect(
        applyPlan(plan(root, [install]), {
          exec: async () => ({ status: 1, stderr: "boom", stdout: "" }),
        }),
      ).rejects.toThrow("claude plugin install failed: boom");
      await expect(
        applyPlan(plan(root, [install, write(join(root, "x.md"), "x\n")]), {
          exec: async (_command, args) =>
            args.includes("uninstall")
              ? { status: 1, stderr: "locked", stdout: "" }
              : { status: 0, stderr: "", stdout: "" },
          failBeforeOp: 1,
        }),
      ).rejects.toThrow(
        "injected failure before op 1 (write-file) (rollback also failed: " +
          "claude plugin uninstall failed: locked)",
      );
    });
  });
});

describe("tree adapter parity with the transactional engines", () => {
  test("skill-explode plan produces the engine's tree (store symlinks and copies)", async () => {
    await withRoot(async (root) => {
      const source = join(root, "catalog");
      await mkdir(join(source, "lint/docs"), { recursive: true });
      await writeFile(join(source, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(source, "lint/docs/guide.md"), "guide\n");
      await symlink("docs/guide.md", join(source, "lint/GUIDE.md"));
      await mkdir(join(source, "test"), { recursive: true });
      await writeFile(join(source, "test/SKILL.md"), "# test\n");
      for (const copy of [false, true]) {
        const viaPlan = join(root, `plan-${copy}`);
        const viaEngine = join(root, `engine-${copy}`);
        const kept = {
          description: "Review",
          pluginId: "review",
          skills: ["lint", "test"].map((name) => ({ name, source: join(source, name) })),
          version: "1",
        };
        const planned = await skillExplodeAdapter.plan({
          env: { cwd: viaPlan, home: viaPlan },
          fs: nodeReadOnlyFs,
          host: "codex",
          kept,
          mode: "explode",
          options: { copy },
          owned: [],
          role: "skill",
          scope: "global",
        });
        await (await applyPlan(planned)).commit();
        await explodePlugin({
          agents: [{ copy, id: "codex", root: join(viaEngine, ".codex/skills") }],
          copy,
          skills: ["lint", "test"],
          sourceSkills: { lint: join(source, "lint"), test: join(source, "test") },
          storeRoot: join(viaEngine, ".agents/skills"),
        });
        expect(filesOnly(await snapshot(viaPlan))).toEqual(filesOnly(await snapshot(viaEngine)));
      }
    });
  });

  test("cursor-drop plan produces the engine's replaced tree", async () => {
    await withRoot(async (root) => {
      const catalog = join(root, "catalog");
      for (const name of ["lint", "test"]) {
        await mkdir(join(catalog, "skills", name), { recursive: true });
        await writeFile(join(catalog, "skills", name, "SKILL.md"), `# ${name}\n`);
      }
      const seed = async (home: string) => {
        const plugin = join(home, ".cursor/plugins/local/review");
        await mkdir(join(plugin, "skills/retired"), { recursive: true });
        await mkdir(join(plugin, "skills/lint"), { recursive: true });
        await writeFile(join(plugin, "skills/retired/SKILL.md"), "# retired\n");
        await writeFile(join(plugin, "skills/lint/SKILL.md"), "# old\n");
        await writeFile(join(plugin, "NOTES.md"), "mine\n");
        return plugin;
      };
      const viaPlan = join(root, "plan");
      const viaEngine = join(root, "engine");
      await seed(viaPlan);
      const enginePlugin = await seed(viaEngine);
      const planned = await cursorDropAdapter.plan({
        env: { cwd: viaPlan, home: viaPlan },
        fs: nodeReadOnlyFs,
        host: "cursor",
        kept: {
          description: "Review",
          pluginId: "review",
          skills: ["lint", "test"].map((name) => ({
            name,
            source: join(catalog, "skills", name),
          })),
          version: "1",
        },
        mode: "native",
        owned: ["lint", "retired"],
        role: "skill",
        scope: "global",
      });
      await (await applyPlan(planned)).commit();
      await installCursorPlugin({
        description: "Review",
        destRoot: join(enginePlugin, ".."),
        pluginId: "review",
        replace: true,
        skills: ["lint", "test"],
        sourceRoot: catalog,
        version: "1",
      });
      expect(filesOnly(await snapshot(viaPlan))).toEqual(filesOnly(await snapshot(viaEngine)));
    });
  });
});
