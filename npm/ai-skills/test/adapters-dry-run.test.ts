import { describe, expect, spyOn, test } from "bun:test";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as childProcess from "node:child_process";

import type { AdapterPlan } from "../lib/adapters/types.ts";
import { UNMANAGED_HANDOFF_LABEL } from "../lib/skills-runner.ts";
import bundleCatalog from "../data/bundles.json" with { type: "json" };
import { isAdapterDryRun, runCli } from "../lib/cli.ts";
import { formatPlans } from "../lib/install-plan.ts";
import { dryRunInstall, install } from "../lib/install.ts";
import { PACKAGE_ROOT } from "../lib/paths.ts";

const SNAPSHOT = join(PACKAGE_ROOT, "test/fixtures/install-dry-run.txt");
const reviewSkills = bundleCatalog.groups.review.skills;

async function listTree(root: string): Promise<string[]> {
  return (await readdir(root, { recursive: true })).map(String).sort();
}

async function composed(home: string, cwd: string, catalog: string): Promise<string> {
  const plans: AdapterPlan[] = [];
  await install(
    {
      agents: ["claude-code", "codex", "copilot", "cursor"],
      bundle: null,
      copy: false,
      global: true,
      onConflict: null,
      project: false,
      projector: null,
      skills: ["lint", "test"],
      vendor: null,
      yes: true,
    },
    async () => {
      throw new Error("a dry run never calls the skills CLI");
    },
    undefined,
    { cwd, home },
    {
      dryRun: (items) => plans.push(...items),
      exec: async () => {
        throw new Error("a dry run never executes a host CLI");
      },
      sourceRoot: catalog,
    },
  );
  return formatPlans(plans, { cwd, home });
}

describe("install --dry-run", () => {
  test("prints a deterministic composed adapter plan without writing", async () => {
    const outputs: string[] = [];
    for (let run = 0; run < 2; run += 1) {
      const home = await mkdtemp(join(tmpdir(), "ai-skills-dry-home-"));
      const cwd = await mkdtemp(join(tmpdir(), "ai-skills-dry-cwd-"));
      try {
        const catalog = join(cwd, "catalog");
        for (const name of ["lint", "test"]) {
          await mkdir(join(catalog, "skills", name), { recursive: true });
          await writeFile(join(catalog, "skills", name, "SKILL.md"), `# ${name}\n`);
        }
        const before = [await listTree(home), await listTree(cwd)];
        outputs.push(await composed(home, cwd, catalog));
        expect([await listTree(home), await listTree(cwd)]).toEqual(before);
      } finally {
        await rm(home, { force: true, recursive: true });
        await rm(cwd, { force: true, recursive: true });
      }
    }
    expect(outputs[1]).toBe(outputs[0]!);
    expect(`${outputs[0]}\n`).toBe(await readFile(SNAPSHOT, "utf8"));
  });

  test("needs a named agent", async () => {
    await expect(
      dryRunInstall({
        agents: [],
        bundle: "review",
        copy: false,
        global: true,
        onConflict: null,
        project: false,
        skills: [],
        vendor: null,
        yes: false,
      }),
    ).rejects.toThrow("needs at least one -a/--agent");
  });

  test("--unmanaged --dry-run prints the handoff and never runs the skills CLI", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-dry-unmanaged-"));
    const executed: string[][] = [];
    const run = async (args: string[]) => {
      executed.splice(executed.length, 0, args);
    };
    const unmanaged = {
      agents: ["codex"],
      bundle: null,
      copy: false,
      global: false,
      onConflict: null,
      project: true,
      skills: ["lint"],
      unmanaged: true,
      vendor: null,
      yes: true,
    };
    try {
      const composed: Array<string[] | undefined> = [];
      await install(
        unmanaged,
        run,
        undefined,
        { cwd, home: cwd },
        {
          dryRun: (_plans, handoff) => composed.splice(composed.length, 0, handoff),
        },
      );
      expect(executed).toEqual([]);
      expect(composed).toEqual([
        [
          "skills@^1.5.0",
          "add",
          "lgtm-hq/ai-skills@v0.0.0-dev",
          "-a",
          "codex",
          "--skill",
          "lint",
          "-y",
        ],
      ]);

      // Without a dry run the explicit handoff still executes.
      const warnings: string[] = [];
      await install(
        unmanaged,
        run,
        undefined,
        { cwd, home: cwd },
        {
          warn: (message) => warnings.splice(warnings.length, 0, message),
        },
      );
      expect(executed).toEqual(composed as string[][]);
      expect(warnings).toEqual([UNMANAGED_HANDOFF_LABEL]);
      expect(await listTree(cwd)).toEqual([]);
    } finally {
      await rm(cwd, { force: true, recursive: true });
    }
  });

  test("runCli install --dry-run --unmanaged prints the command without running it", async () => {
    const lines: string[] = [];
    const log = spyOn(console, "log").mockImplementation((line: string) => {
      lines.splice(lines.length, 0, line);
    });
    const spawn = spyOn(childProcess, "spawn").mockImplementation((() => {
      throw new Error("a dry run must not spawn the skills CLI");
    }) as never);
    try {
      await runCli([
        "install",
        "--dry-run",
        "--unmanaged",
        "-y",
        "--project",
        "--bundle",
        "review",
      ]);
    } finally {
      log.mockRestore();
      spawn.mockRestore();
    }
    expect(lines.join("\n")).toBe(
      `${UNMANAGED_HANDOFF_LABEL}\n` +
        "handoff\tunmanaged\tbunx skills@^1.5.0 add lgtm-hq/ai-skills@v0.0.0-dev --skill " +
        `${reviewSkills.join(" ")} -y\tnot executed (dry run)`,
    );
  });

  test("is the launcher's own plan only without other artifact options", () => {
    expect(isAdapterDryRun("install", ["--dry-run"], {})).toBe(true);
    expect(isAdapterDryRun("install", ["--dry-run", "--json"], {})).toBe(false);
    expect(isAdapterDryRun("install", ["--dry-run"], { AI_SKILLS_ARTIFACTS: "/a" })).toBe(false);
    expect(isAdapterDryRun("update", ["--dry-run"], {})).toBe(false);
  });

  test("runCli prints the plan for a named plugin", async () => {
    const cwd = await mkdtemp(join(tmpdir(), "ai-skills-dry-cli-"));
    const previous = process.cwd();
    const lines: string[] = [];
    const log = spyOn(console, "log").mockImplementation((line: string) => {
      lines.splice(lines.length, 0, line);
    });
    try {
      process.chdir(cwd);
      await runCli(["install", "--dry-run", "-a", "codex", "--bundle", "review", "--project"]);
      expect(await listTree(cwd)).toEqual([]);
    } finally {
      log.mockRestore();
      process.chdir(previous);
      await rm(cwd, { force: true, recursive: true });
    }
    expect(lines.join("\n")).toStartWith(
      "plan\treview\tcodex\tskill-explode\texplode\tproject\trecovery=reversible",
    );
  });
});
