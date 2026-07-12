import { describe, expect, test } from "bun:test";

import { completeInteractively } from "../lib/install.js";
import { KNOWN_AGENTS } from "../lib/ui.js";

/**
 * Build a scripted UI that returns canned answers in order.
 *
 * @param {Array<string | string[] | boolean>} answers - Prompt results.
 * @returns {ReturnType<typeof import("../lib/ui.js").createClackUi>} Mock UI.
 */
function scriptedUi(answers) {
  const queue = [...answers];
  const next = () => {
    if (queue.length === 0) {
      throw new Error("Unexpected prompt");
    }
    return queue.shift();
  };
  return {
    intro() {},
    outro() {},
    note() {},
    isCancel: (value) => value === Symbol.for("clack:cancel"),
    async select() {
      return next();
    },
    async multiselect() {
      return next();
    },
    async confirm() {
      return next();
    },
  };
}

const blankOptions = {
  agents: [],
  bundle: null,
  copy: false,
  global: false,
  onConflict: null,
  project: false,
  skills: [],
  vendor: null,
  yes: false,
};

describe("completeInteractively", () => {
  test("defaults to global scope, symlink, overwrite, and known agents", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi(["bundle:pre-push", KNOWN_AGENTS.map((agent) => agent.value), "global", false]),
    );

    expect(options.bundle).toBe("pre-push");
    expect(options.skills).toEqual(["lint", "test", "greptile", "coderabbit"]);
    expect(options.agents).toEqual(["claude-code", "cursor", "codex"]);
    expect(options.global).toBe(true);
    expect(options.project).toBe(false);
    expect(options.copy).toBe(false);
    expect(options.onConflict).toBe("overwrite");
  });

  test("selects a vendor skill and respects detect-only agent choice", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi(["vendor:anthropics", "pdf", ["__detect__"], "project", false]),
    );

    expect(options.vendor).toBe("anthropics");
    expect(options.skills).toEqual(["pdf"]);
    expect(options.agents).toEqual([]);
    expect(options.project).toBe(true);
    expect(options.global).toBe(false);
  });

  test("offers copy only when advanced options are enabled", async () => {
    const options = await completeInteractively(
      { ...blankOptions },
      scriptedUi(["bundle:git-pr", ["cursor"], "global", true, true]),
    );

    expect(options.agents).toEqual(["cursor"]);
    expect(options.copy).toBe(true);
  });

  test("aborts when the UI reports cancel", async () => {
    await expect(
      completeInteractively({ ...blankOptions }, scriptedUi([Symbol.for("clack:cancel")])),
    ).rejects.toThrow("Install cancelled");
  });
});
