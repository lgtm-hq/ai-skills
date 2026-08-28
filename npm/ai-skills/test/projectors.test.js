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

  test("treats already-present marketplace add as success", async () => {
    await installCliPlugin({
      agent: "copilot",
      exec: async (_command, args) => {
        if (args.includes("add")) {
          return { status: 1, stderr: "already exists", stdout: "" };
        }
        return { status: 0, stderr: "", stdout: "ok" };
      },
      pluginId: "review",
      source: "lgtm-hq/ai-skills@v0.23.0",
    });
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
