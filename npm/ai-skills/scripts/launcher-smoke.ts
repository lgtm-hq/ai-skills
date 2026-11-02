import { strict as assert } from "node:assert";
import { spawn, spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, realpath, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PACKAGE_ROOT } from "../lib/paths.ts";

/** Stage a test payload. The launcher gets an empty PATH and no runtime tools. */
export async function createRuntimeFixture(): Promise<{ root: string; runtimeRoot: string }> {
  const root = await mkdtemp(join(tmpdir(), "ai-skills-runtime-"));
  const runtimeRoot = join(root, "payloads");
  const target = `${process.platform === "win32" ? "windows" : process.platform}-${process.arch}`;
  const bundle = join(runtimeRoot, target);
  const interpreter = Bun.which("python3");
  assert(interpreter, "Python is a test fixture prerequisite");
  const python =
    process.platform === "win32"
      ? join(bundle, "python", "python.exe")
      : join(bundle, "python", "bin", "python3");
  await mkdir(join(python, ".."), { recursive: true });
  await symlink(await realpath(interpreter), python);
  await mkdir(join(bundle, "engine"), { recursive: true });
  await cp(
    join(PACKAGE_ROOT, "test/fixtures/runtime-entry.py"),
    join(bundle, "engine", "__main__.py"),
  );
  await mkdir(join(root, "empty"));
  return { root, runtimeRoot };
}

/** Exercise real source/emitted processes, streams, exit status, and signals. */
export async function launcherSmoke(): Promise<void> {
  const { root, runtimeRoot } = await createRuntimeFixture();
  try {
    const node = Bun.which("node");
    assert(node, "Node is required to test emitted JavaScript");
    for (const [executable, entry] of [
      [process.execPath, join(PACKAGE_ROOT, "bin/skill.ts")],
      [node, join(PACKAGE_ROOT, "dist/bin/skill.js")],
    ] satisfies [string, string][]) {
      const options = {
        cwd: join(root, "empty"),
        env: { ...process.env, PATH: "", AI_SKILLS_RUNTIME_ROOT: runtimeRoot },
        encoding: "utf8" as const,
        timeout: 10000,
      };
      for (const [args, output] of [
        [["--version"], "fixture-engine 1.2.3\n"],
        [["list"], "fixture-plugin\tfixture-skill\n"],
      ] satisfies [string[], string][]) {
        const result = spawnSync(executable, [entry, ...args], options);
        assert.equal(result.status, 0, result.stderr);
        assert.equal(result.stdout, output);
        assert.equal(result.stderr, "");
      }
      const args = ["install", "space argument", "☃", "--flag=literal", ""];
      const result = spawnSync(executable, [entry, ...args], options);
      assert.equal(result.status, 23);
      assert.deepEqual(JSON.parse(result.stdout), args);
      assert.equal(result.stderr, "fixture stderr\n");
      const signaled = spawnSync(executable, [entry, "self-signal"], options);
      assert.equal(signaled.signal, "SIGTERM");
      for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"] as const) {
        await new Promise<void>((resolveDone, reject) => {
          const child = spawn(executable, [entry, "signal"], options);
          const timer = setTimeout(() => {
            child.kill("SIGKILL");
            reject(new Error("signal forwarding timed out"));
          }, 10000);
          child.once("error", reject);
          let output = "";
          child.stdout.on("data", (chunk: Buffer) => {
            output += chunk.toString();
            if (output === "ready\n") {
              output = "";
              child.kill(signal);
            }
          });
          child.once("close", (_code, received) => {
            clearTimeout(timer);
            try {
              assert.equal(received, signal);
              resolveDone();
            } catch (error) {
              reject(error);
            }
          });
        });
      }
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

if (import.meta.main) {
  await launcherSmoke();
  console.log("Launcher fixture: arguments, streams, status, and signals PASS");
}
