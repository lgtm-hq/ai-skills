import { describe, expect, test } from "bun:test";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadVendorIndex } from "../lib/catalog.js";
import { batchesFromCliOptions, install } from "../lib/install.js";
import { MINIMUM_SKILLS_VERSION } from "../lib/options.js";
import { buildSkillsArguments } from "../lib/skills-runner.js";

const unattendedOptions = {
  agents: ["cursor"],
  bundle: "review",
  copy: false,
  global: true,
  onConflict: "overwrite",
  project: false,
  skills: ["lint", "test"],
  vendor: null,
  yes: true,
};

/**
 * Project-scope v2 lock tracking lint on the given agents.
 *
 * @param {string} cwd - Project root.
 * @param {Record<string, string>} agentHashes - Agent id to expected lint/SKILL.md hash.
 * @returns {object} Gateway lock.
 */
function staleProjectLock(cwd, agentHashes) {
  const agentRoots = {
    "claude-code": ".claude/skills",
    cursor: ".cursor/skills",
  };
  const agents = Object.fromEntries(
    Object.entries(agentHashes).map(([agent, digest]) => [
      agent,
      {
        files: { "lint/SKILL.md": digest },
        root: join(cwd, agentRoots[agent]),
      },
    ]),
  );
  return {
    gatewayVersion: "0.0.0-dev",
    plugins: {
      lint: {
        agents,
        installedAt: "2026-07-10T16:00:00.000Z",
        projector: "explode",
        repo: "lgtm-hq/ai-skills",
        sha: "v0.0.0-dev",
        vendor: "lgtm-hq",
        version: "0.0.0-dev",
      },
    },
    scope: "project",
    version: 2,
  };
}

describe("buildSkillsArguments", () => {
  test("pins a published skills 1.x floor", () => {
    expect(MINIMUM_SKILLS_VERSION).toMatch(/^1\.\d+\.\d+$/);
    expect(buildSkillsArguments(unattendedOptions, "lgtm-hq/ai-skills@v1.2.3")[0]).toBe(
      `skills@^${MINIMUM_SKILLS_VERSION}`,
    );
  });

  test("preserves scope and symlink defaults without forwarding on-conflict", () => {
    expect(buildSkillsArguments(unattendedOptions, "lgtm-hq/ai-skills@v1.2.3")).toEqual([
      "skills@^1.5.0",
      "add",
      "lgtm-hq/ai-skills@v1.2.3",
      "-g",
      "-a",
      "cursor",
      "--skill",
      "lint",
      "test",
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
      expect(lock.version).toBe(2);
      expect(lock.plugins.review).toMatchObject({
        projector: "explode",
        repo: "lgtm-hq/ai-skills",
        vendor: "lgtm-hq",
      });
      expect(lock.plugins.review.installedAt).toBe("2026-07-10T16:00:00.000Z");
      expect(lock.plugins.review.agents.cursor.files).toMatchObject({
        "lint/SKILL.md": "",
        "test/SKILL.md": "",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects the retired pre-push bundle key", async () => {
    await expect(
      batchesFromCliOptions({ bundle: "pre-push", skills: [], vendor: null }),
    ).rejects.toThrow("Unknown first-party plugin: pre-push");
  });

  test("rejects the retired agents bundle key", async () => {
    await expect(
      batchesFromCliOptions({ bundle: "agents", skills: [], vendor: null }),
    ).rejects.toThrow("Unknown first-party plugin: agents");
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
      expect(lock.plugins.anthropics).toMatchObject({
        projector: "explode",
        repo: "anthropics/skills",
        sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        vendor: "anthropics",
      });
      expect(lock.plugins.anthropics.agents.cursor.files).toEqual({ "pdf/SKILL.md": "" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("installs a plugin-buried claude-code skill from the baked index", async () => {
    let received = [];
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["frontend-design"],
          vendor: "anthropics-claude-code",
        },
        async (args) => {
          received = args;
        },
        undefined,
        { cwd },
      );

      expect(received).toContain("anthropics/claude-code@15a21e1b4e240e2da6a4953d5f148a806c9c9bb2");
      expect(received).toContain("--skill");
      expect(received).toContain("frontend-design");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins["anthropics-claude-code"]).toMatchObject({
        projector: "explode",
        repo: "anthropics/claude-code",
        sha: "15a21e1b4e240e2da6a4953d5f148a806c9c9bb2",
        vendor: "anthropics-claude-code",
      });
      expect(lock.plugins["anthropics-claude-code"].agents.cursor.files).toEqual({
        "frontend-design/SKILL.md": "",
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
      expect(lock.version).toBe(2);
      expect(lock.plugins.lint.vendor).toBe("lgtm-hq");
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

  test("repairs a stale lock whose tracked files are absent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-repair-"));
    let received = [];
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(staleProjectLock(cwd, { cursor: "abc" }), null, 2)}\n`,
      );
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async () => false,
          hash: async () => "",
        },
      );

      expect(received).toContain("--skill");
      expect(received).toContain("lint");
      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 1 });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repairs a lock whose tracked hashes no longer match disk", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-modified-"));
    let received = [];
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(staleProjectLock(cwd, { cursor: "old" }), null, 2)}\n`,
      );
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async () => true,
          hash: async () => "new",
        },
      );

      expect(received).toContain("--skill");
      expect(received).toContain("lint");
      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 1 });
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toBe("new");
      expect(lock.plugins.lint.installedAt).toBe("2026-07-10T17:00:00.000Z");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("skips a healthy install whose hashes still match disk", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-healthy-"));
    let ran = false;
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(staleProjectLock(cwd, { cursor: "abc" }), null, 2)}\n`,
      );
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {
          ran = true;
        },
        undefined,
        {
          cwd,
          exists: async () => true,
          hash: async () => "abc",
        },
      );

      expect(ran).toBe(false);
      expect(result).toEqual({ alreadyPresent: 1, installed: 0, repaired: 0 });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repairs only the agent whose tracked files are missing", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-partial-"));
    let received = [];
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          staleProjectLock(cwd, { "claude-code": "abc", cursor: "abc" }),
          null,
          2,
        )}\n`,
      );
      const cursorRoot = join(cwd, ".cursor/skills");
      const result = await install(
        {
          ...unattendedOptions,
          agents: ["claude-code", "cursor"],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async (args) => {
          received = args;
        },
        undefined,
        {
          cwd,
          exists: async (path) => String(path).startsWith(cursorRoot),
          hash: async () => "abc",
        },
      );

      expect(received).toContain("claude-code");
      expect(received.includes("cursor")).toBe(false);
      expect(result).toEqual({ alreadyPresent: 1, installed: 0, repaired: 1 });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("runs the skills CLI when agents are left empty for detection", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-"));
    let received = [];
    try {
      const result = await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
      );

      expect(received).toContain("--skill");
      expect(received).toContain("lint");
      expect(received.includes("-a")).toBe(false);
      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 0 });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("records detected agents after an untargeted install", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-lock-"));
    const cursorSkill = join(cwd, ".cursor/skills/lint/SKILL.md");
    try {
      await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {},
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async (path) => path === cursorSkill,
          hash: async () => "abc",
        },
      );

      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(Object.keys(lock.plugins.lint.agents)).toEqual(["cursor"]);
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toBe("abc");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("detect mode records only skills that exist on a discovered agent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-partial-"));
    const cursorLint = join(cwd, ".cursor/skills/lint/SKILL.md");
    try {
      await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint", "test"],
        },
        async () => {},
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async (path) => path === cursorLint,
          hash: async () => "abc",
        },
      );

      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor.files).toEqual({ "lint/SKILL.md": "abc" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not write a lock when detect-mode finds no installed agents", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-empty-"));
    try {
      await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {},
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async () => false,
        },
      );

      await expect(readFile(join(cwd, "ai-skills-lock.json"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("treats a v1 lock as empty and installs instead of skipping", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-v1-"));
    let ran = false;
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.20.0",
            scope: "project",
            skills: {
              lint: {
                agents: ["cursor"],
                installedAt: "2026-07-10T16:00:00.000Z",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.20.0",
                skillPath: "skills/lint/SKILL.md",
                vendor: "lgtm-hq",
              },
            },
            version: 1,
          },
          null,
          2,
        )}\n`,
      );
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {
          ran = true;
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
      );

      expect(ran).toBe(true);
      expect(result).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.version).toBe(2);
      expect(lock.plugins.lint.vendor).toBe("lgtm-hq");
      expect(lock.skills).toBeUndefined();
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("installs newly requested skills on an otherwise healthy plugin", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-add-skill-"));
    let received = [];
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              anthropics: {
                agents: {
                  cursor: {
                    files: { "pdf/SKILL.md": "abc" },
                    root: join(cwd, ".cursor/skills"),
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "explode",
                repo: "anthropics/skills",
                sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
                vendor: "anthropics",
                version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["pdf", "xlsx"],
          vendor: "anthropics",
        },
        async (args) => {
          received = args;
        },
        undefined,
        {
          cwd,
          exists: async () => true,
          hash: async () => "abc",
        },
      );

      expect(received).toContain("xlsx");
      expect(result).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.anthropics.agents.cursor.files).toMatchObject({
        "pdf/SKILL.md": "abc",
        "xlsx/SKILL.md": "abc",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps a stable vendor plugin id when adding a second skill", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-vendor-id-"));
    const env = {
      cwd,
      exists: async () => true,
      hash: async () => "abc",
    };
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
        async () => {},
        () => new Date("2026-07-10T16:00:00.000Z"),
        env,
      );
      const first = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(first.plugins.pdf).toBeUndefined();
      expect(first.plugins.anthropics.agents.cursor.files).toEqual({ "pdf/SKILL.md": "abc" });

      let received = [];
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["pdf", "xlsx"],
          vendor: "anthropics",
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        env,
      );

      expect(received).toContain("xlsx");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.anthropics.agents.cursor.files).toMatchObject({
        "pdf/SKILL.md": "abc",
        "xlsx/SKILL.md": "abc",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back newly written skill directories when the skills CLI fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-atomic-cli-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    const testDir = join(cwd, ".cursor/skills/test");
    try {
      await mkdir(lintDir, { recursive: true });
      await writeFile(join(lintDir, "SKILL.md"), "keep\n");
      await expect(
        install(
          {
            ...unattendedOptions,
            bundle: null,
            global: false,
            project: true,
            skills: ["lint", "test"],
          },
          async () => {
            await mkdir(testDir, { recursive: true });
            await writeFile(join(testDir, "SKILL.md"), "partial\n");
            throw new Error("skills CLI failed");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
        ),
      ).rejects.toThrow("skills CLI failed");

      expect(await readFile(join(lintDir, "SKILL.md"), "utf8")).toBe("keep\n");
      await expect(access(testDir)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(access(join(cwd, "ai-skills-lock.json"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back newly written skill directories when lock update fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-atomic-lock-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    try {
      await expect(
        install(
          {
            ...unattendedOptions,
            bundle: null,
            global: false,
            project: true,
            skills: ["lint"],
          },
          async () => {
            await mkdir(lintDir, { recursive: true });
            await writeFile(join(lintDir, "SKILL.md"), "partial\n");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("disk full");
            },
          },
        ),
      ).rejects.toThrow("gateway lock update failed");

      await expect(access(lintDir)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("writes a lock when lockEnvironment is omitted", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-no-env-"));
    const previous = process.cwd();
    try {
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      process.chdir(cwd);
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {},
        () => new Date("2026-07-10T16:00:00.000Z"),
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toMatch(/^[a-f0-9]{64}$/);
    } finally {
      process.chdir(previous);
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("writes a lock when lockEnvironment is explicitly null", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-null-env-"));
    const previous = process.cwd();
    try {
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      process.chdir(cwd);
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        async () => {},
        () => new Date("2026-07-10T16:00:00.000Z"),
        null,
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toMatch(/^[a-f0-9]{64}$/);
    } finally {
      process.chdir(previous);
      await rm(cwd, { force: true, recursive: true });
    }
  });
});

describe("install conflict policy", () => {
  test("rejects unsupported keep/skip even outside -y", async () => {
    await expect(
      install({
        ...unattendedOptions,
        yes: false,
        onConflict: "keep",
      }),
    ).rejects.toThrow("--on-conflict=keep is unsupported");
  });
});
