import type { AdapterId, Deviation, SupportReport, SupportRequest } from "./types.ts";

/**
 * Build a support report. The state stays `unverified` unless recorded
 * evidence says otherwise; adapters never upgrade a parity cell here.
 */
export function supportReport(
  adapter: AdapterId,
  request: SupportRequest,
  details: Partial<Pick<SupportReport, "route" | "state" | "lostFields" | "reason">> & {
    deviations?: Deviation[];
  } = {},
): SupportReport {
  const route = details.route ?? "available";
  return {
    adapter,
    host: request.host,
    role: request.role,
    mode: request.mode,
    scope: request.scope,
    route,
    state: details.state ?? (route === "available" ? "unverified" : "adapter-missing"),
    lostFields: details.lostFields ?? [],
    deviations: details.deviations ?? [],
    reason:
      details.reason ??
      (route === "available"
        ? "no current parity evidence is wired into this adapter yet (#585)"
        : null),
  };
}

/**
 * Refuse a request outside the adapter's mode or role, or without a local source.
 */
export function routeGate(
  request: SupportRequest,
  expected: { mode: SupportRequest["mode"]; hosts: readonly string[] },
): string | null {
  if (!expected.hosts.includes(request.host)) {
    return `host ${request.host} is not served by this adapter`;
  }
  if (request.mode !== expected.mode) {
    return `this adapter delivers mode ${expected.mode}, not ${request.mode}`;
  }
  if (request.role !== "skill") {
    return `role ${request.role} has no projection yet (#583)`;
  }
  if (!request.localSource) {
    return (
      "no locally rendered, filtered artifact is available; managed installs never " +
      "fetch a remote source or hand off to the skills CLI"
    );
  }
  return null;
}
