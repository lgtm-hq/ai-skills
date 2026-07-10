import { describe, expect, test } from "bun:test";

import { mergeLockEntries, pruneMissingLockEntries } from "../lib/lockfile.js";

const lock = {
  gatewayVersion: "0.0.0-dev",
  scope: "project",
  skills: {
    lint: {
      agents: ["claude-code"],
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
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      skillPath: "skills/pdf/SKILL.md",
      vendor: "anthropics",
    },
  },
  version: 1,
};

describe("gateway lockfile", () => {
  test("merges overlapping installs without dropping tracked agents", () => {
    const merged = mergeLockEntries(lock, {
      lint: {
        ...lock.skills.lint,
        agents: ["cursor"],
        installedAt: "2026-07-10T17:00:00.000Z",
      },
    });

    expect(merged.skills.lint.agents).toEqual(["claude-code", "cursor"]);
    expect(merged.skills.pdf).toEqual(lock.skills.pdf);
  });

  test("prunes entries that conflict with disk state", async () => {
    const { lock: pruned, pruned: names } = await pruneMissingLockEntries(
      lock,
      async (name) => name === "lint",
    );

    expect(names).toEqual(["pdf"]);
    expect(pruned.skills).toEqual({
      lint: lock.skills.lint,
    });
  });
});
