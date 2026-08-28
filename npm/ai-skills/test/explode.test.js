import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { hashFile } from "../lib/lockfile.js";
import {
  destUsesCopyMaterialization,
  discardExplodeBackups,
  explodePlugin,
  pruneEmptyDirTrees,
  removeExplodedFiles,
} from "../lib/projectors/explode.js";

/**
 * @param {string} root - Temp workspace.
 * @returns {Promise<{dest: string, source: string, store: string}>} Layout roots.
 */
async function layout(root) {
  const source = join(root, "src");
  const dest = join(root, ".cursor/skills");
  const store = join(root, ".agents/skills");
  await mkdir(join(source, "lint"), { recursive: true });
  await writeFile(join(source, "lint/SKILL.md"), "# lint\n");
  await mkdir(join(source, "lint/nested/empty"), { recursive: true });
  await writeFile(join(source, "lint/nested/notes.md"), "notes\n");
  return { dest, source, store };
}

describe("explodePlugin", () => {
  test("injected failure mid-stage leaves zero dest footprint", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-stage-"));
    try {
      const { dest, source, store } = await layout(root);
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          failAfter: "stage",
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("injected failure: stage");
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(join(store, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("injected failure mid-commit rolls back dest and store writes", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-commit-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(source, "test"), { recursive: true });
      await writeFile(join(source, "test/SKILL.md"), "# test\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          failAfter: "commit",
          skills: ["lint", "test"],
          sourceSkills: { lint: join(source, "lint"), test: join(source, "test") },
          storeRoot: store,
        }),
      ).rejects.toThrow("injected failure: commit");
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(join(dest, "test"))).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(join(store, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("identical-content dest is skipped and not claimed", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-dedupe-"));
    try {
      const { dest, source } = await layout(root);
      await mkdir(join(dest, "lint/nested"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "lint/nested/notes.md"), "notes\n");
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        copy: true,
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
      });
      expect(result.claimed.cursor).toBeUndefined();
      expect(result.skipped).toEqual([
        { agent: "cursor", dest: join(dest, "lint"), skill: "lint" },
      ]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("different-content collision errors before any write", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-collide-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# local lint\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("Explode collision");
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# local lint\n");
      await expect(lstat(join(store, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("rejects a source symlink that escapes the skill tree", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-symlink-"));
    try {
      const { dest, source, store } = await layout(root);
      const outside = join(root, "secret.txt");
      await writeFile(outside, "secret\n");
      await symlinkEscape(join(source, "lint/escape"), outside);
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("outside explode root");
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("rejects a cyclic directory symlink in the explode source", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-cycle-"));
    try {
      const { dest, source, store } = await layout(root);
      await symlink(".", join(source, "lint/loop"));
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("cyclic symlink");
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("symlinks dest into the managed store and claims hashed files", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-link-"));
    try {
      const { dest, source, store } = await layout(root);
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readlink(join(dest, "lint"))).toBe(join(store, "lint"));
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(result.claimed.cursor["lint/SKILL.md"]).toBe(
        await hashFile(join(source, "lint/SKILL.md")),
      );
      expect(result.claimed.cursor["lint/nested/notes.md"]).toBe(
        await hashFile(join(source, "lint/nested/notes.md")),
      );
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("copy mode writes dest trees without a store symlink", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-copy-"));
    try {
      const { dest, source } = await layout(root);
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        copy: true,
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
      });
      expect((await lstat(join(dest, "lint"))).isDirectory()).toBe(true);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(result.claimed.cursor["lint/SKILL.md"]).toBe(
        await hashFile(join(source, "lint/SKILL.md")),
      );
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("per-agent copy keeps dest directories when the call-level flag is false", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-copy-agent-"));
    try {
      const { dest, source, store } = await layout(root);
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        copy: true,
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
      });
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await explodePlugin({
        agents: [{ copy: true, id: "cursor", replace: new Set(["lint"]), root: dest }],
        copy: false,
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect((await lstat(join(dest, "lint"))).isDirectory()).toBe(true);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
      await expect(lstat(join(store, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("replaces a dangling dest skill symlink instead of throwing ENOENT", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-dangling-"));
    try {
      const { dest, source, store } = await layout(root);
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await rm(join(store, "lint"), { force: true, recursive: true });
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await explodePlugin({
        agents: [{ id: "cursor", replace: new Set(["lint"]), root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readlink(join(dest, "lint"))).toBe(join(store, "lint"));
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("owned replace restores dest and store when commit fails", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-replace-roll-"));
    try {
      const { dest, source, store } = await layout(root);
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", replace: new Set(["lint"]), root: dest }],
          failAfter: "commit",
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("injected failure: commit");
      expect(await readlink(join(dest, "lint"))).toBe(join(store, "lint"));
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("keepBackups leaves dest.bak until the caller discards it", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-keep-bak-"));
    try {
      const { dest, source, store } = await layout(root);
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await mkdir(join(dest, "lint.bak"), { recursive: true });
      await writeFile(join(dest, "lint.bak/USER.txt"), "keep\n");
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      const result = await explodePlugin({
        agents: [{ id: "cursor", replace: new Set(["lint"]), root: dest }],
        keepBackups: true,
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
      expect((await lstat(result.swappedDests[0].backup)).isSymbolicLink()).toBe(true);
      expect(await readFile(join(result.swappedStores[0].backup, "SKILL.md"), "utf8")).toBe(
        "# lint\n",
      );
      expect(await readFile(join(dest, "lint.bak/USER.txt"), "utf8")).toBe("keep\n");
      await discardExplodeBackups(result);
      expect(await readFile(join(dest, "lint.bak/USER.txt"), "utf8")).toBe("keep\n");
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("unowned dest is not claimed on a second explode of the same plugin", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-second-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(dest, "lint/nested"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "lint/nested/notes.md"), "notes\n");
      await mkdir(join(source, "test"), { recursive: true });
      await writeFile(join(source, "test/SKILL.md"), "# test\n");
      const first = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint", "test"],
        sourceSkills: { lint: join(source, "lint"), test: join(source, "test") },
        storeRoot: store,
      });
      expect(first.claimed.cursor["lint/SKILL.md"]).toBeUndefined();
      expect(first.claimed.cursor["test/SKILL.md"]).toBe(
        await hashFile(join(source, "test/SKILL.md")),
      );
      const second = await explodePlugin({
        agents: [
          {
            id: "cursor",
            replace: new Set(["test"]),
            root: dest,
          },
        ],
        skills: ["lint", "test"],
        sourceSkills: { lint: join(source, "lint"), test: join(source, "test") },
        storeRoot: store,
      });
      expect(second.claimed.cursor["lint/SKILL.md"]).toBeUndefined();
      expect(second.skipped).toEqual([
        { agent: "cursor", dest: join(dest, "lint"), skill: "lint" },
      ]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("identical unowned dest is skipped even when leftover store content differs", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-dest-skip-store-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(dest, "lint/nested"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "lint/nested/notes.md"), "notes\n");
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# other\n");
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(result.skipped).toEqual([
        { agent: "cursor", dest: join(dest, "lint"), skill: "lint" },
      ]);
      expect(result.claimed.cursor).toBeUndefined();
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# other\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("injected copy failure does not leave a dest.staging sidecar", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-staging-"));
    try {
      const { dest, source } = await layout(root);
      const { cp } = await import("node:fs/promises");
      let copies = 0;
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          copy: true,
          copyFn: async (from, to, options) => {
            copies += 1;
            await cp(from, to, options);
            if (copies > 1) {
              throw new Error("copy failed");
            }
          },
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
        }),
      ).rejects.toThrow("copy failed");
      const { readdir } = await import("node:fs/promises");
      const names = await readdir(dest).catch(() => []);
      expect(names.filter((name) => name.includes("staging"))).toEqual([]);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("unowned leftover store with different content is replaced when dest is absent", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# store lint\n");
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readlink(join(dest, "lint"))).toBe(join(store, "lint"));
      expect(result.claimed.cursor["lint/SKILL.md"]).toBe(
        await hashFile(join(source, "lint/SKILL.md")),
      );
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("empty existing store is replaced instead of reused as a dangling dest", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-empty-store-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(store, "lint"), { recursive: true });
      const result = await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(result.claimed.cursor["lint/SKILL.md"]).toBe(
        await hashFile(join(source, "lint/SKILL.md")),
      );
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("hard-errors when a leftover store is still linked from another dest", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-live-"));
    try {
      const { dest, source, store } = await layout(root);
      const other = join(root, ".codex/skills");
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# leftover\n");
      await mkdir(other, { recursive: true });
      await symlink(join(store, "lint"), join(other, "lint"));
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          destRoots: [dest, other],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("also linked from");
      expect(await readFile(join(other, "lint/SKILL.md"), "utf8")).toBe("# leftover\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("hard-errors when another lock plugin still owns the leftover store skill", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-owned-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# leftover\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          retainStoreSkills: new Set(["lint"]),
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("existing store content differs");
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# leftover\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("hard-errors when an owned update would rewrite a store still linked elsewhere", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-owned-live-"));
    try {
      const { dest, source, store } = await layout(root);
      const other = join(root, ".codex/skills");
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await mkdir(other, { recursive: true });
      await symlink(join(store, "lint"), join(other, "lint"));
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", replace: new Set(["lint"]), root: dest }],
          destRoots: [dest, other],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("also linked from");
      expect(await readFile(join(other, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("owned update rewrites a shared store when every linked dest is in the transaction", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-owned-txn-"));
    try {
      const { dest, source, store } = await layout(root);
      const other = join(root, ".codex/skills");
      await explodePlugin({
        agents: [
          { id: "cursor", root: dest },
          { id: "codex", root: other },
        ],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await explodePlugin({
        agents: [
          { id: "cursor", replace: new Set(["lint"]), root: dest },
          { id: "codex", replace: new Set(["lint"]), root: other },
        ],
        destRoots: [dest, other],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
      expect(await readFile(join(other, "lint/SKILL.md"), "utf8")).toBe("# lint v2\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("hard-errors when an owned update would replace a store another plugin still owns", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-owned-retain-"));
    try {
      const { dest, source, store } = await layout(root);
      await explodePlugin({
        agents: [{ id: "cursor", root: dest }],
        skills: ["lint"],
        sourceSkills: { lint: join(source, "lint") },
        storeRoot: store,
      });
      await writeFile(join(source, "lint/SKILL.md"), "# lint v2\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", replace: new Set(["lint"]), root: dest }],
          retainStoreSkills: new Set(["lint"]),
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("existing store content differs");
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("in-tree source symlink is part of the collision hash", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-alias-"));
    try {
      const { dest, source } = await layout(root);
      await symlink("SKILL.md", join(source, "lint/alias.md"));
      await mkdir(join(dest, "lint/nested"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await writeFile(join(dest, "lint/nested/notes.md"), "notes\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          copy: true,
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
        }),
      ).rejects.toThrow("Explode collision");
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("removeExplodedFiles", () => {
  test("leaves a later-unclaimed identical dest in place", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-keep-"));
    try {
      const dest = join(root, ".cursor/skills");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      await mkdir(join(dest, "keep"), { recursive: true });
      await writeFile(join(dest, "keep/SKILL.md"), "# keep\n");
      const keepDigest = await hashFile(join(dest, "keep/SKILL.md"));
      const result = await removeExplodedFiles({
        files: [
          {
            absolute: join(dest, "keep/SKILL.md"),
            digest: keepDigest,
            relative: "keep/SKILL.md",
            root: dest,
          },
        ],
        pluginId: "review",
      });
      expect(result.removed).toEqual(["keep/SKILL.md"]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("prunes nested empty directory trees after hash-verified delete", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-prune-"));
    try {
      const dest = join(root, ".cursor/skills");
      await mkdir(join(dest, "lint/a/b/c"), { recursive: true });
      await mkdir(join(dest, "lint/a/empty/nested"), { recursive: true });
      await writeFile(join(dest, "lint/a/b/c/SKILL.md"), "# lint\n");
      const digest = await hashFile(join(dest, "lint/a/b/c/SKILL.md"));
      await removeExplodedFiles({
        files: [
          {
            absolute: join(dest, "lint/a/b/c/SKILL.md"),
            digest,
            relative: "lint/a/b/c/SKILL.md",
            root: dest,
          },
        ],
        pluginId: "review",
      });
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("leaves locally modified files with a warning", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-modified-"));
    const warnings = [];
    try {
      const dest = join(root, ".cursor/skills");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# dirty\n");
      const result = await removeExplodedFiles({
        files: [
          {
            absolute: join(dest, "lint/SKILL.md"),
            digest: "abc",
            relative: "lint/SKILL.md",
            root: dest,
          },
        ],
        hash: async () => "changed",
        pluginId: "review",
        warn: (message) => {
          warnings.push(message);
        },
      });
      expect(result.removed).toEqual([]);
      expect(result.modified).toEqual(["lint/SKILL.md"]);
      expect(warnings).toEqual(["left modified review file lint/SKILL.md"]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# dirty\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("unlinks a dest skill symlink without deleting the managed store", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-unlink-"));
    try {
      const dest = join(root, ".cursor/skills");
      const store = join(root, ".agents/skills");
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# lint\n");
      await mkdir(dest, { recursive: true });
      await symlink(join(store, "lint"), join(dest, "lint"));
      const digest = await hashFile(join(store, "lint/SKILL.md"));
      const result = await removeExplodedFiles({
        files: [
          {
            absolute: join(dest, "lint/SKILL.md"),
            digest,
            relative: "lint/SKILL.md",
            root: dest,
          },
        ],
        pluginId: "review",
      });
      expect(result.removed).toEqual(["lint/SKILL.md"]);
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("unlinks a dangling dest skill symlink without requiring store content", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-dangle-rm-"));
    try {
      const dest = join(root, ".cursor/skills");
      const store = join(root, ".agents/skills");
      await mkdir(dest, { recursive: true });
      await mkdir(store, { recursive: true });
      await symlink(join(store, "lint"), join(dest, "lint"));
      const result = await removeExplodedFiles({
        files: [
          {
            absolute: join(dest, "lint/SKILL.md"),
            digest: "missing",
            relative: "lint/SKILL.md",
            root: dest,
          },
        ],
        pluginId: "review",
      });
      expect(result.removed).toEqual(["lint/SKILL.md"]);
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("destUsesCopyMaterialization", () => {
  test("detects a real dest directory as copy mode", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-copy-detect-"));
    try {
      const dest = join(root, ".cursor/skills");
      await mkdir(join(dest, "lint"), { recursive: true });
      await writeFile(join(dest, "lint/SKILL.md"), "# lint\n");
      expect(await destUsesCopyMaterialization(dest, ["lint", "missing"])).toBe(true);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("does not treat dest skill symlinks as copy mode", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-link-detect-"));
    try {
      const dest = join(root, ".cursor/skills");
      const store = join(root, ".agents/skills/lint");
      await mkdir(dest, { recursive: true });
      await mkdir(store, { recursive: true });
      await writeFile(join(store, "SKILL.md"), "# lint\n");
      await symlink(store, join(dest, "lint"));
      expect(await destUsesCopyMaterialization(dest, ["lint"])).toBe(false);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("pruneEmptyDirTrees", () => {
  test("removes nested empty dirs and stops at the agent root", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-empty-"));
    try {
      const dest = join(root, ".cursor/skills");
      await mkdir(join(dest, "lint/a/empty/nested"), { recursive: true });
      const { rmdir, readdir } = await import("node:fs/promises");
      await pruneEmptyDirTrees(join(dest, "lint"), dest, {
        readDir: (dir) => readdir(dir, { withFileTypes: true }),
        removeDir: rmdir,
      });
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
      expect((await lstat(dest)).isDirectory()).toBe(true);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

/**
 * @param {string} linkPath - Symlink path inside the skill tree.
 * @param {string} target - Absolute path outside the skill tree.
 * @returns {Promise<void>} Resolves when the symlink exists.
 */
async function symlinkEscape(linkPath, target) {
  const { symlink } = await import("node:fs/promises");
  await symlink(target, linkPath);
}
