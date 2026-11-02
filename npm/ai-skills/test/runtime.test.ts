import { expect, test } from "bun:test";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { findPackageRoot, PACKAGE_ROOT } from "../lib/paths.ts";
import { resolvePackagedRuntime, RUNTIME_TARGETS, runPackagedRuntime } from "../lib/runtime.ts";
import { createRuntimeFixture, launcherSmoke } from "../scripts/launcher-smoke.ts";

test("launcher forwards real payload arguments, streams, signals and status", launcherSmoke, 30000);

test("packaged runtime selection covers every supported target and fails closed", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-skills-targets-"));
  try {
    for (const target of RUNTIME_TARGETS) {
      const [os, arch] = target.split("-");
      const platform = os === "windows" ? "win32" : os!;
      const bundle = join(root, target);
      const interpreter =
        platform === "win32"
          ? join(bundle, "python/python.exe")
          : join(bundle, "python/bin/python3");
      await mkdir(resolve(interpreter, ".."), { recursive: true });
      await mkdir(join(bundle, "engine"));
      await writeFile(interpreter, "fixture");
      await writeFile(join(bundle, "engine/__main__.py"), "fixture");
      expect(
        resolvePackagedRuntime({ env: { AI_SKILLS_RUNTIME_ROOT: root }, platform, arch: arch! }),
      ).toEqual({ interpreter, entryPoint: join(bundle, "engine/__main__.py") });
    }
    expect(() =>
      resolvePackagedRuntime({
        env: { AI_SKILLS_RUNTIME_ROOT: root },
        platform: "freebsd",
        arch: "x64",
      }),
    ).toThrow("Unsupported");
    expect(() =>
      resolvePackagedRuntime({ env: { AI_SKILLS_RUNTIME_ROOT: join(root, "absent") } }),
    ).toThrow("incomplete");
    expect(findPackageRoot()).toBe(PACKAGE_ROOT);
    expect(() => findPackageRoot(pathToFileURL(join(root, "absent.ts")).href)).toThrow(
      "Cannot locate",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("runtime completion and spawn errors clean up forwarding listeners", async () => {
  const { root, runtimeRoot } = await createRuntimeFixture();
  const before = process.listenerCount("SIGTERM");
  const priorExitCode = process.exitCode;
  try {
    const runtime = resolvePackagedRuntime({ env: { AI_SKILLS_RUNTIME_ROOT: runtimeRoot } })!;
    await runPackagedRuntime(runtime, ["--version"]);
    expect(process.exitCode).toBe(0);
    expect(process.listenerCount("SIGTERM")).toBe(before);
    await expect(
      runPackagedRuntime({ interpreter: join(root, "absent"), entryPoint: "absent" }, []),
    ).rejects.toThrow();
    expect(process.listenerCount("SIGTERM")).toBe(before);
  } finally {
    process.exitCode = priorExitCode;
    await rm(root, { force: true, recursive: true });
  }
});
