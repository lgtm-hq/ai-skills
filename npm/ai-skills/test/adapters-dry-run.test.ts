import { describe, expect, spyOn, test } from "bun:test";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { AdapterPlan } from "../lib/adapters/types.ts";
import { isAdapterDryRun, runCli } from "../lib/cli.ts";
import { formatPlans } from "../lib/install-plan.ts";
import { dryRunInstall, install } from "../lib/install.ts";
import { PACKAGE_ROOT } from "../lib/paths.ts";

const SNAPSHOT = join(PACKAGE_ROOT, "test/fixtures/install-dry-run.txt");

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
