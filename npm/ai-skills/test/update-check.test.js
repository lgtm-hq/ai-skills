import { describe, expect, test } from "bun:test";

import {
  checkGatewayUpdate,
  checkSkillDrift,
  checkVendorDrift,
  isNewerVersion,
  isUpdateCheckDisabled,
} from "../lib/update-check.js";

const PIN_A = "a".repeat(40);
const PIN_B = "b".repeat(40);

/**
 * Build a fake fetch resolving each URL to a canned JSON body.
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

/**
 * Fetch fake that never settles, to exercise the timeout race.
 *
 * @returns {Promise<never>} A promise that never resolves.
 */
function hangingFetch() {
  return new Promise(() => {});
}

describe("isNewerVersion", () => {
  test("compares numeric semver parts", () => {
    expect(isNewerVersion("0.17.0", "0.13.0")).toBe(true);
    expect(isNewerVersion("0.13.0", "0.17.0")).toBe(false);
    expect(isNewerVersion("1.0.0", "0.99.99")).toBe(true);
    expect(isNewerVersion("0.13.0", "0.13.0")).toBe(false);
  });

  test("accepts v prefixes and ranks releases above prereleases", () => {
    expect(isNewerVersion("v0.17.0", "0.16.2")).toBe(true);
    expect(isNewerVersion("0.17.0", "0.17.0-dev")).toBe(true);
    expect(isNewerVersion("0.17.0-dev", "0.17.0")).toBe(false);
  });

  test("orders prereleases by SemVer identifier precedence", () => {
    expect(isNewerVersion("1.0.0-beta.2", "1.0.0-beta.1")).toBe(true);
    expect(isNewerVersion("1.0.0-beta.1", "1.0.0-beta.2")).toBe(false);
    expect(isNewerVersion("1.0.0-beta", "1.0.0-alpha")).toBe(true);
    expect(isNewerVersion("1.0.0-beta.1", "1.0.0-beta")).toBe(true);
    expect(isNewerVersion("1.0.0-beta", "1.0.0-beta.1")).toBe(false);
    expect(isNewerVersion("1.0.0-alpha.beta", "1.0.0-alpha.1")).toBe(true);
    expect(isNewerVersion("1.0.0-beta.2", "1.0.0-beta.2")).toBe(false);
    expect(isNewerVersion("1.0.0-beta.11", "1.0.0-beta.9")).toBe(true);
  });

  test("treats unparsable versions as not newer", () => {
    expect(isNewerVersion("not-a-version", "0.1.0")).toBe(false);
    expect(isNewerVersion("0.2.0", "garbage")).toBe(false);
  });
});

describe("isUpdateCheckDisabled", () => {
  test("only the exact opt-out value disables checks", () => {
    expect(isUpdateCheckDisabled({ AI_SKILLS_NO_UPDATE_CHECK: "1" })).toBe(true);
    expect(isUpdateCheckDisabled({ AI_SKILLS_NO_UPDATE_CHECK: "0" })).toBe(false);
    expect(isUpdateCheckDisabled({})).toBe(false);
  });
});

describe("checkGatewayUpdate", () => {
  const registryUrl = "https://registry.npmjs.org/@lgtm-hq/ai-skills/latest";

  test("reports a newer published version", async () => {
    const update = await checkGatewayUpdate({
      currentVersion: "0.13.0",
      env: {},
      fetchImplementation: fakeFetch({ [registryUrl]: { version: "0.17.0" } }),
    });
    expect(update).toEqual({ current: "0.13.0", latest: "0.17.0" });
  });

  test("stays silent when already current or ahead", async () => {
    const fetchImplementation = fakeFetch({ [registryUrl]: { version: "0.17.0" } });
    expect(
      await checkGatewayUpdate({ currentVersion: "0.17.0", env: {}, fetchImplementation }),
    ).toBeNull();
    expect(
      await checkGatewayUpdate({ currentVersion: "0.18.0", env: {}, fetchImplementation }),
    ).toBeNull();
  });

  test("soft-fails to null on fetch errors and bad responses", async () => {
    expect(
      await checkGatewayUpdate({
        currentVersion: "0.13.0",
        env: {},
        fetchImplementation: async () => {
          throw new Error("offline");
        },
      }),
    ).toBeNull();
    expect(
      await checkGatewayUpdate({
        currentVersion: "0.13.0",
        env: {},
        fetchImplementation: fakeFetch({}),
      }),
    ).toBeNull();
    expect(
      await checkGatewayUpdate({
        currentVersion: "0.13.0",
        env: {},
        fetchImplementation: fakeFetch({ [registryUrl]: { version: 7 } }),
      }),
    ).toBeNull();
  });

  test("soft-fails to null when the registry never answers within the timeout", async () => {
    const update = await checkGatewayUpdate({
      currentVersion: "0.13.0",
      env: {},
      fetchImplementation: hangingFetch,
      timeoutMs: 10,
    });
    expect(update).toBeNull();
  });

  test("skips the fetch entirely under the env opt-out", async () => {
    /** @type {string[]} */
    const calls = [];
    const update = await checkGatewayUpdate({
      currentVersion: "0.13.0",
      env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
      fetchImplementation: fakeFetch({ [registryUrl]: { version: "0.17.0" } }, calls),
    });
    expect(update).toBeNull();
    expect(calls).toEqual([]);
  });
});

describe("checkVendorDrift", () => {
  const vendors = [
    { id: "drifter", repo: "owner/drifter", sha: PIN_A },
    { id: "steady", repo: "owner/steady", sha: PIN_B },
    { id: "tagged", repo: "owner/tagged", sha: "v1.2.3" },
  ];

  test("flags vendors whose upstream head moved past the pin", async () => {
    /** @type {string[]} */
    const calls = [];
    const drifted = await checkVendorDrift(vendors, {
      env: {},
      fetchImplementation: fakeFetch(
        {
          "https://api.github.com/repos/owner/drifter/commits/HEAD": { sha: PIN_B },
          "https://api.github.com/repos/owner/steady/commits/HEAD": { sha: PIN_B },
        },
        calls,
      ),
    });
    expect(drifted).toEqual(new Set(["drifter"]));
    // Non-SHA pins are not queried at all.
    expect(calls.sort()).toEqual([
      "https://api.github.com/repos/owner/drifter/commits/HEAD",
      "https://api.github.com/repos/owner/steady/commits/HEAD",
    ]);
  });

  test("drops erroring and timing-out vendors silently", async () => {
    const drifted = await checkVendorDrift(vendors, {
      env: {},
      fetchImplementation: async (url) => {
        if (String(url).includes("drifter")) {
          throw new Error("rate limited");
        }
        return hangingFetch();
      },
      timeoutMs: 10,
    });
    expect(drifted).toEqual(new Set());
  });

  test("skips all fetches under the env opt-out", async () => {
    /** @type {string[]} */
    const calls = [];
    const drifted = await checkVendorDrift(vendors, {
      env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
      fetchImplementation: fakeFetch({}, calls),
    });
    expect(drifted).toEqual(new Set());
    expect(calls).toEqual([]);
  });
});

describe("checkSkillDrift", () => {
  const catalog = {
    packageVersion: "0.17.0",
    vendors: [{ id: "acme", sha: PIN_B }],
  };

  /**
   * Build a minimal lock entry.
   *
   * @param {string} vendor - Vendor id.
   * @param {string} sha - Recorded pin.
   * @returns {import("../lib/lockfile.js").LockEntry} Lock entry.
   */
  const entry = (vendor, sha) => ({
    agents: ["claude-code"],
    installedAt: "2026-01-01T00:00:00.000Z",
    repo: "owner/repo",
    sha,
    skillPath: "skills/x/SKILL.md",
    vendor,
  });

  test("flags first-party entries recorded against an older gateway tag", () => {
    const lock = {
      skills: {
        stale: entry("lgtm-hq", "v0.13.0"),
        fresh: entry("lgtm-hq", "v0.17.0"),
      },
    };
    expect(checkSkillDrift(lock, catalog)).toEqual(new Set(["stale"]));
  });

  test("flags vendor entries whose pin no longer matches the baked registry", () => {
    const lock = {
      skills: {
        moved: entry("acme", PIN_A),
        pinned: entry("acme", PIN_B),
        orphan: entry("unknown-vendor", PIN_A),
      },
    };
    expect(checkSkillDrift(lock, catalog)).toEqual(new Set(["moved"]));
  });

  test("returns an empty set for an empty lockfile", () => {
    expect(checkSkillDrift({ skills: {} }, catalog)).toEqual(new Set());
  });
});
