import { describe, expect, test } from "bun:test";

import { ADAPTERS, adapterFor, assertBuiltinPlan } from "../lib/adapters/index.ts";
import {
  AdapterRegistrationError,
  BUILTIN_ADAPTER_IDS,
  assertPlanConforms,
  createRegistry,
} from "../lib/adapters/registry.ts";
import type { RegistrationRule } from "../lib/adapters/registry.ts";
import type { AdapterPlan, DestinationAdapter, Op } from "../lib/adapters/types.ts";

/** A well-formed adapter; each malformed fixture breaks exactly one rule. */
function adapter(overrides: Partial<Record<keyof DestinationAdapter, unknown>> = {}) {
  return {
    hostExec: [],
    hosts: ["codex"],
    id: "skill-explode",
    mode: "explode",
    opKinds: ["mkdir", "write-file"],
    plan: async () => {
      throw new Error("not planned in registry tests");
    },
    recovery: "reversible",
    support: () => {
      throw new Error("not called");
    },
    verify: async () => ({ ok: true, problems: [], unverified: [] }),
    ...overrides,
  } as unknown as DestinationAdapter;
}

const MALFORMED: Array<[RegistrationRule, string, () => DestinationAdapter]> = [
  ["shape", "is missing plan()", () => adapter({ plan: undefined })],
  ["unknown-host", "targets an unregistered host", () => adapter({ hosts: ["notepad"] })],
  ["unknown-host", "declares no hosts", () => adapter({ hosts: [] })],
  [
    "unknown-op-kind",
    "declares an op kind outside the union",
    () => adapter({ opKinds: ["mkdir", "chmod"] }),
  ],
  [
    "undeclared-host-exec",
    "emits host-exec without declaring steps",
    () => adapter({ opKinds: ["host-exec"], recovery: "compensating" }),
  ],
  [
    "undeclared-host-exec",
    "declares steps it never emits",
    () => adapter({ hostExec: [{ compensated: true, id: "install" }], recovery: "compensating" }),
  ],
  [
    "uncompensated-host-exec",
    "has an uncompensated step without disclosure",
    () =>
      adapter({
        hostExec: [{ compensated: false, id: "register" }],
        opKinds: ["host-exec"],
        recovery: "compensating",
      }),
  ],
  ["recovery", "declares an unknown recovery guarantee", () => adapter({ recovery: "eventual" })],
  [
    "recovery",
    "claims reversible recovery while running host CLIs",
    () => adapter({ hostExec: [{ compensated: true, id: "install" }], opKinds: ["host-exec"] }),
  ],
];

describe("adapter registration", () => {
  test.each(MALFORMED)("rejects (%s) an adapter that %s", (rule, _why, fixture) => {
    const registry = createRegistry();
    let caught: unknown;
    try {
      registry.register(fixture());
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(AdapterRegistrationError);
    expect((caught as AdapterRegistrationError).rule).toBe(rule);
    expect(registry.list()).toEqual([]);
  });

  test("rejects (duplicate-id) a second adapter with a registered id", () => {
    const registry = createRegistry();
    registry.register(adapter());
    let caught: unknown;
    try {
      registry.register(adapter({ hosts: ["cursor"] }));
    } catch (error) {
      caught = error;
    }
    expect((caught as AdapterRegistrationError).rule).toBe("duplicate-id");
    expect(registry.list()).toHaveLength(1);
  });

  test("accepts an uncompensated step that discloses its irreversible effect", () => {
    const registry = createRegistry();
    registry.register(
      adapter({
        hostExec: [{ compensated: false, id: "register", irreversible: "stays registered" }],
        opKinds: ["host-exec"],
        recovery: "irreversible",
      }),
    );
    expect(registry.get("skill-explode")?.recovery).toBe("irreversible");
  });

  test("registers every built-in adapter through the same validation", () => {
    expect(
      ADAPTERS.list()
        .map((item) => item.id)
        .sort(),
    ).toEqual([...BUILTIN_ADAPTER_IDS].sort());
    expect(adapterFor("cursor", "native").id).toBe("cursor-drop");
    expect(adapterFor("claude-code", "native").id).toBe("claude-cli");
    expect(adapterFor("copilot", "native").id).toBe("copilot-cli");
    expect(adapterFor("codex", "explode").id).toBe("skill-explode");
    expect(() => adapterFor("codex", "native")).toThrow("No native adapter");
  });
});

describe("plan conformance", () => {
  const plan = (ops: Op[], adapterId: AdapterPlan["adapter"] = "claude-cli"): AdapterPlan =>
    ({ adapter: adapterId, host: "claude-code", ops }) as unknown as AdapterPlan;
  const exec = (step: string, compensate: string[] | null): Op => ({
    argv: ["claude", "plugin", "install", "x@ai-skills"],
    compensate,
    kind: "host-exec",
    step,
  });

  test("accepts a plan that follows the declared steps", () => {
    expect(() =>
      assertBuiltinPlan(
        plan([exec("marketplace-add", null), exec("plugin-install", ["claude", "uninstall"])]),
      ),
    ).not.toThrow();
  });

  test.each([
    ["an undeclared step", [exec("marketplace-remove", ["x"])], "undeclared host-exec step"],
    ["a dropped compensation", [exec("plugin-install", null)], "does not match"],
    ["an invented compensation", [exec("marketplace-add", ["x"])], "does not match"],
  ])("rejects %s", (_name, ops, message) => {
    expect(() => assertBuiltinPlan(plan(ops as Op[]))).toThrow(message);
  });

  test("rejects an op kind the adapter did not declare", () => {
    const registry = createRegistry();
    registry.register(adapter());
    const symlink: Op = { kind: "symlink", path: "/x", target: "/y" };
    expect(() =>
      assertPlanConforms(registry, {
        ...plan([symlink], "skill-explode"),
        host: "codex",
      }),
    ).toThrow("undeclared op symlink");
  });

  test("rejects a plan for an unregistered adapter or undeclared host", () => {
    const registry = createRegistry();
    expect(() => assertPlanConforms(registry, plan([], "skill-explode"))).toThrow("unregistered");
    registry.register(adapter());
    expect(() => assertPlanConforms(registry, plan([], "skill-explode"))).toThrow(
      "undeclared host claude-code",
    );
  });
});
