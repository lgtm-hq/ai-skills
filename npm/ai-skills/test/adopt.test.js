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
        agents: {
          cursor: {
            files: { "pdf/SKILL.md": "" },
            root: expect.stringMatching(/[/\\]\.cursor[/\\]skills$/),
          },
        },
        installedAt: "2026-07-10T21:00:00.000Z",
        projector: "explode",
        repo: "anthropics/skills",
        sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        vendor: "anthropics",
        version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
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
        plugins: {},
        version: 2,
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

    expect(plan.adopt.anthropics).toMatchObject({
      vendor: "anthropics",
      projector: "explode",
    });
    expect(plan.adopt.anthropics.agents.cursor.files).toEqual({ "pdf/SKILL.md": "" });
    expect(plan.adopt.pdf).toBeUndefined();
    expect(plan.skippedMissingLock).toEqual(["orphan"]);
    expect(plan.ambiguous).toEqual(["orphan: installed on disk but absent from skills-lock.json"]);
  });

  test("merges agents into an existing gateway entry without overwriting provenance", () => {
    const existing = {
      agents: {
        "claude-code": {
          files: { "pdf/SKILL.md": "" },
          root: "/tmp/project/.claude/skills",
        },
      },
      installedAt: "2026-07-10T16:00:00.000Z",
      projector: "explode",
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      vendor: "anthropics",
      version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    };
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { pdf: existing },
        scope: "project",
        version: 2,
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

    expect(plan.adopt.pdf).toMatchObject({
      installedAt: existing.installedAt,
      repo: existing.repo,
      sha: existing.sha,
      vendor: existing.vendor,
    });
    expect(Object.keys(plan.adopt.pdf.agents).sort()).toEqual(["claude-code", "cursor"]);
    expect(plan.adopt.pdf.agents["claude-code"]).toEqual(existing.agents["claude-code"]);
  });

  test("merges adopted explode skills into the plugin that already tracks them", () => {
    const review = {
      agents: {
        cursor: {
          files: { "lint/SKILL.md": "abc", "test/SKILL.md": "abc" },
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
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { review },
        scope: "project",
        version: 2,
      },
      { lint: ["cursor"] },
      {},
      vendors,
      undefined,
      { cwd: "/tmp/project" },
    );

    expect(plan.alreadyTracked).toEqual(["lint"]);
    expect(plan.adopt).toEqual({});
  });

  test("keys vendor skills by vendor id and unions later directories onto that plugin", () => {
    const existing = {
      agents: {
        cursor: {
          files: { "pdf/SKILL.md": "abc" },
          root: "/tmp/project/.cursor/skills",
        },
      },
      installedAt: "2026-07-10T16:00:00.000Z",
      projector: "explode",
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      vendor: "anthropics",
      version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    };
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { anthropics: existing },
        scope: "project",
        version: 2,
      },
      { xlsx: ["cursor"] },
      {
        xlsx: {
          sourceUrl: "anthropics/skills",
          ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        },
      },
      vendors,
      undefined,
      { cwd: "/tmp/project" },
    );

    expect(plan.adopt.anthropics.agents.cursor.files).toEqual({
      "pdf/SKILL.md": "abc",
      "xlsx/SKILL.md": "",
    });
    expect(plan.adopt.anthropics.sha).toBe("9d2f1ae187231d8199c64b5b762e1bdf2244733d");
    expect(plan.adopt.xlsx).toBeUndefined();
  });

  test("reports same-vendor skills at different refs as ambiguous", () => {
    const existing = {
      agents: {
        cursor: {
          files: { "pdf/SKILL.md": "abc" },
          root: "/tmp/project/.cursor/skills",
        },
      },
      installedAt: "2026-07-10T16:00:00.000Z",
      projector: "explode",
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      vendor: "anthropics",
      version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    };
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { anthropics: existing },
        scope: "project",
        version: 2,
      },
      { xlsx: ["cursor"] },
      {
        xlsx: {
          sourceUrl: "anthropics/skills",
          ref: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
      },
      vendors,
      undefined,
      { cwd: "/tmp/project" },
    );

    expect(plan.adopt).toEqual({});
    expect(plan.ambiguous).toEqual([
      "xlsx: vendor anthropics provenance anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d (explode) conflicts with anthropics/skills@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb (explode)",
    ]);
  });

  test("does not union two same-vendor skills that pin different refs", () => {
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: {},
        scope: "project",
        version: 2,
      },
      { pdf: ["cursor"], xlsx: ["cursor"] },
      {
        pdf: {
          sourceUrl: "anthropics/skills",
          ref: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        },
        xlsx: {
          sourceUrl: "anthropics/skills",
          ref: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
      },
      vendors,
      () => new Date("2026-07-10T21:00:00.000Z"),
      { cwd: "/tmp/project" },
    );

    expect(Object.keys(plan.adopt.anthropics.agents.cursor.files)).toHaveLength(1);
    expect(plan.ambiguous).toHaveLength(1);
    expect(plan.ambiguous[0]).toContain("conflicts with");
  });

  test("rewrites stale agent roots after the project directory moves", () => {
    const existing = {
      agents: {
        cursor: {
          files: { "lint/SKILL.md": "abc" },
          root: "/old/project/.cursor/skills",
        },
      },
      installedAt: "2026-07-10T16:00:00.000Z",
      projector: "explode",
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      vendor: "lgtm-hq",
      version: "0.0.0-dev",
    };
    const plan = planAdopt(
      {
        gatewayVersion: "0.0.0-dev",
        plugins: { review: existing },
        scope: "project",
        version: 2,
      },
      { lint: ["cursor"] },
      {},
      vendors,
      undefined,
      { cwd: "/new/project" },
    );

    expect(plan.alreadyTracked).toEqual([]);
    expect(plan.adopt.review.agents.cursor.root).toBe(join("/new/project", ".cursor/skills"));
    expect(plan.adopt.review.agents.cursor.files).toEqual({ "lint/SKILL.md": "abc" });
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
          pathEnvironment: { cwd },
          readLock: async () => ({
            gatewayVersion: "0.0.0-dev",
            plugins: {},
            scope: "project",
            version: 2,
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
      expect(result.adopted).toEqual(["anthropics"]);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.anthropics).toMatchObject({
        projector: "explode",
        repo: "anthropics/skills",
        vendor: "anthropics",
      });
      expect(Object.keys(lock.plugins.anthropics.agents)).toEqual(["cursor"]);
      expect(lock.plugins.anthropics.agents.cursor.files["pdf/SKILL.md"]).toMatch(/^[0-9a-f]{64}$/);
      expect(lines.join("\n")).toContain("Adopt plan:");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("default lock reader and writer honor pathEnvironment", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-adopt-path-"));
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
          pathEnvironment: { cwd },
          write: () => {},
        },
      );

      expect(result.wrote).toBe(true);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.anthropics.vendor).toBe("anthropics");
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
          plugins: {},
          scope: "project",
          version: 2,
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
