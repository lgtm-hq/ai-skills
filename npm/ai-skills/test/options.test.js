import { describe, expect, test } from "bun:test";

import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "../lib/options.js";

describe("parseArguments", () => {
  test("defaults to the install command", () => {
    expect(parseArguments(["--global", "--bundle", "review"])).toEqual({
      command: "install",
      options: {
        agents: [],
        bundle: "review",
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
    ]);

    expect(() => validateUnattendedOptions(parsed.options)).not.toThrow();
  });

  test("rejects unsupported conflict policies that upstream cannot honor", () => {
    const parsed = parseArguments([
      "-y",
      "--global",
      "-a",
      "cursor",
      "--bundle",
      "review",
      "--on-conflict",
      "skip",
    ]);

    expect(() => validateUnattendedOptions(parsed.options)).toThrow(
      "--on-conflict=skip is unsupported",
    );
  });

  test("allows overwrite or omitted conflict policy", () => {
    const omitted = parseArguments(["-y", "--global", "-a", "cursor", "--bundle", "review"]);
    const overwrite = parseArguments([
      "-y",
      "--global",
      "-a",
      "cursor",
      "--bundle",
      "review",
      "--on-conflict",
      "overwrite",
    ]);

    expect(() => validateUnattendedOptions(omitted.options)).not.toThrow();
    expect(() => validateUnattendedOptions(overwrite.options)).not.toThrow();
  });

  test("rejects competing scopes", () => {
    expect(() => parseArguments(["--global", "--project"])).toThrow("Choose only one scope");
  });

  test("rejects competing sources", () => {
    expect(() => parseArguments(["--vendor", "anthropics", "--bundle", "review"])).toThrow(
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
