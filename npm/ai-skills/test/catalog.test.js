import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  loadBakedPlugin,
  loadBakedPlugins,
  loadBundles,
  loadVendorIndex,
  loadVendors,
  resolveBakedPluginsRoot,
} from "../lib/catalog.js";

/**
 * Run ``fn`` with ``AI_SKILLS_PLUGINS_BAKED`` pointed at ``root``.
 *
 * @param {string} root - Override directory.
 * @param {() => Promise<void>} fn - Test body.
 */
async function withBakedRoot(root, fn) {
  const previous = process.env.AI_SKILLS_PLUGINS_BAKED;
  process.env.AI_SKILLS_PLUGINS_BAKED = root;
  try {
    await fn();
  } finally {
    if (previous === undefined) {
      delete process.env.AI_SKILLS_PLUGINS_BAKED;
    } else {
      process.env.AI_SKILLS_PLUGINS_BAKED = previous;
    }
  }
}

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

    const { vendors } = await loadVendors();
    const anthropics = vendors.find((vendor) => vendor.id === "anthropics");
    const claudeCode = vendors.find((vendor) => vendor.id === "anthropics-claude-code");
    expect(anthropics?.sha).toBeTruthy();
    expect(claudeCode?.sha).toBeTruthy();

    const documentSkills = plugins.find((plugin) => plugin.id === "document-skills");
    expect(documentSkills).toMatchObject({
      vendor: "anthropics",
      repo: "anthropics/skills",
      sha: anthropics?.sha,
      version: (anthropics?.sha ?? "").slice(0, 7),
      skills: ["docx", "pdf", "pptx", "xlsx"],
    });
    expect(documentSkills?.description).toContain("[baked from vendor 'anthropics']");

    const renamed = await loadBakedPlugin("claude-code-frontend-design");
    expect(renamed?.skills).toEqual(["frontend-design-claude-code"]);
    expect(renamed?.vendor).toBe("anthropics-claude-code");
    expect(renamed?.version).toBe((claudeCode?.sha ?? "").slice(0, 7));

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

  test("an AI_SKILLS_PLUGINS_BAKED override that is not a bake is absent", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-empty-bake-"));
    try {
      await withBakedRoot(root, async () => {
        expect(resolveBakedPluginsRoot()).toBeNull();
        const { plugins } = await loadBakedPlugins();
        expect(plugins).toEqual([]);
      });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("fails closed when a marketplace plugin is missing skills/", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-missing-skills-"));
    try {
      await mkdir(join(root, ".claude-plugin"), { recursive: true });
      await mkdir(join(root, "ghost-plugin"), { recursive: true });
      await writeFile(
        join(root, ".claude-plugin", "marketplace.json"),
        JSON.stringify({
          plugins: [
            {
              name: "ghost-plugin",
              description: "Missing skills tree.",
              version: "1.0.0",
              source: "./ghost-plugin",
            },
          ],
        }),
        "utf8",
      );
      await writeFile(
        join(root, "BAKE.json"),
        JSON.stringify({
          vendors: [
            {
              id: "ghost",
              repo: "owner/ghost",
              sha: "0123456789abcdef0123456789abcdef01234567",
              plugins: [{ id: "ghost-plugin" }],
            },
          ],
        }),
        "utf8",
      );
      await withBakedRoot(root, async () => {
        await expect(loadBakedPlugins()).rejects.toThrow("missing skills directory");
      });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});
