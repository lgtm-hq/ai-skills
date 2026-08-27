import { describe, expect, test } from "bun:test";

import {
  LOCKFILE_VERSION,
  isPluginInstalled,
  mergeLockEntries,
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
});
