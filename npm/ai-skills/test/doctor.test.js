import { describe, expect, test } from "bun:test";
import { access, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  doctorCachePath,
  ensureHostCapability,
  probeHost,
  readDoctorCache,
  runDoctor,
  writeDoctorCache,
} from "../lib/doctor.js";
import { writeLockfile } from "../lib/lockfile.js";

describe("probeHost", () => {
  test("treats a missing Claude CLI as explode", async () => {
    const result = await probeHost("claude-code", {
      exec: async () => {
        const error = new Error("not found");
        error.code = "ENOENT";
        throw error;
      },
    });
    expect(result.capability).toBe("explode");
  });

  test("treats a responding Copilot plugin CLI as native", async () => {
    const result = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.2.3\n" };
        }
        return { status: 0, stderr: "", stdout: "Usage: copilot plugin\n" };
      },
    });
    expect(result).toEqual({ capability: "native", version: "1.2.3" });
  });

  test("treats Cursor plugins/local as native", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-cursor-"));
    try {
      await mkdir(join(home, ".cursor/plugins/local"), { recursive: true });
      const result = await probeHost("cursor", {
        exec: async () => {
          const error = new Error("not found");
          error.code = "ENOENT";
          throw error;
        },
        home,
      });
      expect(result.capability).toBe("native");
      expect(result.version).toBe("global:present:nocli");
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("keeps Codex exploded", async () => {
    expect(await probeHost("codex")).toEqual({
      capability: "explode",
      version: "n/a",
    });
  });

  test("treats an unrecognized plugin subcommand as explode", async () => {
    const result = await probeHost("claude-code", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return {
          status: 1,
          stderr: "error: unrecognized subcommand plugin\n",
          stdout: "",
        };
      },
    });
    expect(result.capability).toBe("explode");
  });

  test("treats unknown subcommand and unrecognized argument as explode", async () => {
    const unknown = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return { status: 1, stderr: "unknown subcommand plugin\n", stdout: "" };
      },
    });
    expect(unknown.capability).toBe("explode");
    const argument = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return {
          status: 1,
          stderr: "unrecognized argument plugin\n",
          stdout: "",
        };
      },
    });
    expect(argument.capability).toBe("explode");
  });

  test("classifies command not found as explode and other not-found as ambiguous", async () => {
    const command = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return {
          status: 127,
          stderr: "command not found: copilot\n",
          stdout: "",
        };
      },
    });
    expect(command.capability).toBe("explode");
    const file = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return { status: 1, stderr: "file not found\n", stdout: "" };
      },
    });
    expect(file.capability).toBe("explode");
    const config = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return { status: 1, stderr: "config not found\n", stdout: "" };
      },
    });
    expect(config.capability).toBe("ambiguous");
    const bare = await probeHost("copilot", {
      exec: async (_command, args) => {
        if (args[0] === "--version") {
          return { status: 0, stderr: "", stdout: "1.0.0\n" };
        }
        return { status: 1, stderr: "plugin not found\n", stdout: "" };
      },
    });
    expect(bare.capability).toBe("ambiguous");
  });
});

describe("ensureHostCapability", () => {
  test("caches a probe and skips the plugin subcommand on the same version", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-cache-"));
    const calls = [];
    const exec = async (command, args) => {
      calls.push([command, ...args]);
      if (args[0] === "--version") {
        return { status: 0, stderr: "", stdout: "9.9.9\n" };
      }
      return { status: 0, stderr: "", stdout: "plugin help\n" };
    };
    try {
      const first = await ensureHostCapability("claude-code", {
        exec,
        home,
        yes: true,
      });
      expect(first).toEqual({
        capability: "native",
        source: "probe",
        version: "9.9.9",
      });
      const cached = JSON.parse(await readFile(doctorCachePath(home), "utf8"));
      expect(cached.hosts["claude-code"].capability).toBe("native");
      calls.length = 0;
      const second = await ensureHostCapability("claude-code", {
        exec,
        home,
        yes: true,
      });
      expect(second.capability).toBe("native");
      expect(calls).toEqual([["claude", "--version"]]);
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("invalidates the cache when the host version changes", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-invalidate-"));
    try {
      await writeDoctorCache(
        {
          hosts: {
            copilot: {
              capability: "explode",
              source: "probe",
              version: "1.0.0",
            },
          },
          schemaVersion: 1,
        },
        { home },
      );
      const result = await ensureHostCapability("copilot", {
        exec: async (_command, args) => {
          if (args[0] === "--version") {
            return { status: 0, stderr: "", stdout: "2.0.0\n" };
          }
          return { status: 0, stderr: "", stdout: "plugin\n" };
        },
        home,
        yes: true,
      });
      expect(result).toEqual({
        capability: "native",
        source: "probe",
        version: "2.0.0",
      });
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("persists one prompted answer for an ambiguous probe", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-prompt-"));
    try {
      const result = await ensureHostCapability("claude-code", {
        exec: async (_command, args) => {
          if (args[0] === "--version") {
            return { status: 0, stderr: "", stdout: "0.1\n" };
          }
          return { status: 1, stderr: "segfault", stdout: "" };
        },
        home,
        prompt: async () => "explode",
      });
      expect(result).toEqual({
        capability: "explode",
        source: "prompt",
        version: "0.1",
      });
      const cache = await readDoctorCache({ home });
      expect(cache.hosts["claude-code"].source).toBe("prompt");
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("hard-errors an ambiguous probe under -y", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-yes-"));
    try {
      await expect(
        ensureHostCapability("claude-code", {
          exec: async (_command, args) => {
            if (args[0] === "--version") {
              return { status: 0, stderr: "", stdout: "0.1\n" };
            }
            return { status: 1, stderr: "segfault", stdout: "" };
          },
          home,
          yes: true,
        }),
      ).rejects.toThrow("ambiguous");
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("does not reuse a Cursor cache entry from a different scope", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-scope-home-"));
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-scope-cwd-"));
    try {
      await writeDoctorCache(
        {
          hosts: {
            cursor: {
              capability: "native",
              source: "probe",
              version: "global:present:nocli",
            },
          },
          schemaVersion: 1,
        },
        { home },
      );
      const result = await ensureHostCapability("cursor", {
        cwd,
        exec: async () => {
          const error = new Error("not found");
          error.code = "ENOENT";
          throw error;
        },
        home,
        scope: "project",
        yes: true,
      });
      expect(result).toEqual({
        capability: "explode",
        source: "probe",
        version: "project:absent:nocli",
      });
    } finally {
      await rm(home, { force: true, recursive: true });
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("project Cursor probe ORs home and cwd plugins/local", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-or-home-"));
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-or-cwd-"));
    const exec = async () => {
      const error = new Error("not found");
      error.code = "ENOENT";
      throw error;
    };
    try {
      await mkdir(join(home, ".cursor/plugins/local"), { recursive: true });
      const fromHome = await ensureHostCapability("cursor", {
        cwd,
        exec,
        home,
        scope: "project",
        yes: true,
      });
      expect(fromHome).toEqual({
        capability: "native",
        source: "probe",
        version: "project:present:nocli",
      });
    } finally {
      await rm(home, { force: true, recursive: true });
      await rm(cwd, { force: true, recursive: true });
    }

    const homeAbsent = await mkdtemp(join(tmpdir(), "ai-skills-doctor-or-home2-"));
    const cwdPresent = await mkdtemp(join(tmpdir(), "ai-skills-doctor-or-cwd2-"));
    try {
      await mkdir(join(cwdPresent, ".cursor/plugins/local"), {
        recursive: true,
      });
      const fromCwd = await ensureHostCapability("cursor", {
        cwd: cwdPresent,
        exec,
        home: homeAbsent,
        scope: "project",
        yes: true,
      });
      expect(fromCwd).toEqual({
        capability: "native",
        source: "probe",
        version: "project:present:nocli",
      });
    } finally {
      await rm(homeAbsent, { force: true, recursive: true });
      await rm(cwdPresent, { force: true, recursive: true });
    }
  });

  test("warns when doctor cache cannot be written", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-cache-warn-"));
    const warnings = [];
    try {
      const result = await ensureHostCapability("codex", {
        home,
        warn: (message) => warnings.push(message),
        write: async () => {
          throw new Error("EACCES");
        },
        yes: true,
      });
      expect(result.capability).toBe("explode");
      expect(warnings.some((message) => message.includes("could not write doctor cache"))).toBe(
        true,
      );
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });
});

describe("runDoctor", () => {
  test("rejects --repair with --migrate", async () => {
    await expect(
      runDoctor({
        agents: [],
        global: true,
        migrate: "cursor",
        project: false,
        repair: true,
        yes: true,
      }),
    ).rejects.toThrow("Choose only one doctor action");
  });

  test("rejects migrate of an unknown host", async () => {
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-unknown-"));
    try {
      await expect(
        runDoctor(
          {
            agents: [],
            global: true,
            migrate: "notepad",
            project: false,
            repair: false,
            yes: true,
          },
          { home, lockEnvironment: { cwd: home, home } },
        ),
      ).rejects.toThrow("Unknown agent");
    } finally {
      await rm(home, { force: true, recursive: true });
    }
  });

  test("reports host capability and lock drift", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-report-"));
    const lines = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
      await mkdir(join(cwd, ".cursor/skills/orphan-skill"), {
        recursive: true,
      });
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
          access: async () => false,
          exec: async () => ({ status: 1, stderr: "", stdout: "" }),
          home: cwd,
          lockEnvironment: { cwd, exists: async () => false, home: cwd },
          log: (line) => lines.push(line),
        },
      );
      expect(lines.some((line) => line.startsWith("host\tcursor\texplode"))).toBe(true);
      expect(lines).toContain("plugin\treview\tcursor\texplode\tMISSING");
      expect(
        lines.some((line) => line.startsWith("orphan\tcursor\t") && line.endsWith("orphan-skill")),
      ).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repair re-materializes only missing plugins", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-repair-"));
    const sourceRoot = join(cwd, "catalog");
    const missingFile = join(cwd, ".cursor/skills/lint/SKILL.md");
    const healthyFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    try {
      await mkdir(join(sourceRoot, "skills/lint"), { recursive: true });
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/lint/SKILL.md"), "# lint\n");
      await writeFile(healthyFile, "# jira keep\n");
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
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
            lint: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: true,
          yes: true,
        },
        {
          exec: async () => ({ status: 1, stderr: "", stdout: "" }),
          home: cwd,
          installExtras: { sourceRoot },
          lockEnvironment: { cwd, hash: async () => "abc", home: cwd },
          log: () => {},
        },
      );
      expect(result.repaired).toEqual(["lint"]);
      expect(await readFile(missingFile, "utf8")).toBe("# lint\n");
      expect(await readFile(healthyFile, "utf8")).toBe("# jira keep\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repair failures reject after warning", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-repair-fail-"));
    const warnings = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
        runDoctor(
          {
            agents: ["cursor"],
            global: false,
            migrate: null,
            project: true,
            repair: true,
            yes: true,
          },
          {
            access: async () => false,
            exec: async () => ({ status: 1, stderr: "", stdout: "" }),
            home: cwd,
            installExtras: {
              explode: async () => {
                throw new Error("catalog boom");
              },
              sourceRoot: cwd,
            },
            lockEnvironment: {
              cwd,
              exists: async () => false,
              hash: async () => "abc",
              home: cwd,
            },
            log: () => {},
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow("Repair failed for review:cursor");
      expect(warnings.some((message) => message.includes("catalog boom"))).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("report without --repair or --migrate does not rematerialize", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-report-only-"));
    const installs = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: false,
          yes: true,
        },
        {
          exec: async () => ({ status: 1, stderr: "", stdout: "" }),
          home: cwd,
          installExtras: {
            explode: async () => {
              installs.push("explode");
              throw new Error("report-only must not rematerialize");
            },
            sourceRoot: cwd,
          },
          lockEnvironment: {
            cwd,
            exists: async () => false,
            hash: async () => "abc",
            home: cwd,
          },
          log: () => {},
        },
      );
      expect(result).toEqual({ migrated: [], repaired: [] });
      expect(installs).toEqual([]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrate requires confirmation unless -y", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-"));
    try {
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
        runDoctor(
          {
            agents: ["cursor"],
            global: false,
            migrate: "cursor",
            project: true,
            repair: false,
            yes: false,
          },
          {
            confirm: async () => false,
            exec: async () => ({ status: 1, stderr: "not found", stdout: "" }),
            home: cwd,
            lockEnvironment: {
              cwd,
              exists: async () => true,
              hash: async () => "abc",
              home: cwd,
            },
            log: () => {},
          },
        ),
      ).rejects.toThrow("Migrate cancelled");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("does not leak a sibling MISSING status onto a healthy agent", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-status-"));
    const lines = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                "claude-code": {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".claude/skills"),
                },
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "abc");
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
          access: async () => false,
          exec: async () => ({ status: 1, stderr: "not found", stdout: "" }),
          home: cwd,
          lockEnvironment: {
            cwd,
            exists: async (path) => path.includes(`${join(".cursor", "skills")}`),
            hash: async () => "abc",
            home: cwd,
          },
          log: (line) => lines.push(line),
        },
      );
      expect(lines).toContain("plugin\treview\tcursor\texplode\t");
      expect(lines).not.toContain("plugin\treview\tcursor\texplode\tMISSING");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repair skips a missing agent that also has modified files", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-mixed-repair-"));
    const warnings = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc", "test/SKILL.md": "def" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: true,
          yes: true,
        },
        {
          access: async () => false,
          exec: async () => ({ status: 1, stderr: "not found", stdout: "" }),
          home: cwd,
          lockEnvironment: {
            cwd,
            exists: async (path) => path.endsWith("lint/SKILL.md"),
            hash: async () => "zzz",
            home: cwd,
          },
          log: () => {},
          warn: (message) => warnings.push(message),
        },
      );
      expect(result.repaired).toEqual([]);
      expect(warnings.some((message) => message.includes("modified"))).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("reports symlink orphans and does not treat native Cursor dirs as explode orphans", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-orphans-"));
    const lines = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { ".claude-plugin/plugin.json": "abc" },
                  projector: "native",
                  root: join(cwd, ".cursor/plugins/local/review"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
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
        { cwd },
      );
      await mkdir(join(cwd, ".cursor/skills"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local/review"), {
        recursive: true,
      });
      await symlink("/tmp/untracked-skill", join(cwd, ".cursor/skills/orphan-link"));
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
          access: async () => true,
          exec: async () => {
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          home: cwd,
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: (line) => lines.push(line),
        },
      );
      expect(
        lines.some((line) => line.startsWith("orphan\tcursor\t") && line.endsWith("orphan-link")),
      ).toBe(true);
      expect(lines.some((line) => line.endsWith("plugins/local/review"))).toBe(false);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrates an adopted first-party skill without dropping the lock on failure", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-fail-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await writeFile(explodeFile, "# jira\n");
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
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const warnings = [];
      await expect(
        runDoctor(
          {
            agents: ["cursor"],
            global: false,
            migrate: "cursor",
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
            installExtras: { sourceRoot: null },
            lockEnvironment: {
              cwd,
              exists: async () => true,
              hash: async () => "abc",
              home: cwd,
            },
            log: () => {},
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow("Migrate failed for jira");
      expect(warnings.some((message) => message.includes("catalog checkout"))).toBe(true);
      expect(await readFile(explodeFile, "utf8")).toBe("# jira\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.jira.agents.cursor.projector).toBe("explode");
      expect(lock.plugins.jira.agents.cursor.root).toBe(join(cwd, ".cursor/skills"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrates explode Cursor dests to native and keeps adopted plugin ids", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-ok-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
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
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: "cursor",
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
          installExtras: { sourceRoot },
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: () => {},
        },
      );
      expect(result.migrated).toEqual(["jira"]);
      await expect(access(explodeFile)).rejects.toMatchObject({
        code: "ENOENT",
      });
      expect(
        await readFile(join(cwd, ".cursor/plugins/local/jira/skills/jira/SKILL.md"), "utf8"),
      ).toBe("# jira\n");
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.jira.agents.cursor.projector).toBe("native");
      expect(lock.plugins.jira.agents.cursor.root).toBe(join(cwd, ".cursor/plugins/local/jira"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrate without --agent still migrates when an unrelated host is ambiguous", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-unrelated-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    const lines = [];
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
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
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: [],
          global: false,
          migrate: "cursor",
          project: true,
          repair: false,
          yes: true,
        },
        {
          exec: async (command, args) => {
            if (command === "claude") {
              if (args[0] === "--version") {
                return { status: 0, stderr: "", stdout: "0.1\n" };
              }
              return { status: 1, stderr: "segfault", stdout: "" };
            }
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          home: cwd,
          installExtras: { sourceRoot },
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: (line) => lines.push(line),
        },
      );
      expect(result.migrated).toEqual(["jira"]);
      expect(lines.some((line) => line.startsWith("host\tclaude-code\tambiguous\terror"))).toBe(
        true,
      );
      await expect(access(explodeFile)).rejects.toMatchObject({
        code: "ENOENT",
      });
      expect(
        await readFile(join(cwd, ".cursor/plugins/local/jira/skills/jira/SKILL.md"), "utf8"),
      ).toBe("# jira\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrate of an ambiguous host still fail-closes", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-ambiguous-"));
    try {
      await expect(
        runDoctor(
          {
            agents: [],
            global: false,
            migrate: "claude-code",
            project: true,
            repair: false,
            yes: true,
          },
          {
            exec: async (command, args) => {
              if (command === "claude") {
                if (args[0] === "--version") {
                  return { status: 0, stderr: "", stdout: "0.1\n" };
                }
                return { status: 1, stderr: "segfault", stdout: "" };
              }
              const error = new Error("not found");
              error.code = "ENOENT";
              throw error;
            },
            home: cwd,
            lockEnvironment: { cwd, exists: async () => false, home: cwd },
            log: () => {},
          },
        ),
      ).rejects.toThrow("ambiguous");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrate force-removes modified explode dests", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-migrate-modified-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/jira"), { recursive: true });
      await writeFile(explodeFile, "# edited locally\n");
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
              installedAt: "2026-08-28T00:00:00.000Z",
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
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: "cursor",
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
          installExtras: { sourceRoot },
          lockEnvironment: { cwd, home: cwd },
          log: () => {},
        },
      );
      expect(result.migrated).toEqual(["jira"]);
      await expect(access(explodeFile)).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("reports explode orphans from per-agent files not plugin-wide membership", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-orphan-files-"));
    const lines = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            review: {
              agents: {
                cursor: {
                  files: { "lint/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              skills: ["lint", "test"],
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      await mkdir(join(cwd, ".cursor/skills/lint"), { recursive: true });
      await mkdir(join(cwd, ".cursor/skills/test"), { recursive: true });
      await writeFile(join(cwd, ".cursor/skills/lint/SKILL.md"), "abc");
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
          access: async () => false,
          exec: async () => ({ status: 1, stderr: "not found", stdout: "" }),
          home: cwd,
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: (line) => lines.push(line),
        },
      );
      expect(
        lines.some((line) => line.startsWith("orphan\tcursor\t") && line.endsWith("/test")),
      ).toBe(true);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrates an adopted raycast skill without expanding the raycast bundle", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-raycast-adopt-"));
    const explodeFile = join(cwd, ".cursor/skills/raycast/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(cwd, ".cursor/skills/raycast"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/raycast"), { recursive: true });
      await writeFile(explodeFile, "# raycast\n");
      await writeFile(join(sourceRoot, "skills/raycast/SKILL.md"), "# raycast\n");
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            raycast: {
              agents: {
                cursor: {
                  files: { "raycast/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              skills: ["raycast"],
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: "cursor",
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
          installExtras: { sourceRoot },
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: () => {},
        },
      );
      expect(result.migrated).toEqual(["raycast"]);
      expect(
        await readFile(join(cwd, ".cursor/plugins/local/raycast/skills/raycast/SKILL.md"), "utf8"),
      ).toBe("# raycast\n");
      await expect(
        access(join(cwd, ".cursor/plugins/local/raycast/skills/pr-raycast")),
      ).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repairs an adopted raycast skill without expanding the raycast bundle", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-raycast-repair-"));
    const sourceRoot = join(cwd, "catalog");
    try {
      await mkdir(join(sourceRoot, "skills/raycast"), { recursive: true });
      await mkdir(join(sourceRoot, "skills/pr-raycast"), { recursive: true });
      await writeFile(join(sourceRoot, "skills/raycast/SKILL.md"), "# raycast\n");
      await writeFile(join(sourceRoot, "skills/pr-raycast/SKILL.md"), "# pr-raycast\n");
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            raycast: {
              agents: {
                cursor: {
                  files: { "raycast/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "lgtm-hq/ai-skills",
              sha: "v0.0.0-dev",
              skills: ["raycast"],
              vendor: "lgtm-hq",
              version: "0.0.0-dev",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: true,
          yes: true,
        },
        {
          exec: async () => {
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          home: cwd,
          installExtras: { sourceRoot },
          lockEnvironment: { cwd, hash: async () => "abc", home: cwd },
          log: () => {},
        },
      );
      expect(result.repaired).toEqual(["raycast"]);
      expect(await readFile(join(cwd, ".cursor/skills/raycast/SKILL.md"), "utf8")).toBe(
        "# raycast\n",
      );
      await expect(access(join(cwd, ".cursor/skills/pr-raycast"))).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("commits native lock when migrate dest cleanup fails", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-uninstall-fail-"));
    const explodeFile = join(cwd, ".cursor/skills/jira/SKILL.md");
    const sourceRoot = join(cwd, "catalog");
    const warnings = [];
    try {
      await mkdir(join(cwd, ".cursor/skills/jira"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
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
              installedAt: "2026-08-28T00:00:00.000Z",
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
        runDoctor(
          {
            agents: ["cursor"],
            global: false,
            migrate: "cursor",
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
            installExtras: {
              remove: async () => {
                throw new Error("rm boom");
              },
              sourceRoot,
            },
            lockEnvironment: {
              cwd,
              exists: async () => true,
              hash: async () => "abc",
              home: cwd,
            },
            log: () => {},
            remove: async () => {
              throw new Error("rm boom");
            },
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow("Migrate failed for jira");
      expect(warnings.some((message) => message.includes("rm boom"))).toBe(true);
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

  test("repair rematerializes a baked vendor plugin by slice id", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-vendor-repair-"));
    /** @type {Array<{bundle: string | null, vendor: string | null, skills: string[]}>} */
    const installCalls = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            "document-skills": {
              agents: {
                cursor: {
                  files: { "pdf/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "anthropics/skills",
              sha: "abc123",
              vendor: "anthropics",
              version: "abc1234",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: null,
          project: true,
          repair: true,
          yes: true,
        },
        {
          exec: async () => ({ status: 1, stderr: "", stdout: "" }),
          home: cwd,
          install: async (options) => {
            installCalls.push({
              bundle: options.bundle,
              vendor: options.vendor,
              skills: options.skills,
            });
            return { alreadyPresent: 0, installed: 0, repaired: 1 };
          },
          lockEnvironment: { cwd, hash: async () => "abc", home: cwd },
          log: () => {},
        },
      );
      expect(result.repaired).toEqual(["document-skills"]);
      expect(installCalls).toEqual([
        {
          bundle: "document-skills",
          vendor: "anthropics",
          skills: [],
        },
      ]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("repair of a legacy vendor-id lock cannot rematerialize", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-legacy-vendor-"));
    const warnings = [];
    try {
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            anthropics: {
              agents: {
                cursor: {
                  files: { "pdf/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "anthropics/skills",
              sha: "abc123",
              vendor: "anthropics",
              version: "abc1234",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      await expect(
        runDoctor(
          {
            agents: ["cursor"],
            global: false,
            migrate: null,
            project: true,
            repair: true,
            yes: true,
          },
          {
            exec: async () => ({ status: 1, stderr: "", stdout: "" }),
            home: cwd,
            lockEnvironment: { cwd, hash: async () => "abc", home: cwd },
            log: () => {},
            warn: (message) => warnings.push(message),
          },
        ),
      ).rejects.toThrow(/Repair failed for anthropics:cursor/);
      expect(warnings.join("\n")).toMatch(/Unknown plugin for vendor anthropics: anthropics/);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("skips vendor plugins when migrating to native", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-vendor-skip-"));
    const explodeFile = join(cwd, ".cursor/skills/foo/SKILL.md");
    const warnings = [];
    try {
      await mkdir(join(cwd, ".cursor/skills/foo"), { recursive: true });
      await mkdir(join(cwd, ".cursor/plugins/local"), { recursive: true });
      await writeFile(explodeFile, "# foo\n");
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: {
            "acme-tools": {
              agents: {
                cursor: {
                  files: { "foo/SKILL.md": "abc" },
                  projector: "explode",
                  root: join(cwd, ".cursor/skills"),
                },
              },
              installedAt: "2026-08-28T00:00:00.000Z",
              projector: "explode",
              repo: "acme/tools",
              sha: "abc123",
              vendor: "acme",
              version: "1.0.0",
            },
          },
          scope: "project",
          version: 2,
        },
        { cwd },
      );
      const result = await runDoctor(
        {
          agents: ["cursor"],
          global: false,
          migrate: "cursor",
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
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home: cwd,
          },
          log: () => {},
          warn: (message) => warnings.push(message),
        },
      );
      expect(result.migrated).toEqual([]);
      expect(warnings.some((message) => message.includes("acme-tools"))).toBe(true);
      expect(await readFile(explodeFile, "utf8")).toBe("# foo\n");
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("migrate skips CLI uninstall when the sibling lock still owns the plugin", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-doctor-sibling-"));
    const home = await mkdtemp(join(tmpdir(), "ai-skills-doctor-sibling-home-"));
    const execCalls = [];
    const warnings = [];
    try {
      const entry = {
        agents: {
          "claude-code": {
            files: { "lint/SKILL.md": "abc" },
            projector: "native",
            root: "cli:claude-code",
          },
        },
        installedAt: "2026-08-28T00:00:00.000Z",
        projector: "native",
        repo: "lgtm-hq/ai-skills",
        sha: "v0.0.0-dev",
        vendor: "lgtm-hq",
        version: "0.0.0-dev",
      };
      await writeLockfile(
        {
          gatewayVersion: "0.0.0-dev",
          plugins: { review: entry },
          scope: "project",
          version: 2,
        },
        { cwd, home },
      );
      await mkdir(join(home, ".ai-skills"), { recursive: true });
      await writeFile(
        join(home, ".ai-skills/lock.json"),
        `${JSON.stringify(
          {
            gatewayVersion: "0.0.0-dev",
            plugins: { review: entry },
            scope: "global",
            version: 2,
          },
          null,
          2,
        )}\n`,
      );
      const result = await runDoctor(
        {
          agents: ["claude-code"],
          global: false,
          migrate: "claude-code",
          project: true,
          repair: false,
          yes: true,
        },
        {
          exec: async (command, args) => {
            execCalls.push([command, ...args]);
            const error = new Error("not found");
            error.code = "ENOENT";
            throw error;
          },
          home,
          installExtras: {
            explode: async () => ({
              claimed: { "claude-code": { "lint/SKILL.md": "abc" } },
              skipped: [],
              swappedDests: [],
            }),
            exec: async (command, args) => {
              execCalls.push([command, ...args]);
              const error = new Error("not found");
              error.code = "ENOENT";
              throw error;
            },
            sourceRoot: cwd,
          },
          lockEnvironment: {
            cwd,
            exists: async () => true,
            hash: async () => "abc",
            home,
          },
          log: () => {},
          warn: (message) => warnings.push(message),
        },
      );
      expect(result.migrated).toEqual(["review"]);
      expect(execCalls.some((call) => call.includes("uninstall"))).toBe(false);
      expect(warnings.some((message) => message.includes("sibling"))).toBe(true);
      const lock = JSON.parse(await readFile(join(cwd, "ai-skills-lock.json"), "utf8"));
      expect(lock.plugins.review.agents["claude-code"].projector).toBe("explode");
      expect(lock.plugins.review.agents["claude-code"].root).toBe(join(cwd, ".claude/skills"));
    } finally {
      await rm(cwd, { force: true, recursive: true });
      await rm(home, { force: true, recursive: true });
    }
  });
});
