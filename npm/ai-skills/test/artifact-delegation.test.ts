import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { cp, mkdir, mkdtemp, realpath, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";

import { delegateArtifactCommand } from "../lib/install.ts";
import { CHECKOUT_ROOT, PACKAGE_ROOT } from "../lib/paths.ts";
import type { PackagedRuntime } from "../lib/runtime.ts";

// The launcher must reproduce the engine's result byte for byte; the expected
// kept sets are the same builder-recorded golden the pytest suite asserts.
const GOLDEN = join(CHECKOUT_ROOT, "tests/fixtures/artifacts/golden");
const EXPECTED: {
  cases: {
    name: string;
    exclude: string[];
    deny: string[];
    kept?: { capabilities: string[]; resources: string[] };
    error?: { chain: string; suggest: string[] };
  }[];
} = JSON.parse(
  readFileSync(join(CHECKOUT_ROOT, "tests/fixtures/install/expected-kept.json"), "utf8"),
);

interface Engine {
  root: string;
  python: string;
  env: Record<string, string>;
  work: string;
}

let engine: Engine;

/** Stage the real engine as the bundled payload, with no PATH and a fake home. */
async function stageEngine(): Promise<Engine> {
  const venv = join(
    CHECKOUT_ROOT,
    ".venv",
    ...(process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python3"]),
  );
  if (!existsSync(venv)) {
    throw new Error(`Run \`uv sync\` first: the engine test needs ${venv}`);
  }
  const purelib = spawnSync(
    venv,
    ["-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
    {
      encoding: "utf8",
    },
  ).stdout.trim();
  const root = await mkdtemp(join(tmpdir(), "ai-skills-engine-"));
  const target = `${process.platform === "win32" ? "windows" : process.platform}-${process.arch}`;
  const bundle = join(root, "payloads", target);
  const python =
    process.platform === "win32"
      ? join(bundle, "python", "python.exe")
      : join(bundle, "python", "bin", "python3");
  await mkdir(join(python, ".."), { recursive: true });
  await symlink(await realpath(venv), python);
  await mkdir(join(bundle, "engine"));
  await cp(join(PACKAGE_ROOT, "test/fixtures/engine-entry.py"), join(bundle, "engine/__main__.py"));
  const home = join(root, "home");
  const work = join(root, "work");
  await mkdir(home);
  await mkdir(work);
  return {
    root,
    python,
    work,
    env: {
      PATH: "",
      HOME: home,
      AI_SKILLS_RUNTIME_ROOT: join(root, "payloads"),
      AI_SKILLS_NO_UPDATE_CHECK: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONPATH: [join(CHECKOUT_ROOT, "src"), purelib].join(delimiter),
    },
  };
}

/** Run one entry point and capture the full process contract. */
function invoke(argv: string[], env: Record<string, string> = engine.env) {
  const result = spawnSync(argv[0]!, argv.slice(1), {
    cwd: engine.work,
    env,
    encoding: "utf8",
    timeout: 30000,
  });
  return { status: result.status, stdout: result.stdout, stderr: result.stderr };
}

beforeAll(async () => {
  engine = await stageEngine();
});

afterAll(async () => {
  await rm(engine.root, { recursive: true, force: true });
});

describe("artifact install delegation", () => {
  for (const item of EXPECTED.cases) {
    test(`launcher preserves the engine result: ${item.name}`, () => {
      const flags = [
        ...item.exclude.flatMap((value) => ["--exclude", value]),
        ...item.deny.flatMap((value) => ["--deny-origin", value]),
      ];
      const args = ["--artifacts", GOLDEN, "--dry-run", "--json", ...flags];
      const direct = invoke([engine.python, "-m", "ai_skills_engine", "install", ...args]);
      const launcher = invoke([
        process.execPath,
        join(PACKAGE_ROOT, "bin/skill.ts"),
        "install",
        ...args,
      ]);
      // The parsed CLI path normalizes an implicit install before forwarding.
      const parsed = invoke([
        process.execPath,
        join(PACKAGE_ROOT, "test/fixtures/run-cli.ts"),
        ...args,
      ]);
      expect(launcher).toEqual(direct);
      expect(parsed).toEqual(direct);
      if (item.kept) {
        expect(direct.status).toBe(0);
        expect(JSON.parse(direct.stdout).kept).toEqual(item.kept);
      } else {
        expect(direct.status).toBe(1);
        expect(direct.stderr).toContain(item.error!.chain);
        for (const suggestion of item.error!.suggest) {
          expect(direct.stderr).toContain(`--exclude ${suggestion}`);
        }
      }
    }, 30000);
  }

  test("digest mismatch exits nonzero through the launcher with nothing written", async () => {
    const corrupt = join(engine.root, "corrupt");
    await cp(GOLDEN, corrupt, { recursive: true });
    await cp(join(GOLDEN, "index.json"), join(corrupt, "fixture--tools.tar"));
    const args = ["install", "--artifacts", corrupt, "--exclude", "package:fixture/tools"];
    const direct = invoke([engine.python, "-m", "ai_skills_engine", ...args]);
    const launcher = invoke([process.execPath, join(PACKAGE_ROOT, "bin/skill.ts"), ...args]);
    expect(launcher).toEqual(direct);
    expect(direct.status).toBe(1);
    expect(direct.stderr).toContain("fixture/tools: digest mismatch: sidecar pin");
    expect(existsSync(join(engine.env.HOME!, ".config"))).toBe(false);
  }, 30000);

  test("without a bundled engine the parsed CLI refuses instead of filtering", () => {
    // No payload override and no packaged data/runtime: the legacy CLI runs.
    const env = Object.fromEntries(
      Object.entries(engine.env).filter(([key]) => key !== "AI_SKILLS_RUNTIME_ROOT"),
    );
    const result = invoke(
      [process.execPath, join(PACKAGE_ROOT, "bin/skill.ts"), "--exclude", "package:a/b"],
      env,
    );
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("evaluated by the bundled ai-skills engine");
    expect(result.stdout).toBe("");
  });

  test("delegation forwards argv unchanged to the resolved runtime", async () => {
    const runtime: PackagedRuntime = { interpreter: "python", entryPoint: "engine" };
    const calls: [PackagedRuntime, string[]][] = [];
    const argv = ["install", "--exclude", "capability:a/b:skill/c", "☃", ""];
    await delegateArtifactCommand(argv, {
      resolveRuntime: () => runtime,
      run: async (selected, forwarded) => {
        calls.push([selected, forwarded]);
      },
    });
    expect(calls).toEqual([[runtime, argv]]);
    await expect(delegateArtifactCommand(argv, { resolveRuntime: () => null })).rejects.toThrow(
      "does not include",
    );
  });
});
