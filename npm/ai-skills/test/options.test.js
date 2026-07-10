import { describe, expect, test } from "bun:test";

import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "../lib/options.js";

describe("parseArguments", () => {
  test("defaults to the install command", () => {
    expect(parseArguments(["--global", "--bundle", "pre-push"])).toEqual({
      command: "install",
      options: {
        agents: [],
        bundle: "pre-push",
        copy: false,
        global: true,
        onConflict: null,
        project: false,
        skills: [],
        vendor: null,
        yes: false,
      },
    });
  });

  test("accepts an unattended vendor install", () => {
    const parsed = parseArguments([
      "install",
      "-y",
      "--project",
      "-a",
      "cursor",
      "--vendor",
      "anthropics",
      "--skill",
      "pdf",
      "--on-conflict",
      "skip",
    ]);

    expect(() => validateUnattendedOptions(parsed.options)).not.toThrow();
  });

  test("fails closed for unattended conflict decisions", () => {
    const parsed = parseArguments(["-y", "--global", "-a", "cursor", "--bundle", "pre-push"]);

    expect(() => validateUnattendedOptions(parsed.options)).toThrow("-y requires --on-conflict");
  });

  test("rejects competing scopes", () => {
    expect(() => parseArguments(["--global", "--project"])).toThrow("Choose only one scope");
  });

  test("rejects competing sources", () => {
    expect(() => parseArguments(["--vendor", "anthropics", "--bundle", "pre-push"])).toThrow(
      "Choose only one source",
    );
  });

  test("accepts a scoped unattended update", () => {
    const parsed = parseArguments(["update", "-y", "--project", "-a", "cursor"]);

    expect(parsed.command).toBe("update");
    expect(() => validateUnattendedCommandOptions(parsed.options)).not.toThrow();
  });

  test("rejects an unattended remove without an agent", () => {
    const parsed = parseArguments(["remove", "-y", "--global", "--skill", "lint"]);

    expect(() => validateUnattendedCommandOptions(parsed.options)).toThrow(
      "-y requires at least one",
    );
  });

  test("allows unattended list without agents", () => {
    const parsed = parseArguments(["list", "-y", "--global"]);

    expect(() =>
      validateUnattendedCommandOptions(parsed.options, { requireAgents: false }),
    ).not.toThrow();
  });
});
