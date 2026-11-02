import { expect, test } from "bun:test";
import { ChildProcess } from "node:child_process";

import { buildSkillsRemoveArguments, runSkills } from "../lib/skills-runner.ts";

test.each([0, 2, null])("legacy skills runner forwards spawn and status %s", async (status) => {
  const calls: unknown[] = [];
  const pending = runSkills(["fixture", "literal argument"], (command, args, options) => {
    calls.push({ command, args, options });
    const child = new ChildProcess();
    queueMicrotask(() => child.emit("exit", status));
    return child;
  });
  if (status === 0) {
    await pending;
  } else {
    await expect(pending).rejects.toThrow(`skills CLI exited with status ${status ?? "unknown"}`);
  }
  expect(calls).toEqual([
    { command: "bunx", args: ["fixture", "literal argument"], options: { stdio: "inherit" } },
  ]);
});

test("legacy skills runner propagates spawn failures", async () => {
  const failure = new Error("fixture spawn failure");
  await expect(
    runSkills([], () => {
      const child = new ChildProcess();
      queueMicrotask(() => child.emit("error", failure));
      return child;
    }),
  ).rejects.toBe(failure);
});

test("legacy skills remove arguments preserve scope, agents and confirmation", () => {
  expect(
    buildSkillsRemoveArguments({ agents: ["cursor", "codex"], global: true, yes: true }, ["lint"]),
  ).toEqual(["skills@^1.5.0", "remove", "lint", "-g", "-a", "cursor", "codex", "-y"]);
  expect(buildSkillsRemoveArguments({ agents: [], global: false, yes: false }, [])).toEqual([
    "skills@^1.5.0",
    "remove",
  ]);
});
