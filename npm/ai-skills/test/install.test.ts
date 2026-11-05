import { describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  readlink,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadVendorIndex } from "../lib/catalog.ts";
import { writeDoctorCache, runDoctor } from "../lib/doctor.ts";
import { batchesFromCliOptions, install } from "../lib/install.ts";
import { removeSkills, updateSkills } from "../lib/gateway-commands.ts";
import { MINIMUM_SKILLS_VERSION } from "../lib/options.ts";
import { buildSkillsArguments, UNMANAGED_HANDOFF_LABEL } from "../lib/skills-runner.ts";
import vendorCatalog from "../data/vendors.json" with { type: "json" };
import { editState, readState, skillSources, writeLegacyLock } from "./fixtures/state.ts";

const claudeCode = vendorCatalog.vendors.find((vendor) => vendor.id === "anthropics-claude-code");

const unattendedOptions = {
  agents: ["cursor"],
  bundle: "review",
  copy: false,
  global: true,
  onConflict: "overwrite",
  // Explicit explode keeps pre-native tests off the catalog-checkout path.
  // Production default is native; projector:null cases cover that below.
  projector: "explode" as const,
  project: false,
  skills: ["lint", "test"],
  vendor: null,
  yes: true,
};

/** Real one-file sources (`# <name>`) for the explode lane. */
const stubSources = await skillSources(["lint", "test", "greptile", "coderabbit", "lintro-review"]);

/** Hex sha256 of a stub source's `SKILL.md`. */
const stubDigest = (name: string) => createHash("sha256").update(`# ${name}\n`).digest("hex");

const skillsCliForbidden = async () => {
  throw new Error("managed installs must not call the skills CLI");
};

/**
 * Write a catalog checkout with `skills/<name>/SKILL.md` for each name.
 */
async function writeCatalog(root: string, names: string[]): Promise<string> {
  for (const name of names) {
    await mkdir(join(root, "skills", name), { recursive: true });
    await writeFile(join(root, "skills", name, "SKILL.md"), `# ${name}\n`);
  }
  return root;
}

/**
 * Project-scope v2 lock tracking lint on the given agents.
 */
function staleProjectLock(cwd: string, agentHashes: Record<string, string>): object {
  const agentRoots: Record<string, string> = {
    "claude-code": ".claude/skills",
    cursor: ".cursor/skills",
  };
  const agents = Object.fromEntries(
    Object.entries(agentHashes).map(([agent, digest]) => [
      agent,
      {
        files: { "lint/SKILL.md": digest },
        root: join(cwd, agentRoots[agent]!),
      },
    ]),
  );
  return {
    gatewayVersion: "0.0.0-dev",
    plugins: {
      lint: {
        agents,
        installedAt: "2026-07-10T16:00:00.000Z",
        projector: "explode" as const,
        repo: "lgtm-hq/ai-skills",
        sha: "v0.0.0-dev",
        vendor: "lgtm-hq",
        version: "0.0.0-dev",
      },
    },
    scope: "project" as const,
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
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-install-"));
    try {
      await install(
        {
          ...unattendedOptions,
          global: false,
          project: true,
          skills: [],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceSkills: stubSources },
      );

      const lock = await readState("project", { cwd });
      expect(lock.version).toBe(2);
      expect(lock.plugins.review).toMatchObject({
        projector: "explode" as const,
        repo: "lgtm-hq/ai-skills",
        vendor: "lgtm-hq",
      });
      expect(lock.plugins.review.installedAt).toBe("2026-07-10T16:00:00.000Z");
      expect(lock.plugins.review.agents.cursor.files).toMatchObject({
        "lint/SKILL.md": stubDigest("lint"),
        "test/SKILL.md": stubDigest("test"),
      });
      expect(lock.plugins.review.skills).toContain("lint");
      // The lock file is never written into the repository any more.
      await expect(access(join(cwd, "ai-skills-lock.json"))).rejects.toMatchObject({
        code: "ENOENT",
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

  test("fails closed when a registered vendor has no baked plugins", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-no-bake-"));
    const previous = process.env.AI_SKILLS_PLUGINS_BAKED;
    process.env.AI_SKILLS_PLUGINS_BAKED = root;
    try {
      await expect(
        batchesFromCliOptions({ bundle: null, skills: [], vendor: "mattpocock" }),
      ).rejects.toThrow("Vendor mattpocock has no baked plugins");
    } finally {
      if (previous === undefined) {
        delete process.env.AI_SKILLS_PLUGINS_BAKED;
      } else {
        process.env.AI_SKILLS_PLUGINS_BAKED = previous;
      }
      await rm(root, { force: true, recursive: true });
    }
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
      const lock = await readState("project", { cwd });
      expect(lock.plugins.hookify).toMatchObject({
        projector: "explode" as const,
        repo: "anthropics/claude-code",
        sha: claudeCode!.sha,
        vendor: "anthropics-claude-code",
        version: claudeCode!.sha.slice(0, 7),
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
      const before = await readState("project", { cwd });
      const result = await updateSkills(
        {
          agents: ["cursor"],
          global: false,
          project: true,
          skills: [],
          yes: true,
        },
        {
          isInstalled: async () => true,
          lockEnvironment: { cwd },
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          run: async () => {
            throw new Error("skills CLI must not run for baked plugins");
          },
        },
      );
      const after = await readState("project", { cwd });
      expect(result).toEqual({ pruned: [], updated: [] });
      expect(after.plugins.hookify.installedAt).toBe(before.plugins.hookify.installedAt);
      expect(after.plugins.hookify.version).toBe(claudeCode!.sha.slice(0, 7));
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects managed agent detection for baked vendor plugins", async () => {
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
    ).rejects.toThrow("Agent detection hands off to the upstream skills CLI");
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
      const lock = await readState("project", { cwd });
      expect(lock.plugins["claude-code-frontend-design"]).toMatchObject({
        projector: "explode" as const,
        repo: "anthropics/claude-code",
        sha: claudeCode!.sha,
        vendor: "anthropics-claude-code",
        version: claudeCode!.sha.slice(0, 7),
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

  test("defaults unset scope to global for both destinations and lock", async () => {
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
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { home },
        { sourceSkills: stubSources },
      );

      expect(await readlink(join(home, ".cursor/skills/lint"))).toBe(
        join(home, ".agents/skills/lint"),
      );
      const lock = await readState("global", { home });
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
        skillsCliForbidden,
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async () => false,
          hash: async () => "",
        },
        { sourceSkills: stubSources },
      );

      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 1 });
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repairs a lock whose tracked hashes no longer match disk", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-modified-"));
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
        skillsCliForbidden,
        () => new Date("2026-07-10T17:00:00.000Z"),
        {
          cwd,
          exists: async () => true,
          hash: async () => "new",
        },
        { sourceSkills: stubSources },
      );

      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 1 });
      const lock = await readState("project", { cwd });
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toBe(stubDigest("lint"));
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
        skillsCliForbidden,
        undefined,
        {
          cwd,
          exists: async (path) => String(path).startsWith(cursorRoot),
          hash: async () => "abc",
        },
        { sourceSkills: stubSources },
      );

      expect(result).toEqual({ alreadyPresent: 1, installed: 0, repaired: 1 });
      await access(join(cwd, ".claude/skills/lint/SKILL.md"));
      await expect(access(join(cwd, ".cursor/skills/lint"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      const lock = await readState("project", { cwd });
      expect(lock.plugins.lint.agents.cursor.files["lint/SKILL.md"]).toBe("abc");
      expect(lock.plugins.lint.agents["claude-code"].files["lint/SKILL.md"]).toBe(
        stubDigest("lint"),
      );
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("refuses managed agent detection instead of handing off to the skills CLI", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-detect-"));
    let ran = false;
    try {
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: [],
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
        ),
      ).rejects.toThrow("pass --unmanaged for an unmanaged handoff");
      expect(ran).toBe(false);
      await expect(readFile(join(cwd, "ai-skills-lock.json"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("hands off to the skills CLI only as a labeled unmanaged install with no lock", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-unmanaged-"));
    let received: string[] = [];
    const warnings: string[] = [];
    try {
      const result = await install(
        {
          ...unattendedOptions,
          agents: [],
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
          unmanaged: true,
        },
        async (args) => {
          received = args;
          await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
          await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "# lint\n");
        },
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
        { warn: (message) => warnings.push(message) },
      );

      expect(received).toEqual([
        "skills@^1.5.0",
        "add",
        "lgtm-hq/ai-skills@v0.0.0-dev",
        "--skill",
        "lint",
        "-y",
      ]);
      expect(warnings).toEqual([UNMANAGED_HANDOFF_LABEL]);
      expect(result).toEqual({ alreadyPresent: 0, installed: 0, repaired: 0 });
      // No managed receipt: the gateway lock is never written for a handoff.
      await expect(readFile(join(cwd, "ai-skills-lock.json"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("refuses a managed first-party install without a local artifact", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-no-artifact-"));
    let ran = false;
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
            ran = true;
          },
          () => new Date("2026-07-10T17:00:00.000Z"),
          { cwd },
          { sourceRoot: null },
        ),
      ).rejects.toThrow("managed installs never fall back to the upstream skills CLI");
      expect(ran).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("treats a v1 lock as empty and installs instead of skipping", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-v1-"));
    try {
      await Bun.write(
        join(cwd, "ai-skills-lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.20.0",
            scope: "project" as const,
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
        skillsCliForbidden,
        () => new Date("2026-07-10T17:00:00.000Z"),
        { cwd },
        { sourceSkills: stubSources },
      );

      expect(result).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      await access(join(cwd, ".cursor/skills/lint/SKILL.md"));
      const lock = await readState("project", { cwd });
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
                projector: "explode" as const,
                repo: "anthropics/skills",
                sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
                vendor: "anthropics",
                version: "9d2f1ae",
              },
            },
            scope: "project" as const,
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
      const lock = await readState("project", { cwd });
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
      const first = await readState("project", { cwd });
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

      const lock = await readState("project", { cwd });
      expect(lock.plugins.hookify.agents.cursor.files["writing-rules/SKILL.md"]).toBeTruthy();
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back a targeted install when an op fails part way", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-partial-plugin-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    const testDir = join(cwd, ".cursor/skills/test");
    try {
      for (const failBeforeOp of [2, 5]) {
        await expect(
          install(
            {
              ...unattendedOptions,
              bundle: null,
              global: false,
              project: true,
              skills: ["lint", "test"],
            },
            skillsCliForbidden,
            () => new Date("2026-07-10T16:00:00.000Z"),
            { cwd },
            { journal: { failBeforeOp }, sourceSkills: stubSources },
          ),
        ).rejects.toThrow(`Install rolled back: injected failure before op ${failBeforeOp}`);

        await expect(access(lintDir)).rejects.toMatchObject({ code: "ENOENT" });
        await expect(access(testDir)).rejects.toMatchObject({ code: "ENOENT" });
        await expect(access(join(cwd, ".agents"))).rejects.toMatchObject({ code: "ENOENT" });
        expect((await readState("project", { cwd })).plugins).toEqual({});
      }
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back newly written skill directories and keeps identical existing ones", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-atomic-cli-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    const testDir = join(cwd, ".cursor/skills/test");
    try {
      await mkdir(lintDir, { recursive: true });
      await writeFile(join(lintDir, "SKILL.md"), "# lint\n");
      const warnings: string[] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            bundle: null,
            global: false,
            project: true,
            skills: ["lint", "test"],
          },
          skillsCliForbidden,
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          {
            journal: {
              // An existing real dest selects copy mode: mkdir then write per skill.
              afterOp: (index) => {
                if (index === 1) {
                  throw new Error("explode failed");
                }
              },
            },
            sourceSkills: stubSources,
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow("explode failed");

      expect(warnings).toContain(`skipped identical ${lintDir} (not claiming lint on cursor)`);
      expect(await readFile(join(lintDir, "SKILL.md"), "utf8")).toBe("# lint\n");
      await expect(access(testDir)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(access(join(cwd, "ai-skills-lock.json"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rolls back newly written skill directories when the commit fails", async () => {
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
          skillsCliForbidden,
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { journal: { failBeforeCommit: true }, sourceSkills: stubSources },
        ),
      ).rejects.toThrow("Install rolled back: injected failure before commit");

      await expect(access(lintDir)).rejects.toMatchObject({ code: "ENOENT" });
      expect((await readState("project", { cwd })).plugins).toEqual({});
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps the original install error and the journal when rollback also fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-rollback-fail-"));
    const home = await mkdtemp(join(tmpdir(), "ai-skills-rollback-home-"));
    const lintDir = join(cwd, ".cursor/skills/lint");
    try {
      const error = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home },
        {
          journal: {
            afterOp: (index) => {
              if (index === 1) {
                throw new Error("explode failed");
              }
            },
            io: {
              rm: async () => {
                throw new Error("rm denied");
              },
            },
          },
          sourceSkills: stubSources,
        },
      ).then(
        () => new Error("install unexpectedly succeeded"),
        (caught: unknown) => caught as Error,
      );

      expect(error.message).toStartWith(
        "Install rolled back: explode failed (rollback also failed: ",
      );
      expect(error.message).toContain("rm denied");
      expect(error.message).toContain("the next command retries recovery");
      expect(await readFile(join(cwd, ".agents/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      // The next command finishes the rollback from the kept journal.
      const result = await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home },
        { sourceSkills: stubSources, warn: () => {} },
      );
      expect(result).toEqual({ alreadyPresent: 0, installed: 1, repaired: 0 });
      expect(await readlink(lintDir)).toBe(join(cwd, ".agents/skills/lint"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
      await rm(home, { force: true, recursive: true });
    }
  });

  test("writes a lock when lockEnvironment is omitted", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-no-env-"));
    const previous = process.cwd();
    try {
      const catalog = await writeCatalog(join(cwd, "catalog"), ["lint"]);
      process.chdir(cwd);
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        undefined,
        { sourceRoot: catalog },
      );
      const lock = await readState("project", { cwd });
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
      const catalog = await writeCatalog(join(cwd, "catalog"), ["lint"]);
      process.chdir(cwd);
      await install(
        {
          ...unattendedOptions,
          bundle: null,
          global: false,
          project: true,
          skills: ["lint"],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        null,
        { sourceRoot: catalog },
      );
      const lock = await readState("project", { cwd });
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
          projector: "native" as const,
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
      const lock = await readState("project", { cwd });
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
        projector: "native" as const,
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
        projector: "native" as const,
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
      const lock = await readState("project", { cwd });
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
        { lockEnvironment: { cwd } },
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
          projector: "native" as const,
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
      const calls: string[][] = [];
      await install(
        {
          ...unattendedOptions,
          agents: ["claude-code"],
          global: false,
          projector: "native" as const,
          project: true,
        },
        async () => {
          throw new Error("explode runner must not run");
        },
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        {
          exec: async (command, args) => {
            calls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "ok" };
          },
        },
      );
      expect(calls).toEqual([
        ["claude", "plugin", "marketplace", "add", join(cwd, ".ai-skills/native/claude-code")],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      const lock = await readState("project", { cwd, home: cwd });
      expect(lock.plugins.review.projector).toBe("native");
      expect(lock.plugins.review.agents["claude-code"]).toMatchObject({
        projector: "native" as const,
        root: "cli:claude-code",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("refuses native CLI delivery without a local artifact and never calls the host", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-no-artifact-"));
    try {
      const calls: string[][] = [];
      const exec = async (command: string, args: string[]) => {
        calls.splice(calls.length, 0, [command, ...args]);
        return { status: 0, stderr: "", stdout: "ok" };
      };
      const native = {
        ...unattendedOptions,
        agents: ["claude-code"],
        global: false,
        project: true,
      };
      await expect(
        install(
          { ...native, projector: "native" as const },
          skillsCliForbidden,
          undefined,
          { cwd, home: cwd },
          { exec, sourceRoot: null },
        ),
      ).rejects.toThrow("the remote marketplace is never used");
      // Implicit native falls back to explode, which also needs a local artifact.
      await expect(
        install(
          { ...native, projector: null },
          skillsCliForbidden,
          undefined,
          { cwd, home: cwd },
          {
            exec,
            hostCapabilities: { "claude-code": "native" },
            sourceRoot: null,
          },
        ),
      ).rejects.toThrow("managed installs never fall back to the upstream skills CLI");
      expect(calls).toEqual([]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("rejects native projector when agents are left empty for detection", async () => {
    await expect(
      install({
        ...unattendedOptions,
        agents: [],
        projector: "native" as const,
      }),
    ).rejects.toThrow("Agent detection hands off to the upstream skills CLI");
  });

  test("rejects --projector native for Codex", async () => {
    await expect(
      install({
        ...unattendedOptions,
        agents: ["codex"],
        projector: "native" as const,
      }),
    ).rejects.toThrow('Native projector is not supported for agent "codex"');
  });

  test("does not uninstall when Claude Code plugin install fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-native-cli-rollback-"));
    try {
      const calls: string[][] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd, home: cwd },
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
        ["claude", "plugin", "marketplace", "add", join(cwd, ".ai-skills/native/claude-code")],
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
      const received: string[][] = [];
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
      const lock = await readState("project", { cwd, home: cwd });
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
      let received: string[] = [];
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
      const lock = await readState("project", { cwd, home: cwd });
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
              capability: "explode" as const,
              source: "probe" as const,
              version: "project:present:nocli",
            },
          },
          schemaVersion: 1,
        },
        { home: cwd },
      );
      let received: string[] = [];
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
            const error: NodeJS.ErrnoException = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          sourceRoot,
        },
      );
      expect(received).toEqual([]);
      expect(await readFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      const lock = await readState("project", { cwd, home: cwd });
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
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: null,
          project: true,
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd, home: cwd },
        {
          hostCapabilities: { cursor: "native" },
          sourceRoot: null,
          sourceSkills: stubSources,
        },
      );
      expect(await readlink(join(cwd, ".cursor/skills/lint"))).toBe(
        join(cwd, ".agents/skills/lint"),
      );
      const lock = await readState("project", { cwd, home: cwd });
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
      await writeLegacyLock(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            jira: {
              agents: {
                cursor: {
                  files: { "jira/SKILL.md": "abc" },
                  projector: "explode" as const,
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-07-10T16:00:00.000Z",
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
          },
          scope: "project" as const,
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
          projector: "native" as const,
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
    const warnings: string[] = [];
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/jira"), { recursive: true });
      await writeFile(explodeFile, "# jira\n");
      await writeFile(join(sourceRoot, "skills/jira/SKILL.md"), "# jira\n");
      await writeLegacyLock(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            jira: {
              agents: {
                cursor: {
                  files: { "jira/SKILL.md": "abc" },
                  projector: "explode" as const,
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-07-10T16:00:00.000Z",
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
          },
          scope: "project" as const,
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
            projector: "native" as const,
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
      const lock = await readState("project", { cwd, home: cwd });
      expect(lock.plugins.jira.agents.cursor.projector).toBe("native");
      expect(await readFile(explodeFile, "utf8")).toBe("# jira\n");
      const lines: string[] = [];
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
            const error: NodeJS.ErrnoException = new Error("not found");
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
                    projector: "native" as const,
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native" as const,
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-dev",
                vendor: "lgtm-hq",
                version: "0.0.0-dev",
              },
            },
            scope: "project" as const,
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
      const lock = await readState("project", { cwd });
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
      let received: string[] = [];
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
      const lock = await readState("project", { cwd });
      expect(lock.plugins.lint.agents.cursor.projector).toBe("explode");
      expect(lock.plugins.lint.agents.cursor.root).toBe(join(cwd, ".cursor/skills"));
      expect(lock.plugins.lint.agents.cursor.files).toEqual({
        "lint/SKILL.md": stubDigest("lint"),
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("uninstalls a Claude plugin this run created when lock write fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-created-rollback-"));
    try {
      const calls: string[][] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd, home: cwd },
          {
            journal: { failBeforeCommit: true },
            exec: async (command, args) => {
              calls.push([command, ...args]);
              return { status: 0, stderr: "", stdout: "ok" };
            },
          },
        ),
      ).rejects.toThrow("rolled back");
      expect(calls).toEqual([
        ["claude", "plugin", "marketplace", "add", join(cwd, ".ai-skills/native/claude-code")],
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
      const calls: string[][] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd, home: cwd },
          {
            journal: { failBeforeCommit: true },
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
      const calls: string[][] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd, home: cwd },
          {
            journal: { failBeforeCommit: true },
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
      const calls: string[][] = [];
      await expect(
        install(
          {
            ...unattendedOptions,
            agents: ["claude-code"],
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {
            throw new Error("explode runner must not run");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd, home: cwd },
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
                    projector: "native" as const,
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native" as const,
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project" as const,
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
            projector: "native" as const,
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { journal: { failBeforeCommit: true }, sourceRoot },
        ),
      ).rejects.toThrow("Install rolled back: injected failure before commit");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      await expect(readFile(join(pluginDir, "skills/lint/SKILL.md"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("keeps a prior Cursor tree's user files when a write fails mid-install", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-write-fail-"));
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
                    projector: "native" as const,
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native" as const,
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project" as const,
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      let writes = 0;
      await expect(
        install(
          {
            ...unattendedOptions,
            global: false,
            projector: "native" as const,
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          {
            journal: {
              io: {
                writeFile: (async (...args: Parameters<typeof writeFile>) => {
                  writes += 1;
                  if (writes === 2) {
                    throw new Error("ENOSPC: disk full");
                  }
                  return writeFile(...args);
                }) as typeof writeFile,
              },
            },
            sourceRoot,
          },
        ),
      ).rejects.toThrow("Install rolled back: ENOSPC: disk full");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      await expect(access(join(pluginDir, "skills"))).rejects.toMatchObject({ code: "ENOENT" });
      expect((await readState("project", { cwd })).plugins.review?.version).toBe("0.0.0-old");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("replaces a Cursor tree without leaving backup trees beside it", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cursor-no-backup-"));
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
                    projector: "native" as const,
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native" as const,
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project" as const,
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      await install(
        {
          ...unattendedOptions,
          global: false,
          projector: "native" as const,
          project: true,
        },
        async () => {},
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceRoot, warn: () => {} },
      );
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      const siblings = await readdir(join(cwd, ".cursor/plugins/local"));
      expect(siblings).toEqual(["review"]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not touch a leftover Cursor backup when a kept skill has no source", async () => {
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
                    projector: "native" as const,
                    root: pluginDir,
                  },
                },
                installedAt: "2026-07-10T16:00:00.000Z",
                projector: "native" as const,
                repo: "lgtm-hq/ai-skills",
                sha: "v0.0.0-old",
                skills: ["lint", "test"],
                vendor: "lgtm-hq",
                version: "0.0.0-old",
              },
            },
            scope: "project" as const,
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
            projector: "native" as const,
            project: true,
          },
          async () => {},
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { sourceRoot },
        ),
      ).rejects.toThrow("has no source directory");
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
          projector: "explode" as const,
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
      const lock = await readState("project", { cwd });
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
        projector: "explode" as const,
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
      const lock = await readState("project", { cwd });
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
          projector: "explode" as const,
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
            projector: "explode" as const,
            project: true,
            skills: ["test"],
          },
          async () => {
            throw new Error("skills CLI must not run when catalog sources resolve");
          },
          () => new Date("2026-07-10T16:00:00.000Z"),
          { cwd },
          { journal: { failBeforeCommit: true }, sourceRoot },
        ),
      ).rejects.toThrow("Install rolled back: injected failure before commit");
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
          projector: "explode" as const,
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
      const warnings: string[] = [];
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode" as const,
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
      expect(warnings).toContain(
        `skipped identical ${join(cwd, ".cursor/skills/lint")} (not claiming lint on cursor)`,
      );
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("explode lock records nested dest files so remove deletes them", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-cli-explode-nested-"));
    try {
      const dest = join(cwd, ".cursor/skills/lint");
      const source = join(cwd, "catalog/lint");
      await mkdir(source, { recursive: true });
      await writeFile(join(source, "SKILL.md"), "# lint\n");
      await writeFile(join(source, "notes.md"), "notes\n");
      await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode" as const,
          project: true,
          skills: ["lint"],
        },
        skillsCliForbidden,
        () => new Date("2026-07-10T16:00:00.000Z"),
        { cwd },
        { sourceSkills: { lint: source } },
      );
      const lock = await readState("project", { cwd });
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
          run: async () => {
            throw new Error("skills CLI must not run for explode remove");
          },
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
          projector: "explode" as const,
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
      await editState("project", { cwd }, (plugins) => {
        plugins.test!.sha = "v0.0.0-old";
        plugins.test!.version = "0.0.0-old";
      });
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
          run: async () => {
            throw new Error("skills CLI must not run when catalog sources resolve");
          },
          sourceRoot,
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
          projector: "explode" as const,
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
          projector: "explode" as const,
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
          projector: "explode" as const,
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
        },
      );
      await expect(lstat(dest)).rejects.toMatchObject({ code: "ENOENT" });
      const result = await install(
        {
          ...unattendedOptions,
          agents: ["cursor"],
          bundle: null,
          global: false,
          projector: "explode" as const,
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
        projector: "explode" as const,
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
