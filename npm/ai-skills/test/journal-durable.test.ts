import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { mkdirDurable, syncCreatedDirs } from "../lib/journal/durable.ts";
import { JournalTxn } from "../lib/journal/journal.ts";

async function withDir(run: (dir: string) => Promise<void>): Promise<void> {
  const dir = await realpath(await mkdtemp(join(tmpdir(), "ai-skills-durable-")));
  try {
    await run(dir);
  } finally {
    await rm(dir, { force: true, recursive: true });
  }
}

describe("durable directories", () => {
  test("flushes every directory level mkdir -p created", async () => {
    await withDir(async (dir) => {
      await mkdir(join(dir, "existing"));
      const synced: string[] = [];
      await mkdirDurable(join(dir, "existing/a/b/c"), async (path) => {
        synced.push(path);
      });
      expect(synced).toEqual([
        join(dir, "existing"),
        join(dir, "existing/a"),
        join(dir, "existing/a/b"),
        join(dir, "existing/a/b/c"),
      ]);
      synced.length = 0;
      await mkdirDurable(join(dir, "existing/a/b/c"), async (path) => {
        synced.push(path);
      });
      expect(synced).toEqual([]);
      await syncCreatedDirs(join(dir, "x"), undefined, async (path) => {
        synced.push(path);
      });
      expect(synced).toEqual([]);
    });
  });
});

describe("journal log tail", () => {
  /** An open transaction with no ops; its log is then edited by hand. */
  async function openTxn(dir: string): Promise<JournalTxn> {
    return JournalTxn.open({
      base: { generation: 0, txn: null },
      baseState: { plugins: {}, receipt: null },
      journalRoot: join(dir, "journal"),
      keepGenerations: 1,
      kind: "install",
      next: { artifactDigest: null, fingerprints: { adapters: {}, policy: null }, plugins: {} },
      ops: [],
      planned: true,
      root: dir,
      scope: "project",
      scopeDir: dir,
    });
  }

  test("drops a torn final record before the next append", async () => {
    await withDir(async (dir) => {
      const txn = await openTxn(dir);
      const log = join(txn.dir, "log.jsonl");
      await writeFile(log, '{"phase":"done","op":0}\n{"phase":"beg');
      const loaded = await JournalTxn.load(txn.dir);
      await loaded.compensate();
      expect(await readFile(log, "utf8")).toBe(
        '{"phase":"done","op":0}\n{"phase":"compensate"}\n{"phase":"compensated"}\n',
      );
      expect((await JournalTxn.load(txn.dir)).isCompensating).toBe(true);
    });
  });

  test("terminates a complete final record that lost its newline", async () => {
    await withDir(async (dir) => {
      const txn = await openTxn(dir);
      const log = join(txn.dir, "log.jsonl");
      await writeFile(log, '{"phase":"compensate"}');
      const loaded = await JournalTxn.load(txn.dir);
      expect(loaded.isCompensating).toBe(true);
      await loaded.compensate();
      expect(await readFile(log, "utf8")).toBe('{"phase":"compensate"}\n{"phase":"compensated"}\n');
    });
  });
});
