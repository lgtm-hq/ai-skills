import { HOST_DEFINITIONS, defaultHostMode, nativeRoute } from "./hosts.ts";
import type { Mode } from "./types.ts";

const NATIVE: Mode = "native";
const EXPLODE: Mode = "explode";

/**
 * Hosts that can receive a native plugin (tree drop or CLI).
 */
export const NATIVE_PROJECTOR_AGENTS: ReadonlySet<string> = new Set(
  HOST_DEFINITIONS.filter((host) => host.native !== null).map((host) => host.id),
);

/**
 * Default projector when doctor has no cache yet (issue #376).
 *
 * Read from each host definition. Install consults ``sk doctor``'s host cache
 * before this default.
 */
export const DEFAULT_PROJECTOR_BY_AGENT: Readonly<Record<string, Mode>> = Object.fromEntries(
  HOST_DEFINITIONS.map((host) => [host.id, host.defaultMode]),
);

/**
 * Resolve the projector for one agent.
 *
 * Vendor installs are always exploded: native delivery is first-party only.
 *
 * @throws {Error} When `--projector native` is combined with `--vendor`.
 */
export function resolveProjector(
  agent: string,
  override?: Mode | null,
  options: { vendor?: boolean } = {},
): Mode {
  if (options.vendor) {
    if (override === NATIVE) {
      throw new Error(
        "--projector native is first-party only; omit --vendor or use --projector explode",
      );
    }
    return EXPLODE;
  }
  if (override === NATIVE || override === EXPLODE) {
    return override;
  }
  return defaultHostMode(agent);
}

/**
 * Reject native delivery on hosts that cannot load plugins.
 *
 * @throws {Error} When native is requested for an explode-only host.
 */
export function assertProjectorSupported(agent: string, projector: Mode): void {
  if (projector !== NATIVE || nativeRoute(agent) !== null) {
    return;
  }
  throw new Error(
    `Native projector is not supported for agent "${agent}". Use --projector explode.`,
  );
}
