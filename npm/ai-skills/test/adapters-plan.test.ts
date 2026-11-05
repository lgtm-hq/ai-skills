import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import * as childProcess from "node:child_process";
import * as fsPromises from "node:fs/promises";

import { claudeCliAdapter } from "../lib/adapters/claude-code/cli.ts";
import { copilotCliAdapter } from "../lib/adapters/copilot/cli.ts";
import { cursorDropAdapter } from "../lib/adapters/cursor/drop-adapter.ts";
import { assertBuiltinPlan } from "../lib/adapters/index.ts";
import { skillExplodeAdapter } from "../lib/adapters/shared/skill-explode-adapter.ts";
import type { AdapterPlan, PlanInput, SupportRequest } from "../lib/adapters/types.ts";
import { memoryFs } from "./fixtures/memory-fs.ts";
import type { MemoryNode } from "./fixtures/memory-fs.ts";

const HOME = "/virtual/home";
const CWD = "/virtual/repo";
const CATALOG = "/virtual/catalog/skills";

const catalog: Record<string, MemoryNode> = {
  [`${CATALOG}/lint/SKILL.md`]: "# lint\n",
  [`${CATALOG}/lint/docs/guide.md`]: "guide\n",
  [`${CATALOG}/lint/GUIDE.md`]: { link: "docs/guide.md" },
  [`${CATALOG}/test/SKILL.md`]: "# test\n",
};

function input(host: string, overrides: Partial<PlanInput> = {}, extra = {}): PlanInput {
  return {
    env: { cwd: CWD, home: HOME },
    fs: memoryFs({ ...catalog, ...extra }),
    host,
    kept: {
      description: "Review",
      pluginId: "review",
      skills: ["lint", "test"].map((name) => ({ name, source: `${CATALOG}/${name}` })),
      version: "1.2.3",
    },
    mode: "explode",
    owned: [],
    role: "skill",
    scope: "global",
    ...overrides,
  };
}

const summarize = (plan: AdapterPlan) =>
  plan.ops.map((op) =>
    op.kind === "host-exec"
      ? `${op.kind} ${op.argv.join(" ")}`
      : `${op.kind} ${op.path}${op.kind === "symlink" ? ` -> ${op.target}` : ""}`,
  );

describe("plan() purity", () => {
  const spies: Array<{ mockRestore(): void }> = [];
  beforeEach(() => {
    // Every real fs and process entry point throws: plans read only through input.fs.
    for (const name of Object.keys(fsPromises) as Array<keyof typeof fsPromises>) {
      if (typeof fsPromises[name] === "function") {
        spies.push(
          spyOn(fsPromises, name).mockImplementation((() => {
            throw new Error(`plan() called fs.${String(name)}`);
          }) as never),
        );
      }
    }
    for (const name of ["spawn", "spawnSync", "exec", "execFile", "execSync"] as const) {
      spies.push(
        spyOn(childProcess, name).mockImplementation((() => {
          throw new Error(`plan() executed ${name}`);
        }) as never),
      );
    }
    spies.push(
      spyOn(Bun, "spawn").mockImplementation((() => {
        throw new Error("plan() executed Bun.spawn");
      }) as never),
    );
  });
  afterEach(() => {
    for (const spy of spies.splice(0)) {
      spy.mockRestore();
    }
  });

  test("the harness blocks real filesystem and process access", async () => {
    expect(() => fsPromises.writeFile("/tmp/never", "x")).toThrow("plan() called fs.writeFile");
    expect(() => fsPromises.lstat("/tmp")).toThrow("plan() called fs.lstat");
    expect(() => childProcess.spawn("true")).toThrow("plan() executed spawn");
    const view = memoryFs({});
    expect(() => (view as unknown as { writeFile: unknown }).writeFile).toThrow(
      "non-read filesystem method writeFile",
    );
  });

  test("skill-explode plans store writes and dest symlinks from the read-only view", async () => {
    const plan = await skillExplodeAdapter.plan(input("codex"));
    assertBuiltinPlan(plan);
    expect(plan.roots).toEqual([`${HOME}/.codex/skills`, `${HOME}/.agents/skills`]);
    expect(summarize(plan)).toEqual([
      `mkdir ${HOME}/.agents/skills/lint`,
      `symlink ${HOME}/.agents/skills/lint/GUIDE.md -> docs/guide.md`,
      `write-file ${HOME}/.agents/skills/lint/SKILL.md`,
      `mkdir ${HOME}/.agents/skills/lint/docs`,
      `write-file ${HOME}/.agents/skills/lint/docs/guide.md`,
      `mkdir ${HOME}/.codex/skills`,
      `symlink ${HOME}/.codex/skills/lint -> ${HOME}/.agents/skills/lint`,
      `mkdir ${HOME}/.agents/skills/test`,
      `write-file ${HOME}/.agents/skills/test/SKILL.md`,
      `mkdir ${HOME}/.codex/skills`,
      `symlink ${HOME}/.codex/skills/test -> ${HOME}/.agents/skills/test`,
    ]);
  });

  test("skill-explode replaces an owned copy-mode dest with a hash-checked remove", async () => {
    const plan = await skillExplodeAdapter.plan(
      input(
        "cursor",
        { options: { copy: true }, owned: ["lint"], scope: "project" },
        {
          [`${CWD}/.cursor/skills/lint/SKILL.md`]: "# old lint\n",
        },
      ),
    );
    expect(plan.roots).toEqual([`${CWD}/.cursor/skills`]);
    expect(summarize(plan).slice(0, 2)).toEqual([
      `remove-owned ${CWD}/.cursor/skills/lint`,
      `mkdir ${CWD}/.cursor/skills/lint`,
    ]);
    const removal = plan.ops[0]!;
    expect(removal.kind === "remove-owned" && removal.expectHash.startsWith("tree:")).toBe(true);
  });

  test("skill-explode skips a byte-identical unowned dest and notes it", async () => {
    const plan = await skillExplodeAdapter.plan(
      input("codex", {}, { [`${HOME}/.codex/skills/test/SKILL.md`]: "# test\n" }),
    );
    expect(summarize(plan).some((line) => line.includes("/test"))).toBe(false);
    expect(plan.notes).toEqual([
      `skipped identical ${HOME}/.codex/skills/test (not claiming test on codex)`,
    ]);
  });

  test("skill-explode refuses a colliding dest before anything is written", async () => {
    await expect(
      skillExplodeAdapter.plan(
        input("codex", {}, { [`${HOME}/.codex/skills/lint/SKILL.md`]: "# someone else\n" }),
      ),
    ).rejects.toThrow("Explode collision");
  });

  test("cursor-drop replaces owned skills and leaves untracked files alone", async () => {
    const root = `${HOME}/.cursor/plugins/local/review`;
    const plan = await cursorDropAdapter.plan(
      input(
        "cursor",
        { mode: "native", owned: ["lint", "retired"] },
        {
          [`${root}/skills/retired/SKILL.md`]: "# retired\n",
          [`${root}/skills/lint/SKILL.md`]: "# old lint\n",
          [`${root}/NOTES.md`]: "mine\n",
        },
      ),
    );
    assertBuiltinPlan(plan);
    expect(plan.roots).toEqual([root]);
    const lines = summarize(plan);
    expect(lines[0]).toBe(`remove-owned ${root}/skills/retired/SKILL.md`);
    expect(lines).toContain(`write-file ${root}/skills/lint/SKILL.md`);
    expect(lines).toContain(`write-file ${root}/.claude-plugin/plugin.json`);
    expect(lines.some((line) => line.includes("NOTES.md"))).toBe(false);
  });

  test("cursor-drop refuses an unowned, non-empty plugin directory", async () => {
    await expect(
      cursorDropAdapter.plan(
        input(
          "cursor",
          { mode: "native" },
          {
            [`${HOME}/.cursor/plugins/local/review/README.md`]: "someone else\n",
          },
        ),
      ),
    ).rejects.toThrow("Refusing to overwrite unowned Cursor plugin");
  });

  test.each([
    [claudeCliAdapter, "claude-code", "claude"],
    [copilotCliAdapter, "copilot", "copilot"],
  ] as const)(
    "%#: CLI adapters render a local envelope and register only that directory",
    async (adapter, host, binary) => {
      const plan = await adapter.plan(input(host, { mode: "native" }));
      assertBuiltinPlan(plan);
      const envelope = `${HOME}/.ai-skills/native/${host}`;
      expect(plan.roots).toEqual([envelope]);
      const execs = plan.ops.filter((op) => op.kind === "host-exec");
      expect(execs.map((op) => op.argv)).toEqual([
        [binary, "plugin", "marketplace", "add", envelope],
        [binary, "plugin", "install", "review@ai-skills"],
      ]);
      // No marketplace argument names a remote owner/repo source.
      for (const op of execs) {
        for (const argument of op.argv.slice(3)) {
          expect(argument).not.toMatch(/^[\w.-]+\/[\w.-]+(@.*)?$/);
          expect(argument).not.toMatch(/^(https?|git|ssh):/);
        }
      }
      const written = summarize(plan).filter((line) => line.startsWith("write-file"));
      expect(written).toEqual([
        `write-file ${envelope}/.claude-plugin/marketplace.json`,
        `write-file ${envelope}/review/.claude-plugin/plugin.json`,
        `write-file ${envelope}/review/skills/lint/SKILL.md`,
        `write-file ${envelope}/review/skills/lint/docs/guide.md`,
        `write-file ${envelope}/review/skills/test/SKILL.md`,
      ]);
      const marketplace = plan.ops.find(
        (op) => op.kind === "write-file" && op.path.endsWith("marketplace.json"),
      );
      expect(
        JSON.parse(
          new TextDecoder().decode(
            marketplace?.kind === "write-file" ? marketplace.content : undefined,
          ),
        ),
      ).toEqual({
        name: "ai-skills",
        owner: { name: "lgtm-hq" },
        plugins: [{ description: "Review", name: "review", source: "./review", version: "1.2.3" }],
      });
    },
  );

  test("CLI envelopes keep other plugins listed and drop this plugin's stale files", async () => {
    const envelope = `${HOME}/.ai-skills/native/claude-code`;
    const plan = await claudeCliAdapter.plan(
      input(
        "claude-code",
        { mode: "native" },
        {
          [`${envelope}/.claude-plugin/marketplace.json`]: JSON.stringify({
            plugins: [{ name: "git-pr", source: "./git-pr" }, { name: "review" }],
          }),
          [`${envelope}/review/skills/retired/SKILL.md`]: "# retired\n",
        },
      ),
    );
    expect(summarize(plan)[0]).toBe(`remove-owned ${envelope}/review/skills/retired/SKILL.md`);
    const index = plan.ops.find(
      (op) => op.kind === "write-file" && op.path.endsWith("marketplace.json"),
    );
    const parsed = JSON.parse(
      new TextDecoder().decode(index?.kind === "write-file" ? index.content : undefined),
    );
    expect(parsed.plugins.map((plugin: { name: string }) => plugin.name)).toEqual([
      "git-pr",
      "review",
    ]);
  });
});

describe("support reports", () => {
  const request = (host: string, overrides: Partial<SupportRequest> = {}): SupportRequest => ({
    host,
    localSource: true,
    mode: "native",
    role: "skill",
    scope: "global",
    ...overrides,
  });
  const ids = (adapter: typeof claudeCliAdapter, req: SupportRequest) =>
    adapter.support(req).deviations.map((deviation) => deviation.id);

  test("record the known CLI deviations as data", () => {
    expect(ids(claudeCliAdapter, request("claude-code", { scope: "project" }))).toEqual([
      "cli-user-scope",
      "existing-marketplace-kept",
    ]);
    expect(ids(copilotCliAdapter, request("copilot"))).toEqual([
      "cli-user-scope",
      "existing-marketplace-kept",
      "source-tag-stripped",
    ]);
    for (const deviation of copilotCliAdapter.support(request("copilot")).deviations) {
      expect(deviation.issue).toBe("#584");
    }
  });

  test("record the unverified Cursor project path and its observed state", () => {
    const project = cursorDropAdapter.support(request("cursor", { scope: "project" }));
    expect(project.deviations.map((deviation) => deviation.id)).toEqual([
      "cursor-project-path-unverified",
    ]);
    expect(project.state).toBe("adapter-missing");
    expect(project.route).toBe("available");
    const user = cursorDropAdapter.support(request("cursor"));
    expect(user).toMatchObject({ deviations: [], route: "available", state: "unverified" });
  });

  test("make native unavailable without a local artifact instead of using a remote source", () => {
    for (const [adapter, host] of [
      [claudeCliAdapter, "claude-code"],
      [copilotCliAdapter, "copilot"],
      [cursorDropAdapter, "cursor"],
    ] as const) {
      const report = adapter.support(request(host, { localSource: false }));
      expect(report.route).toBe("unavailable");
      expect(report.reason).toContain("never fetch a remote source");
    }
  });

  test("refuse other modes, roles and hosts", () => {
    expect(skillExplodeAdapter.support(request("codex")).reason).toContain("mode explode");
    expect(
      skillExplodeAdapter.support(request("codex", { mode: "explode", role: "workflow" })).reason,
    ).toContain("#583");
    expect(claudeCliAdapter.support(request("cursor")).route).toBe("unavailable");
    expect(skillExplodeAdapter.support(request("codex", { mode: "explode" })).route).toBe(
      "available",
    );
  });
});
