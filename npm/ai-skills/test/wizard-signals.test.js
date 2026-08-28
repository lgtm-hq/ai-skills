import { describe, expect, test } from "bun:test";

import { completeInteractively } from "../lib/install.js";
import { getPackageVersion } from "../lib/package-version.js";
import {
  formatGatewayUpdateNotice,
  formatInstallCounts,
  formatInstalledSummary,
  formatSkillStatusSuffix,
  VENDOR_DRIFT_SUFFIX,
} from "../lib/ui.js";

const REGISTRY_URL = "https://registry.npmjs.org/@lgtm-hq/ai-skills/latest";
/** Baked anthropics pin from data/vendors.json (matching entries show as fresh). */
const ANTHROPICS_PIN = "9d2f1ae187231d8199c64b5b762e1bdf2244733d";

const blankOptions = {
  agents: [],
  bundle: null,
  copy: false,
  global: false,
  onConflict: null,
  project: false,
  skills: [],
  vendor: null,
  yes: false,
};

/**
 * Fixture lockfile: one fresh and one drifted first-party plugin plus one fresh
 * vendor plugin, spread over two agents.
 *
 * @returns {object} Parsed global-scope lockfile.
 */
function lockFixture() {
  const entry = (name, vendor, sha, agents) => ({
    agents: Object.fromEntries(
      agents.map((agent) => [
        agent,
        {
          files: { [`${name}/SKILL.md`]: "hash" },
          root: `/tmp/${agent}/skills`,
        },
      ]),
    ),
    installedAt: "2026-01-01T00:00:00.000Z",
    projector: "explode",
    repo: vendor === "lgtm-hq" ? "lgtm-hq/ai-skills" : "anthropics/skills",
    sha,
    vendor,
    version: sha.replace(/^v/, ""),
  });
  return {
    gatewayVersion: getPackageVersion(),
    plugins: {
      review: entry("review", "lgtm-hq", `v${getPackageVersion()}`, ["claude-code"]),
      "git-pr": entry("git-pr", "lgtm-hq", "v0.1.0", ["claude-code", "cursor"]),
      anthropics: entry("anthropics", "anthropics", ANTHROPICS_PIN, ["claude-code"]),
    },
    scope: "global",
    version: 2,
  };
}

/**
 * Minimal plugin entry for status-suffix tests.
 *
 * @param {string[]} agents - Agent ids.
 * @returns {import("../lib/lockfile.js").PluginLockEntry} Plugin lock entry.
 */
function suffixEntry(agents) {
  return {
    agents: Object.fromEntries(agents.map((agent) => [agent, { files: {}, root: "" }])),
    installedAt: "2026-01-01T00:00:00.000Z",
    projector: "explode",
    repo: "lgtm-hq/ai-skills",
    sha: "v0.0.0-dev",
    vendor: "lgtm-hq",
    version: "0.0.0-dev",
  };
}

/**
 * Scripted UI that records notes and prompt options for assertions.
 *
 * @param {Array<string | string[] | boolean>} answers - Prompt results.
 * @returns {{ui: object, notes: Array<{message: string, title?: string}>, selects: Array<{value: string, label: string}[]>, groupSelects: Array<Record<string, {value: string, label: string}[]>>, multiSelects: Array<{value: string, label: string}[]>}} UI and captures.
 */
function recordingUi(answers) {
  const queue = [...answers];
  const next = () => {
    if (queue.length === 0) {
      throw new Error("Unexpected prompt");
    }
    return queue.shift();
  };
  /** @type {Array<{message: string, title?: string}>} */
  const notes = [];
  /** @type {Array<{value: string, label: string}[]>} */
  const selects = [];
  /** @type {Array<Record<string, {value: string, label: string}[]>>} */
  const groupSelects = [];
  /** @type {Array<{value: string, label: string}[]>} */
  const multiSelects = [];
  const ui = {
    intro() {},
    outro() {},
    note(message, title) {
      notes.push({ message, title });
    },
    isCancel: (value) => value === Symbol.for("clack:cancel"),
    async select(options) {
      selects.push(options.options);
      return next();
    },
    async multiselect(options) {
      multiSelects.push(options.options);
      return next();
    },
    async groupMultiselect(options) {
      groupSelects.push(options.options);
      return next();
    },
    async confirm() {
      return next();
    },
  };
  return { ui, notes, selects, groupSelects, multiSelects };
}

/**
 * Fake fetch resolving each URL to a canned JSON body (unrouted URLs 404).
 *
 * @param {Record<string, unknown>} routes - JSON body per URL.
 * @param {string[]} [calls] - Collector for requested URLs.
 * @returns {typeof fetch} Injectable fetch fake.
 */
function fakeFetch(routes, calls = []) {
  return async (url) => {
    calls.push(String(url));
    const body = routes[String(url)];
    if (body === undefined) {
      return { ok: false, json: async () => ({}) };
    }
    return { ok: true, json: async () => body };
  };
}

describe("ui signal formatting", () => {
  test("summarizes installed plugins and agents, omitting when empty", () => {
    expect(formatInstalledSummary(lockFixture())).toBe("3 plugins installed · 2 agents");
    expect(
      formatInstalledSummary({
        plugins: {
          solo: {
            ...suffixEntry(["cursor"]),
            agents: {
              cursor: {
                files: { "solo/SKILL.md": "hash" },
                root: "/tmp/cursor/skills",
              },
            },
          },
        },
      }),
    ).toBe("1 plugin installed · 1 agent");
    expect(
      formatInstalledSummary({
        plugins: {
          review: {
            ...suffixEntry(["cursor"]),
            agents: {
              cursor: {
                files: { "lint/SKILL.md": "hash", "test/SKILL.md": "hash" },
                root: "/tmp/cursor/skills",
              },
            },
          },
        },
      }),
    ).toBe("1 plugin installed · 1 agent");
    expect(formatInstalledSummary({ plugins: {} })).toBeNull();
  });

  test("formats install counts for new, present, and repaired agents", () => {
    expect(formatInstallCounts({ alreadyPresent: 0, installed: 1, repaired: 1 })).toBe(
      "1 installed · 0 already present · 1 repaired",
    );
  });

  test("renders the gateway notice with both remedies", () => {
    const notice = formatGatewayUpdateNotice({ current: "0.13.0", latest: "0.17.0" });
    expect(notice).toContain("Update available: v0.13.0 → v0.17.0");
    expect(notice).toContain("bun update -g @lgtm-hq/ai-skills");
    expect(notice).toContain("bunx --package=@lgtm-hq/ai-skills@0.17.0 skill");
  });

  test("formats installed and drifted skill suffixes", () => {
    expect(formatSkillStatusSuffix({ entry: undefined, drifted: false })).toBe("");
    expect(formatSkillStatusSuffix({ entry: suffixEntry(["claude-code"]), drifted: false })).toBe(
      " ✔ installed (claude-code)",
    );
    expect(
      formatSkillStatusSuffix({
        entry: suffixEntry(["claude-code", "cursor"]),
        drifted: true,
      }),
    ).toBe(" ✔ installed (claude-code, cursor) · update available (run skill update)");
  });

  test("strips terminal control sequences from lockfile agent names", () => {
    expect(
      formatSkillStatusSuffix({
        entry: suffixEntry(["safe", "\u001b]0;attacker\u0007", "\u001b[31mred"]),
        drifted: false,
      }),
    ).toBe(" ✔ installed ([31mred, ]0;attacker, safe)");
  });
});

describe("completeInteractively signals", () => {
  test("surfaces installed markers, drift, summary and update notices", async () => {
    const captured = recordingUi([[]]);
    const dependencies = {
      env: {},
      fetchImplementation: fakeFetch({
        [REGISTRY_URL]: { version: "9999.0.0" },
        "https://api.github.com/repos/davidondrej/skills/commits/HEAD": {
          sha: "f".repeat(40),
        },
      }),
      lockEnvironment: {
        home: "/nonexistent",
        read: async () => `${JSON.stringify(lockFixture())}\n`,
      },
    };

    await expect(
      completeInteractively({ ...blankOptions }, captured.ui, dependencies),
    ).rejects.toThrow("Install cancelled");

    const noteTitles = captured.notes.map((note) => note.title);
    expect(noteTitles).toContain("Update available");
    expect(noteTitles).toContain("Installed");
    const updateNote = captured.notes.find((note) => note.title === "Update available");
    expect(updateNote?.message).toContain("→ v9999.0.0");
    expect(updateNote?.message).toContain("bun update -g @lgtm-hq/ai-skills");
    const installedNote = captured.notes.find((note) => note.title === "Installed");
    expect(installedNote?.message).toBe("3 plugins installed · 2 agents");

    const pluginLabels = captured.multiSelects[0].map((option) => option.label);
    expect(
      pluginLabels.some(
        (label) => label.includes("davidondrej/skills") && label.endsWith(VENDOR_DRIFT_SUFFIX),
      ),
    ).toBe(true);
    expect(
      pluginLabels.some(
        (label) => label.includes("anthropics/skills") && label.includes("newer commits"),
      ),
    ).toBe(false);
    expect(
      pluginLabels.some((label) => label.includes("Review") && label.includes("installed")),
    ).toBe(true);
    expect(
      pluginLabels.some(
        (label) => label.includes("Git & PR") && label.includes("update available"),
      ),
    ).toBe(true);
    expect(
      pluginLabels.some(
        (label) => label.includes("anthropics/skills") && label.includes("installed"),
      ),
    ).toBe(true);
  });

  test("merges global and project lockfiles while scope is undetermined", async () => {
    const captured = recordingUi([[]]);
    const projectLock = {
      gatewayVersion: getPackageVersion(),
      plugins: {
        raycast: {
          agents: {
            cursor: {
              files: { "raycast/SKILL.md": "hash" },
              root: "/project/.cursor/skills",
            },
          },
          installedAt: "2026-01-01T00:00:00.000Z",
          projector: "explode",
          repo: "lgtm-hq/ai-skills",
          sha: `v${getPackageVersion()}`,
          vendor: "lgtm-hq",
          version: getPackageVersion(),
        },
        "git-pr": {
          agents: {
            codex: {
              files: { "git-pr/SKILL.md": "hash" },
              root: "/project/.codex/skills",
            },
          },
          installedAt: "2026-01-01T00:00:00.000Z",
          projector: "explode",
          repo: "lgtm-hq/ai-skills",
          sha: `v${getPackageVersion()}`,
          vendor: "lgtm-hq",
          version: getPackageVersion(),
        },
      },
      scope: "project",
      version: 2,
    };
    const dependencies = {
      env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
      lockEnvironment: {
        home: "/nonexistent",
        cwd: "/project",
        read: async (path) =>
          String(path).startsWith("/project")
            ? `${JSON.stringify(projectLock)}\n`
            : `${JSON.stringify(lockFixture())}\n`,
      },
    };

    await expect(
      completeInteractively({ ...blankOptions }, captured.ui, dependencies),
    ).rejects.toThrow("Install cancelled");

    // Union of both scopes: 3 global plugins + 1 project-only plugin.
    const installedNote = captured.notes.find((note) => note.title === "Installed");
    expect(installedNote?.message).toBe("4 plugins installed · 3 agents");

    const pluginLabels = captured.multiSelects[0].map((option) => option.label);
    expect(
      pluginLabels.some((label) => label.includes("Raycast") && label.includes("cursor")),
    ).toBe(true);
    expect(
      pluginLabels.some(
        (label) =>
          label.includes("Git & PR") && label.includes("claude-code") && label.includes("codex"),
      ),
    ).toBe(true);
  });

  test("explicit scope flags read only that scope's lockfile", async () => {
    const captured = recordingUi([[]]);
    /** @type {string[]} */
    const readPaths = [];
    const dependencies = {
      env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
      lockEnvironment: {
        home: "/nonexistent",
        cwd: "/project",
        read: async (path) => {
          readPaths.push(String(path));
          return `${JSON.stringify(lockFixture())}\n`;
        },
      },
    };

    await expect(
      completeInteractively({ ...blankOptions, global: true }, captured.ui, dependencies),
    ).rejects.toThrow("Install cancelled");

    expect(readPaths).toEqual(["/nonexistent/.ai-skills/lock.json"]);
  });

  test("env opt-out skips every network fetch and shows no notices", async () => {
    const captured = recordingUi([[]]);
    /** @type {string[]} */
    const calls = [];
    const dependencies = {
      env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
      fetchImplementation: fakeFetch({ [REGISTRY_URL]: { version: "9999.0.0" } }, calls),
      lockEnvironment: {
        home: "/nonexistent",
        read: async () => {
          throw Object.assign(new Error("no lockfile"), { code: "ENOENT" });
        },
      },
    };

    await expect(
      completeInteractively({ ...blankOptions }, captured.ui, dependencies),
    ).rejects.toThrow("Install cancelled");

    expect(calls).toEqual([]);
    expect(captured.notes).toEqual([]);
    expect(
      captured.multiSelects[0].every((option) => !option.label.includes("newer commits")),
    ).toBe(true);
  });

  test("network errors, timeouts and a malformed lockfile stay silent", async () => {
    const captured = recordingUi([[]]);
    const dependencies = {
      env: {},
      fetchImplementation: async (url) => {
        if (String(url) === REGISTRY_URL) {
          throw new Error("offline");
        }
        return new Promise(() => {});
      },
      timeoutMs: 10,
      lockEnvironment: {
        home: "/nonexistent",
        read: async () => "not json at all",
      },
    };

    await expect(
      completeInteractively({ ...blankOptions }, captured.ui, dependencies),
    ).rejects.toThrow("Install cancelled");

    expect(captured.notes).toEqual([]);
    const pluginLabels = captured.multiSelects[0].map((option) => option.label);
    expect(pluginLabels.every((label) => !label.includes("newer commits"))).toBe(true);
    expect(pluginLabels.every((label) => !label.includes("installed"))).toBe(true);
  });
});
