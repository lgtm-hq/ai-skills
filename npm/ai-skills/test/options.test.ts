import { describe, expect, test } from "bun:test";

import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "../lib/options.ts";

describe("parseArguments", () => {
  test("defaults to the install command", () => {
    expect(parseArguments(["--global", "--bundle", "review"])).toEqual({
      command: "install",
      options: {
        agents: [],
        bundle: "review",
        copy: false,
        engine: [],
        global: true,
        migrate: null,
        onConflict: null,
        project: false,
        projector: null,
        repair: false,
        skills: [],
        vendor: null,
        yes: false,
      },
    });
  });

  test("accepts an unattended vendor plugin install", () => {
    const parsed = parseArguments([
      "install",
      "-y",
      "--project",
      "-a",
      "cursor",
      "--vendor",
      "anthropics",
    ]);

    expect(() => validateUnattendedOptions(parsed.options)).not.toThrow();
  });

  test("rejects cherry-picking skills from a vendor plugin", () => {
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

    expect(() => validateUnattendedOptions(parsed.options)).toThrow("plugin-atomic");
  });

  test("accepts an unattended first-party plugin id via --skill", () => {
    const parsed = parseArguments(["-y", "--global", "-a", "cursor", "--skill", "review"]);

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

  test("rejects an unknown agent id before install", () => {
    expect(() => parseArguments(["-y", "--global", "-a", "notepad"])).toThrow("Unknown agent");
  });

  test("accepts --projector native or explode", () => {
    expect(parseArguments(["--projector", "native"]).options.projector).toBe("native");
    expect(parseArguments(["--projector", "explode"]).options.projector).toBe("explode");
  });

  test("rejects an unknown --projector value", () => {
    expect(() => parseArguments(["--projector", "both"])).toThrow(
      "--projector must be native or explode",
    );
  });

  test("rejects native projector with a vendor source", () => {
    expect(() => parseArguments(["--vendor", "anthropics", "--projector", "native"])).toThrow(
      "first-party only",
    );
  });

  test("rejects --projector on update", () => {
    expect(() => parseArguments(["update", "--projector", "explode"])).toThrow(
      "does not accept install source options",
    );
  });

  test("accepts copilot as a known agent", () => {
    expect(parseArguments(["-a", "copilot"]).options.agents).toEqual(["copilot"]);
  });

  test("accepts doctor with --repair or --migrate", () => {
    expect(parseArguments(["doctor", "--repair", "-y", "--global"]).options.repair).toBe(true);
    expect(
      parseArguments(["doctor", "--migrate", "cursor", "-y", "--project"]).options.migrate,
    ).toBe("cursor");
  });

  test("rejects --repair on install", () => {
    expect(() => parseArguments(["install", "--repair"])).toThrow("doctor-only");
  });

  test("rejects --migrate on install", () => {
    expect(() => parseArguments(["install", "--migrate", "cursor"])).toThrow("doctor-only");
    expect(() => parseArguments(["--migrate", "cursor"])).toThrow("doctor-only");
  });

  test("allows unattended doctor without agents", () => {
    const parsed = parseArguments(["doctor", "-y", "--global", "--repair"]);
    expect(() =>
      validateUnattendedCommandOptions(parsed.options, { requireAgents: false }),
    ).not.toThrow();
  });

  test("rejects --migrate on an unknown host", () => {
    expect(() => parseArguments(["doctor", "--migrate", "notepad"])).toThrow("Unknown agent");
  });

  test("rejects inherited names as --migrate hosts", () => {
    expect(() => parseArguments(["doctor", "--migrate", "constructor"])).toThrow("Unknown agent");
  });

  test("rejects install source options and skills on doctor", () => {
    expect(() => parseArguments(["doctor", "--vendor", "vercel-labs"])).toThrow(
      "does not accept install source options",
    );
    expect(() => parseArguments(["doctor", "--skill", "review"])).toThrow(
      "doctor does not accept --skill",
    );
  });

  test("rejects --migrate without an agent", () => {
    expect(() => parseArguments(["doctor", "--migrate"])).toThrow(
      "--migrate requires an agent name",
    );
  });
});

describe("engine-owned artifact options", () => {
  test("collects artifact options verbatim for the bundled engine", () => {
    const parsed = parseArguments([
      "install",
      "--exclude",
      "capability:lgtm-hq/other:skill/jira",
      "--deny-origin",
      "github.com/example/vendor-x",
      "-a",
      "codex",
      "-y",
      "--global",
      "--frozen",
    ]);
    expect(parsed.options.engine).toEqual([
      "--exclude",
      "capability:lgtm-hq/other:skill/jira",
      "--deny-origin",
      "github.com/example/vendor-x",
      "--frozen",
    ]);
    expect(parsed.options.agents).toEqual(["codex"]);
  });

  test("leaves selector semantics to the engine", () => {
    // The launcher checks arity only; the engine rejects the unknown kind.
    expect(parseArguments(["--exclude", "skill:anything"]).options.engine).toEqual([
      "--exclude",
      "skill:anything",
    ]);
  });

  test("update forwards pins and frozen but not new selectors", () => {
    const parsed = parseArguments(["update", "--frozen", "--digest", "sha256:ab", "--json"]);
    expect(parsed.options.engine).toEqual(["--frozen", "--digest", "sha256:ab", "--json"]);
    expect(() => parseArguments(["update", "--exclude", "package:a/b"])).toThrow(
      "--exclude applies only to install; update replays the profile",
    );
  });

  test("rejects missing values and other commands", () => {
    expect(() => parseArguments(["install", "--deny-origin"])).toThrow(
      "--deny-origin requires a value",
    );
    expect(() => parseArguments(["install", "--artifacts", ""])).toThrow(
      "--artifacts requires a value",
    );
    expect(() => parseArguments(["list", "--frozen"])).toThrow(
      "--frozen applies only to install and update",
    );
  });
});
