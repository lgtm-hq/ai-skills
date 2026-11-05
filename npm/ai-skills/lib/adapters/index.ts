import { claudeCliAdapter } from "./claude-code/cli.ts";
import { copilotCliAdapter } from "./copilot/cli.ts";
import { cursorDropAdapter } from "./cursor/drop-adapter.ts";
import { assertPlanConforms, createRegistry, resolveAdapter } from "./registry.ts";
import { skillExplodeAdapter } from "./shared/skill-explode-adapter.ts";
import type { AdapterPlan, DestinationAdapter, Mode } from "./types.ts";

/**
 * The gateway's adapter registry. Every built-in adapter passes the same
 * registration-time validation a third-party adapter would.
 */
export const ADAPTERS = createRegistry();
for (const adapter of [
  claudeCliAdapter,
  copilotCliAdapter,
  cursorDropAdapter,
  skillExplodeAdapter,
]) {
  ADAPTERS.register(adapter);
}

/**
 * The registered adapter delivering `mode` to `host`.
 *
 * @throws {Error} When no adapter serves that host and mode.
 */
export function adapterFor(host: string, mode: Mode): DestinationAdapter {
  return resolveAdapter(ADAPTERS, host, mode);
}

/**
 * Validate a plan against the built-in registry.
 *
 * @throws {Error} When the plan breaks its adapter's declared contract.
 */
export function assertBuiltinPlan(plan: AdapterPlan): void {
  assertPlanConforms(ADAPTERS, plan);
}
