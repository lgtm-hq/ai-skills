import { describe, expect, test } from "bun:test";

import {
  batchesFromCart,
  batchesFromCliOptions,
  buildHomeOptions,
  buildVendorSkillPicker,
  cartSkillCount,
  completeInteractively,
  formatVendorGroupHeading,
  vendorDisplayLabel,
  vendorSkillGroupKey,
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

/**
 * Wizard dependencies that disable network checks and read no real lockfile.
 *
 * @returns {never} Never returns; throws a synthetic ENOENT.
 */
const missingLockRead = async () => {
  throw Object.assign(new Error("no lockfile"), { code: "ENOENT" });
};

const offlineDependencies = {
  env: { AI_SKILLS_NO_UPDATE_CHECK: "1" },
  lockEnvironment: { cwd: "/nonexistent", home: "/nonexistent", read: missingLockRead },
};

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

describe("vendorSkillGroupKey", () => {
  test("groups nested skills under a literal skillRoot", () => {
    expect(vendorSkillGroupKey("skills/engineering/tdd", ["skills"])).toBe("engineering");
    expect(vendorSkillGroupKey("skills/in-progress/wizard", ["skills"])).toBe("in-progress");
  });

  test("leaves skills sitting directly under a literal root uncategorized", () => {
    expect(vendorSkillGroupKey("skills/pdf", ["skills"])).toBeNull();
  });

  test("uses wildcard captures from skillRoots as the group", () => {
    expect(
      vendorSkillGroupKey("plugins/plugin-dev/skills/hook-development", ["plugins/*/skills"]),
    ).toBe("plugin-dev");
    expect(
      vendorSkillGroupKey("plugins/frontend-design/skills/frontend-design", ["plugins/*/skills"]),
    ).toBe("frontend-design");
  });
});

describe("buildVendorSkillPicker", () => {
  test("stays flat when every skill is directly under the root", () => {
    const picker = buildVendorSkillPicker(
      [
        { name: "pdf", path: "skills/pdf" },
        { name: "docx", path: "skills/docx" },
      ],
      ["skills"],
    );
    expect(picker).toEqual({
      mode: "flat",
      options: [
        { value: "pdf", label: "pdf" },
        { value: "docx", label: "docx" },
      ],
    });
  });

  test("groups nested vendor folders for groupMultiselect", () => {
    const picker = buildVendorSkillPicker(
      [
        { name: "tdd", path: "skills/engineering/tdd" },
        { name: "grill-me", path: "skills/productivity/grill-me" },
        { name: "qa", path: "skills/deprecated/qa" },
      ],
      ["skills"],
    );
    expect(picker.mode).toBe("grouped");
    expect(picker.options).toEqual({
      Deprecated: [{ value: "qa", label: "qa" }],
      Engineering: [{ value: "tdd", label: "tdd" }],
      Productivity: [{ value: "grill-me", label: "grill-me" }],
    });
  });

  test("groups claude-code skills by plugin folder", () => {
    const picker = buildVendorSkillPicker(
      [
        {
          name: "hook-development",
          path: "plugins/plugin-dev/skills/hook-development",
        },
        {
          name: "skill-development",
          path: "plugins/plugin-dev/skills/skill-development",
        },
        {
          name: "frontend-design",
          path: "plugins/frontend-design/skills/frontend-design",
        },
      ],
      ["plugins/*/skills"],
    );
    expect(picker.mode).toBe("grouped");
    expect(picker.options).toEqual({
      "Frontend Design": [{ value: "frontend-design", label: "frontend-design" }],
      "Plugin Dev": [
        { value: "hook-development", label: "hook-development" },
        { value: "skill-development", label: "skill-development" },
      ],
    });
  });

  test("puts uncategorized skills under Other when mixed with groups", () => {
    const picker = buildVendorSkillPicker(
      [
        { name: "tdd", path: "skills/engineering/tdd" },
        { name: "orphan", path: "skills/orphan" },
      ],
      ["skills"],
    );
    expect(picker.mode).toBe("grouped");
    expect(picker.options).toEqual({
      Engineering: [{ value: "tdd", label: "tdd" }],
      Other: [{ value: "orphan", label: "orphan" }],
    });
  });

  test("title-cases path-derived headings", () => {
    expect(formatVendorGroupHeading("in-progress")).toBe("In Progress");
    expect(formatVendorGroupHeading("plugin-dev")).toBe("Plugin Dev");
  });

  test("disambiguates title-cased headings that would collide", () => {
    const picker = buildVendorSkillPicker(
      [
        { name: "a", path: "skills/plugin-dev/a" },
        { name: "b", path: "skills/plugin_dev/b" },
        { name: "c", path: "skills/other/c" },
        { name: "orphan", path: "skills/orphan" },
      ],
      ["skills"],
    );
    expect(picker.mode).toBe("grouped");
    expect(Object.keys(picker.options).sort()).toEqual([
      "Other",
      "Other (other)",
      "Plugin Dev",
      "Plugin Dev (plugin_dev)",
    ]);
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
      offlineDependencies,
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
      offlineDependencies,
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
      offlineDependencies,
    );

    expect(options.installBatches).toEqual([
      { vendor: null, skills: ["branch"] },
      { vendor: "anthropics", skills: ["pdf"] },
    ]);
  });

  test("uses groupMultiselect for nested vendor catalogs", async () => {
    /** @type {string[]} */
    const prompts = [];
    const base = scriptedUi([
      "browse:vendor:mattpocock",
      ["tdd", "grill-me"],
      "proceed",
      ["cursor"],
      "global",
      false,
    ]);
    const ui = {
      ...base,
      async multiselect(options) {
        prompts.push("multiselect");
        return base.multiselect(options);
      },
      async groupMultiselect(options) {
        prompts.push("groupMultiselect");
        expect(Object.keys(options.options).length).toBeGreaterThan(1);
        return base.groupMultiselect(options);
      },
    };

    const options = await completeInteractively({ ...blankOptions }, ui, offlineDependencies);

    expect(prompts[0]).toBe("groupMultiselect");
    expect(options.installBatches).toEqual([{ vendor: "mattpocock", skills: ["tdd", "grill-me"] }]);
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
      offlineDependencies,
    );

    expect(options.installBatches).toEqual([{ vendor: null, skills: ["commit"] }]);
    expect(options.agents).toEqual(["cursor"]);
    expect(options.project).toBe(true);
  });

  test("cancel from home aborts", async () => {
    await expect(
      completeInteractively({ ...blankOptions }, scriptedUi(["cancel"]), offlineDependencies),
    ).rejects.toThrow("Install cancelled");
  });

  test("aborts when the UI reports cancel", async () => {
    await expect(
      completeInteractively(
        { ...blankOptions },
        scriptedUi([Symbol.for("clack:cancel")]),
        offlineDependencies,
      ),
    ).rejects.toThrow("Install cancelled");
  });

  test("offers copy only when advanced options are enabled", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi(["browse:first-party", ["branch"], "proceed", ["cursor"], "global", true, true]),
      offlineDependencies,
    );

    expect(options.copy).toBe(true);
  });
});
