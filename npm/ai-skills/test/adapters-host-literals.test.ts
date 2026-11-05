import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { hostIds } from "../lib/adapters/hosts.ts";
import { PACKAGE_ROOT } from "../lib/paths.ts";

const LIB = join(PACKAGE_ROOT, "lib");
const HOST_IDS = ["claude-code", "codex", "copilot", "cursor"];

/**
 * Host-specific constructs core code must not contain: a quoted host ID, a
 * property or path segment named after a host (`.cursor`, `agents?.codex`,
 * `.claude/skills`), or an object key naming a host.
 */
function hostViolations(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
  const ids = HOST_IDS.join("|");
  const patterns = [
    new RegExp(`["'\`](?:${ids})["'\`]`, "g"),
    new RegExp(`\\.(?:${ids}|claude)\\b(?![-\\w])`, "g"),
    new RegExp(`(?:^|[{,\\s])(?:${ids.replace("claude-code|", "")})\\s*:`, "gm"),
  ];
  return patterns.flatMap((pattern) => [...code.matchAll(pattern)].map((match) => match[0].trim()));
}

function coreFiles(dir: string = LIB): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return relative(LIB, path) === "adapters" ? [] : coreFiles(path);
    }
    return path.endsWith(".ts") ? [path] : [];
  });
}

describe("host literal guard", () => {
  test("the guard covers every registered host", () => {
    expect([...hostIds()].sort()).toEqual(HOST_IDS);
  });

  test.each([
    ['if (agent === "cursor") {', '"cursor"'],
    ["const cli = { copilot: 'copilot' };", "copilot:"],
    ["existing?.agents?.codex", ".codex"],
    ['join(home, ".claude", "skills")', ".claude"],
    ["roots[`claude-code`]", "`claude-code`"],
  ])("flags host-specific core code: %s", (snippet, expected) => {
    expect(hostViolations(snippet)).toContain(expected);
  });

  test.each([
    'join(root, ".claude-plugin", "marketplace.json")',
    "// Cursor native trees are dropped by an adapter",
    "const cursorDestHasFiles = true;",
    'nativeRoute(agent)?.kind === "tree"',
  ])("leaves host-neutral code alone: %s", (snippet) => {
    expect(hostViolations(snippet)).toEqual([]);
  });

  test("no file outside lib/adapters/ names a host or branches on one", () => {
    const files = coreFiles();
    expect(files.length).toBeGreaterThan(10);
    const offenders = files.flatMap((path) =>
      hostViolations(readFileSync(path, "utf8")).map(
        (match) => `${relative(PACKAGE_ROOT, path)}: ${match}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
