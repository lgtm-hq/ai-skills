import { describe, expect, test } from "bun:test";

import { listSkills, removeSkills, updateSkills } from "../lib/gateway-commands.js";

const pluginEntry = (overrides) => ({
  agents: {
    cursor: {
      files: { "pdf/SKILL.md": "abc" },
      root: "/tmp/project/.cursor/skills",
    },
  },
  installedAt: "2026-07-10T16:00:00.000Z",
  projector: "explode",
  repo: "anthropics/skills",
  sha: "outdated",
  vendor: "anthropics",
  version: "outdated",
  ...overrides,
});

const lock = {
  gatewayVersion: "0.0.0-dev",
  plugins: {
    lint: pluginEntry({
      agents: {
        cursor: {
          files: { "lint/SKILL.md": "abc" },
          root: "/tmp/project/.cursor/skills",
        },
      },
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      vendor: "lgtm-hq",
      version: "0.0.0-dev",
    }),
    pdf: pluginEntry({}),
  },
  scope: "project",
  version: 2,
};

const options = {
  agents: ["cursor"],
  global: false,
  project: true,
  skills: [],
  yes: true,
};

describe("gateway maintenance commands", () => {
  test("updates surviving lock entries through a mocked skills CLI", async () => {
    const calls = [];
    let written;
    const result = await updateSkills(options, {
      isInstalled: async (name) => name === "pdf",
      now: () => new Date("2026-07-10T17:00:00.000Z"),
      readLock: async () => lock,
      run: async (args) => {
        calls.push(args);
      },
      writeLock: async (next) => {
        written = next;
      },
    });

    expect(result).toEqual({
      pruned: ["lint"],
      updated: ["pdf"],
    });
    expect(calls).toEqual([
      [
        "skills@^1.5.0",
        "add",
        "anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        "-a",
        "cursor",
        "--skill",
        "pdf",
        "-y",
      ],
    ]);
    expect(written.plugins.pdf).toMatchObject({
      installedAt: "2026-07-10T17:00:00.000Z",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    });
    expect(written.plugins.lint).toBeUndefined();
    expect(written.skills).toBeUndefined();
  });

  test("removes only lock-managed selections after mocked CLI success", async () => {
    const calls = [];
    let written;
    const removed = await removeSkills(
      {
        ...options,
        skills: ["pdf"],
      },
      {
        readLock: async () => lock,
        run: async (args) => {
          calls.push(args);
        },
        writeLock: async (next) => {
          written = next;
        },
      },
    );

    expect(removed).toEqual(["pdf"]);
    expect(calls).toEqual([["skills@^1.5.0", "remove", "pdf", "-a", "cursor", "-y"]]);
    expect(written.plugins).toEqual({
      lint: lock.plugins.lint,
    });
  });

  test("lists lock-managed installs in name order", async () => {
    const plugins = await listSkills(options, {
      lockEnvironment: {
        exists: async () => true,
        hash: async () => "abc",
      },
      readLock: async () => lock,
    });

    expect(plugins.map((plugin) => plugin.name)).toEqual(["lint", "pdf"]);
    expect(plugins.every((plugin) => plugin.status === "")).toBe(true);
  });

  test("annotates missing and modified plugins instead of listing them as healthy", async () => {
    const plugins = await listSkills(options, {
      lockEnvironment: {
        exists: async (path) => String(path).endsWith("lint/SKILL.md"),
        hash: async () => "zzz",
      },
      readLock: async () => lock,
    });

    expect(plugins).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "lint", status: "MODIFIED" }),
        expect.objectContaining({ name: "pdf", status: "MISSING" }),
      ]),
    );
  });
});
