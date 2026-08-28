import { describe, expect, test } from "bun:test";

import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { listSkills, removeSkills, updateSkills } from "../lib/gateway-commands.js";
import { getPackageVersion } from "../lib/package-version.js";

const pluginEntry = (overrides) => ({
  agents: {
    cursor: {
      files: { "pdf/SKILL.md": "abc" },
      root: "/tmp/project/.cursor/skills",
    },
  },
  installedAt: "2026-07-10T16:00:00.000Z",
  projector: "explode",
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
          root: "/tmp/project/.cursor/skills",
        },
      },
      repo: "lgtm-hq/ai-skills",
      sha: "v0.0.0-dev",
      vendor: "lgtm-hq",
      version: "0.0.0-dev",
    }),
    pdf: pluginEntry({}),
  },
  scope: "project",
  version: 2,
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
      hash: async () => "refreshed",
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
    expect(written.plugins.pdf).toMatchObject({
      installedAt: "2026-07-10T17:00:00.000Z",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
    });
    expect(written.plugins.pdf.agents.cursor.files["pdf/SKILL.md"]).toBe("refreshed");
    expect(written.plugins.lint).toBeUndefined();
    expect(written.skills).toBeUndefined();
  });

  test("skips update when the pin is current and files match", async () => {
    const calls = [];
    const current = {
      ...lock,
      plugins: {
        anthropics: pluginEntry({
          sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
          version: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        }),
      },
    };
    const result = await updateSkills(options, {
      isInstalled: async () => true,
      lockEnvironment: {
        exists: async () => true,
        hash: async () => "abc",
      },
      readLock: async () => current,
      run: async (args) => {
        calls.push(args);
      },
      writeLock: async () => {},
    });

    expect(calls).toEqual([]);
    expect(result).toEqual({ pruned: [], updated: [] });
  });

  test("updates every tracked agent on a plugin even when -a is a subset", async () => {
    const calls = [];
    let written;
    const multiAgentLock = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            "claude-code": {
              files: { "pdf/SKILL.md": "abc" },
              root: "/tmp/project/.claude/skills",
            },
            cursor: {
              files: { "pdf/SKILL.md": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
        }),
      },
    };

    await updateSkills(
      { ...options, agents: ["cursor"] },
      {
        hash: async () => "refreshed",
        isInstalled: async () => true,
        now: () => new Date("2026-07-10T17:00:00.000Z"),
        readLock: async () => multiAgentLock,
        run: async (args) => {
          calls.push(args);
        },
        writeLock: async (next) => {
          written = next;
        },
      },
    );

    expect(calls).toEqual([
      [
        "skills@^1.5.0",
        "add",
        "anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d",
        "-a",
        "claude-code",
        "cursor",
        "--skill",
        "pdf",
        "-y",
      ],
    ]);
    expect(written.plugins.pdf.agents["claude-code"].files["pdf/SKILL.md"]).toBe("refreshed");
    expect(written.plugins.pdf.agents.cursor.files["pdf/SKILL.md"]).toBe("refreshed");
  });

  test("updates same-source plugins against only their own tracked agents", async () => {
    const calls = [];
    const mixed = {
      ...lock,
      plugins: {
        lint: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
        test: pluginEntry({
          agents: {
            "claude-code": {
              files: { "test/SKILL.md": "abc" },
              root: "/tmp/project/.claude/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.0.0-dev",
          vendor: "lgtm-hq",
          version: "0.0.0-dev",
        }),
      },
    };

    await updateSkills(options, {
      hash: async () => "refreshed",
      isInstalled: async () => true,
      now: () => new Date("2026-07-10T17:00:00.000Z"),
      readLock: async () => mixed,
      run: async (args) => {
        calls.push(args);
      },
      writeLock: async () => {},
    });

    expect(calls).toEqual([
      [
        "skills@^1.5.0",
        "add",
        `lgtm-hq/ai-skills@v0.0.0-dev`,
        "-a",
        "cursor",
        "--skill",
        "lint",
        "-y",
      ],
      [
        "skills@^1.5.0",
        "add",
        `lgtm-hq/ai-skills@v0.0.0-dev`,
        "-a",
        "claude-code",
        "--skill",
        "test",
        "-y",
      ],
    ]);
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
    expect(written.plugins).toEqual({
      lint: lock.plugins.lint,
    });
  });

  test("leaves locally modified files with a warning during remove", async () => {
    const warnings = [];
    const unlinked = [];
    const calls = [];
    await removeSkills(
      { ...options, skills: ["pdf"] },
      {
        hash: async () => "changed",
        readLock: async () => lock,
        run: async (args) => {
          calls.push(args);
        },
        unlink: async (path) => {
          unlinked.push(path);
        },
        warn: (message) => {
          warnings.push(message);
        },
        writeLock: async () => {},
      },
    );

    expect(calls).toEqual([]);
    expect(unlinked).toEqual([]);
    expect(warnings).toEqual(["left modified pdf file pdf/SKILL.md"]);
  });

  test("keeps the lock when a verified unlink fails", async () => {
    let written;
    const denied = Object.assign(new Error("EPERM"), { code: "EPERM" });
    await expect(
      removeSkills(
        { ...options, skills: ["pdf"] },
        {
          hash: async () => "abc",
          readLock: async () => lock,
          run: async () => {},
          unlink: async () => {
            throw denied;
          },
          writeLock: async (next) => {
            written = next;
          },
        },
      ),
    ).rejects.toThrow("EPERM");
    expect(written).toBeUndefined();
  });

  test("keeps the lock when a tracked file cannot be hashed", async () => {
    let written;
    const denied = Object.assign(new Error("EACCES"), { code: "EACCES" });
    await expect(
      removeSkills(
        { ...options, skills: ["pdf"] },
        {
          hash: async () => {
            throw denied;
          },
          readLock: async () => lock,
          run: async () => {},
          writeLock: async (next) => {
            written = next;
          },
        },
      ),
    ).rejects.toThrow("EACCES");
    expect(written).toBeUndefined();
  });

  test("refuses to delete lock paths that escape the agent root", async () => {
    const evil = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            cursor: {
              files: { "../../etc/passwd": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
        }),
      },
    };

    await expect(
      removeSkills(
        { ...options, skills: ["pdf"] },
        {
          hash: async () => "abc",
          readLock: async () => evil,
          run: async () => {},
          writeLock: async () => {},
        },
      ),
    ).rejects.toThrow("outside plugin root");
  });

  test("keeps a locally modified skill file on a real filesystem remove", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-remove-mod-"));
    const skillDir = join(cwd, ".cursor/skills/pdf");
    const skillFile = join(skillDir, "SKILL.md");
    const warnings = [];
    const calls = [];
    try {
      await mkdir(skillDir, { recursive: true });
      await writeFile(skillFile, "local edit\n");
      const onDisk = {
        ...lock,
        plugins: {
          pdf: pluginEntry({
            agents: {
              cursor: {
                files: { "pdf/SKILL.md": "abc" },
                root: join(cwd, ".cursor/skills"),
              },
            },
          }),
        },
      };

      await removeSkills(
        { ...options, skills: ["pdf"] },
        {
          readLock: async () => onDisk,
          run: async (args) => {
            calls.push(args);
          },
          warn: (message) => {
            warnings.push(message);
          },
          writeLock: async () => {},
        },
      );

      expect(calls).toEqual([]);
      expect(warnings).toEqual(["left modified pdf file pdf/SKILL.md"]);
      expect(await readFile(skillFile, "utf8")).toBe("local edit\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("prunes nested empty directories after a verified remove", async () => {
    const removed = [];
    const nested = {
      ...lock,
      plugins: {
        pdf: pluginEntry({
          agents: {
            cursor: {
              files: { "pdf/docs/guide.md": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
        }),
      },
    };
    await removeSkills(
      { ...options, skills: ["pdf"] },
      {
        hash: async () => "abc",
        readLock: async () => nested,
        rmdir: async (path) => {
          removed.push(`dir:${path}`);
        },
        run: async () => {},
        unlink: async (path) => {
          removed.push(`file:${path}`);
        },
        writeLock: async () => {},
      },
    );

    expect(removed).toEqual([
      "file:/tmp/project/.cursor/skills/pdf/docs/guide.md",
      "dir:/tmp/project/.cursor/skills/pdf/docs",
      "dir:/tmp/project/.cursor/skills/pdf",
    ]);
  });

  test("rematerializes current first-party plugin skills on update", async () => {
    const calls = [];
    let written;
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };

    await updateSkills(options, {
      hash: async () => "refreshed",
      isInstalled: async () => true,
      now: () => new Date("2026-07-10T17:00:00.000Z"),
      readLock: async () => stale,
      run: async (args) => {
        calls.push(args);
      },
      writeLock: async (next) => {
        written = next;
      },
    });

    expect(calls[0]).toEqual(
      expect.arrayContaining(["--skill", "lint", "test", "greptile", "coderabbit"]),
    );
    expect(Object.keys(written.plugins.review.agents.cursor.files).sort()).toEqual([
      "coderabbit/SKILL.md",
      "greptile/SKILL.md",
      "lint/SKILL.md",
      "test/SKILL.md",
    ]);
  });

  test("keeps nested tracked files for remaining skills on update", async () => {
    let written;
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: {
                "lint/SKILL.md": "abc",
                "lint/docs/guide.md": "abc",
                "retired/docs/old.md": "abc",
              },
              root: "/tmp/project/.cursor/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };

    await updateSkills(options, {
      hash: async () => "refreshed",
      isInstalled: async () => true,
      now: () => new Date("2026-07-10T17:00:00.000Z"),
      readLock: async () => stale,
      rmdir: async () => {},
      run: async () => {},
      unlink: async () => {},
      warn: () => {},
      writeLock: async (next) => {
        written = next;
      },
    });

    expect(written.plugins.review.agents.cursor.files).toMatchObject({
      "lint/SKILL.md": "refreshed",
      "lint/docs/guide.md": "refreshed",
    });
    expect(Object.keys(written.plugins.review.agents.cursor.files)).not.toContain(
      "retired/docs/old.md",
    );
  });

  test("hash-verifies and drops skills removed from the catalog on update", async () => {
    const calls = [];
    const unlinked = [];
    let written;
    const stale = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: {
                "lint/SKILL.md": "abc",
                "retired/SKILL.md": "abc",
              },
              root: "/tmp/project/.cursor/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: "v0.21.0",
          vendor: "lgtm-hq",
          version: "0.21.0",
        }),
      },
    };

    await updateSkills(options, {
      hash: async () => "abc",
      isInstalled: async () => true,
      now: () => new Date("2026-07-10T17:00:00.000Z"),
      readLock: async () => stale,
      run: async (args) => {
        calls.push(args);
      },
      unlink: async (path) => {
        unlinked.push(path);
      },
      writeLock: async (next) => {
        written = next;
      },
    });

    expect(calls).toEqual(
      expect.arrayContaining([
        expect.arrayContaining(["add", "--skill", "lint", "test", "greptile", "coderabbit"]),
        ["skills@^1.5.0", "remove", "retired", "-a", "cursor", "-y"],
      ]),
    );
    expect(unlinked).toEqual(["/tmp/project/.cursor/skills/retired/SKILL.md"]);
    expect(Object.keys(written.plugins.review.agents.cursor.files)).not.toContain(
      "retired/SKILL.md",
    );
  });

  test("skips first-party update when the package pin is current and files match", async () => {
    const version = getPackageVersion();
    const calls = [];
    const current = {
      ...lock,
      plugins: {
        review: pluginEntry({
          agents: {
            cursor: {
              files: { "lint/SKILL.md": "abc" },
              root: "/tmp/project/.cursor/skills",
            },
          },
          repo: "lgtm-hq/ai-skills",
          sha: `v${version}`,
          vendor: "lgtm-hq",
          version,
        }),
      },
    };

    const result = await updateSkills(options, {
      isInstalled: async () => true,
      lockEnvironment: {
        exists: async () => true,
        hash: async () => "abc",
      },
      readLock: async () => current,
      run: async (args) => {
        calls.push(args);
      },
      writeLock: async () => {},
    });

    expect(calls).toEqual([]);
    expect(result).toEqual({ pruned: [], updated: [] });
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
});
