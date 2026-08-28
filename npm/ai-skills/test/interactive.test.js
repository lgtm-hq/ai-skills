import { describe, expect, test } from "bun:test";

import {
  batchesFromCart,
  batchesFromCliOptions,
  buildPluginChecklist,
  buildVendorSkillPicker,
  cartPluginCount,
  completeInteractively,
  formatVendorGroupHeading,
  partitionPluginSelection,
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
  test("counts plugins and expands first-party batches", async () => {
    const cart = {
      firstParty: ["review"],
      vendors: [],
    };
    expect(cartPluginCount(cart)).toBe(1);
    expect(partitionPluginSelection(["review", "vendor:anthropics"])).toEqual({
      firstParty: ["review"],
      vendors: ["anthropics"],
    });
    const batches = await batchesFromCart(cart);
    expect(batches).toEqual([
      {
        pluginId: "review",
        vendor: null,
        skills: ["lint", "test", "greptile", "coderabbit"],
      },
    ]);
  });

  test("expands a vendor plugin from CLI options", async () => {
    await expect(
      batchesFromCliOptions({ vendor: "anthropics", skills: ["pdf"], bundle: null }),
    ).rejects.toThrow(/plugin-atomic/);
    const batches = await batchesFromCliOptions({
      vendor: "anthropics",
      skills: [],
      bundle: null,
    });
    expect(batches.map((batch) => batch.pluginId)).toEqual([
      "document-skills",
      "example-skills",
      "claude-api",
    ]);
    expect(batches[0]).toMatchObject({
      pluginId: "document-skills",
      vendor: "anthropics",
    });
    expect(batches[0]?.skills).toEqual(["docx", "pdf", "pptx", "xlsx"]);
  });

  test("expands a baked plugin id from --skill", async () => {
    const [batch] = await batchesFromCliOptions({
      vendor: null,
      skills: ["document-skills"],
      bundle: null,
    });
    expect(batch).toEqual({
      pluginId: "document-skills",
      vendor: "anthropics",
      skills: ["docx", "pdf", "pptx", "xlsx"],
    });
  });

  test("lists first-party and baked vendor plugins on one checklist", async () => {
    const { loadBundles, loadVendors } = await import("../lib/catalog.js");
    const bundles = await loadBundles();
    const vendors = await loadVendors();
    const options = await buildPluginChecklist(bundles, vendors, {
      driftedVendors: new Set(["davidondrej"]),
    });
    expect(options.some((option) => option.value === "review")).toBe(true);
    expect(options.find((option) => option.value === "review")?.label).toContain("4 skills");
    expect(options.some((option) => option.value === "document-skills")).toBe(true);
    expect(options.find((option) => option.value === "document-skills")?.label).toContain(
      "[baked from vendor 'anthropics']",
    );
    expect(options.find((option) => option.value === "davidondrej-skills")?.label).toContain(
      "newer commits",
    );
  });
});

describe("completeInteractively", () => {
  test("honors CLI vendor plugin without opening the checklist", async () => {
    const options = await completeInteractively(
      { ...blankOptions, vendor: "anthropics" },
      scriptedUi([["cursor"], "global", false]),
      offlineDependencies,
    );

    expect(options.installBatches[0]?.pluginId).toBe("document-skills");
    expect(options.installBatches[0]?.vendor).toBe("anthropics");
    expect(options.installBatches.map((batch) => batch.pluginId)).toEqual([
      "document-skills",
      "example-skills",
      "claude-api",
    ]);
    expect(options.vendor).toBeNull();
    expect(options.skills).toEqual([]);
    expect(options.agents).toEqual(["cursor"]);
  });

  test("selects first-party plugins then proceeds with defaults", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi([["review"], KNOWN_AGENTS.map((agent) => agent.value), "global", false]),
      offlineDependencies,
    );

    expect(options.bundle).toBeNull();
    expect(options.vendor).toBeNull();
    expect(options.installBatches).toEqual([
      {
        pluginId: "review",
        vendor: null,
        skills: ["lint", "test", "greptile", "coderabbit"],
      },
    ]);
    expect(options.agents).toEqual(["claude-code", "cursor", "codex", "copilot"]);
    expect(options.global).toBe(true);
    expect(options.copy).toBe(false);
    expect(options.onConflict).toBe("overwrite");
  });

  test("selects first-party and vendor plugins on one checklist", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi([
        ["review", "document-skills"],
        KNOWN_AGENTS.map((agent) => agent.value),
        "global",
        false,
      ]),
      offlineDependencies,
    );

    expect(options.installBatches[0]).toEqual({
      pluginId: "review",
      vendor: null,
      skills: ["lint", "test", "greptile", "coderabbit"],
    });
    expect(options.installBatches[1]?.pluginId).toBe("document-skills");
    expect(options.installBatches[1]?.vendor).toBe("anthropics");
    expect(options.installBatches[1]?.skills).toEqual(["docx", "pdf", "pptx", "xlsx"]);
  });

  test("empty plugin selection cancels", async () => {
    await expect(
      completeInteractively({ ...blankOptions }, scriptedUi([[]]), offlineDependencies),
    ).rejects.toThrow("Install cancelled");
  });

  test("cancel from the plugin checklist aborts", async () => {
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
      scriptedUi([["git-pr"], ["cursor"], "global", true, true]),
      offlineDependencies,
    );

    expect(options.copy).toBe(true);
    expect(options.installBatches[0]?.pluginId).toBe("git-pr");
  });
});
