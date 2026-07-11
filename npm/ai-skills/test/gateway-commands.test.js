import { describe, expect, test } from "bun:test";

import { listSkills, removeSkills, updateSkills } from "../lib/gateway-commands.js";

const lock = {
  gatewayVersion: "0.0.0-dev",
  scope: "project",
  skills: {
    lint: {
      agents: ["cursor"],
      installedAt: "2026-07-10T16:00:00.000Z",
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      skillPath: "skills/lint/SKILL.md",
      vendor: "lgtm-hq",
    },
    pdf: {
      agents: ["cursor"],
      installedAt: "2026-07-10T16:00:00.000Z",
      repo: "anthropics/skills",
      sha: "outdated",
      skillPath: "skills/pdf/SKILL.md",
      vendor: "anthropics",
    },
  },
  version: 1,
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
    expect(written.skills.pdf).toMatchObject({
      installedAt: "2026-07-10T17:00:00.000Z",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    });
    expect(written.skills.lint).toBeUndefined();
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
    expect(written.skills).toEqual({
      lint: lock.skills.lint,
    });
  });

  test("lists lock-managed installs in name order", async () => {
    const skills = await listSkills(options, {
      readLock: async () => lock,
    });

    expect(skills.map((skill) => skill.name)).toEqual(["lint", "pdf"]);
  });
});
