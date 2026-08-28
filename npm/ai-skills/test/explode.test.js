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

  test("different existing store content is a hard collision", async () => {
    const root = await mkdtemp(join(tmpdir(), "ai-skills-explode-store-"));
    try {
      const { dest, source, store } = await layout(root);
      await mkdir(join(store, "lint"), { recursive: true });
      await writeFile(join(store, "lint/SKILL.md"), "# store lint\n");
      await expect(
        explodePlugin({
          agents: [{ id: "cursor", root: dest }],
          skills: ["lint"],
          sourceSkills: { lint: join(source, "lint") },
          storeRoot: store,
        }),
      ).rejects.toThrow("existing store content differs");
      expect(await readFile(join(store, "lint/SKILL.md"), "utf8")).toBe("# store lint\n");
      await expect(lstat(join(dest, "lint"))).rejects.toMatchObject({ code: "ENOENT" });
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
      const digest = await hashFile(join(dest, "lint/SKILL.md"));
      const result = await removeExplodedFiles({
        files: [],
        pluginId: "review",
      });
      expect(result.removed).toEqual([]);
      expect(await readFile(join(dest, "lint/SKILL.md"), "utf8")).toBe("# lint\n");
      expect(digest).toHaveLength(64);
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
