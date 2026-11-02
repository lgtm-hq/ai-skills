import { PROJECTOR_EXPLODE, PROJECTOR_NATIVE } from "../lockfile.ts";

/**
 * Hosts that can receive a native plugin (tree drop or CLI).
 */
export const NATIVE_PROJECTOR_AGENTS = new Set(["claude-code", "copilot", "cursor"]);

/**
 * Default projector when doctor has no cache yet (issue #376).
 *
 * Cursor drops a local plugin tree. Claude Code and Copilot install through
 * their plugin CLIs. Codex has no native plugin host, so it stays exploded.
 * Install consults ``sk doctor``'s host cache before this default.
 */
export const DEFAULT_PROJECTOR_BY_AGENT: Record<string, "native" | "explode"> = {
  "claude-code": PROJECTOR_NATIVE,
  copilot: PROJECTOR_NATIVE,
  cursor: PROJECTOR_NATIVE,
  codex: PROJECTOR_EXPLODE,
};

/**
 * Resolve the projector for one agent.
 *
 * Vendor installs are always exploded: native delivery is first-party only.
 *
 * @throws {Error} When `--projector native` is combined with `--vendor`.
 */
export function resolveProjector(
  agent: string,
  override?: "native" | "explode" | null,
  options: { vendor?: boolean } = {},
): "native" | "explode" {
  if (options.vendor) {
    if (override === PROJECTOR_NATIVE) {
      throw new Error(
        "--projector native is first-party only; omit --vendor or use --projector explode",
      );
    }
    return PROJECTOR_EXPLODE;
  }
  if (override === PROJECTOR_NATIVE || override === PROJECTOR_EXPLODE) {
    return override;
  }
  return DEFAULT_PROJECTOR_BY_AGENT[agent] ?? PROJECTOR_EXPLODE;
}

/**
 * Reject native delivery on hosts that cannot load plugins.
 *
 * @throws {Error} When native is requested for an explode-only host.
 */
export function assertProjectorSupported(agent: string, projector: "native" | "explode"): void {
  if (projector !== PROJECTOR_NATIVE) {
    return;
  }
  if (NATIVE_PROJECTOR_AGENTS.has(agent)) {
    return;
  }
  throw new Error(
    `Native projector is not supported for agent "${agent}". Use --projector explode.`,
  );
}
