import { describe, expect, test } from "bun:test";
import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadVendorIndex } from "../lib/catalog.js";
import { writeDoctorCache, runDoctor } from "../lib/doctor.js";
import { batchesFromCliOptions, install } from "../lib/install.js";
import { removeSkills, updateSkills } from "../lib/gateway-commands.js";
import { readLockfile, writeLockfile } from "../lib/lockfile.js";
import { MINIMUM_SKILLS_VERSION } from "../lib/options.js";
import { buildSkillsArguments } from "../lib/skills-runner.js";

const unattendedOptions = {
  agents: ["cursor"],
  bundle: "review",
  copy: false,
  global: true,
  onConflict: "overwrite",
  // Explicit explode keeps pre-native tests off the catalog-checkout path.
  // Production default is native; projector:null cases cover that below.
  projector: "explode",
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
        { sourceRoot: null },
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
    ).rejects.toThrow("Unknown plugin: pre-push");
  });

  test("rejects the retired agents bundle key", async () => {
    await expect(
      batchesFromCliOptions({ bundle: "agents", skills: [], vendor: null }),
    ).rejects.toThrow("Unknown plugin: agents");
  });

  test("explodes a baked vendor plugin from plugins-baked", async () => {
    let ran = false;
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: "hookify",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          ran = true;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
      );

      expect(ran).toBe(false);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.hookify).toMatchObject({
        projector: "explode",
        repo: "anthropics/claude-code",
        sha: "15a21e1b4e240e2da6a4953d5f148a806c9c9bb2",
        vendor: "anthropics-claude-code",
        version: "15a21e1",
        skills: ["writing-rules"],
      });
      expect(lock.plugins.hookify.agents.cursor.files["writing-rules/SKILL.md"]).toBeTruthy();
      await access(join(cwd, ".cursor/skills/writing-rules/SKILL.md"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not rematerialize a baked plugin whose pin and short version match", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-baked-update-"));
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: "hookify",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          throw new Error("skills CLI must not run for baked plugins");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
      );
      const lockPath = join(cwd, "ai-skills-lock.json");
      const before = JSON.parse(await readFile(lockPath, "utf8"));
      let exploded = false;
      const result = await updateSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: [],
          yes: true,
        },
        {
          explode: async () => {
            exploded = true;
            return { claimed: {}, skipped: [], swappedDests: [] };
          },
          isInstalled: async () => true,
          lockEnvironment: { cwd },
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          readLock: (scope) => readLockfile(scope, { cwd }),
          run: async () => {
            throw new Error("skills CLI must not run for baked plugins");
          },
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      const after = JSON.parse(await readFile(lockPath, "utf8"));
      expect(exploded).toBe(false);
      expect(result).toEqual({ pruned: [], updated: [] });
      expect(after.plugins.hookify.installedAt).toBe(before.plugins.hookify.installedAt);
      expect(after.plugins.hookify.version).toBe("15a21e1");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects detect-agent installs for baked vendor plugins", async () => {
    let ran = false;
    await expect(
      install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: "hookify",
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          ran = true;
        },
      ),
    ).rejects.toThrow("Vendor plugin installs require -a/--agent");
    expect(ran).toBe(false);
  });

  test("installs a renamed claude-code skill from the baked plugin tree", async () => {
    let ran = false;
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: "claude-code-frontend-design",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          ran = true;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
      );

      expect(ran).toBe(false);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins["claude-code-frontend-design"]).toMatchObject({
        projector: "explode",
        repo: "anthropics/claude-code",
        sha: "15a21e1b4e240e2da6a4953d5f148a806c9c9bb2",
        vendor: "anthropics-claude-code",
        version: "15a21e1",
      });
      expect(
        lock.plugins["claude-code-frontend-design"].agents.cursor.files[
          "frontend-design-claude-code/SKILL.md"
        ],
      ).toBeTruthy();
      await access(join(cwd, ".cursor/skills/frontend-design-claude-code/SKILL.md"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects skills absent from the selected vendor catalog", async () => {
    await expect(
      install(
        {
          ...unattendedOptions,
          bundle: "document-skills",
          skills: ["typo"],
          vendor: "anthropics",
        },
        async () => {},
      ),
    ).rejects.toThrow("Unknown skill for vendor anthropics: typo");
  });

  test("rejects a vendor skill subset as non-atomic", async () => {
    await expect(
      install(
        {
          ...unattendedOptions,
          bundle: "document-skills",
          skills: ["pdf"],
          vendor: "anthropics",
        },
        async () => {},
      ),
    ).rejects.toThrow("Vendor installs are plugin-atomic; omit --skill and --bundle");
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
        { sourceRoot: null },
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
        { sourceRoot: null },
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
        { sourceRoot: null },
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
        { sourceRoot: null },
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

  test("detect mode records exploded projectors even when native is the host default", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-explode-"));
    const cursorSkill = join(cwd, ".cursor/skills/lint/SKILL.md");
    const claudeSkill = join(cwd, ".claude/skills/lint/SKILL.md");
    try {
      await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          projector: null,
          project: true,
          skills: ["lint"],
        },
        async () => {},
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async (path) => path === cursorSkill || path === claudeSkill,
          hash: async () => "abc",
        },
      );

      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor).toMatchObject({
        files: { "lint/SKILL.md": "abc" },
        projector: "explode",
        root: join(cwd, ".cursor/skills"),
      });
      expect(lock.plugins.lint.agents["claude-code"]).toMatchObject({
        files: { "lint/SKILL.md": "abc" },
        projector: "explode",
        root: join(cwd, ".claude/skills"),
      });
      expect(lock.plugins.lint.agents["claude-code"].root).not.toBe("cli:claude-code");
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
        { sourceRoot: null },
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

  test("completes remaining vendor membership on a full reinstall", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-add-skill-"));
    let ran = false;
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              "document-skills": {
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
                version: "9d2f1ae",
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
          bundle: "document-skills",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics",
        },
        async () => {
          ran = true;
        },
        undefined,
        { cwd },
      );

      expect(ran).toBe(false);
      expect(result).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      const files = Object.keys(lock.plugins["document-skills"].agents.cursor.files);
      expect(files).toContain("pdf/SKILL.md");
      expect(files).toContain("xlsx/SKILL.md");
      expect(files.length).toBeGreaterThan(2);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps a stable vendor plugin id across full installs", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-vendor-id-"));
    const env = { cwd };
    try {
      await install(
        {
          ...unattendedOptions,
          bundle: "hookify",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          throw new Error("baked install should not shell out to skills");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        env,
      );
      const first = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(first.plugins["writing-rules"]).toBeUndefined();
      expect(first.plugins.hookify.agents.cursor.files["writing-rules/SKILL.md"]).toBeTruthy();

      await install(
        {
          ...unattendedOptions,
          bundle: "hookify",
          global: false,
          project: true,
          skills: [],
          vendor: "anthropics-claude-code",
        },
        async () => {
          throw new Error("second install should no-op");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        env,
      );

      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.hookify.agents.cursor.files["writing-rules/SKILL.md"]).toBeTruthy();
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back a targeted install that wrote only some plugin skills", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-partial-plugin-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    const testDir = join(cwd, ".cursor/skills/test");
    try {
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
            await mkdir(lintDir, { recursive: true });
            await writeFile(join(lintDir, "SKILL.md"), "partial\n");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { sourceRoot: null },
        ),
      ).rejects.toThrow("Plugin install incomplete");

      await expect(access(lintDir)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(access(testDir)).rejects.toMatchObject({ code: "ENOENT" });
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
          { sourceRoot: null },
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
          { sourceRoot: null },
        ),
      ).rejects.toThrow("gateway lock update failed");

      await expect(access(lintDir)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps the original install error when rollback also fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-rollback-fail-"));
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
            throw new Error("skills CLI failed");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            rm: async () => {
              throw new Error("rm denied");
            },
          },
          { sourceRoot: null },
        ),
      ).rejects.toThrow("skills CLI failed (rollback also failed: rm denied)");

      expect(await readFile(join(lintDir, "SKILL.md"), "utf8")).toBe("partial\n");
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
        undefined,
        { sourceRoot: null },
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
        { sourceRoot: null },
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

describe("native projectors", () => {
  test("assembles a Cursor plugin tree and records native hashes", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-cursor-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      let ran = false;
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: "native",
          project: true,
        },
        async () => {
          ran = true;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );

      expect(ran).toBe(false);
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.projector).toBe("native");
      expect(lock.plugins.review.agents.cursor.projector).toBe("native");
      expect(lock.plugins.review.agents.cursor.root).toBe(pluginDir);
      expect(lock.plugins.review.agents.cursor.files[".claude-plugin/plugin.json"]).toMatch(
        /^[a-f0-9]{64}$/,
      );
      expect(lock.plugins.review.agents.cursor.files["skills/lint/SKILL.md"]).toMatch(
        /^[a-f0-9]{64}$/,
      );
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("reinstalls a Cursor plugin after a clean native remove", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-cursor-reinstall-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const nativeOptions = {
        ...unattendedOptions,
        global: false,
        projector: "native",
        project: true,
      };
      await install(
        nativeOptions,
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: [],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          writeLock: (lock) => writeLockfile(lock, { cwd }),
        },
      );
      await expect(access(pluginDir)).rejects.toMatchObject({ code: "ENOENT" });
      await install(
        nativeOptions,
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not lock untracked Cursor files so remove leaves them", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-untracked-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const nativeOptions = {
        ...unattendedOptions,
        global: false,
        projector: "native",
        project: true,
      };
      await install(
        nativeOptions,
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await install(
        nativeOptions,
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents.cursor.files["USER-DATA.txt"]).toBeUndefined();
      expect(lock.plugins.review.agents.cursor.files[".claude-plugin/plugin.json"]).toMatch(
        /^[a-f0-9]{64}$/,
      );
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: [],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: async () => lock,
          writeLock: async () => {},
        },
      );
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("fails closed when Cursor native has no catalog checkout", async () => {
    await expect(
      install(
        {
          ...unattendedOptions,
          projector: "native",
        },
        async () => {},
        undefined,
        { cwd: "/tmp/ai-skills-no-catalog" },
        { sourceRoot: null },
      ),
    ).rejects.toThrow("Native Cursor projector requires a catalog checkout");
  });

  test("installs Claude Code through the host CLI", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-cli-"));
    try {
      const calls = [];
      await install(
        {
          ...unattendedOptions,
          agents: ["claude-code"],
          global: false,
          projector: "native",
          project: true,
        },
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        {
          exec: async (command, args) => {
            calls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "ok" };
          },
        },
      );
      expect(calls).toEqual([
        ["claude", "plugin", "marketplace", "add", "lgtm-hq/ai-skills@v0.0.0-dev"],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.projector).toBe("native");
      expect(lock.plugins.review.agents["claude-code"]).toMatchObject({
        projector: "native",
        root: "cli:claude-code",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects native projector when agents are left empty for detection", async () => {
    await expect(
      install({
        ...unattendedOptions,
        agents: [],
        projector: "native",
      }),
    ).rejects.toThrow("Native projector requires -a/--agent");
  });

  test("rejects --projector native for Codex", async () => {
    await expect(
      install({
        ...unattendedOptions,
        agents: ["codex"],
        projector: "native",
      }),
    ).rejects.toThrow('Native projector is not supported for agent "codex"');
  });

  test("does not uninstall when Claude Code plugin install fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-cli-rollback-"));
    try {
      const calls = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native",
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          {
            exec: async (command, args) => {
              calls.push([command, ...args]);
              if (args.includes("install")) {
                return { status: 1, stderr: "boom", stdout: "" };
              }
              return { status: 0, stderr: "", stdout: "ok" };
            },
          },
        ),
      ).rejects.toThrow("claude plugin install failed: boom");
      expect(calls).toEqual([
        ["claude", "plugin", "marketplace", "add", "lgtm-hq/ai-skills@v0.0.0-dev"],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      expect(calls.some((argv) => argv.includes("uninstall"))).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("splits mixed Cursor native and Codex explode in one install", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-mixed-projectors-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const received = [];
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor", "codex"],
          global: false,
          projector: null,
          project: true,
        },
        async (args) => {
          received.push(args);
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        { hostCapabilities: { cursor: "native", codex: "explode" }, sourceRoot },
      );
      expect(received).toEqual([]);
      expect(await readFile(join(cwd, ".codex/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents.cursor.projector).toBe("native");
      expect(lock.plugins.review.agents.codex.projector).toBe("explode");
      expect(lock.plugins.review.projector).toBe("explode");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("consults doctor hostCapabilities when --projector is omitted", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-install-"));
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      let received = [];
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: null,
          project: true,
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        { hostCapabilities: { cursor: "explode" }, sourceRoot },
      );
      expect(received).toEqual([]);
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents.cursor.projector).toBe("explode");
      await expect(access(join(cwd, ".cursor/plugins/local/review"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("reads doctor.json when hostCapabilities is omitted", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-json-"));
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await writeDoctorCache(
        {
          hosts: {
            cursor: {
              capability: "explode",
              source: "probe",
              version: "project:present:nocli",
            },
          },
          schemaVersion: 1,
        },
        { home: cwd },
      );
      let received = [];
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: null,
          project: true,
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        {
          exec: async () => {
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          sourceRoot,
        },
      );
      expect(received).toEqual([]);
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents.cursor.projector).toBe("explode");
      await expect(access(join(cwd, ".cursor/plugins/local/review"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("falls back Cursor to explode when native is implicit and catalog is absent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-implicit-explode-"));
    try {
      let received = [];
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: null,
          project: true,
        },
        async (args) => {
          received = args;
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        { hostCapabilities: { cursor: "native" }, sourceRoot: null },
      );
      expect(received).toContain("cursor");
      expect(received).toContain("add");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.projector).toBe("explode");
      expect(lock.plugins.review.agents.cursor.projector).toBe("explode");
      expect(lock.plugins.review.agents.cursor.root).toBe(join(cwd, ".cursor/skills"));
      expect(lock.plugins.review.agents.cursor.root).not.toContain("plugins/local");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("removes explode dests when --projector native rematerializes a locked agent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-projector-override-cleanup-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/jira"), { recursive: true });
      await writeFile(explodeFile, "# jira\n");
      await writeFile(join(sourceRoot, "skills/jira/SKILL.md"), "# jira\n");
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            jira: {
              agents: {
                cursor: {
                  files: { "jira/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
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
        },
        { cwd },
      );
      const counts = await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "native",
          project: true,
          skills: ["jira"],
        },
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd, exists: async () => true, hash: async () => "abc", home: cwd },
        { sourceRoot },
      );
      expect(counts).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      await expect(access(explodeFile)).rejects.toMatchObject({ code: "ENOENT" });
      expect(
        await readFile(join(cwd, ".cursor/plugins/local/jira/skills/jira/SKILL.md"), "utf8"),
      ).toBe("# jira\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("commits native lock when --projector dest cleanup fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-projector-override-rmfail-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    const warnings = [];
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/jira"), { recursive: true });
      await writeFile(explodeFile, "# jira\n");
      await writeFile(join(sourceRoot, "skills/jira/SKILL.md"), "# jira\n");
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            jira: {
              agents: {
                cursor: {
                  files: { "jira/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
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
        },
        { cwd },
      );
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["cursor"],
            bundle: null,
            global: false,
            projector: "native",
            project: true,
            skills: ["jira"],
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T17:00:00.000Z"),
          { cwd, exists: async () => true, hash: async () => "abc", home: cwd },
          {
            remove: async () => {
              throw new Error("rm boom");
            },
            sourceRoot,
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow("rm boom");
      expect(warnings.some((message) => message.includes("could not remove"))).toBe(true);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.jira.agents.cursor.projector).toBe("native");
      expect(await readFile(explodeFile, "utf8")).toBe("# jira\n");
      const lines = [];
      await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: false,
          yes: true,
        },
        {
          exec: async () => {
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          home: cwd,
          lockEnvironment: { cwd, home: cwd },
          log: (line) => lines.push(line),
        },
      );
      expect(
        lines.some((line) => line.startsWith("orphan\tcursor\t") && line.endsWith("/jira")),
      ).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not demote a locked native Cursor install when catalog is absent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-repair-native-no-catalog-"));
    try {
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              review: {
                agents: {
                  cursor: {
                    files: { ".claude-plugin/plugin.json": "abc" },
                    projector: "native",
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-dev",
                vendor: "lgtm-hq",
                version: "0.0.0-dev",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            projector: null,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T17:00:00.000Z"),
          {
            cwd,
            exists: async () => false,
            hash: async () => "",
          },
          { sourceRoot: null },
        ),
      ).rejects.toThrow("requires a catalog checkout");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents.cursor.projector).toBe("native");
      expect(lock.plugins.review.agents.cursor.root).toBe(pluginDir);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repairs an exploded Cursor lock without switching to native", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-repair-explode-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(staleProjectLock(cwd, { cursor: "abc" }), null, 2)}\n`,
      );
      let received = [];
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          projector: null,
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
        { sourceRoot },
      );
      expect(received).toEqual([]);
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      await expect(access(join(cwd, ".cursor/plugins/local/lint"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.lint.agents.cursor.projector).toBe("explode");
      expect(lock.plugins.lint.agents.cursor.root).toBe(join(cwd, ".cursor/skills"));
      expect(lock.plugins.lint.agents.cursor.files).toEqual({ "lint/SKILL.md": "" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("uninstalls a Claude plugin this run created when lock write fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-created-rollback-"));
    try {
      const calls = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native",
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("EACCES");
            },
          },
          {
            exec: async (command, args) => {
              calls.push([command, ...args]);
              return { status: 0, stderr: "", stdout: "ok" };
            },
          },
        ),
      ).rejects.toThrow("rolled back");
      expect(calls).toEqual([
        ["claude", "plugin", "marketplace", "add", "lgtm-hq/ai-skills@v0.0.0-dev"],
        ["claude", "plugin", "install", "review@ai-skills"],
        ["claude", "plugin", "uninstall", "review@ai-skills"],
      ]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not uninstall a pre-existing Claude plugin when lock write fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-already-"));
    try {
      const calls = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native",
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("EACCES");
            },
          },
          {
            exec: async (command, args) => {
              calls.push([command, ...args]);
              return { status: 1, stderr: "already installed", stdout: "" };
            },
          },
        ),
      ).rejects.toThrow("rolled back");
      expect(calls.some((argv) => argv.includes("uninstall"))).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not uninstall a status-zero already-installed Claude plugin when lock write fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-already-zero-"));
    try {
      const calls = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native",
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("EACCES");
            },
          },
          {
            exec: async (command, args) => {
              calls.push([command, ...args]);
              return { status: 0, stderr: "", stdout: "already installed" };
            },
          },
        ),
      ).rejects.toThrow("rolled back");
      expect(calls.some((argv) => argv.includes("uninstall"))).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not uninstall a pre-existing Claude plugin when marketplace add fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-marketplace-fail-"));
    try {
      const calls = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native",
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          {
            exec: async (command, args) => {
              calls.push([command, ...args]);
              if (args.includes("marketplace")) {
                return { status: 1, stderr: "network error", stdout: "" };
              }
              return { status: 0, stderr: "", stdout: "" };
            },
          },
        ),
      ).rejects.toThrow("marketplace add failed");
      expect(calls.some((argv) => argv.includes("uninstall"))).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("restores a prior native Cursor tree when lock write fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-restore-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              review: {
                agents: {
                  cursor: {
                    files: { ".claude-plugin/plugin.json": "old" },
                    projector: "native",
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            projector: "native",
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("EACCES");
            },
          },
          { sourceRoot },
        ),
      ).rejects.toThrow("rolled back");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      await expect(readFile(join(pluginDir, "skills/lint/SKILL.md"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("restores a prior native Cursor tree when promote and inner restore fail", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-swap-fail-restore-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              review: {
                agents: {
                  cursor: {
                    files: { ".claude-plugin/plugin.json": "old" },
                    projector: "native",
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      let moves = 0;
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            projector: "native",
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          {
            move: async (from, to) => {
              moves += 1;
              if (moves === 2) {
                throw new Error("staging promote failed");
              }
              if (moves === 3) {
                throw new Error("inner restore failed");
              }
              return rename(from, to);
            },
            sourceRoot,
          },
        ),
      ).rejects.toThrow(
        "staging promote failed (Cursor restore also failed: inner restore failed)",
      );
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps the new Cursor tree when backup discard fails after lock write", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-discard-warn-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              review: {
                agents: {
                  cursor: {
                    files: { ".claude-plugin/plugin.json": "old" },
                    projector: "native",
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      const warnings = [];
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: "native",
          project: true,
        },
        async () => {},
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        {
          remove: async () => {
            throw new Error("EACCES bak");
          },
          sourceRoot,
          warn: (message) => warnings.push(message),
        },
      );
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      expect(warnings.some((message) => message.includes("discard Cursor plugin backup"))).toBe(
        true,
      );
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not restore a leftover Cursor backup when install fails before swap", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-preswap-bak-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(sourceRoot, { recursive: true });
      const pluginDir = join(cwd, ".cursor/plugins/local/review");
      await mkdir(pluginDir, { recursive: true });
      await writeFile(join(pluginDir, "USER-DATA.txt"), "fresh\n");
      await mkdir(`${pluginDir}.bak`, { recursive: true });
      await writeFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "stale\n");
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: {
              review: {
                agents: {
                  cursor: {
                    files: { ".claude-plugin/plugin.json": "old" },
                    projector: "native",
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native",
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            projector: "native",
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { sourceRoot },
        ),
      ).rejects.toThrow();
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("fresh\n");
      expect(await readFile(join(`${pluginDir}.bak`, "USER-DATA.txt"), "utf8")).toBe("stale\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("explodes transactionally and leaves an identical unowned dest after remove", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-unowned-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["lint", "test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(Object.keys(lock.plugins.lint.agents.cursor.files)).toEqual(["test/SKILL.md"]);
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["lint"],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      await expect(
        readFile(join(cwd, ".cursor/skills/test/SKILL.md"), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("second explode install still does not claim a skipped identical dest", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-second-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      const options = {
        ...unattendedOptions,
        agents: ["cursor"],
        bundle: null,
        global: false,
        projector: "explode",
        project: true,
        skills: ["lint", "test"],
      };
      const extras = { sourceRoot };
      const environment = { cwd };
      await install(
        options,
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        environment,
        extras,
      );
      await install(
        options,
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        environment,
        extras,
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(Object.keys(lock.plugins.lint.agents.cursor.files).sort()).toEqual(["test/SKILL.md"]);
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("remove unlinks dest skill symlink and leaves the managed store", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-keep-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const dest = join(cwd, ".cursor/skills/test");
      const store = join(cwd, ".agents/skills/test");
      expect(await readlink(dest)).toBe(store);
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["test"],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      await expect(lstat(dest)).rejects.toMatchObject({ code: "ENOENT" });
      expect(await readFile(join(store, "SKILL.md"), "utf8")).toBe("# test\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back exploded dest and store when lock update fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-lock-fail-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["cursor"],
            bundle: null,
            global: false,
            projector: "explode",
            project: true,
            skills: ["test"],
          },
          async () => {
            throw new Error("skills CLI must not run when catalog sources resolve");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          {
            cwd,
            write: async () => {
              throw new Error("disk full");
            },
          },
          { sourceRoot },
        ),
      ).rejects.toThrow("gateway lock update failed");
      await expect(lstat(join(cwd, ".cursor/skills/test"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      await expect(lstat(join(cwd, ".agents/skills/test"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not lock an all-skipped identical dest", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-all-skip-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      const result = await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["lint"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 0 });
      await expect(readFile(join(cwd, "ai-skills-lock.json"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("warns when an identical dest is skipped without claiming ownership", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-skip-warn-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
      const warnings = [];
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["lint"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        {
          sourceRoot,
          warn: (message) => {
            warnings.push(message);
          },
        },
      );
      expect(warnings.some((item) => item.includes("skipped identical explode dest"))).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("CLI explode lock records nested dest files so remove deletes them", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-explode-nested-"));
    try {
      const dest = join(cwd, ".cursor/skills/lint");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["lint"],
        },
        async () => {
          await mkdir(dest, { recursive: true });
          await writeFile(join(dest, "SKILL.md"), "# lint\n");
          await writeFile(join(dest, "notes.md"), "notes\n");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot: null },
      );
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(Object.keys(lock.plugins.lint.agents.cursor.files).sort()).toEqual([
        "lint/SKILL.md",
        "lint/notes.md",
      ]);
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["lint"],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          run: async () => {
            throw new Error("skills CLI must not run for explode remove");
          },
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      await expect(readFile(join(dest, "notes.md"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("update preserves copy dest directories instead of rewriting store symlinks", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-copy-update-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          copy: true,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect((await lstat(join(cwd, ".cursor/skills/test"))).isDirectory()).toBe(true);
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test v2\n");
      const lockPath = join(cwd, "ai-skills-lock.json");
      const lock = JSON.parse(await readFile(lockPath, "utf8"));
      lock.plugins.test.sha = "v0.0.0-old";
      lock.plugins.test.version = "0.0.0-old";
      await writeFile(lockPath, `${JSON.stringify(lock, null, 2)}\n`);
      await updateSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["test"],
          yes: true,
        },
        {
          isInstalled: async () => true,
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          run: async () => {
            throw new Error("skills CLI must not run when catalog sources resolve");
          },
          sourceRoot,
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      expect((await lstat(join(cwd, ".cursor/skills/test"))).isDirectory()).toBe(true);
      expect(await readFile(join(cwd, ".cursor/skills/test/SKILL.md"), "utf8")).toBe("# test v2\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("install repair keeps --copy dest directories", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-copy-repair-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          copy: true,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect((await lstat(join(cwd, ".cursor/skills/test"))).isDirectory()).toBe(true);
      await writeFile(join(cwd, ".cursor/skills/test/SKILL.md"), "# dirty\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test v2\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          copy: false,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect((await lstat(join(cwd, ".cursor/skills/test"))).isDirectory()).toBe(true);
      expect(await readFile(join(cwd, ".cursor/skills/test/SKILL.md"), "utf8")).toBe("# test v2\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("remove unlinks a dangling dest skill symlink so reinstall can proceed", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-dangle-rm-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      const dest = join(cwd, ".cursor/skills/test");
      const store = join(cwd, ".agents/skills/test");
      expect(await readlink(dest)).toBe(store);
      await rm(store, { force: true, recursive: true });
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["test"],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      await expect(lstat(dest)).rejects.toMatchObject({ code: "ENOENT" });
      const result = await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode",
          project: true,
          skills: ["test"],
        },
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect(result.installed).toBe(1);
      expect(await readlink(dest)).toBe(store);
      expect(await readFile(join(dest, "SKILL.md"), "utf8")).toBe("# test\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("remove then reinstall with drifted content does not collide on a leftover store", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-gc-"));
    try {
      const sourceRoot = join(cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      const options = {
        ...unattendedOptions,
        agents: ["cursor"],
        bundle: null,
        global: false,
        projector: "explode",
        project: true,
        skills: ["test"],
      };
      await install(
        options,
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      await removeSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: ["test"],
          yes: true,
        },
        {
          lockEnvironment: { cwd },
          readLock: (scope) => readLockfile(scope, { cwd }),
          writeLock: (next) => writeLockfile(next, { cwd }),
        },
      );
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test v2\n");
      await install(
        options,
        async () => {
          throw new Error("skills CLI must not run when catalog sources resolve");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot },
      );
      expect(await readFile(join(cwd, ".cursor/skills/test/SKILL.md"), "utf8")).toBe("# test v2\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });
});
