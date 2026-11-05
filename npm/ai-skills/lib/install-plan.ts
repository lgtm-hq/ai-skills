import { readDoctorCache } from "./doctor.ts";
import { adapterFor, assertBuiltinPlan } from "./adapters/index.ts";
import { applyPlan } from "./adapters/execute.ts";
import type { ExecuteOptions, Transaction } from "./adapters/execute.ts";
import { nodeReadOnlyFs } from "./adapters/fs.ts";
import { destUsesCopyMaterialization } from "./adapters/shared/skill-explode.ts";
import type { AdapterPlan, KeptSet, Mode, Op, PlanInput, ReadOnlyFs } from "./adapters/types.ts";
import {
  agentProjector,
  agentSkillsRoot,
  PROJECTOR_EXPLODE,
  PROJECTOR_NATIVE,
  skillNamesFromFiles,
} from "./lockfile.ts";
import type { PluginLockEntry } from "./lockfile.ts";

/**
 * Everything an install decided before its first write: the lanes, the kept
 * set's local sources and the roots each adapter plans against.
 */
export interface InstallComposition {
  copy: boolean;
  description: string;
  destRoots: string[];
  env: { cwd: string; home: string };
  existing: PluginLockEntry | undefined;
  lanes: { cliNative: string[]; explode: string[]; treeNative: string[] };
  pluginId: string;
  retainStoreSkills: string[];
  scope: "global" | "project";
  skills: string[];
  sources: { explode: Record<string, string> | null; native: Record<string, string> | null };
  storeRoot: string;
  version: string;
}

/**
 * Compose every lane's adapter plan without writing or executing anything.
 *
 * `install --dry-run` prints this. Each plan is validated against its
 * adapter's registered contract.
 */
export async function composeInstallPlans(
  composition: InstallComposition,
  fs: ReadOnlyFs = nodeReadOnlyFs,
): Promise<AdapterPlan[]> {
  const plans: AdapterPlan[] = [];
  for (const agent of composition.lanes.explode) {
    const root = agentSkillsRoot(composition.scope, agent, composition.env);
    const owned = ownedSkills(composition.existing, agent);
    const copy =
      composition.copy ||
      (await destUsesCopyMaterialization(root, [...new Set([...composition.skills, ...owned])]));
    plans.push(
      await planLane(composition, agent, PROJECTOR_EXPLODE, fs, {
        copy,
        destRoots: composition.destRoots,
        retainStoreSkills: composition.retainStoreSkills,
        storeRoot: composition.storeRoot,
      }),
    );
  }
  for (const agent of [...composition.lanes.treeNative, ...composition.lanes.cliNative]) {
    plans.push(
      await planLane(composition, agent, PROJECTOR_NATIVE, fs, {
        replace: lockedNative(composition.existing, agent),
      }),
    );
  }
  return plans;
}

/**
 * Plan and apply one CLI-native lane through the executor.
 *
 * The returned transaction keeps its undo log until the caller commits it
 * (after the gateway lock write) or rolls it back.
 */
export async function applyCliLane(
  composition: InstallComposition,
  agent: string,
  options: Pick<ExecuteOptions, "exec">,
): Promise<Transaction> {
  const plan = await planLane(composition, agent, PROJECTOR_NATIVE, nodeReadOnlyFs, {});
  return applyPlan(plan, { exec: options.exec });
}

/**
 * Commit applied transactions after ownership is recorded; warn, never throw.
 */
export async function finishTransactions(
  transactions: Transaction[],
  warn: (message: string) => void,
): Promise<void> {
  for (const transaction of transactions) {
    try {
      await transaction.commit();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      warn(`Warning: could not discard native envelope backups (${detail})`);
    }
  }
}

/**
 * Roll back applied transactions newest first, returning undo failures.
 */
export async function undoTransactions(transactions: Transaction[]): Promise<unknown[]> {
  const failures: unknown[] = [];
  for (const transaction of [...transactions].reverse()) {
    try {
      await transaction.rollback();
    } catch (error) {
      failures.push(error);
    }
  }
  return failures;
}

/**
 * Doctor-cache capabilities without probing or writing (dry runs).
 */
export async function cachedCapabilities(
  agents: string[],
  existing: PluginLockEntry | undefined,
  provided: Record<string, Mode> = {},
  home: string,
): Promise<Record<string, Mode>> {
  const cache = await readDoctorCache({ home });
  const capabilities: Record<string, Mode> = { ...provided };
  for (const agent of agents) {
    const cached = cache.hosts[agent]?.capability;
    if (!capabilities[agent] && !existing?.agents?.[agent] && cached) {
      capabilities[agent] = cached;
    }
  }
  return capabilities;
}

/**
 * Deterministic text rendering of composed plans.
 *
 * Paths under the install's home or working directory print as `~` and `.`
 * so the output does not depend on the machine.
 */
export function formatPlans(plans: AdapterPlan[], env: { cwd: string; home: string }): string {
  const show = (path: string) => displayPath(path, env);
  const lines: string[] = [];
  for (const plan of plans) {
    const support = plan.support;
    lines.push(
      [
        "plan",
        plan.pluginId,
        plan.host,
        plan.adapter,
        plan.mode,
        plan.scope,
        `recovery=${plan.recovery}`,
        `support=${support.state}`,
      ].join("\t"),
    );
    lines.push(`roots\t${plan.roots.map(show).join(" ")}`);
    for (const deviation of support.deviations) {
      lines.push(`deviation\t${deviation.id}\t${deviation.issue}\t${deviation.detail}`);
    }
    for (const note of plan.notes) {
      lines.push(`note\t${note}`);
    }
    for (const op of plan.ops) {
      lines.push(formatOp(op, show));
    }
  }
  return lines.join("\n");
}

function formatOp(op: Op, show: (path: string) => string): string {
  switch (op.kind) {
    case "mkdir":
      return `op\tmkdir\t${show(op.path)}`;
    case "write-file":
      return `op\twrite-file\t${show(op.path)}\tsha256:${op.hash}`;
    case "symlink":
      return `op\tsymlink\t${show(op.path)}\t-> ${show(op.target)}`;
    case "remove-owned":
      return `op\tremove-owned\t${show(op.path)}\texpect:${op.expectHash}`;
    case "host-exec":
      return [
        "op",
        "host-exec",
        op.argv.map(show).join(" "),
        op.compensate ? `compensate: ${op.compensate.join(" ")}` : `irreversible: ${op.step}`,
      ].join("\t");
  }
}

function displayPath(path: string, env: { cwd: string; home: string }): string {
  for (const [base, label] of [
    [env.cwd, "."],
    [env.home, "~"],
  ] as const) {
    if (path === base) {
      return label;
    }
    if (path.startsWith(`${base}/`)) {
      return `${label}${path.slice(base.length)}`;
    }
  }
  return path;
}

async function planLane(
  composition: InstallComposition,
  agent: string,
  mode: Mode,
  fs: ReadOnlyFs,
  options: PlanInput["options"],
): Promise<AdapterPlan> {
  const sources =
    mode === PROJECTOR_EXPLODE ? composition.sources.explode : composition.sources.native;
  const plan = await adapterFor(agent, mode).plan({
    env: composition.env,
    fs,
    host: agent,
    kept: keptSet(composition, sources ?? {}),
    mode,
    options,
    owned: ownedSkills(composition.existing, agent),
    role: "skill",
    scope: composition.scope,
  });
  assertBuiltinPlan(plan);
  return plan;
}

function keptSet(composition: InstallComposition, sources: Record<string, string>): KeptSet {
  return {
    description: composition.description,
    pluginId: composition.pluginId,
    skills: composition.skills.map((name) => {
      const source = sources[name];
      if (!source) {
        throw new Error(
          `No local source for skill ${JSON.stringify(name)} in ${composition.pluginId}`,
        );
      }
      return { name, source };
    }),
    version: composition.version,
  };
}

function ownedSkills(existing: PluginLockEntry | undefined, agent: string): string[] {
  return [...skillNamesFromFiles(existing?.agents?.[agent]?.files ?? {})];
}

function lockedNative(existing: PluginLockEntry | undefined, agent: string): boolean {
  return (
    Boolean(existing?.agents?.[agent]) && agentProjector(existing!, agent) === PROJECTOR_NATIVE
  );
}
