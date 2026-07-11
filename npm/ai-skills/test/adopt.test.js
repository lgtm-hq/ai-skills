import { describe, expect, test } from "bun:test";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  adoptSkills,
  mapSkillsLockEntry,
  planAdopt,
  readSkillsLock,
  scanInstalledSkills,
} from "../lib/adopt.js";
import { parseArguments, validateUnattendedCommandOptions } from "../lib/options.js";

const vendors = [
  { id: "anthropics", repo: "anthropics/skills" },
  { id: "mattpocock", repo: "mattpocock/skills" },
];

describe("parseArguments adopt", () => {
  test("accepts an unattended project adopt", () => {
    const parsed = parseArguments(["adopt", "-y", "--project"]);
    expect(parsed.command).toBe("adopt");
    expect(() =>
      validateUnattendedCommandOptions(parsed.options, { requireAgents: false }),
    ).not.toThrow();
  });

  test("rejects install source options on adopt", () => {
    expect(() => parseArguments(["adopt", "--vendor", "anthropics"])).toThrow(
      "does not accept install source options",
    );
  });
});

describe("adoptSkills scope", () => {
  test("requires an explicit scope even interactively", async () => {
    await expect(
      adoptSkills({
        agents: [],
        global: false,
        project: false,
        yes: false,
      }),
    ).rejects.toThrow("adopt requires an explicit --global or --project scope");
  });
});

describe("mapSkillsLockEntry", () => {
  test("maps a github skills-lock entry onto a gateway lock record", () => {
    const mapped = mapSkillsLockEntry(
      "pdf",
      {
        sourceType: "github",
        sourceUrl: "https://github.com/anthropics/skills.git",
        ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        skillPath: "skills/pdf/SKILL.md",
      },
      ["cursor"],
      vendors,
      () => new Date("2026-07-10T21:00:00.000Z"),
    );

    expect(mapped).toEqual({
      entry: {
        agents: ["cursor"],
        installedAt: "2026-07-10T21:00:00.000Z",
        repo: "anthropics/skills",
        sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        skillPath: "skills/pdf/SKILL.md",
        vendor: "anthropics",
      },
    });
  });

  test("marks entries without a ref as ambiguous", () => {
    expect(
      mapSkillsLockEntry("pdf", { sourceUrl: "anthropics/skills" }, ["cursor"], vendors),
    ).toEqual({
      ambiguous: "pdf: skills-lock entry has no commit/tag ref",
    });
  });

  test("marks non-registry sources as ambiguous instead of vendor=external", () => {
    expect(
      mapSkillsLockEntry(
        "weird",
        {
          sourceUrl: "someone/else",
          ref: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
        ["cursor"],
        vendors,
      ),
    ).toEqual({
      ambiguous: "weird: source someone/else is not in the gateway vendor registry",
    });
  });

  test("normalizes matched vendor repo casing from the registry", () => {
    const mapped = mapSkillsLockEntry(
      "pdf",
      {
        sourceUrl: "https://github.com/Anthropics/Skills.git",
        ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      },
      ["cursor"],
      vendors,
      () => new Date("2026-07-10T21:00:00.000Z"),
    );
    expect(mapped).toMatchObject({
      entry: {
        repo: "anthropics/skills",
        vendor: "anthropics",
      },
    });
  });
});

describe("planAdopt", () => {
  test("adopts lock-backed installs and reports ambiguous disk-only skills", () => {
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        scope: "project",
        skills: {},
        version: 1,
      },
      {
        pdf: ["cursor"],
        orphan: ["claude-code"],
      },
      {
        pdf: {
          sourceUrl: "anthropics/skills",
          ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
          skillPath: "skills/pdf",
        },
      },
      vendors,
      () => new Date("2026-07-10T21:00:00.000Z"),
    );

    expect(plan.adopt.pdf).toMatchObject({
      vendor: "anthropics",
      skillPath: "skills/pdf/SKILL.md",
    });
    expect(plan.skippedMissingLock).toEqual(["orphan"]);
    expect(plan.ambiguous).toEqual(["orphan: installed on disk but absent from skills-lock.json"]);
  });

  test("merges agents into an existing gateway entry without overwriting provenance", () => {
    const existing = {
      agents: ["claude-code"],
      installedAt: "2026-07-10T16:00:00.000Z",
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      skillPath: "skills/pdf/SKILL.md",
      vendor: "anthropics",
    };
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        scope: "project",
        skills: { pdf: existing },
        version: 1,
      },
      { pdf: ["cursor"] },
      {
        pdf: {
          sourceUrl: "someone/else",
          ref: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
      },
      vendors,
    );

    expect(plan.adopt.pdf).toEqual({
      ...existing,
      agents: ["claude-code", "cursor"],
    });
  });
});

describe("adoptSkills", () => {
  test("writes a gateway lock from skills-lock installs without calling skills CLI", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-adopt-"));
    try {
      await mkdir(join(cwd, ".cursor/skills/pdf"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/pdf/SKILL.md"), "# pdf\n");
      await writeFile(
        join(cwd, "skills-lock.json"),
        `${JSON.stringify(
          {
            version: 1,
            skills: {
              pdf: {
                sourceType: "github",
                sourceUrl: "https://github.com/anthropics/skills",
                ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
                skillPath: "skills/pdf/SKILL.md",
              },
            },
          },
          null,
          2,
        )}\n`,
      );

      const lines = [];
      const result = await adoptSkills(
        {
          agents: [],
          global: false,
          project: true,
          yes: true,
        },
        {
          loadVendors: async () => ({ vendors }),
          now: () => new Date("2026-07-10T21:00:00.000Z"),
          readLock: async () => ({
            gatewayVersion: "0.0.0-dev",
            scope: "project",
            skills: {},
            version: 1,
          }),
          readSkillsLock: async () => readSkillsLock("project", { cwd }),
          scanInstalled: async () => scanInstalledSkills("project", { cwd }),
          writeLock: async (lock) => {
            await writeFile(join(cwd, "ai-skills-lock.json"), `${JSON.stringify(lock, null, 2)}\n`);
          },
          write: (line) => lines.push(line),
        },
      );

      expect(result.wrote).toBe(true);
      expect(result.adopted).toEqual(["pdf"]);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.skills.pdf).toMatchObject({
        agents: ["cursor"],
        repo: "anthropics/skills",
        vendor: "anthropics",
      });
      expect(lines.join("\n")).toContain("Adopt plan:");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("skips ambiguous disk-only skills under -y and leaves the lock unchanged when nothing maps", async () => {
    const result = await adoptSkills(
      {
        agents: [],
        global: false,
        project: true,
        yes: true,
      },
      {
        loadVendors: async () => ({ vendors }),
        readLock: async () => ({
          gatewayVersion: "0.0.0-dev",
          scope: "project",
          skills: {},
          version: 1,
        }),
        readSkillsLock: async () => ({ version: 1, skills: {} }),
        scanInstalled: async () => ({ mystery: ["cursor"] }),
        writeLock: async () => {
          throw new Error("should not write");
        },
        write: () => {},
      },
    );

    expect(result.wrote).toBe(false);
    expect(result.adopted).toEqual([]);
    expect(result.ambiguous).toEqual([
      "mystery: installed on disk but absent from skills-lock.json",
    ]);
  });
});
