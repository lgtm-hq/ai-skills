import { getPackageVersion } from "./package-version.ts";

/** Registry document describing the latest published gateway release. */
const REGISTRY_LATEST_URL = "https://registry.npmjs.org/@lgtm-hq/ai-skills/latest";

/** Soft-fail budget for every update-check network request. */
export const DEFAULT_UPDATE_CHECK_TIMEOUT_MS = 1500;

const COMMIT_SHA_PATTERN = /^[0-9a-f]{40}$/;

/**
 * Whether the env opt-out disables network update checks.
 */
export function isUpdateCheckDisabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.AI_SKILLS_NO_UPDATE_CHECK === "1";
}

/**
 * Whether `candidate` is a strictly newer semver than `current`.
 *
 * Unparsable versions compare as not-newer so callers stay silent instead of
 * nagging on malformed data. On equal numeric triples a release counts as newer
 * than a prerelease (`0.17.0` > `0.17.0-dev`), and prereleases compare by
 * SemVer identifier precedence (`0.17.0-beta.2` > `0.17.0-beta.1`).
 */
export function isNewerVersion(candidate: string, current: string): boolean {
  const parsedCandidate = parseSemver(candidate);
  const parsedCurrent = parseSemver(current);
  if (!parsedCandidate || !parsedCurrent) {
    return false;
  }
  for (const part of ["major", "minor", "patch"] as const) {
    if (parsedCandidate[part] !== parsedCurrent[part]) {
      return parsedCandidate[part] > parsedCurrent[part];
    }
  }
  if (parsedCandidate.prerelease === null || parsedCurrent.prerelease === null) {
    return parsedCurrent.prerelease !== null && parsedCandidate.prerelease === null;
  }
  return comparePrereleases(parsedCandidate.prerelease, parsedCurrent.prerelease) > 0;
}

/**
 * Compare two prerelease identifier strings per SemVer precedence (spec item 11).
 *
 * Dot-separated identifiers compare pairwise: numeric identifiers compare
 * numerically and rank below alphanumeric ones; alphanumeric identifiers
 * compare in ASCII order; with all shared identifiers equal, more identifiers
 * ranks higher (`beta.1` > `beta`).
 */
function comparePrereleases(left: string, right: string): number {
  const leftIdentifiers = left.split(".");
  const rightIdentifiers = right.split(".");
  const shared = Math.min(leftIdentifiers.length, rightIdentifiers.length);
  for (let index = 0; index < shared; index += 1) {
    const leftIdentifier = leftIdentifiers[index];
    const rightIdentifier = rightIdentifiers[index];
    if (leftIdentifier === rightIdentifier) {
      continue;
    }
    const leftIsNumeric = /^\d+$/.test(leftIdentifier!);
    const rightIsNumeric = /^\d+$/.test(rightIdentifier!);
    if (leftIsNumeric && rightIsNumeric) {
      return Number(leftIdentifier) - Number(rightIdentifier);
    }
    if (leftIsNumeric !== rightIsNumeric) {
      return leftIsNumeric ? -1 : 1;
    }
    return leftIdentifier! < rightIdentifier! ? -1 : 1;
  }
  return leftIdentifiers.length - rightIdentifiers.length;
}

/**
 * Check the npm registry for a newer gateway release (soft-fail).
 */
export async function checkGatewayUpdate(
  dependencies: UpdateCheckDependencies & { currentVersion?: string } = {},
): Promise<{ current: string; latest: string } | null> {
  if (isUpdateCheckDisabled(dependencies.env)) {
    return null;
  }
  const current = dependencies.currentVersion ?? getPackageVersion();
  const document = await fetchJson(REGISTRY_LATEST_URL, dependencies);
  const latest = document && typeof document.version === "string" ? document.version : null;
  if (!latest || !isNewerVersion(latest, current)) {
    return null;
  }
  return { current, latest };
}

/**
 * Check SHA-pinned vendors for upstream commits beyond the baked pin (soft-fail).
 *
 * Fetches every vendor's default-branch head concurrently and compares it to the
 * pinned SHA. Any per-vendor error or timeout silently drops that vendor.
 */
export async function checkVendorDrift(
  vendors: Array<{ id: string; repo: string; sha: string }>,
  dependencies: UpdateCheckDependencies = {},
): Promise<Set<string>> {
  const drifted: Set<string> = new Set();
  if (isUpdateCheckDisabled(dependencies.env)) {
    return drifted;
  }
  const pinned = vendors.filter((vendor) => COMMIT_SHA_PATTERN.test(vendor.sha));
  await Promise.all(
    pinned.map(async (vendor) => {
      const commit = await fetchJson(
        `https://api.github.com/repos/${vendor.repo}/commits/HEAD`,
        dependencies,
      );
      if (commit && typeof commit.sha === "string" && commit.sha !== vendor.sha) {
        drifted.add(vendor.id);
      }
    }),
  );
  return drifted;
}

/**
 * Compare lockfile pins against the running package's baked catalog (pure/local).
 *
 * First-party entries drift when their recorded tag differs from the running
 * package version; vendor entries drift when the baked registry re-pinned the
 * vendor to a different SHA. Entries for unknown vendors are left unmarked.
 */
export function checkSkillDrift(
  lock: { plugins: Record<string, import("./lockfile.ts").PluginLockEntry> },
  catalog: { vendors: Array<{ id: string; sha: string }>; packageVersion?: string },
): Set<string> {
  const packageVersion = catalog.packageVersion ?? getPackageVersion();
  const pins = new Map(catalog.vendors.map((vendor) => [vendor.id, vendor.sha]));

  const drifted: Set<string> = new Set();
  for (const [name, entry] of Object.entries(lock.plugins ?? {})) {
    if (entry.vendor === "lgtm-hq") {
      if (entry.sha !== `v${packageVersion}`) {
        drifted.add(name);
      }
      continue;
    }
    const pin = pins.get(entry.vendor);
    if (pin !== undefined && pin !== entry.sha) {
      drifted.add(name);
    }
  }
  return drifted;
}

/**
 * Fetch JSON with an abort-plus-race timeout, soft-failing to null.
 *
 * Races the timeout even when the injected fetch ignores abort signals so the
 * wizard is never blocked beyond the budget.
 */
async function fetchJson(
  url: string,
  dependencies: UpdateCheckDependencies,
): Promise<Record<string, unknown> | null> {
  const fetchImplementation = dependencies.fetchImplementation ?? fetch;
  const timeoutMs = dependencies.timeoutMs ?? DEFAULT_UPDATE_CHECK_TIMEOUT_MS;
  const controller = new AbortController();

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const timeout = new Promise<null>((resolve) => {
      timer = setTimeout(() => {
        controller.abort();
        resolve(null);
      }, timeoutMs);
    });
    // Swallow late rejections so a request losing the race cannot surface as an
    // unhandled rejection after the timeout already resolved null.
    const request = (async () => {
      const response = await fetchImplementation(url, {
        headers: { accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        return null;
      }
      return response.json() as Promise<Record<string, unknown> | null>;
    })().catch(() => null);
    return await Promise.race([timeout, request]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Parse a lenient semver string.
 */
function parseSemver(
  version: string,
): { major: number; minor: number; patch: number; prerelease: string | null } | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(
    typeof version === "string" ? version.trim() : "",
  );
  if (!match) {
    return null;
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ?? null,
  };
}

/** Injectable network/env dependencies shared by the update checks. */
export interface UpdateCheckDependencies {
  env?: NodeJS.ProcessEnv;
  fetchImplementation?: FetchImplementation;
  timeoutMs?: number;
}

export type FetchImplementation = (
  url: string | URL | Request,
  init?: RequestInit,
) => Promise<{ ok: boolean; json: () => Promise<unknown> }>;
