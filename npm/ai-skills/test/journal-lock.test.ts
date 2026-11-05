import { describe, expect, test } from "bun:test";
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, utimes, writeFile } from "node:fs/promises";
import { hostname, tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { acquireStateLock, breakStaleLock, StateLockBusyError } from "../lib/journal/journal.ts";
import { readReceipt, stateRoot } from "../lib/journal/receipts.ts";
import { withStateSession } from "../lib/journal/recover.ts";
import { PACKAGE_ROOT } from "../lib/paths.ts";
import { createWorld, hostPlugins, WORLD_PLUGIN } from "./fixtures/journal-world.ts";

const HOLDER = join(PACKAGE_ROOT, "test/fixtures/lock-holder.ts");
const CHILD = join(PACKAGE_ROOT, "test/fixtures/journal-child.ts");

async function withHome(run: (home: string, lock: string) => Promise<void>): Promise<void> {
  const home = await mkdtemp(join(tmpdir(), "ai-skills-lock-"));
  try {
    await run(home, join(stateRoot({ home }), "lock"));
  } finally {
    await rm(home, { force: true, recursive: true });
  }
}

/** Start a process that takes the lock; resolves once it holds it. */
function holdLock(lock: string, holdMs?: number): Promise<ChildProcess> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [HOLDER, lock, ...(holdMs ? [String(holdMs)] : [])], {
      stdio: ["ignore", "pipe", "inherit"],
    });
    child.on("error", reject);
    child.stdout!.on("data", (chunk) => {
      if (String(chunk).includes("locked")) {
        resolve(child);
      }
    });
  });
}

function exited(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    child.on("close", () => resolve());
  });
}

describe("state lock", () => {
  test("a second command fails clearly while a live process holds the lock", async () => {
    await withHome(async (home, lock) => {
      const holder = await holdLock(lock);
      try {
        const error = await withStateSession(
          { env: { cwd: home, home }, lockWaitMs: 150, scope: "global" },
          async () => "ran",
        ).catch((caught: unknown) => caught);
        expect(error).toBeInstanceOf(StateLockBusyError);
        expect(String(error)).toContain(`pid ${holder.pid} on ${hostname()}`);
        expect(String(error)).toContain(lock);
      } finally {
        holder.kill("SIGKILL");
        await exited(holder);
      }
    });
  });

  test("a second command waits for the holder to finish", async () => {
    await withHome(async (home, lock) => {
      const holder = await holdLock(lock, 400);
      const started = Date.now();
      const result = await withStateSession(
        { env: { cwd: home, home }, lockWaitMs: 20_000, scope: "global" },
        async () => "ran",
      );
      expect(result).toBe("ran");
      expect(Date.now() - started).toBeGreaterThanOrEqual(200);
      await exited(holder);
    });
  });

  test("recovers a stale lock left by a killed process", async () => {
    await withHome(async (home, lock) => {
      const holder = await holdLock(lock);
      holder.kill("SIGKILL");
      await exited(holder);
      expect(JSON.parse(await readFile(lock, "utf8")).pid).toBe(holder.pid);
      const reports: string[] = [];
      const result = await withStateSession(
        {
          env: { cwd: home, home },
          lockWaitMs: 0,
          report: (line) => reports.push(line),
          scope: "global",
        },
        async () => "ran",
      );
      expect(result).toBe("ran");
      expect(reports).toEqual([
        expect.stringContaining(`recovered a stale state lock left by pid ${holder.pid}`),
      ]);
      await expect(readFile(lock, "utf8")).rejects.toThrow("ENOENT");
    });
  });

  test("a lock held on another host blocks because its liveness is unknown", async () => {
    await withHome(async (_home, lock) => {
      await mkdir(dirname(lock), { recursive: true });
      await writeFile(
        lock,
        JSON.stringify({ hostname: "elsewhere", pid: 1, startedAt: "2026-01-01", token: "t" }),
      );
      await expect(acquireStateLock(lock, { waitMs: 100 })).rejects.toThrow(
        "pid 1 on elsewhere, since 2026-01-01",
      );
    });
  });

  test("an unreadable lock blocks while fresh and is recovered once old", async () => {
    await withHome(async (_home, lock) => {
      await mkdir(dirname(lock), { recursive: true });
      await writeFile(lock, "");
      await expect(acquireStateLock(lock, { waitMs: 100 })).rejects.toThrow(
        "its holder could not be read",
      );
      const old = new Date(Date.now() - 60_000);
      await utimes(lock, old, old);
      const release = await acquireStateLock(lock, { waitMs: 0 });
      expect(JSON.parse(await readFile(lock, "utf8")).pid).toBe(process.pid);
      await release();
      await expect(readFile(lock, "utf8")).rejects.toThrow("ENOENT");
    });
  });

  test("stale recovery never removes a lock that changed since it was judged", async () => {
    await withHome(async (_home, lock) => {
      await mkdir(dirname(lock), { recursive: true });
      const fresh = { hostname: hostname(), pid: process.pid, startedAt: "now", token: "fresh" };
      await writeFile(lock, JSON.stringify(fresh));
      // Judged torn, or judged as another holder: the fresh lock stays.
      expect(await breakStaleLock(lock, null)).toBe(false);
      expect(await breakStaleLock(lock, { ...fresh, pid: 999_999_999, token: "dead" })).toBe(false);
      expect(JSON.parse(await readFile(lock, "utf8")).token).toBe("fresh");
      // Another recoverer holds the guard: nothing is touched.
      const dead = { ...fresh, pid: 999_999_999, token: "dead" };
      await writeFile(lock, JSON.stringify(dead));
      await writeFile(`${lock}.recover`, "");
      expect(await breakStaleLock(lock, dead)).toBe(false);
      expect(JSON.parse(await readFile(lock, "utf8")).token).toBe("dead");
      // An abandoned guard is cleared once old; the stale lock then goes.
      const old = new Date(Date.now() - 60_000);
      await utimes(`${lock}.recover`, old, old);
      expect(await breakStaleLock(lock, dead)).toBe(false);
      expect(await breakStaleLock(lock, dead)).toBe(true);
      await expect(readFile(lock, "utf8")).rejects.toThrow("ENOENT");
      await expect(readFile(`${lock}.recover`, "utf8")).rejects.toThrow("ENOENT");
    });
  });

  test("two concurrent installs serialize and leave one consistent generation", async () => {
    const world = await createWorld();
    try {
      const run = () =>
        new Promise<number | null>((resolve, reject) => {
          const child = spawn(process.execPath, [CHILD, JSON.stringify(world), "install"], {
            env: { ...process.env, AI_SKILLS_NO_UPDATE_CHECK: "1" },
            stdio: ["ignore", "ignore", "inherit"],
          });
          child.on("error", reject);
          child.on("close", (code) => resolve(code));
        });
      expect(await Promise.all([run(), run()])).toEqual([0, 0]);
      const receipt = await readReceipt("project", { cwd: world.cwd, home: world.home });
      expect(receipt?.generation).toBe(1);
      expect(Object.keys(receipt!.plugins)).toEqual([WORLD_PLUGIN]);
      expect(await hostPlugins(world)).toEqual([`claude:${WORLD_PLUGIN}@ai-skills`]);
    } finally {
      await rm(world.root, { force: true, recursive: true });
    }
  });
});
