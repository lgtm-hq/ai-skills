import { describe, expect, test } from "bun:test";

import { parseArguments, validateUnattendedOptions } from "../lib/options.js";

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
});
