import { describe, expect, test } from "bun:test";
import {
  access,
  chmod,
  rename,
  stat,
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
import type { ExecuteOptions } from "../lib/adapters/execute.ts";
import { nodeReadOnlyFs, ownedPathHash, sha256 } from "../lib/adapters/fs.ts";
import { skillExplodeAdapter } from "../lib/adapters/shared/skill-explode-adapter.ts";
import { explodePlugin } from "../lib/adapters/shared/skill-explode.ts";
import type { AdapterPlan, Op } from "../lib/adapters/types.ts";

const text = (value: string) => new TextEncoder().encode(value);
const write = (path: string, value: string, mode?: number): Op => ({
  content: text(value),
  hash: sha256(value),
  kind: "write-file",
  path,
  ...(mode === undefined ? {} : { mode }),
});

/** Permission bits of every regular file under `root`, keyed by relative path. */
async function modes(root: string): Promise<Record<string, number>> {
  const found: Record<string, number> = {};
  for (const relative of (await readdir(root, { recursive: true })).map(String)) {
    const info = await stat(join(root, relative)).catch(() => null);
    if (info?.isFile()) {
      found[relative] = info.mode & 0o777;
    }
  }
  return found;
}

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

/** Journal directory of the current `withRoot`, kept outside the snapshotted tree. */
let journalRoot = "";

async function withRoot(run: (root: string) => Promise<void>): Promise<void> {
  const base = await mkdtemp(join(tmpdir(), "ai-skills-execute-"));
  const root = join(base, "tree");
  await mkdir(root);
  journalRoot = join(base, "journal");
  try {
    await run(root);
  } finally {
    await rm(base, { force: true, recursive: true });
  }
}

/** `applyPlan` journaled under the current root's journal directory. */
const apply = (planned: AdapterPlan, options: Omit<ExecuteOptions, "journalRoot"> = {}) =>
  applyPlan(planned, { journalRoot, ...options });

/** Transaction directories left in the journal. */
const journals = async () => readdir(journalRoot).catch(() => [] as string[]);

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
        await expect(apply(prepared, { failBeforeOp: index })).rejects.toThrow(
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
        apply(prepared, {
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
        apply(plan(root, [write(target, "new\n")]), {
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

  test("keeps the journal and names it when restoring a removed path fails", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      const failRestore = (async (from: string, to: string) => {
        // Putting `dest/old` back from its staged preimage fails (EXDEV, EACCES, ...).
        if (String(from).includes(".aiskills-") && String(to).endsWith("dest/old")) {
          throw Object.assign(new Error("EXDEV: cross-device link"), { code: "EXDEV" });
        }
        return rename(from, to);
      }) as typeof rename;
      const transaction = await apply(prepared, { io: { rename: failRestore } });
      let message = "";
      try {
        await transaction.rollback();
      } catch (error) {
        message = (error as Error).message;
      }
      expect(message).toContain(`remove-owned ${join(root, "dest/old")}: EXDEV`);
      const kept = /journal kept at (\S+)\)$/.exec(message)?.[1] ?? "";
      expect(kept).toStartWith(journalRoot);
      // The removed content survives as a preimage, and every other op was undone.
      const objects = await readdir(join(kept, "pre"));
      const contents = await Promise.all(
        objects.map((name) => readFile(join(kept, "pre", name), "utf8")),
      );
      expect(contents).toContain("old\n");
      expect(await readFile(join(root, "dest/keep.md"), "utf8")).toBe("before\n");
      await expect(access(join(root, "store"))).rejects.toMatchObject({ code: "ENOENT" });
      expect(
        Object.keys(await snapshot(root)).filter((path) => path.includes(".aiskills-")),
      ).toEqual([]);
    });
  });

  test("keeps the journal when a failed apply cannot restore a removed path", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      await expect(
        apply(prepared, {
          failBeforeOp: 2,
          io: {
            rename: (async (from: string, to: string) => {
              if (String(from).includes(".aiskills-") && String(to).endsWith("dest/old")) {
                throw Object.assign(new Error("EACCES: permission denied"), { code: "EACCES" });
              }
              return rename(from, to);
            }) as typeof rename,
          },
        }),
      ).rejects.toThrow("(rollback also failed: remove-owned");
      expect(await journals()).toHaveLength(1);
    });
  });

  test("applies a write-file mode and restores the previous mode on undo", async () => {
    await withRoot(async (root) => {
      await writeFile(join(root, "run.sh"), "old\n");
      await chmod(join(root, "run.sh"), 0o600);
      const transaction = await apply(
        plan(root, [write(join(root, "run.sh"), "#!/bin/sh\n", 0o755)]),
      );
      expect((await stat(join(root, "run.sh"))).mode & 0o777).toBe(0o755);
      await transaction.rollback();
      expect((await stat(join(root, "run.sh"))).mode & 0o777).toBe(0o600);
      expect(await readFile(join(root, "run.sh"), "utf8")).toBe("old\n");
    });
  });

  test("applies, verifies, and either commits or rolls back on request", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      const before = await snapshot(root);
      const transaction = await apply(prepared);
      expect(transaction.applied).toBe(prepared.ops.length);
      expect(await verifyPlanOps(prepared)).toEqual({ ok: true, problems: [], unverified: [] });
      const applied = await snapshot(root);
      expect(applied["dest/keep.md"]).toBe("after\n");
      expect(applied["dest/lint"]).toBe("-> <root>/store/lint");
      // Undo lives in the journal, not in backup trees beside the destination.
      expect(Object.keys(applied).some((path) => /\.bak\.|\.aiskills-/.test(path))).toBe(false);
      expect(await journals()).toHaveLength(1);
      await transaction.rollback();
      expect(await snapshot(root)).toEqual(before);
      expect(await journals()).toEqual([]);

      const again = await apply(await seededPlan(root));
      await again.commit();
      expect(await journals()).toEqual([]);
      const committed = await snapshot(root);
      expect(Object.keys(committed).some((path) => /\.bak\.|\.aiskills-/.test(path))).toBe(false);
      expect(committed["dest/old"]).toBeUndefined();
      expect(committed["untracked.md"]).toBe("mine\n");
    });
  });

  test("verify reports drift after apply", async () => {
    await withRoot(async (root) => {
      const prepared = await seededPlan(root);
      await (await apply(prepared)).commit();
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
        apply(
          plan(
            root,
            [write(join(root, "inside/a.md"), "a\n"), write(join(root, "outside.md"), "b\n")],
            [join(root, "inside")],
          ),
        ),
      ).rejects.toThrow("outside the plan's declared roots");
      await expect(
        apply(
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
        apply(plan(root, [write(join(root, "inside/link/a.md"), "a\n")], [join(root, "inside")])),
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
        apply(
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
        apply(plan(root, [{ kind: "symlink", path: join(root, "file.md"), target: "x" }])),
      ).rejects.toThrow("Refusing to replace existing path");
      await expect(apply(plan(root, [write(join(root, "dir"), "x\n")]))).rejects.toThrow(
        "non-file",
      );
      await expect(
        apply(
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
        apply(plan(root, [register, install, write(join(root, "x.md"), "x\n")]), {
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
        await apply(plan(root, [register, install, write(join(root, "x.md"), "x\n")]), {
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
        apply(plan(root, [install]), {
          exec: async () => ({ status: 1, stderr: "boom", stdout: "" }),
        }),
      ).rejects.toThrow("claude plugin install failed: boom");
      await expect(
        apply(plan(root, [install, write(join(root, "x.md"), "x\n")]), {
          exec: async (_command, args) =>
            args.includes("uninstall")
              ? { status: 1, stderr: "locked", stdout: "" }
              : { status: 0, stderr: "", stdout: "" },
          failBeforeOp: 1,
        }),
      ).rejects.toThrow(
        "injected failure before op 1 (write-file) (rollback also failed: host-exec claude " +
          "plugin install review@ai-skills: claude plugin uninstall failed: locked",
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
      await writeFile(join(source, "lint/check.sh"), "#!/bin/sh\nexit 0\n");
      await chmod(join(source, "lint/check.sh"), 0o755);
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
        await (await apply(planned)).commit();
        await explodePlugin({
          agents: [{ copy, id: "codex", root: join(viaEngine, ".codex/skills") }],
          copy,
          skills: ["lint", "test"],
          sourceSkills: { lint: join(source, "lint"), test: join(source, "test") },
          storeRoot: join(viaEngine, ".agents/skills"),
        });
        expect(filesOnly(await snapshot(viaPlan))).toEqual(filesOnly(await snapshot(viaEngine)));
        // Executable skill scripts keep their mode, exactly as the engine copy does.
        expect(await modes(viaPlan)).toEqual(await modes(viaEngine));
        const script = copy ? ".codex/skills/lint/check.sh" : ".agents/skills/lint/check.sh";
        expect((await modes(viaPlan))[script]).toBe(0o755);
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
      await (await apply(planned)).commit();
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
