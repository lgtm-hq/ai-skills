import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  LOCKFILE_VERSION,
  hashTree,
  isCliOwnedNativeInstall,
  isPluginInstalled,
  mergeLockEntries,
  pluginSkillNames,
  pruneMissingLockEntries,
  readLockfile,
  reconcileLock,
} from "../lib/lockfile.js";

const explodeEntry = {
  agents: {
    cursor: {
      files: { "lint/SKILL.md": "abc" },
      root: "/tmp/project/.cursor/skills",
    },
  },
  installedAt: "2026-07-10T16:00:00.000Z",
  projector: "explode",
  repo: "lgtm-hq/ai-skills",
  sha: "v0.0.0-dev",
  vendor: "lgtm-hq",
  version: "0.0.0-dev",
};

const lock = {
  gatewayVersion: "0.0.0-dev",
  plugins: {
    review: explodeEntry,
    pdf: {
      ...explodeEntry,
      agents: {
        cursor: {
          files: { "pdf/SKILL.md": "def" },
          root: "/tmp/project/.cursor/skills",
        },
      },
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      vendor: "anthropics",
    },
  },
  scope: "project",
  version: LOCKFILE_VERSION,
};

describe("gateway lockfile", () => {
  test("merges overlapping installs without dropping tracked agents", () => {
    const merged = mergeLockEntries(lock, {
      review: {
        ...explodeEntry,
        agents: {
          "claude-code": {
            files: { "lint/SKILL.md": "abc" },
            root: "/tmp/project/.claude/skills",
          },
        },
        installedAt: "2026-07-10T17:00:00.000Z",
      },
    });

    expect(Object.keys(merged.plugins.review.agents).sort()).toEqual(["claude-code", "cursor"]);
    expect(merged.plugins.pdf).toEqual(lock.plugins.pdf);
  });

  test("replaces an agent file map when projector or root changes", () => {
    const merged = mergeLockEntries(lock, {
      review: {
        ...explodeEntry,
        agents: {
          cursor: {
            files: { "skills/lint/SKILL.md": "native" },
            projector: "native",
            root: "/tmp/project/.cursor/plugins/local/review",
          },
        },
        projector: "native",
      },
    });
    expect(merged.plugins.review.agents.cursor.files).toEqual({
      "skills/lint/SKILL.md": "native",
    });
    expect(merged.plugins.review.agents.cursor.root).toBe(
      "/tmp/project/.cursor/plugins/local/review",
    );
  });

  test("prunes entries that conflict with disk state", async () => {
    const { lock: pruned, pruned: names } = await pruneMissingLockEntries(
      lock,
      async (pluginId) => pluginId === "review",
    );

    expect(names).toEqual(["pdf"]);
    expect(pruned.plugins).toEqual({
      review: lock.plugins.review,
    });
  });

  test("treats a v1 lock as empty", async () => {
    const empty = await readLockfile("project", {
      cwd: "/tmp/unused",
      read: async () =>
        JSON.stringify({
          gatewayVersion: "0.20.0",
          scope: "project",
          skills: { lint: { agents: ["cursor"] } },
          version: 1,
        }),
    });

    expect(empty.version).toBe(LOCKFILE_VERSION);
    expect(empty.plugins).toEqual({});
  });

  test("reconcileLock partitions present, missing, and modified agents", async () => {
    const hashes = {
      "/tmp/project/.cursor/skills/lint/SKILL.md": "abc",
      "/tmp/project/.cursor/skills/pdf/SKILL.md": "zzz",
    };
    const result = await reconcileLock(lock, {
      exists: async (path) => path.endsWith("lint/SKILL.md") || path.endsWith("pdf/SKILL.md"),
      hash: async (path) => hashes[path] ?? "",
    });

    expect(result.present).toEqual([{ agent: "cursor", pluginId: "review" }]);
    expect(result.modified).toEqual([{ agent: "cursor", pluginId: "pdf" }]);
    expect(result.missing).toEqual([]);
  });

  test("reconcileLock reports missing when a tracked file is absent", async () => {
    const result = await reconcileLock(lock, {
      exists: async () => false,
      hash: async () => "",
    });

    expect(result.missing).toEqual([
      { agent: "cursor", pluginId: "review" },
      { agent: "cursor", pluginId: "pdf" },
    ]);
    expect(result.present).toEqual([]);
    expect(result.modified).toEqual([]);
  });

  test("rejects a lock with an unknown version", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () => JSON.stringify({ version: 99 }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("rejects a v2 lock whose plugin ids are not kebab-case", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () =>
          JSON.stringify({
            gatewayVersion: "0.0.0-dev",
            plugins: { "../../../victim": explodeEntry },
            scope: "project",
            version: LOCKFILE_VERSION,
          }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("rejects a v2 lock whose plugin entries are malformed", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () =>
          JSON.stringify({
            gatewayVersion: "0.0.0-dev",
            plugins: { lint: { agents: null, projector: "explode" } },
            scope: "project",
            version: LOCKFILE_VERSION,
          }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("rejects a v2 lock whose tracked file digests are not strings", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () =>
          JSON.stringify({
            gatewayVersion: "0.0.0-dev",
            plugins: {
              lint: {
                ...explodeEntry,
                agents: {
                  cursor: {
                    files: { "lint/SKILL.md": 12 },
                    root: "/tmp/project/.cursor/skills",
                  },
                },
              },
            },
            scope: "project",
            version: LOCKFILE_VERSION,
          }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("rejects a v2 lock whose provenance fields are not strings", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () =>
          JSON.stringify({
            gatewayVersion: "0.0.0-dev",
            plugins: { lint: { ...explodeEntry, vendor: 1 } },
            scope: "project",
            version: LOCKFILE_VERSION,
          }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("rejects a v2 lock whose plugins value is an array", async () => {
    await expect(
      readLockfile("project", {
        cwd: "/tmp/unused",
        read: async () =>
          JSON.stringify({
            gatewayVersion: "0.0.0-dev",
            plugins: [],
            scope: "project",
            version: LOCKFILE_VERSION,
          }),
      }),
    ).rejects.toThrow("Invalid gateway lockfile");
  });

  test("does not prune plugins whose tracked files are modified", async () => {
    const { lock: kept, pruned: removed } = await pruneMissingLockEntries(
      lock,
      async (pluginId, entry, scope) =>
        isPluginInstalled(pluginId, entry, scope, {
          exists: async () => true,
          hash: async () => "zzz",
        }),
    );

    expect(removed).toEqual([]);
    expect(Object.keys(kept.plugins).sort()).toEqual(["pdf", "review"]);
  });

  test("reads skill names from Cursor native trees and explicit skills lists", () => {
    expect(
      pluginSkillNames({
        ...explodeEntry,
        agents: {
          cursor: {
            files: {
              ".claude-plugin/plugin.json": "abc",
              "skills/lint/SKILL.md": "def",
              "skills/test/SKILL.md": "ghi",
            },
            root: "/tmp/.cursor/plugins/local/review",
          },
        },
      }),
    ).toEqual(["lint", "test"]);
    expect(pluginSkillNames({ ...explodeEntry, skills: ["lint", "test"] })).toEqual([
      "lint",
      "test",
    ]);
  });

  test("treats CLI-owned native installs as present without hashing", async () => {
    const entry = {
      ...explodeEntry,
      projector: "native",
      agents: {
        "claude-code": {
          files: { "lint/SKILL.md": "" },
          projector: "native",
          root: "cli:claude-code",
        },
      },
    };
    expect(isCliOwnedNativeInstall(entry.agents["claude-code"], "native")).toBe(true);
    const result = await reconcileLock(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { review: entry },
        scope: "project",
        version: LOCKFILE_VERSION,
      },
      {
        exists: async () => false,
        hash: async () => {
          throw new Error("CLI native must not hash");
        },
      },
    );
    expect(result.present).toEqual([{ agent: "claude-code", pluginId: "review" }]);
    expect(result.missing).toEqual([]);
  });

  test("does not treat an empty Cursor native file map as CLI-owned", () => {
    expect(
      isCliOwnedNativeInstall(
        {
          files: {},
          projector: "native",
          root: "/tmp/.cursor/plugins/local/review",
        },
        "native",
      ),
    ).toBe(false);
  });

  test("hashes every regular file in a plugin tree", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-hash-tree-"));
    try {
      await mkdir(join(root, ".claude-plugin"), { recursive: true });
      await writeFile(join(root, ".claude-plugin/plugin.json"), "{}\n");
      const files = await hashTree(root);
      expect(files[".claude-plugin/plugin.json"]).toMatch(/^[a-f0-9]{64}$/);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});
