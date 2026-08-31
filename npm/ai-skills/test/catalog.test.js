import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { join } from "node:path";

import {
  loadBakedPlugin,
  loadBakedPlugins,
  loadBundles,
  loadVendorIndex,
  resolveBakedPluginsRoot,
} from "../lib/catalog.js";

describe("baked plugin catalog", () => {
  test("rejects a vendor path traversal attempt", () => {
    expect(() => loadVendorIndex("../outside")).toThrow("Invalid vendor identifier");
  });

  test("rejects a baked plugin path traversal attempt", async () => {
    await expect(loadBakedPlugin("../outside")).rejects.toThrow("Invalid baked plugin identifier");
  });

  test("merges the five baked vendors into the install catalog", async () => {
    const root = resolveBakedPluginsRoot();
    if (!root) {
      throw new Error("plugins-baked/ missing; run scripts/bake_vendor_plugins.py");
    }
    expect(root).toBeTruthy();
    expect(existsSync(join(root ?? "", "BAKE.json"))).toBe(true);

    const { plugins } = await loadBakedPlugins();
    expect(plugins.map((plugin) => plugin.id)).toEqual([
      "mattpocock-skills",
      "document-skills",
      "example-skills",
      "claude-api",
      "claude-opus-4-5-migration",
      "claude-code-frontend-design",
      "hookify",
      "plugin-dev",
      "caveman",
      "davidondrej-skills",
    ]);

    const documentSkills = plugins.find((plugin) => plugin.id === "document-skills");
    expect(documentSkills).toMatchObject({
      vendor: "anthropics",
      repo: "anthropics/skills",
      sha: "9d2f1ae187231d8199c64b5b762e1bdf2244733d",
      version: "9d2f1ae",
      skills: ["docx", "pdf", "pptx", "xlsx"],
    });
    expect(documentSkills?.description).toContain("[baked from vendor 'anthropics']");

    const renamed = await loadBakedPlugin("claude-code-frontend-design");
    expect(renamed?.skills).toEqual(["frontend-design-claude-code"]);
    expect(renamed?.vendor).toBe("anthropics-claude-code");
    expect(renamed?.version).toBe("15a21e1");

    const david = await loadBakedPlugin("davidondrej-skills");
    expect(david?.skills).toContain("teach-davidondrej");
    expect(david?.skills).toContain("handoff-davidondrej");
    expect(david?.skills).not.toContain("teach");
    expect(david?.description).toContain("[baked from vendor 'davidondrej']");
  });

  test("baked plugin ids do not collide with first-party bundle ids", async () => {
    const bundles = await loadBundles();
    const { plugins } = await loadBakedPlugins();
    for (const plugin of plugins) {
      expect(bundles.groups[plugin.id]).toBeUndefined();
    }
  });
});
