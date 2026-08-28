import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { PROJECTOR_EXPLODE, PROJECTOR_NATIVE } from "../lib/lockfile.js";
import { assertProjectorSupported, resolveProjector } from "../lib/projectors/defaults.js";
import {
  CLI_BY_AGENT,
  installCliPlugin,
  uninstallCliPlugin,
} from "../lib/projectors/native-cli.js";
import {
  cursorPluginsRoot,
  findCatalogSourceRoot,
  installCursorPlugin,
  removeCursorPlugin,
  restoreCursorPluginInstall,
} from "../lib/projectors/native-cursor.js";

describe("resolveProjector", () => {
  test("defaults native for Cursor, Claude, and Copilot", () => {
    expect(resolveProjector("cursor")).toBe(PROJECTOR_NATIVE);
    expect(resolveProjector("claude-code")).toBe(PROJECTOR_NATIVE);
    expect(resolveProjector("copilot")).toBe(PROJECTOR_NATIVE);
    expect(resolveProjector("codex")).toBe(PROJECTOR_EXPLODE);
  });

  test("lets --projector override the host default", () => {
    expect(resolveProjector("cursor", PROJECTOR_EXPLODE)).toBe(PROJECTOR_EXPLODE);
    expect(resolveProjector("codex", PROJECTOR_NATIVE)).toBe(PROJECTOR_NATIVE);
  });

  test("forces explode for vendor installs unless native is requested", () => {
    expect(resolveProjector("cursor", null, { vendor: true })).toBe(PROJECTOR_EXPLODE);
    expect(() => resolveProjector("cursor", PROJECTOR_NATIVE, { vendor: true })).toThrow(
      "first-party only",
    );
  });
});

describe("native Cursor projector", () => {
  test("assembles a plugin tree from sliced skills and round-trips remove", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-plugin-"));
    try {
      const sourceRoot = join(root, "src");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = await installCursorPlugin({
        description: "Lint and test.",
        destRoot,
        pluginId: "review",
        skills: ["lint", "test"],
        sourceRoot,
        version: "0.23.0",
      });

      expect(pluginDir).toBe(join(root, ".cursor/plugins/local/review"));
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(pluginDir, "skills/test/SKILL.md"), "utf8")).toBe("# test\n");
      expect(
        JSON.parse(await readFile(join(pluginDir, ".claude-plugin/plugin.json"), "utf8")),
      ).toEqual({
        description: "Lint and test.",
        name: "review",
        version: "0.23.0",
      });

      await removeCursorPlugin({ destRoot, pluginId: "review" });
      await expect(
        readFile(join(pluginDir, ".claude-plugin/plugin.json"), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("refuses a path-escaping plugin id", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-escape-"));
    try {
      const destRoot = join(root, ".cursor/plugins/local");
      await mkdir(destRoot, { recursive: true });
      const victim = join(root, "victim");
      await mkdir(victim);
      await writeFile(join(victim, "keep.txt"), "safe\n");
      await expect(removeCursorPlugin({ destRoot, pluginId: "../../../victim" })).rejects.toThrow(
        "kebab-case",
      );
      expect(await readFile(join(victim, "keep.txt"), "utf8")).toBe("safe\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("refuses a path-escaping skill name", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-skill-escape-"));
    try {
      const sourceRoot = join(root, "src");
      const destRoot = join(root, ".cursor/plugins/local");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(destRoot, { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await expect(
        installCursorPlugin({
          description: "Lint.",
          destRoot,
          pluginId: "review",
          skills: ["../etc"],
          sourceRoot,
          version: "0.23.0",
        }),
      ).rejects.toThrow("must be kebab-case");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("refuses to overwrite an unowned Cursor plugin tree", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-unowned-"));
    try {
      const sourceRoot = join(root, "src");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await expect(
        installCursorPlugin({
          description: "Lint.",
          destRoot,
          pluginId: "review",
          skills: ["lint"],
          sourceRoot,
          version: "0.23.0",
        }),
      ).rejects.toThrow("unowned");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("preserves an owned Cursor tree when staging copy fails", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-copy-fail-"));
    try {
      const sourceRoot = join(root, "src");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await expect(
        installCursorPlugin({
          copy: async () => {
            throw new Error("copy failed");
          },
          description: "Lint.",
          destRoot,
          pluginId: "review",
          replace: true,
          skills: ["lint"],
          sourceRoot,
          version: "0.23.0",
        }),
      ).rejects.toThrow("copy failed");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("does not restore a leftover backup when staging fails before swap", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-stale-bak-"));
    try {
      const sourceRoot = join(root, "src");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await mkdir(`${pluginDir}.bak`, { recursive: true });
      await writeFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "stale\n");
      await expect(
        installCursorPlugin({
          copy: async () => {
            throw new Error("copy failed");
          },
          description: "Lint.",
          destRoot,
          pluginId: "review",
          replace: true,
          skills: ["lint"],
          sourceRoot,
          version: "0.23.0",
        }),
      ).rejects.toThrow("copy failed");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("does not restore a leftover backup when this run did not swap", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-restore-stale-bak-"));
    try {
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "fresh\n");
      await mkdir(`${pluginDir}.bak`, { recursive: true });
      await writeFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "stale\n");
      await restoreCursorPluginInstall({
        created: true,
        destRoot,
        pluginId: "review",
        swapped: false,
      });
      await expect(readFile(join(pluginDir, "USER-DATA.txt"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      await expect(readFile(join(`${pluginDir}.bak`, "USER-DATA.txt"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("leaves an existing Cursor tree and leftover backup when neither created nor swapped", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-restore-owned-noswap-"));
    try {
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "fresh\n");
      await mkdir(`${pluginDir}.bak`, { recursive: true });
      await writeFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "stale\n");
      await restoreCursorPluginInstall({
        created: false,
        destRoot,
        pluginId: "review",
        swapped: false,
      });
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("fresh\n");
      expect(await readFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "utf8")).toBe("stale\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("keeps untracked files when an owned Cursor tree is replaced", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-cursor-replace-untracked-"));
    try {
      const sourceRoot = join(root, "src");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      const destRoot = cursorPluginsRoot({ cwd: root, home: root, scope: "project" });
      const pluginDir = join(destRoot, "review");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# old\n");
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await installCursorPlugin({
        description: "Lint.",
        destRoot,
        pluginId: "review",
        replace: true,
        skills: ["lint"],
        sourceRoot,
        version: "0.23.0",
      });
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("finds a catalog checkout from cwd", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-catalog-root-"));
    try {
      await mkdir(join(root, "skills"), { recursive: true });
      await mkdir(join(root, ".claude-plugin"), { recursive: true });
      await writeFile(join(root, ".claude-plugin/marketplace.json"), "{}\n");
      expect(findCatalogSourceRoot(root)).toBe(root);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("falls back to the clone catalog when cwd has none", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-catalog-miss-"));
    try {
      const found = findCatalogSourceRoot(root);
      expect(found).not.toBeNull();
      await expect(
        readFile(join(found, ".claude-plugin/marketplace.json"), "utf8"),
      ).resolves.toMatch(/"name"/);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("native CLI projector", () => {
  test("adds the marketplace then installs through the host CLI", async () => {
    const calls = [];
    await installCliPlugin({
      agent: "claude-code",
      exec: async (command, args) => {
        calls.push([command, ...args]);
        return { status: 0, stderr: "", stdout: "ok" };
      },
      pluginId: "review",
      source: "lgtm-hq/ai-skills@v0.23.0",
    });
    expect(CLI_BY_AGENT["claude-code"]).toBe("claude");
    expect(calls).toEqual([
      ["claude", "plugin", "marketplace", "add", "lgtm-hq/ai-skills@v0.23.0"],
      ["claude", "plugin", "install", "review@ai-skills"],
    ]);
  });

  test("adds Copilot marketplace sources without a git tag", async () => {
    const calls = [];
    await installCliPlugin({
      agent: "copilot",
      exec: async (command, args) => {
        calls.push([command, ...args]);
        return { status: 0, stderr: "", stdout: "ok" };
      },
      pluginId: "review",
      source: "lgtm-hq/ai-skills@v0.23.0",
    });
    expect(calls).toEqual([
      ["copilot", "plugin", "marketplace", "add", "lgtm-hq/ai-skills"],
      ["copilot", "plugin", "install", "review@ai-skills"],
    ]);
  });

  test("treats already-present marketplace add as success", async () => {
    const calls = [];
    await installCliPlugin({
      agent: "copilot",
      exec: async (command, args) => {
        calls.push([command, ...args]);
        if (args.includes("add")) {
          return { status: 1, stderr: "already exists", stdout: "" };
        }
        return { status: 0, stderr: "", stdout: "ok" };
      },
      pluginId: "review",
      source: "lgtm-hq/ai-skills@v0.23.0",
    });
    expect(calls).toEqual([
      ["copilot", "plugin", "marketplace", "add", "lgtm-hq/ai-skills"],
      ["copilot", "plugin", "install", "review@ai-skills"],
    ]);
  });

  test("does not treat does not exist as already present", async () => {
    await expect(
      installCliPlugin({
        agent: "claude-code",
        exec: async (_command, args) => {
          if (args.includes("install")) {
            return { status: 1, stderr: "plugin does not exist", stdout: "" };
          }
          return { status: 0, stderr: "", stdout: "" };
        },
        pluginId: "review",
        source: "lgtm-hq/ai-skills@v0.23.0",
      }),
    ).rejects.toThrow("claude plugin install failed: plugin does not exist");
  });

  test("does not treat no plugin exists as already present", async () => {
    await expect(
      installCliPlugin({
        agent: "claude-code",
        exec: async (_command, args) => {
          if (args.includes("install")) {
            return { status: 1, stderr: "no plugin exists", stdout: "" };
          }
          return { status: 0, stderr: "", stdout: "" };
        },
        pluginId: "review",
        source: "lgtm-hq/ai-skills@v0.23.0",
      }),
    ).rejects.toThrow("claude plugin install failed: no plugin exists");
  });

  test("does not treat a missing plugin as a successful install", async () => {
    await expect(
      installCliPlugin({
        agent: "claude-code",
        exec: async (_command, args) => {
          if (args.includes("install")) {
            return { status: 1, stderr: "plugin not found", stdout: "" };
          }
          return { status: 0, stderr: "", stdout: "" };
        },
        pluginId: "review",
        source: "lgtm-hq/ai-skills@v0.23.0",
      }),
    ).rejects.toThrow("claude plugin install failed: plugin not found");
  });

  test("surfaces a failed install instead of swallowing it", async () => {
    await expect(
      installCliPlugin({
        agent: "claude-code",
        exec: async (_command, args) => {
          if (args.includes("install")) {
            return { status: 1, stderr: "boom", stdout: "" };
          }
          return { status: 0, stderr: "", stdout: "" };
        },
        pluginId: "review",
        source: "lgtm-hq/ai-skills@v0.23.0",
      }),
    ).rejects.toThrow("claude plugin install failed: boom");
  });

  test("treats uninstall of an already-missing plugin as success", async () => {
    await uninstallCliPlugin({
      agent: "copilot",
      exec: async () => ({ status: 1, stderr: "not installed", stdout: "" }),
      pluginId: "review",
    });
  });

  test("does not treat uninstall still exists as already absent", async () => {
    await expect(
      uninstallCliPlugin({
        agent: "copilot",
        exec: async () => ({ status: 1, stderr: "plugin still exists", stdout: "" }),
        pluginId: "review",
      }),
    ).rejects.toThrow("copilot plugin uninstall failed: plugin still exists");
  });

  test("uninstalls through the host CLI", async () => {
    const calls = [];
    await uninstallCliPlugin({
      agent: "copilot",
      exec: async (command, args) => {
        calls.push([command, ...args]);
        return { status: 0, stderr: "", stdout: "" };
      },
      pluginId: "review",
    });
    expect(calls).toEqual([["copilot", "plugin", "uninstall", "review@ai-skills"]]);
  });

  test("rejects native delivery on explode-only hosts", () => {
    expect(() => assertProjectorSupported("codex", PROJECTOR_NATIVE)).toThrow(
      'Native projector is not supported for agent "codex"',
    );
    expect(() => assertProjectorSupported("cursor", PROJECTOR_NATIVE)).not.toThrow();
  });
});
