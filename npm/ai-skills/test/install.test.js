import { describe, expect, test } from "bun:test";

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
  test("expands an unattended first-party bundle", async () => {
    let received = [];
    await install(
      {
        ...unattendedOptions,
        skills: [],
      },
      async (args) => {
        received = args;
      },
    );

    expect(received).toContain("--skill");
    expect(received).toContain("lint");
  });

  test("uses the pinned vendor source from baked data", async () => {
    let received = [];
    await install(
      {
        ...unattendedOptions,
        bundle: null,
        skills: ["pdf"],
        vendor: "anthropics",
      },
      async (args) => {
        received = args;
      },
    );

    expect(received).toContain("anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d");
  });
});
