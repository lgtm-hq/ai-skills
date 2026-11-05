import { dirname, join } from "node:path";

import { verifyPlanOps } from "../execute.ts";
import { copyTreeOps, existsNoFollow, ownedPathHash } from "../fs.ts";
import { findHost, hostIds } from "../hosts.ts";
import { routeGate, supportReport } from "../support.ts";
import type { AdapterPlan, DestinationAdapter, Op, PlanInput, SupportRequest } from "../types.ts";
import { planExplode } from "./skill-explode.ts";

/**
 * Directory a scope's paths hang from.
 */
function scopeBase(input: Pick<PlanInput, "env" | "scope">): string {
  return input.scope === "project" ? input.env.cwd : input.env.home;
}

const EXPLODE_HOSTS = hostIds();

/**
 * Support for one explode cell.
 */
function explodeSupport(request: SupportRequest) {
  const reason = routeGate(request, { hosts: EXPLODE_HOSTS, mode: "explode" });
  return supportReport("skill-explode", request, reason ? { route: "unavailable", reason } : {});
}

/**
 * Skill-directory explode for every registered host's skills directory plus
 * the shared `.agents/skills` store, in symlink or copy mode.
 *
 * `plan()` runs the same decision function as the transactional engine
 * (`planExplode`), so collisions, identical-dest skips and store reuse are
 * decided once. Ops mirror the engine's commit: a replaced dest or store is
 * a hash-checked `remove-owned`, copies are `mkdir`/`write-file`/`symlink`
 * with symlink targets kept verbatim, and store mode links the dest to the store.
 */
export const skillExplodeAdapter: DestinationAdapter = {
  id: "skill-explode",
  hosts: EXPLODE_HOSTS,
  mode: "explode",
  opKinds: ["mkdir", "write-file", "symlink", "remove-owned"],
  hostExec: [],
  recovery: "reversible",
  support: explodeSupport,
  async plan(input: PlanInput): Promise<AdapterPlan> {
    const support = explodeSupport({ ...input, localSource: true });
    if (support.route === "unavailable") {
      throw new Error(`skill-explode cannot plan ${input.host}: ${support.reason}`);
    }
    const base = scopeBase(input);
    const root = join(base, findHost(input.host)!.skillDir);
    const storeRoot = input.options?.storeRoot ?? join(base, ".agents", "skills");
    const copy = Boolean(input.options?.copy);
    const sourceSkills = Object.fromEntries(
      input.kept.skills.map((skill) => [skill.name, skill.source]),
    );
    const decisions = await planExplode({
      agents: [{ copy, id: input.host, replace: new Set(input.owned), root }],
      copy,
      destRoots: input.options?.destRoots ?? [],
      fs: input.fs,
      retainStoreSkills: new Set(input.options?.retainStoreSkills ?? []),
      skills: input.kept.skills.map((skill) => skill.name),
      sourceSkills,
      storeRoot,
    });
    const ops: Op[] = [];
    const writtenStores = new Set<string>();
    for (const item of decisions.toWrite) {
      const source = sourceSkills[item.skill]!;
      if (await existsNoFollow(input.fs, item.dest)) {
        ops.push({
          kind: "remove-owned",
          path: item.dest,
          expectHash: await ownedPathHash(input.fs, item.dest),
        });
      }
      if (item.copy) {
        ops.push(...(await copyTreeOps(input.fs, source, item.dest)));
        continue;
      }
      if (!writtenStores.has(item.storeDir)) {
        const storeExists = await existsNoFollow(input.fs, item.storeDir);
        if (storeExists && item.replace) {
          ops.push({
            kind: "remove-owned",
            path: item.storeDir,
            expectHash: await ownedPathHash(input.fs, item.storeDir),
          });
        }
        if (!storeExists || item.replace) {
          ops.push(...(await copyTreeOps(input.fs, source, item.storeDir)));
        }
        writtenStores.add(item.storeDir);
      }
      ops.push({ kind: "mkdir", path: dirname(item.dest) });
      ops.push({ kind: "symlink", path: item.dest, target: item.storeDir });
    }
    return {
      adapter: "skill-explode",
      host: input.host,
      role: input.role,
      mode: input.mode,
      scope: input.scope,
      pluginId: input.kept.pluginId,
      recovery: "reversible",
      roots: copy ? [root] : [root, storeRoot],
      ops,
      support,
      notes: decisions.skipped.map(
        (item) => `skipped identical ${item.dest} (not claiming ${item.skill} on ${item.agent})`,
      ),
      owns: { files: { ...decisions.claimed[input.host] }, root },
    };
  },
  verify(plan, env) {
    return verifyPlanOps(plan, env.fs);
  },
};
