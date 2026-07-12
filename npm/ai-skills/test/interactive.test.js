import { describe, expect, test } from "bun:test";

import {
  batchesFromCart,
  batchesFromCliOptions,
  buildHomeOptions,
  cartSkillCount,
  completeInteractively,
  vendorDisplayLabel,
} from "../lib/install.js";
import { KNOWN_AGENTS } from "../lib/ui.js";

/**
 * Build a scripted UI that returns canned answers in order.
 *
 * @param {Array<string | string[] | boolean>} answers - Prompt results.
 * @returns {ReturnType<typeof import("../lib/ui.js").createClackUi>} Mock UI.
 */
function scriptedUi(answers) {
  const queue = [...answers];
  const next = () => {
    if (queue.length === 0) {
      throw new Error("Unexpected prompt");
    }
    return queue.shift();
  };
  return {
    intro() {},
    outro() {},
    note() {},
    isCancel: (value) => value === Symbol.for("clack:cancel"),
    async select() {
      return next();
    },
    async multiselect() {
      return next();
    },
    async groupMultiselect() {
      return next();
    },
    async confirm() {
      return next();
    },
  };
}

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

describe("vendorDisplayLabel", () => {
  test("uses displayRef when present and defaults to latest", () => {
    expect(vendorDisplayLabel({ repo: "mattpocock/skills", displayRef: "latest" })).toBe(
      "mattpocock/skills @ latest",
    );
    expect(vendorDisplayLabel({ repo: "owner/repo", displayRef: "v1.1.0" })).toBe(
      "owner/repo @ v1.1.0",
    );
    expect(vendorDisplayLabel({ repo: "owner/repo" })).toBe("owner/repo @ latest");
  });

  test("ignores non-string displayRef values", () => {
    expect(vendorDisplayLabel({ repo: "owner/repo", displayRef: true })).toBe(
      "owner/repo @ latest",
    );
  });

  test("treats whitespace-only displayRef as absent", () => {
    expect(vendorDisplayLabel({ repo: "owner/repo", displayRef: "   " })).toBe(
      "owner/repo @ latest",
    );
  });
});

describe("cart helpers", () => {
  test("counts skills and builds install batches", () => {
    const cart = {
      firstParty: ["branch", "lint"],
      vendors: { anthropics: ["pdf"], mattpocock: [] },
    };
    expect(cartSkillCount(cart)).toBe(3);
    expect(batchesFromCart(cart)).toEqual([
      { vendor: null, skills: ["branch", "lint"] },
      { vendor: "anthropics", skills: ["pdf"] },
    ]);
  });

  test("builds a vendor batch from CLI options", async () => {
    await expect(
      batchesFromCliOptions({ vendor: "anthropics", skills: [], bundle: null }),
    ).rejects.toThrow(/requires --skill/);
    expect(
      await batchesFromCliOptions({
        vendor: "anthropics",
        skills: ["pdf"],
        bundle: null,
      }),
    ).toEqual([{ vendor: "anthropics", skills: ["pdf"] }]);
  });

  test("omits Proceed until the cart has skills", () => {
    const vendors = {
      vendors: [{ id: "anthropics", repo: "anthropics/skills", displayRef: "latest" }],
    };
    const empty = buildHomeOptions({ firstParty: [], vendors: {} }, vendors);
    expect(empty.map((option) => option.value)).toEqual([
      "browse:first-party",
      "browse:vendor:anthropics",
      "cancel",
    ]);
    const filled = buildHomeOptions({ firstParty: ["branch"], vendors: {} }, vendors);
    expect(filled.some((option) => option.value === "proceed")).toBe(true);
    expect(filled.find((option) => option.value === "proceed")?.label).toBe(
      "Proceed with install (1 skill)",
    );
  });
});

describe("completeInteractively", () => {
  test("honors CLI vendor/skills without opening the home wizard", async () => {
    const options = await completeInteractively(
      { ...blankOptions, vendor: "anthropics", skills: ["pdf"] },
      scriptedUi([["cursor"], "global", false]),
    );

    expect(options.installBatches).toEqual([{ vendor: "anthropics", skills: ["pdf"] }]);
    expect(options.vendor).toBeNull();
    expect(options.skills).toEqual([]);
    expect(options.agents).toEqual(["cursor"]);
  });

  test("browse first-party then proceed with defaults", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi([
        "browse:first-party",
        ["lint", "test", "greptile", "coderabbit"],
        "proceed",
        KNOWN_AGENTS.map((agent) => agent.value),
        "global",
        false,
      ]),
    );

    expect(options.bundle).toBeNull();
    expect(options.vendor).toBeNull();
    expect(options.installBatches).toEqual([
      { vendor: null, skills: ["lint", "test", "greptile", "coderabbit"] },
    ]);
    expect(options.agents).toEqual(["claude-code", "cursor", "codex"]);
    expect(options.global).toBe(true);
    expect(options.copy).toBe(false);
    expect(options.onConflict).toBe("overwrite");
  });

  test("accumulates first-party and vendor catalogs before proceed", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi([
        "browse:first-party",
        ["branch"],
        "browse:vendor:anthropics",
        ["pdf"],
        "proceed",
        KNOWN_AGENTS.map((agent) => agent.value),
        "global",
        false,
      ]),
    );

    expect(options.installBatches).toEqual([
      { vendor: null, skills: ["branch"] },
      { vendor: "anthropics", skills: ["pdf"] },
    ]);
  });

  test("empty catalog selection returns home without installing", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi([
        "browse:vendor:anthropics",
        [],
        "browse:first-party",
        ["commit"],
        "proceed",
        ["cursor"],
        "project",
        false,
      ]),
    );

    expect(options.installBatches).toEqual([{ vendor: null, skills: ["commit"] }]);
    expect(options.agents).toEqual(["cursor"]);
    expect(options.project).toBe(true);
  });

  test("cancel from home aborts", async () => {
    await expect(
      completeInteractively({ ...blankOptions }, scriptedUi(["cancel"])),
    ).rejects.toThrow("Install cancelled");
  });

  test("aborts when the UI reports cancel", async () => {
    await expect(
      completeInteractively({ ...blankOptions }, scriptedUi([Symbol.for("clack:cancel")])),
    ).rejects.toThrow("Install cancelled");
  });

  test("offers copy only when advanced options are enabled", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi(["browse:first-party", ["branch"], "proceed", ["cursor"], "global", true, true]),
    );

    expect(options.copy).toBe(true);
  });
});
