import { isKnownHost, nativeRoute } from "./hosts.ts";
import { OP_KINDS } from "./types.ts";
import type { AdapterId, AdapterPlan, DestinationAdapter, Mode, OpKind } from "./types.ts";

const RECOVERY = new Set(["reversible", "compensating", "irreversible"]);
const MODES = new Set(["native", "explode"]);

/** Registration-time contract rule an adapter broke. */
export type RegistrationRule =
  | "shape"
  | "duplicate-id"
  | "unknown-host"
  | "unknown-op-kind"
  | "undeclared-host-exec"
  | "uncompensated-host-exec"
  | "recovery";

/**
 * An adapter failed registration-time validation.
 */
export class AdapterRegistrationError extends Error {
  readonly rule: RegistrationRule;

  constructor(rule: RegistrationRule, message: string) {
    super(`Adapter registration rejected (${rule}): ${message}`);
    this.name = "AdapterRegistrationError";
    this.rule = rule;
  }
}

/** A set of validated adapters. */
export interface AdapterRegistry {
  register(adapter: DestinationAdapter): DestinationAdapter;
  get(id: string): DestinationAdapter | undefined;
  forHost(host: string, mode: Mode): DestinationAdapter | undefined;
  list(): DestinationAdapter[];
}

/**
 * Create an empty registry. The gateway's built-in registry lives in
 * `index.ts`; tests create their own so fixtures never leak.
 */
export function createRegistry(): AdapterRegistry {
  const adapters: Map<string, DestinationAdapter> = new Map();
  return {
    register(adapter) {
      validateAdapter(adapter, adapters);
      adapters.set(adapter.id, Object.freeze(adapter));
      return adapter;
    },
    get(id) {
      return adapters.get(id);
    },
    forHost(host, mode) {
      // A host's native route names its adapter; otherwise use whichever
      // registered adapter serves this host and mode.
      const serves = (adapter: DestinationAdapter | undefined) =>
        adapter !== undefined && adapter.mode === mode && adapter.hosts.includes(host);
      const routed = mode === "native" ? adapters.get(nativeRoute(host)?.adapter ?? "") : undefined;
      return serves(routed) ? routed : [...adapters.values()].find(serves);
    },
    list() {
      return [...adapters.values()];
    },
  };
}

/**
 * The adapter `registry` uses to deliver `mode` to `host`.
 *
 * @throws {Error} When no registered adapter serves that host and mode.
 */
export function resolveAdapter(
  registry: AdapterRegistry,
  host: string,
  mode: Mode,
): DestinationAdapter {
  const adapter = registry.forHost(host, mode);
  if (!adapter) {
    throw new Error(`No ${mode} adapter is registered for host ${host}`);
  }
  return adapter;
}

/**
 * Validate the adapter contract before an adapter can plan anything.
 *
 * @throws {AdapterRegistrationError} Naming the first broken rule.
 */
function validateAdapter(
  adapter: DestinationAdapter,
  registered: ReadonlyMap<string, DestinationAdapter>,
): void {
  const candidate = adapter as Partial<DestinationAdapter> | null;
  if (
    !candidate ||
    typeof candidate.id !== "string" ||
    (candidate.id as string) === "" ||
    !Array.isArray(candidate.hosts) ||
    !Array.isArray(candidate.opKinds) ||
    !Array.isArray(candidate.hostExec) ||
    !MODES.has(candidate.mode as string) ||
    typeof candidate.support !== "function" ||
    typeof candidate.plan !== "function" ||
    typeof candidate.verify !== "function"
  ) {
    throw new AdapterRegistrationError(
      "shape",
      "an adapter needs id, hosts, mode, opKinds, hostExec, support(), plan() and verify()",
    );
  }
  if (registered.has(adapter.id)) {
    throw new AdapterRegistrationError("duplicate-id", `${adapter.id} is already registered`);
  }
  const unknownHost = adapter.hosts.find((host) => !isKnownHost(host));
  if (adapter.hosts.length === 0 || unknownHost !== undefined) {
    throw new AdapterRegistrationError(
      "unknown-host",
      `${adapter.id} names unknown host ${JSON.stringify(unknownHost ?? null)}`,
    );
  }
  const unknownKind = adapter.opKinds.find(
    (kind) => !(OP_KINDS as readonly string[]).includes(kind),
  );
  if (unknownKind !== undefined) {
    throw new AdapterRegistrationError(
      "unknown-op-kind",
      `${adapter.id} declares op kind ${JSON.stringify(unknownKind)}`,
    );
  }
  if (!RECOVERY.has(adapter.recovery)) {
    throw new AdapterRegistrationError(
      "recovery",
      `${adapter.id} declares recovery ${JSON.stringify(adapter.recovery)}`,
    );
  }
  const execKind: OpKind = "host-exec";
  const declaresExec = adapter.opKinds.includes(execKind);
  if (declaresExec !== adapter.hostExec.length > 0) {
    throw new AdapterRegistrationError(
      "undeclared-host-exec",
      `${adapter.id} must declare its host-exec steps exactly when it emits host-exec`,
    );
  }
  const silent = adapter.hostExec.find((step) => !step.compensated && !step.irreversible);
  if (silent) {
    throw new AdapterRegistrationError(
      "uncompensated-host-exec",
      `${adapter.id} step ${silent.id} has no compensation and no irreversible disclosure`,
    );
  }
  if (declaresExec && adapter.recovery === "reversible") {
    throw new AdapterRegistrationError(
      "recovery",
      `${adapter.id} runs host CLIs, so it can only promise compensating or irreversible recovery`,
    );
  }
}

/**
 * Check a plan against its adapter's declared contract before any write.
 *
 * @throws {Error} When the plan uses an undeclared op kind or host-exec step,
 *   or an uncompensated host-exec that its step does not disclose.
 */
export function assertPlanConforms(registry: AdapterRegistry, plan: AdapterPlan): void {
  const adapter = registry.get(plan.adapter);
  if (!adapter) {
    throw new Error(`Plan names unregistered adapter ${plan.adapter}`);
  }
  if (!adapter.hosts.includes(plan.host)) {
    throw new Error(`${plan.adapter} plan targets undeclared host ${plan.host}`);
  }
  const steps = new Map(adapter.hostExec.map((step) => [step.id, step]));
  for (const op of plan.ops) {
    if (!adapter.opKinds.includes(op.kind)) {
      throw new Error(`${plan.adapter} plan uses undeclared op ${op.kind}`);
    }
    if (op.kind !== "host-exec") {
      continue;
    }
    const step = steps.get(op.step);
    if (!step) {
      throw new Error(`${plan.adapter} plan uses undeclared host-exec step ${op.step}`);
    }
    if (step.compensated !== (op.compensate !== null)) {
      throw new Error(`${plan.adapter} host-exec ${op.step} does not match its declared recovery`);
    }
  }
}

/** Adapter IDs the gateway ships, for exhaustiveness checks. */
export const BUILTIN_ADAPTER_IDS: readonly AdapterId[] = [
  "claude-cli",
  "copilot-cli",
  "cursor-drop",
  "skill-explode",
];
