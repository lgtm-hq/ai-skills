import { CLAUDE_CODE_HOST } from "./claude-code/host.ts";
import { CODEX_HOST } from "./codex/host.ts";
import { COPILOT_HOST } from "./copilot/host.ts";
import { CURSOR_HOST } from "./cursor/host.ts";
import type { HostDefinition, Mode, NativeRoute, Scope } from "./types.ts";
import { join } from "node:path";

/**
 * Host table, in interactive display order.
 *
 * This is the only place host IDs, skill directories, CLI binaries and labels
 * are enumerated; core modules read them through the helpers below. The module
 * is a leaf (no gateway imports) so `lockfile.ts` can use it without a cycle.
 */
export const HOST_DEFINITIONS: readonly HostDefinition[] = Object.freeze([
  CLAUDE_CODE_HOST,
  CURSOR_HOST,
  CODEX_HOST,
  COPILOT_HOST,
]);

const BY_ID: ReadonlyMap<string, HostDefinition> = new Map(
  HOST_DEFINITIONS.map((host) => [host.id, host]),
);

/**
 * Known host IDs in display order.
 */
export function hostIds(): string[] {
  return HOST_DEFINITIONS.map((host) => host.id);
}

/**
 * Whether `id` names a registered host.
 */
export function isKnownHost(id: unknown): id is string {
  return typeof id === "string" && BY_ID.has(id);
}

/**
 * Host definition, or undefined for an unknown ID.
 */
export function findHost(id: string): HostDefinition | undefined {
  return BY_ID.get(id);
}

/**
 * Exploded skills directory per host, relative to the scope base.
 */
export function hostSkillPaths(): Record<string, string> {
  return Object.fromEntries(HOST_DEFINITIONS.map((host) => [host.id, host.skillDir]));
}

/**
 * Native route for a host, or null when the host is explode-only or unknown.
 */
export function nativeRoute(id: string): NativeRoute | null {
  return BY_ID.get(id)?.native ?? null;
}

/**
 * Hosts that can receive a native plugin, sorted.
 */
export function nativeHostIds(): string[] {
  return HOST_DEFINITIONS.filter((host) => host.native !== null)
    .map((host) => host.id)
    .sort();
}

/**
 * Projector a host uses when neither the lock nor doctor decides.
 */
export function defaultHostMode(id: string): Mode {
  return BY_ID.get(id)?.defaultMode ?? "explode";
}

/**
 * Hosts whose native route drops a local plugin tree.
 */
export function treeHostIds(): string[] {
  return HOST_DEFINITIONS.filter((host) => host.native?.kind === "tree").map((host) => host.id);
}

/**
 * Local plugin-tree root for a tree host, or null for other hosts.
 */
export function hostPluginsRoot(
  id: string,
  environment: { cwd: string; home: string; scope: Scope },
): string | null {
  const route = nativeRoute(id);
  if (route?.kind !== "tree") {
    return null;
  }
  const base = environment.scope === "project" ? environment.cwd : environment.home;
  return join(base, route.pluginsDir);
}
