import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadVendorIndex } from "../lib/catalog.js";
import { install } from "../lib/install.js";
import { buildSkillsArguments } from "../lib/skills-runner.js";

const unattendedOptions = {
  agents: ["cursor"],
  bundle: "pre-push",
  copy: false,
  global: true,
  onConflict: "overwrite",
  project: false,
  skills: ["lint", "test"],
  vendor: null,
  yes: true,
};

describe("buildSkillsArguments", () => {
  test("preserves scope, conflict, and symlink defaults", () => {
    expect(buildSkillsArguments(unattendedOptions, "lgtm-hq/ai-skills@v1.2.3")).toEqual([
      "skills@^0.16.0",
      "add",
      "lgtm-hq/ai-skills@v1.2.3",
      "-g",
      "-a",
      "cursor",
      "--skill",
      "lint",
      "test",
      "--on-conflict",
      "overwrite",
      "-y",
    ]);
  });
});

describe("install", () => {
  test("rejects a vendor path traversal attempt", () => {
    expect(() => loadVendorIndex("../outside")).toThrow("Invalid vendor identifier");
  });

  test("expands an unattended first-party bundle", async () => {
    let received = [];
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          global: false,
          project: true,
          skills: [],
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
      );

      expect(received).toContain("--skill");
      expect(received).toContain("lint");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.skills.lint).toMatchObject({
        agents: ["cursor"],
        repo: "lgtm-hq/ai-skills",
        skillPath: "skills/lint/SKILL.md",
        vendor: "lgtm-hq",
      });
      expect(lock.skills.lint.installedAt).toBe("2026-07-10T16:00:00.000Z");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("uses the pinned vendor source from baked data", async () => {
    let received = [];
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["pdf"],
          vendor: "anthropics",
        },
        async (args) => {
          received = args;
        },
        undefined,
        { cwd },
      );

      expect(received).toContain("anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.skills.pdf).toMatchObject({
        repo: "anthropics/skills",
        sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        skillPath: "skills/pdf/SKILL.md",
        vendor: "anthropics",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects skills absent from the selected vendor catalog", async () => {
    await expect(
      install(
        {
          ...unattendedOptions,
          bundle: null,
          skills: ["typo"],
          vendor: "anthropics",
        },
        async () => {},
      ),
    ).rejects.toThrow("Unknown skill for vendor anthropics: typo");
  });

  test("defaults unset scope to global for both CLI and lock", async () => {
    let received = [];
    const home = await mkdtemp(join(tmpdir(), "ai-skills-home-"));
    try {
      await install(
        {
          ...unattendedOptions,
          global: false,
          project: false,
          skills: ["lint"],
          bundle: null,
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { home },
      );

      expect(received).toContain("-g");
      const lock = JSON.parse(await readFile(join(home, ".ai-skills", "lock.json"), "utf8"));
      expect(lock.scope).toBe("global");
      expect(lock.skills.lint.vendor).toBe("lgtm-hq");
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("fails closed on a malformed lock before invoking skills", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-bad-lock-"));
    let ran = false;
    try {
      await Bun.write(join(cwd, "ai-skills-lock.json"), '{"version":99}\n');
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            project: true,
            skills: ["lint"],
            bundle: null,
          },
          async () => {
            ran = true;
          },
          undefined,
          { cwd },
        ),
      ).rejects.toThrow("Invalid gateway lockfile");
      expect(ran).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });
});
