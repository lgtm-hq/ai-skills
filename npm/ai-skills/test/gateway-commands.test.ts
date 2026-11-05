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
  rename,
  rm,
  rmdir,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { listSkills, removeSkills, updateSkills } from "../lib/gateway-commands.ts";
import { readReceipt } from "../lib/journal/receipts.ts";
import { hashFile } from "../lib/lockfile.ts";
import { getPackageVersion } from "../lib/package-version.ts";
import bundleCatalog from "../data/bundles.json" with { type: "json" };
import vendorCatalog from "../data/vendors.json" with { type: "json" };
import { readState, skillSources, writeLegacyLock } from "./fixtures/state.ts";

// These integration tests project the current catalog, not historical vendor pins.
const anthropics = vendorCatalog.vendors.find((vendor) => vendor.id === "anthropics");
const reviewSkills = bundleCatalog.groups.review.skills;
const gitPrSkills = bundleCatalog.groups["git-pr"].skills;

/** Placeholder project root in fixtures; rebased onto a temp project per test. */
const FIXTURE_ROOT = "/tmp/project";

const pluginEntry = (
  overrides: Partial<import("../lib/lockfile.ts").PluginLockEntry>,
): import("../lib/lockfile.ts").PluginLockEntry => ({
  agents: {
    cursor: {
      files: { "pdf/SKILL.md": "abc" },
      root: `${FIXTURE_ROOT}/.cursor/skills`,
    },
  },
  installedAt: "2026-07-10T16:00:00.000Z",
  projector: "explode" as const,
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
          root: `${FIXTURE_ROOT}/.cursor/skills`,
        },
      },
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      vendor: "lgtm-hq",
      version: "0.0.0-dev",
    }),
    pdf: pluginEntry({}),
  },
  scope: "project" as const,
  version: 2,
};

const options = {
  agents: ["cursor"],
  global: false,
  project: true,
  skills: [],
  yes: true,
};

/** Real one-file sources (`# <name>`) for every skill these tests explode. */
const stubSources = await skillSources([
  ...new Set([...reviewSkills, ...gitPrSkills, "lint", "test", "pdf", "retired"]),
]);

const sha = (text: string) => createHash("sha256").update(text).digest("hex");

/** Hex sha256 of a stub source's `SKILL.md`. */
const stubDigest = (name: string) => sha(`# ${name}\n`);

/** A temporary project and home with a legacy lock v2 seeded (roots rebased). */
interface Project {
  cwd: string;
  home: string;
  env: { cwd: string; home: string };
}

async function withProject(
  seed: object | null,
  run: (project: Project) => Promise<void>,
  files: Record<string, string> = {},
): Promise<void> {
  const base = await mkdtemp(join(tmpdir(), "ai-skills-gateway-"));
  const cwd = join(base, "project");
  const home = join(base, "home");
  await mkdir(cwd, { recursive: true });
  await mkdir(home, { recursive: true });
  try {
    for (const [relative, content] of Object.entries(files)) {
      await mkdir(dirname(join(cwd, relative)), { recursive: true });
      await writeFile(join(cwd, relative), content);
    }
    if (seed) {
      await writeLegacyLock(JSON.parse(JSON.stringify(seed).replaceAll(FIXTURE_ROOT, cwd)), {
        cwd,
        home,
      });
    }
    await run({ cwd, env: { cwd, home }, home });
  } finally {
    await rm(base, { force: true, recursive: true });
  }
}

/** The legacy lock file stays byte-identical and no receipt is committed. */
async function expectUncommitted(project: Project): Promise<void> {
  expect(await readReceipt("project", project.env)).toBeNull();
}

const forbidSkillsCli = async () => {
  throw new Error("managed commands must not call the skills CLI");
};

describe("gateway maintenance commands", () => {
  test("updates surviving lock entries through the explode lane", async () => {
    await withProject(lock, async (project) => {
      const result = await updateSkills(options, {
        isInstalled: async (name) => name === "pdf",
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        run: forbidSkillsCli,
        sourceSkills: stubSources,
        warn: () => {},
      });

      expect(result).toEqual({ pruned: ["lint"], updated: ["pdf"] });
      const written = await readState("project", project.env);
      expect(written.plugins.pdf).toMatchObject({
        installedAt: "2026-07-10T17:00:00.000Z",
        sha: anthropics!.sha,
      });
      expect(written.plugins.pdf.agents.cursor.files["pdf/SKILL.md"]).toBe(stubDigest("pdf"));
      expect(written.plugins.lint).toBeUndefined();
      expect(await readFile(join(project.cwd, ".cursor/skills/pdf/SKILL.md"), "utf8")).toBe(
        "# pdf\n",
      );
    });
  });

  test("refuses a managed update without a local artifact instead of calling the skills CLI", async () => {
    await withProject(lock, async (project) => {
      let ran = false;
      await expect(
        updateSkills(options, {
          isInstalled: async (name) => name === "pdf",
          lockEnvironment: project.env,
          run: async () => {
            ran = true;
          },
          warn: () => {},
        }),
      ).rejects.toThrow("managed installs never fall back to the upstream skills CLI");
      expect(ran).toBe(false);
      await expectUncommitted(project);
    });
  });

  test("skips update when the pin is current and files match", async () => {
    const current = {
      ...lock,
      plugins: {
        anthropics: pluginEntry({ sha: anthropics!.sha, version: anthropics!.sha }),
      },
    };
    await withProject(current, async (project) => {
      const calls: string[][] = [];
      const result = await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: { ...project.env, exists: async () => true, hash: async () => "abc" },
        run: async (args) => {
          calls.push(args);
        },
      });

      expect(calls).toEqual([]);
      expect(result).toEqual({ pruned: [], updated: [] });
      await expectUncommitted(project);
    });
  });

  test("skips update when a baked plugin pin and short version match", async () => {
    const current = {
      ...lock,
      plugins: {
        "document-skills": {
          agents: {
            cursor: {
              files: {
                "docx/SKILL.md": "abc",
                "pdf/SKILL.md": "abc",
                "pptx/SKILL.md": "abc",
                "xlsx/SKILL.md": "abc",
              },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          installedAt: "2026-07-10T16:00:00.000Z",
          projector: "explode" as const,
          repo: "anthropics/skills",
          sha: anthropics!.sha,
          skills: ["docx", "pdf", "pptx", "xlsx"],
          vendor: "anthropics",
          version: anthropics!.sha.slice(0, 7),
        },
      },
    };
    await withProject(current, async (project) => {
      const result = await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: { ...project.env, exists: async () => true, hash: async () => "abc" },
        run: forbidSkillsCli,
      });

      expect(result).toEqual({ pruned: [], updated: [] });
      await expect(access(join(project.cwd, ".cursor"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      await expectUncommitted(project);
    });
  });

  test("updates every tracked agent on a plugin even when -a is a subset", async () => {
    const multiAgentLock = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            "claude-code": {
              files: { "pdf/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.claude/skills`,
            },
            cursor: {
              files: { "pdf/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
        }),
      },
    };
    await withProject(multiAgentLock, async (project) => {
      await updateSkills(
        { ...options, agents: ["cursor"] },
        {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          sourceSkills: stubSources,
          warn: () => {},
        },
      );

      const written = await readState("project", project.env);
      expect(written.plugins.pdf.agents["claude-code"].files["pdf/SKILL.md"]).toBe(
        stubDigest("pdf"),
      );
      expect(written.plugins.pdf.agents.cursor.files["pdf/SKILL.md"]).toBe(stubDigest("pdf"));
      await access(join(project.cwd, ".claude/skills/pdf/SKILL.md"));
      await access(join(project.cwd, ".cursor/skills/pdf/SKILL.md"));
    });
  });

  test("updates same-source plugins against only their own tracked agents", async () => {
    const mixed = {
      ...lock,
      plugins: {
        lint: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-old",
          vendor: "lgtm-hq",
          version: "0.0.0-old",
        }),
        test: pluginEntry({
          agents: {
            "claude-code": {
              files: { "test/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.claude/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-old",
          vendor: "lgtm-hq",
          version: "0.0.0-old",
        }),
      },
    };
    await withProject(mixed, async (project) => {
      await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        sourceSkills: stubSources,
        warn: () => {},
      });

      const written = await readState("project", project.env);
      expect(Object.keys(written.plugins.lint.agents)).toEqual(["cursor"]);
      expect(Object.keys(written.plugins.test.agents)).toEqual(["claude-code"]);
      await access(join(project.cwd, ".cursor/skills/lint/SKILL.md"));
      await access(join(project.cwd, ".claude/skills/test/SKILL.md"));
      await expect(access(join(project.cwd, ".claude/skills/lint"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      await expect(access(join(project.cwd, ".cursor/skills/test"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    });
  });

  test("removes explode lock selections without calling the skills CLI", async () => {
    await withProject(lock, async (project) => {
      const removed = await removeSkills(
        { ...options, skills: ["pdf"] },
        { lockEnvironment: project.env, run: forbidSkillsCli },
      );

      expect(removed).toEqual(["pdf"]);
      const written = await readState("project", project.env);
      expect(written.plugins).toEqual({
        lint: JSON.parse(JSON.stringify(lock.plugins.lint).replaceAll(FIXTURE_ROOT, project.cwd)),
      });
    });
  });

  test("leaves locally modified files with a warning during remove", async () => {
    await withProject(
      lock,
      async (project) => {
        const warnings: string[] = [];
        await removeSkills(
          { ...options, skills: ["pdf"] },
          {
            lockEnvironment: project.env,
            run: forbidSkillsCli,
            warn: (message) => {
              warnings.push(message);
            },
          },
        );

        expect(warnings).toEqual(["left modified pdf file pdf/SKILL.md"]);
        expect(await readFile(join(project.cwd, ".cursor/skills/pdf/SKILL.md"), "utf8")).toBe(
          "changed\n",
        );
        expect((await readState("project", project.env)).plugins.pdf).toBeUndefined();
      },
      { ".cursor/skills/pdf/SKILL.md": "changed\n" },
    );
  });

  test("does not treat native skills/ prefix as a modified skill name", async () => {
    await withProject(null, async (project) => {
      const warnings: string[] = [];
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# dirty\n");
      await writeLegacyLock(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            lint: pluginEntry({
              agents: {
                cursor: {
                  files: { "skills/lint/SKILL.md": "abc" },
                  projector: "native" as const,
                  root: pluginDir,
                },
                codex: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode" as const,
                  root: join(project.cwd, ".codex/skills"),
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              skills: ["lint"],
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            }),
          },
          scope: "project" as const,
          version: 2,
        },
        project.env,
      );
      await removeSkills(
        { ...options, agents: ["cursor", "codex"], skills: ["lint"] },
        {
          hash: async (path) =>
            path === join(pluginDir, "skills/lint/SKILL.md") ? "changed" : "abc",
          lockEnvironment: project.env,
          run: forbidSkillsCli,
          warn: (message) => {
            warnings.push(message);
          },
        },
      );
      expect(warnings).toEqual(["left modified lint file skills/lint/SKILL.md"]);
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# dirty\n");
    });
  });

  test("keeps the lock when a verified unlink fails", async () => {
    const owned = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            cursor: {
              files: { "pdf/SKILL.md": sha("# pdf\n") },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
        }),
      },
    };
    await withProject(
      owned,
      async (project) => {
        const denied = Object.assign(new Error("EPERM: operation not permitted"), {
          code: "EPERM",
        });
        await expect(
          removeSkills(
            { ...options, skills: ["pdf"] },
            {
              journal: {
                io: {
                  rename: (async (from: string, to: string) => {
                    if (String(from).endsWith("pdf/SKILL.md")) {
                      throw denied;
                    }
                    return rename(from, to);
                  }) as typeof rename,
                },
              },
              lockEnvironment: project.env,
              run: forbidSkillsCli,
            },
          ),
        ).rejects.toThrow("Remove rolled back: EPERM");
        await expectUncommitted(project);
        expect(await readFile(join(project.cwd, ".cursor/skills/pdf/SKILL.md"), "utf8")).toBe(
          "# pdf\n",
        );
      },
      { ".cursor/skills/pdf/SKILL.md": "# pdf\n" },
    );
  });

  test("keeps the lock when a tracked file cannot be hashed", async () => {
    await withProject(
      lock,
      async (project) => {
        const denied = Object.assign(new Error("EACCES"), { code: "EACCES" });
        await expect(
          removeSkills(
            { ...options, skills: ["pdf"] },
            {
              hash: async () => {
                throw denied;
              },
              lockEnvironment: project.env,
              run: forbidSkillsCli,
            },
          ),
        ).rejects.toThrow("EACCES");
        await expectUncommitted(project);
      },
      { ".cursor/skills/pdf/SKILL.md": "# pdf\n" },
    );
  });

  test("does not commit an update when stale cleanup cannot hash", async () => {
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": sha("# lint\n"), "retired/SKILL.md": sha("# retired\n") },
              projector: "explode" as const,
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };
    await withProject(
      stale,
      async (project) => {
        const denied = Object.assign(new Error("EACCES"), { code: "EACCES" });
        await expect(
          updateSkills(options, {
            hash: async () => {
              throw denied;
            },
            isInstalled: async () => true,
            lockEnvironment: project.env,
            sourceSkills: stubSources,
            warn: () => {},
          }),
        ).rejects.toThrow("EACCES");
        await expectUncommitted(project);
        expect(await readFile(join(project.cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe(
          "# lint\n",
        );
        await expect(access(join(project.cwd, ".cursor/skills/test"))).rejects.toMatchObject({
          code: "ENOENT",
        });
      },
      {
        ".cursor/skills/lint/SKILL.md": "# lint\n",
        ".cursor/skills/retired/SKILL.md": "# retired\n",
      },
    );
  });

  test("refuses to delete lock paths that escape the agent root", async () => {
    const evil = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            cursor: {
              files: { "../../etc/passwd": "abc" },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
        }),
      },
    };
    await withProject(evil, async (project) => {
      await expect(
        removeSkills(
          { ...options, skills: ["pdf"] },
          { hash: async () => "abc", lockEnvironment: project.env, run: forbidSkillsCli },
        ),
      ).rejects.toThrow("outside explode root");
      await expectUncommitted(project);
    });
  });

  test("keeps a locally modified skill file on a real filesystem remove", async () => {
    await withProject(
      lock,
      async (project) => {
        const warnings: string[] = [];
        await removeSkills(
          { ...options, skills: ["pdf"] },
          {
            lockEnvironment: project.env,
            run: forbidSkillsCli,
            warn: (message) => {
              warnings.push(message);
            },
          },
        );

        expect(warnings).toEqual(["left modified pdf file pdf/SKILL.md"]);
        expect(await readFile(join(project.cwd, ".cursor/skills/pdf/SKILL.md"), "utf8")).toBe(
          "local edit\n",
        );
      },
      { ".cursor/skills/pdf/SKILL.md": "local edit\n" },
    );
  });

  test("prunes nested empty directories after a verified remove", async () => {
    const nested = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            cursor: {
              files: { "pdf/docs/guide.md": sha("guide\n") },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
        }),
      },
    };
    await withProject(
      nested,
      async (project) => {
        await removeSkills(
          { ...options, skills: ["pdf"] },
          { lockEnvironment: project.env, run: forbidSkillsCli },
        );

        await expect(access(join(project.cwd, ".cursor/skills/pdf"))).rejects.toMatchObject({
          code: "ENOENT",
        });
        expect(await readdir(join(project.cwd, ".cursor/skills"))).toEqual([]);
      },
      { ".cursor/skills/pdf/docs/guide.md": "guide\n" },
    );
  });

  test("rematerializes current first-party plugin skills on update", async () => {
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };
    await withProject(stale, async (project) => {
      await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        sourceSkills: stubSources,
        warn: () => {},
      });

      const written = await readState("project", project.env);
      expect(Object.keys(written.plugins.review.agents.cursor.files).sort()).toEqual(
        reviewSkills.map((skill) => `${skill}/SKILL.md`).sort(),
      );
      for (const skill of reviewSkills) {
        await access(join(project.cwd, ".cursor/skills", skill, "SKILL.md"));
      }
    });
  });

  test("keeps nested tracked files for remaining skills on update", async () => {
    await withProject(null, async (project) => {
      const dest = join(project.cwd, ".cursor/skills");
      await mkdir(join(dest, "lint/docs"), { recursive: true });
      await mkdir(join(dest, "retired/docs"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "lint/docs/guide.md"), "guide\n");
      await writeFile(join(dest, "retired/docs/old.md"), "old\n");
      const lintHash = await hashFile(join(dest, "lint/SKILL.md"));
      const guideHash = await hashFile(join(dest, "lint/docs/guide.md"));
      const retiredHash = await hashFile(join(dest, "retired/docs/old.md"));
      const sources = { ...stubSources, lint: join(project.cwd, "catalog/lint") };
      await mkdir(join(sources.lint, "docs"), { recursive: true });
      await writeFile(join(sources.lint, "SKILL.md"), "# lint\n");
      await writeFile(join(sources.lint, "docs/guide.md"), "guide\n");
      await writeLegacyLock(
        {
          ...lock,
          plugins: {
            review: pluginEntry({
              agents: {
                cursor: {
                  files: {
                    "lint/SKILL.md": lintHash,
                    "lint/docs/guide.md": guideHash,
                    "retired/docs/old.md": retiredHash,
                  },
                  projector: "explode" as const,
                  root: dest,
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.21.0",
              vendor: "lgtm-hq",
              version: "0.21.0",
            }),
          },
        },
        project.env,
      );
      await updateSkills(options, {
        hash: hashFile,
        isInstalled: async () => true,
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        sourceSkills: sources,
        warn: () => {},
      });
      const written = await readState("project", project.env);
      expect(written.plugins.review.agents.cursor.files).toMatchObject({
        "lint/SKILL.md": lintHash,
        "lint/docs/guide.md": guideHash,
      });
      expect(Object.keys(written.plugins.review.agents.cursor.files)).not.toContain(
        "retired/docs/old.md",
      );
      await expect(access(join(dest, "retired"))).rejects.toMatchObject({ code: "ENOENT" });
    });
  });

  test("hash-verifies and drops skills removed from the catalog on update", async () => {
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": sha("# lint\n"), "retired/SKILL.md": sha("# retired\n") },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };
    await withProject(
      stale,
      async (project) => {
        await updateSkills(options, {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          sourceSkills: stubSources,
          warn: () => {},
        });

        await expect(access(join(project.cwd, ".cursor/skills/retired"))).rejects.toMatchObject({
          code: "ENOENT",
        });
        const written = await readState("project", project.env);
        expect(Object.keys(written.plugins.review.agents.cursor.files).sort()).toEqual(
          reviewSkills.map((skill) => `${skill}/SKILL.md`).sort(),
        );
      },
      {
        ".cursor/skills/lint/SKILL.md": "# lint\n",
        ".cursor/skills/retired/SKILL.md": "# retired\n",
      },
    );
  });

  test("does not commit when stale cleanup cannot remove a file", async () => {
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": sha("# lint\n"), "retired/SKILL.md": sha("# retired\n") },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };
    await withProject(
      stale,
      async (project) => {
        const warnings: string[] = [];
        await expect(
          updateSkills(options, {
            isInstalled: async () => true,
            journal: {
              io: {
                rename: (async (from: string, to: string) => {
                  if (String(from).endsWith("retired/SKILL.md")) {
                    throw Object.assign(new Error("EACCES: permission denied"), {
                      code: "EACCES",
                    });
                  }
                  return rename(from, to);
                }) as typeof rename,
              },
            },
            lockEnvironment: project.env,
            now: () => new Date("2026-07-10T17:00:00.000Z"),
            sourceSkills: stubSources,
            warn: (message) => warnings.push(message),
          }),
        ).rejects.toThrow("Update rolled back: EACCES");
        await expectUncommitted(project);
        expect(warnings).toEqual([]);
        expect(await readFile(join(project.cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe(
          "# lint\n",
        );
      },
      {
        ".cursor/skills/lint/SKILL.md": "# lint\n",
        ".cursor/skills/retired/SKILL.md": "# retired\n",
      },
    );
  });

  test("restores stale dests when the commit fails after cleanup", async () => {
    await withProject(null, async (project) => {
      const dest = join(project.cwd, ".cursor/skills");
      await mkdir(join(dest, "lint"), { recursive: true });
      await mkdir(join(dest, "retired"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "retired/SKILL.md"), "# retired\n");
      await writeLegacyLock(
        {
          ...lock,
          plugins: {
            review: pluginEntry({
              agents: {
                cursor: {
                  files: {
                    "lint/SKILL.md": await hashFile(join(dest, "lint/SKILL.md")),
                    "retired/SKILL.md": await hashFile(join(dest, "retired/SKILL.md")),
                  },
                  projector: "explode" as const,
                  root: dest,
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.21.0",
              skills: ["lint", "retired"],
              vendor: "lgtm-hq",
              version: "0.21.0",
            }),
          },
        },
        project.env,
      );

      await expect(
        updateSkills(options, {
          hash: hashFile,
          isInstalled: async () => true,
          journal: { failBeforeCommit: true },
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          sourceSkills: stubSources,
          warn: () => {},
        }),
      ).rejects.toThrow("Update rolled back: injected failure before commit");

      expect(await readFile(join(dest, "retired/SKILL.md"), "utf8")).toBe("# retired\n");
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect((await readdir(dest)).sort()).toEqual(["lint", "retired"]);
      await expectUncommitted(project);
    });
  });

  test("stale cleanup does not unlink a dest another plugin still catalogs", async () => {
    await withProject(null, async (project) => {
      const destRoot = join(project.cwd, ".cursor/skills");
      await mkdir(join(destRoot, "lint"), { recursive: true });
      await writeFile(join(destRoot, "lint/SKILL.md"), "# lint\n");
      const lintHash = await hashFile(join(destRoot, "lint/SKILL.md"));
      await writeLegacyLock(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: pluginEntry({
              agents: {
                cursor: {
                  files: { "test/SKILL.md": "keep" },
                  projector: "explode" as const,
                  root: destRoot,
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.21.0",
              vendor: "lgtm-hq",
              version: "0.21.0",
            }),
            "git-pr": pluginEntry({
              agents: {
                cursor: {
                  files: { "branch/SKILL.md": "keep", "lint/SKILL.md": lintHash },
                  projector: "explode" as const,
                  root: destRoot,
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.21.0",
              vendor: "lgtm-hq",
              version: "0.21.0",
            }),
          },
          scope: "project" as const,
          version: 2,
        },
        project.env,
      );
      await updateSkills(
        { agents: ["cursor"], global: false, project: true, skills: [], yes: true },
        {
          hash: hashFile,
          isInstalled: async () => true,
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          sourceSkills: stubSources,
          warn: () => {},
        },
      );
      expect(await readFile(join(destRoot, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    });
  });

  test("explode update records nested dest files so remove deletes them", async () => {
    await withProject(null, async (project) => {
      const dest = join(project.cwd, ".cursor/skills");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      const source = join(project.cwd, "catalog/lint");
      await mkdir(source, { recursive: true });
      await writeFile(join(source, "SKILL.md"), "# lint\n");
      await writeFile(join(source, "notes.md"), "notes\n");
      const lintHash = await hashFile(join(dest, "lint/SKILL.md"));
      await writeLegacyLock(
        {
          gatewayVersion: "0.0.0-old",
          plugins: {
            leftover: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": lintHash },
                  projector: "explode" as const,
                  root: dest,
                },
              },
              installedAt: "2026-07-10T16:00:00.000Z",
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-old",
              skills: ["lint"],
              vendor: "lgtm-hq",
              version: "0.0.0-old",
            },
          },
          scope: "project" as const,
          version: 2,
        },
        project.env,
      );
      await updateSkills(
        { agents: ["cursor"], global: false, project: true, skills: ["leftover"], yes: true },
        {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          sourceSkills: { lint: source },
          warn: () => {},
        },
      );
      const updated = await readState("project", project.env);
      expect(Object.keys(updated.plugins.leftover.agents.cursor.files).sort()).toEqual([
        "lint/SKILL.md",
        "lint/notes.md",
      ]);
      await removeSkills(
        { agents: ["cursor"], global: false, project: true, skills: ["leftover"], yes: true },
        { lockEnvironment: project.env, run: forbidSkillsCli },
      );
      await expect(readFile(join(dest, "lint/notes.md"), "utf8")).rejects.toMatchObject({
        code: "ENOENT",
      });
    });
  });

  test("drops only catalog-removed skills when the lock lists a v2 skills array", async () => {
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": sha("# lint\n"), "retired/SKILL.md": sha("# retired\n") },
              projector: "explode" as const,
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
            "claude-code": {
              files: { "lint/SKILL.md": "", "retired/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "explode" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          skills: ["lint", "test", "greptile", "coderabbit", "retired"],
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };
    await withProject(
      stale,
      async (project) => {
        const calls: string[][] = [];
        await updateSkills(options, {
          exec: async (command, args) => {
            calls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "" };
          },
          isInstalled: async () => true,
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          sourceSkills: stubSources,
          warn: () => {},
        });

        expect(calls.find((args) => args.includes("remove"))).toBeUndefined();
        expect(calls.find((args) => args.includes("uninstall"))).toBeUndefined();
        await expect(access(join(project.cwd, ".cursor/skills/retired"))).rejects.toMatchObject({
          code: "ENOENT",
        });
        expect(await readFile(join(project.cwd, ".cursor/skills/lint/SKILL.md"), "utf8")).toBe(
          "# lint\n",
        );
      },
      {
        ".cursor/skills/lint/SKILL.md": "# lint\n",
        ".cursor/skills/retired/SKILL.md": "# retired\n",
      },
    );
  });

  test("skips first-party update when the package pin is current and files match", async () => {
    const version = getPackageVersion();
    const current = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: `${FIXTURE_ROOT}/.cursor/skills`,
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: `v${version}`,
          vendor: "lgtm-hq",
          version,
        }),
      },
    };
    await withProject(current, async (project) => {
      const result = await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: { ...project.env, exists: async () => true, hash: async () => "abc" },
        run: forbidSkillsCli,
      });

      expect(result).toEqual({ pruned: [], updated: [] });
      await expectUncommitted(project);
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
    expect(plugins.find((plugin) => plugin.name === "lint")?.agentStatus).toEqual({ cursor: "" });
    expect(plugins.find((plugin) => plugin.name === "lint")?.skills).toEqual(["lint"]);
    expect(plugins.find((plugin) => plugin.name === "pdf")?.skills).toEqual(["pdf"]);
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
        expect.objectContaining({
          name: "lint",
          status: "MODIFIED",
          agentStatus: { cursor: "MODIFIED" },
        }),
        expect.objectContaining({
          name: "pdf",
          status: "MISSING",
          agentStatus: { cursor: "MISSING" },
        }),
      ]),
    );
  });

  test("updates a native CLI plugin through the host CLI instead of skills add", async () => {
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            "claude-code": {
              files: { "lint/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-old",
          vendor: "lgtm-hq",
          version: "0.0.0-old",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const execCalls: string[][] = [];
      await updateSkills(options, {
        exec: async (command, args) => {
          execCalls.push([command, ...args]);
          return { status: 0, stderr: "", stdout: "" };
        },
        isInstalled: async () => true,
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        run: forbidSkillsCli,
        warn: () => {},
      });
      // Native delivery registers the locally rendered envelope, never a remote repo.
      const envelope = join(project.home, ".ai-skills/native/claude-code");
      expect(execCalls).toEqual([
        ["claude", "plugin", "marketplace", "add", envelope],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      const marketplace = JSON.parse(
        await readFile(join(envelope, ".claude-plugin/marketplace.json"), "utf8"),
      );
      expect(marketplace.plugins.map((plugin: { name: string }) => plugin.name)).toEqual([
        "review",
      ]);
      await expect(
        readFile(join(envelope, "review/skills/lint/SKILL.md"), "utf8"),
      ).resolves.toContain("name:");
      const receipt = await readReceipt("project", project.env);
      expect(receipt?.registrations.map((item) => item.argv.slice(0, 3))).toEqual([
        ["claude", "plugin", "marketplace"],
        ["claude", "plugin", "install"],
      ]);
    });
  });

  test("removes a native CLI plugin through the host CLI", async () => {
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            "claude-code": {
              files: { "lint/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const execCalls: string[][] = [];
      const removed = await removeSkills(options, {
        exec: async (command, args) => {
          execCalls.push([command, ...args]);
          return { status: 0, stderr: "", stdout: "" };
        },
        lockEnvironment: project.env,
        run: forbidSkillsCli,
      });
      expect(removed).toEqual(["review"]);
      expect(execCalls).toEqual([["claude", "plugin", "uninstall", "review@ai-skills"]]);
      expect((await readState("project", project.env)).plugins).toEqual({});
    });
  });

  test("rolls back a remove when the host uninstall fails", async () => {
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            "claude-code": {
              files: { "lint/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const execCalls: string[][] = [];
      await expect(
        removeSkills(options, {
          exec: async (command, args) => {
            execCalls.push([command, ...args]);
            return { status: 1, stderr: "permission denied", stdout: "" };
          },
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        }),
      ).rejects.toThrow("Remove rolled back: claude plugin uninstall failed: permission denied");
      expect(execCalls).toEqual([["claude", "plugin", "uninstall", "review@ai-skills"]]);
      await expectUncommitted(project);
      expect(Object.keys((await readState("project", project.env)).plugins)).toEqual(["review"]);
    });
  });

  test("reinstalls a CLI plugin it uninstalled when a sibling uninstall fails", async () => {
    const native = (root: string) => ({
      files: { "lint/SKILL.md": "" },
      projector: "native" as const,
      root,
    });
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: { "claude-code": native("cli:claude-code"), copilot: native("cli:copilot") },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const execCalls: string[][] = [];
      await expect(
        removeSkills(options, {
          exec: async (command, args) => {
            execCalls.push([command, ...args]);
            if (command === "copilot" && args.includes("uninstall")) {
              return { status: 1, stderr: "permission denied", stdout: "" };
            }
            return { status: 0, stderr: "", stdout: "" };
          },
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        }),
      ).rejects.toThrow("copilot plugin uninstall failed: permission denied");
      expect(execCalls).toEqual([
        ["claude", "plugin", "uninstall", "review@ai-skills"],
        ["copilot", "plugin", "uninstall", "review@ai-skills"],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      await expectUncommitted(project);
    });
  });

  test("restores removed files when a later host uninstall fails", async () => {
    await withProject(null, async (project) => {
      const pluginDir = join(project.cwd, ".cursor/plugins/local/review");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint\n");
      await mkdir(join(project.cwd, ".codex/skills/lint"), { recursive: true });
      await writeFile(join(project.cwd, ".codex/skills/lint/SKILL.md"), "# lint\n");
      const lintHash = sha("# lint\n");
      await writeLegacyLock(
        {
          ...lock,
          plugins: {
            review: pluginEntry({
              agents: {
                "claude-code": {
                  files: { "lint/SKILL.md": "" },
                  projector: "native" as const,
                  root: "cli:claude-code",
                },
                cursor: {
                  files: { "skills/lint/SKILL.md": lintHash },
                  projector: "native" as const,
                  root: pluginDir,
                },
                codex: {
                  files: { "lint/SKILL.md": lintHash },
                  projector: "explode" as const,
                  root: join(project.cwd, ".codex/skills"),
                },
              },
              projector: "explode" as const,
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            }),
          },
        },
        project.env,
      );
      await expect(
        removeSkills(options, {
          exec: async () => ({ status: 1, stderr: "permission denied", stdout: "" }),
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        }),
      ).rejects.toThrow("claude plugin uninstall failed: permission denied");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(project.cwd, ".codex/skills/lint/SKILL.md"), "utf8")).toBe(
        "# lint\n",
      );
      await expectUncommitted(project);
    });
  });

  test("keeps the uninstall error and the journal when compensation also fails", async () => {
    const native = (root: string) => ({
      files: { "lint/SKILL.md": "" },
      projector: "native" as const,
      root,
    });
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: { "claude-code": native("cli:claude-code"), copilot: native("cli:copilot") },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const error = await removeSkills(options, {
        exec: async (command, args) =>
          command === "claude" && args.includes("uninstall")
            ? { status: 0, stderr: "", stdout: "" }
            : { status: 1, stderr: "permission denied", stdout: "" },
        lockEnvironment: project.env,
        run: forbidSkillsCli,
      }).then(
        () => new Error("remove unexpectedly succeeded"),
        (caught: unknown) => caught as Error,
      );
      expect(error.message).toContain("copilot plugin uninstall failed: permission denied");
      expect(error.message).toContain(
        "rollback also failed: host-exec claude plugin uninstall review@ai-skills: " +
          "claude plugin install failed: permission denied",
      );
      expect(error.message).toContain(join(project.home, ".ai-skills/state/journal"));
      await expectUncommitted(project);
    });
  });

  test("reinstalls a CLI plugin when the remove cannot commit", async () => {
    const nativeLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            "claude-code": {
              files: { "lint/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };
    await withProject(nativeLock, async (project) => {
      const execCalls: string[][] = [];
      await expect(
        removeSkills(options, {
          exec: async (command, args) => {
            execCalls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "" };
          },
          journal: { failBeforeCommit: true },
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        }),
      ).rejects.toThrow("Remove rolled back: injected failure before commit");
      expect(execCalls).toEqual([
        ["claude", "plugin", "uninstall", "review@ai-skills"],
        ["claude", "plugin", "install", "review@ai-skills"],
      ]);
      await expectUncommitted(project);
    });
  });

  test("keeps a user-scoped CLI plugin when the sibling lock still owns it", async () => {
    const projectLock = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            "claude-code": {
              files: { "lint/SKILL.md": "" },
              projector: "native" as const,
              root: "cli:claude-code",
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
      scope: "project" as const,
    };
    await withProject(projectLock, async (project) => {
      await writeLegacyLock({ ...projectLock, scope: "global" as const }, project.env);
      const execCalls: string[][] = [];
      const removed = await removeSkills(options, {
        exec: async (command, args) => {
          execCalls.push([command, ...args]);
          return { status: 0, stderr: "", stdout: "" };
        },
        lockEnvironment: project.env,
        run: forbidSkillsCli,
      });
      expect(removed).toEqual(["review"]);
      expect(execCalls).toEqual([]);
    });
  });

  test("skips host uninstall on global remove when the cwd project lock still owns it", async () => {
    const entry = pluginEntry({
      agents: {
        "claude-code": {
          files: { "lint/SKILL.md": "" },
          projector: "native" as const,
          root: "cli:claude-code",
        },
      },
      projector: "native" as const,
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      vendor: "lgtm-hq",
      version: "0.0.0-dev",
    });
    const projectLock = {
      gatewayVersion: "0.0.0-dev",
      plugins: { review: entry },
      scope: "project" as const,
      version: 2,
    };
    await withProject(projectLock, async (project) => {
      await writeLegacyLock({ ...projectLock, scope: "global" as const }, project.env);
      const execCalls: string[][] = [];
      const removed = await removeSkills(
        { agents: ["claude-code"], global: true, project: false, skills: [], yes: true },
        {
          exec: async (command, args) => {
            execCalls.push([command, ...args]);
            return { status: 0, stderr: "", stdout: "" };
          },
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        },
      );
      expect(removed).toEqual(["review"]);
      expect(execCalls).toEqual([]);
    });
  });

  test("updates a first-party plugin from its baked tree without a catalog checkout", async () => {
    const baked = await mkdtemp(join(tmpdir(), "ai-skills-baked-first-party-"));
    const previous = process.env.AI_SKILLS_PLUGINS_BAKED;
    try {
      await mkdir(join(baked, ".claude-plugin"), { recursive: true });
      await writeFile(
        join(baked, ".claude-plugin/marketplace.json"),
        JSON.stringify({ name: "ai-skills", plugins: [{ name: "zeta-tools", version: "9.9.9" }] }),
      );
      await writeFile(
        join(baked, "BAKE.json"),
        JSON.stringify({
          vendors: [
            {
              id: "lgtm-hq",
              plugins: [{ id: "zeta-tools" }],
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
            },
          ],
        }),
      );
      await mkdir(join(baked, "zeta-tools/skills/zeta-one"), { recursive: true });
      await writeFile(join(baked, "zeta-tools/skills/zeta-one/SKILL.md"), "# zeta-one baked\n");
      process.env.AI_SKILLS_PLUGINS_BAKED = baked;
      const stale = {
        ...lock,
        plugins: {
          "zeta-tools": pluginEntry({
            agents: {
              cursor: {
                files: { "zeta-one/SKILL.md": "abc" },
                projector: "explode" as const,
                root: `${FIXTURE_ROOT}/.cursor/skills`,
              },
            },
            repo: "lgtm-hq/ai-skills",
            sha: "v0.0.0-old",
            vendor: "lgtm-hq",
            version: "0.0.0-old",
          }),
        },
      };
      await withProject(stale, async (project) => {
        const result = await updateSkills(options, {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          run: forbidSkillsCli,
          warn: () => {},
        });
        expect(result.updated).toEqual(["zeta-tools"]);
        expect(await readFile(join(project.cwd, ".cursor/skills/zeta-one/SKILL.md"), "utf8")).toBe(
          "# zeta-one baked\n",
        );
        const written = await readState("project", project.env);
        expect(written.plugins["zeta-tools"].version).toBe(getPackageVersion());
        expect(written.plugins["zeta-tools"].sha).toBe(`v${getPackageVersion()}`);
      });
    } finally {
      if (previous === undefined) {
        delete process.env.AI_SKILLS_PLUGINS_BAKED;
      } else {
        process.env.AI_SKILLS_PLUGINS_BAKED = previous;
      }
      await rm(baked, { force: true, recursive: true });
    }
  });

  test("does not tell update to pass --projector explode when catalog is missing", async () => {
    const nativeLock = {
      gatewayVersion: "0.0.0-dev",
      plugins: {
        lint: pluginEntry({
          agents: {
            cursor: {
              files: { ".claude-plugin/plugin.json": "old" },
              projector: "native" as const,
              root: `${FIXTURE_ROOT}/.cursor/plugins/local/lint`,
            },
          },
          projector: "native" as const,
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-old",
          skills: ["lint"],
          vendor: "lgtm-hq",
          version: "0.0.0-old",
        }),
      },
      scope: "project" as const,
      version: 2,
    };
    await withProject(nativeLock, async (project) => {
      let message = "";
      try {
        await updateSkills(options, {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          run: forbidSkillsCli,
          sourceRoot: null,
        });
      } catch (error) {
        message = error instanceof Error ? error.message : String(error);
      }
      expect(message).toContain("requires a catalog checkout");
      expect(message).toContain("Run update from the ai-skills repository");
      expect(message).not.toMatch(/Use --projector explode/);
    });
  });

  /** Legacy lock for a native Cursor `lint` plugin at `pluginDir`. */
  const cursorLock = (pluginDir: string, files: Record<string, string>) => ({
    gatewayVersion: "0.0.0-dev",
    plugins: {
      lint: pluginEntry({
        agents: { cursor: { files, projector: "native" as const, root: pluginDir } },
        projector: "native" as const,
        repo: "lgtm-hq/ai-skills",
        sha: "v0.0.0-old",
        skills: ["lint"],
        vendor: "lgtm-hq",
        version: "0.0.0-old",
      }),
    },
    scope: "project" as const,
    version: 2,
  });

  test("rolls back a remove when the plugin directory cannot be removed", async () => {
    await withProject(null, async (project) => {
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint\n");
      await writeLegacyLock(
        cursorLock(pluginDir, { "skills/lint/SKILL.md": sha("# lint\n") }),
        project.env,
      );
      await expect(
        removeSkills(options, {
          journal: {
            io: {
              rmdir: (async (path: string) => {
                if (path === pluginDir) {
                  throw Object.assign(new Error("EACCES: permission denied"), {
                    code: "EACCES",
                  });
                }
                return rmdir(path);
              }) as typeof rmdir,
            },
          },
          lockEnvironment: project.env,
          run: forbidSkillsCli,
        }),
      ).rejects.toThrow("Remove rolled back: EACCES");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint\n");
      await expectUncommitted(project);
    });
  });

  test("updates a native Cursor plugin by reassembling the local tree", async () => {
    await withProject(null, async (project) => {
      const sourceRoot = join(project.cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint v2\n");
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await writeLegacyLock(
        cursorLock(pluginDir, { ".claude-plugin/plugin.json": "old" }),
        project.env,
      );
      await updateSkills(options, {
        isInstalled: async () => true,
        lockEnvironment: project.env,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        run: forbidSkillsCli,
        sourceRoot,
        warn: () => {},
      });
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
      const written = await readState("project", project.env);
      expect(written.plugins.lint.agents.cursor.files["skills/lint/SKILL.md"]).toBe(
        sha("# lint v2\n"),
      );
    });
  });

  test("restores a native Cursor tree when the update cannot commit", async () => {
    await withProject(null, async (project) => {
      const sourceRoot = join(project.cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint v2\n");
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint v1\n");
      await writeLegacyLock(cursorLock(pluginDir, { "skills/lint/SKILL.md": "old" }), project.env);
      await expect(
        updateSkills(options, {
          isInstalled: async () => true,
          journal: { failBeforeCommit: true },
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          run: forbidSkillsCli,
          sourceRoot,
          warn: () => {},
        }),
      ).rejects.toThrow("Update rolled back: injected failure before commit");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint v1\n");
      await expect(access(join(pluginDir, ".claude-plugin"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      await expectUncommitted(project);
    });
  });

  test("restores a native Cursor tree when a write fails mid-update", async () => {
    await withProject(null, async (project) => {
      const sourceRoot = join(project.cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint v2\n");
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint v1\n");
      await writeLegacyLock(cursorLock(pluginDir, { "skills/lint/SKILL.md": "old" }), project.env);
      let writes = 0;
      await expect(
        updateSkills(options, {
          isInstalled: async () => true,
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
          lockEnvironment: project.env,
          now: () => new Date("2026-07-10T17:00:00.000Z"),
          run: forbidSkillsCli,
          sourceRoot,
          warn: () => {},
        }),
      ).rejects.toThrow("Update rolled back: ENOSPC: disk full");
      expect(await readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).toBe("# lint v1\n");
      expect((await readdir(join(pluginDir, "skills/lint"))).sort()).toEqual(["SKILL.md"]);
      await expectUncommitted(project);
    });
  });

  test("remove leaves untracked Cursor plugin files in place", async () => {
    await withProject(null, async (project) => {
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, ".claude-plugin"), { recursive: true });
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, ".claude-plugin/plugin.json"), "{}\n");
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(pluginDir, "USER-DATA.txt"), "keep\n");
      await writeLegacyLock(
        cursorLock(pluginDir, {
          ".claude-plugin/plugin.json": await hashFile(
            join(pluginDir, ".claude-plugin/plugin.json"),
          ),
          "skills/lint/SKILL.md": await hashFile(join(pluginDir, "skills/lint/SKILL.md")),
        }),
        project.env,
      );
      await removeSkills(options, { lockEnvironment: project.env, run: forbidSkillsCli });
      expect(await readFile(join(pluginDir, "USER-DATA.txt"), "utf8")).toBe("keep\n");
      await expect(
        readFile(join(pluginDir, ".claude-plugin/plugin.json"), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" });
      await expect(readFile(join(pluginDir, "skills/lint/SKILL.md"), "utf8")).rejects.toMatchObject(
        { code: "ENOENT" },
      );
    });
  });

  test("remove deletes an empty Cursor plugin directory after verified files", async () => {
    await withProject(null, async (project) => {
      const pluginDir = join(project.cwd, ".cursor/plugins/local/lint");
      await mkdir(join(pluginDir, ".claude-plugin"), { recursive: true });
      await mkdir(join(pluginDir, "skills/lint"), { recursive: true });
      await writeFile(join(pluginDir, ".claude-plugin/plugin.json"), "{}\n");
      await writeFile(join(pluginDir, "skills/lint/SKILL.md"), "# lint\n");
      await writeLegacyLock(
        cursorLock(pluginDir, {
          ".claude-plugin/plugin.json": await hashFile(
            join(pluginDir, ".claude-plugin/plugin.json"),
          ),
          "skills/lint/SKILL.md": await hashFile(join(pluginDir, "skills/lint/SKILL.md")),
        }),
        project.env,
      );
      await removeSkills(options, { lockEnvironment: project.env, run: forbidSkillsCli });
      await expect(access(pluginDir)).rejects.toMatchObject({ code: "ENOENT" });
    });
  });

  /** Legacy lock for an explode `leftover` plugin owning `files` under `dest`. */
  const leftoverLock = (dest: string, files: Record<string, string>, skills: string[]) => ({
    gatewayVersion: "0.0.0-old",
    plugins: {
      leftover: {
        agents: { cursor: { files, projector: "explode" as const, root: dest } },
        installedAt: "2026-07-10T16:00:00.000Z",
        projector: "explode" as const,
        repo: "lgtm-hq/ai-skills",
        sha: "v0.0.0-old",
        skills,
        vendor: "lgtm-hq",
        version: "0.0.0-old",
      },
    },
    scope: "project" as const,
    version: 2,
  });

  test("update explode does not claim a skipped identical dest", async () => {
    await withProject(null, async (project) => {
      const dest = join(project.cwd, ".cursor/skills");
      const sourceRoot = join(project.cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/test"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(join(sourceRoot, "skills/test/SKILL.md"), "# test\n");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await mkdir(join(dest, "test"), { recursive: true });
      await writeFile(join(dest, "test/SKILL.md"), "# test\n");
      const testHash = await hashFile(join(sourceRoot, "skills/test/SKILL.md"));
      await writeLegacyLock(
        leftoverLock(dest, { "test/SKILL.md": testHash }, ["lint", "test"]),
        project.env,
      );
      await updateSkills(
        { agents: ["cursor"], global: false, project: true, skills: ["leftover"], yes: true },
        {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          run: forbidSkillsCli,
          sourceRoot,
          warn: () => {},
        },
      );
      const updated = await readState("project", project.env);
      expect(updated.plugins.leftover.sha).not.toBe("v0.0.0-old");
      expect(updated.plugins.leftover.installedAt).not.toBe("2026-07-10T16:00:00.000Z");
      expect(Object.keys(updated.plugins.leftover.agents.cursor.files).sort()).toEqual([
        "test/SKILL.md",
      ]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    });
  });

  test("update keeps ownership of an owned dest whose content is unchanged", async () => {
    await withProject(null, async (project) => {
      const dest = join(project.cwd, ".cursor/skills");
      const sourceRoot = join(project.cwd, "catalog");
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      const lintHash = await hashFile(join(dest, "lint/SKILL.md"));
      await writeLegacyLock(
        leftoverLock(dest, { "lint/SKILL.md": lintHash }, ["lint"]),
        project.env,
      );
      await updateSkills(
        { agents: ["cursor"], global: false, project: true, skills: ["leftover"], yes: true },
        {
          isInstalled: async () => true,
          lockEnvironment: project.env,
          run: forbidSkillsCli,
          sourceRoot,
          warn: () => {},
        },
      );
      const updated = await readState("project", project.env);
      expect(updated.plugins.leftover.agents.cursor.files).toEqual({ "lint/SKILL.md": lintHash });
      expect(updated.plugins.leftover.sha).not.toBe("v0.0.0-old");
      // The owned real directory stays a copy, not a store symlink.
      expect((await lstat(join(dest, "lint"))).isDirectory()).toBe(true);
      await expect(readlink(join(dest, "lint"))).rejects.toMatchObject({ code: "EINVAL" });
    });
  });
});
