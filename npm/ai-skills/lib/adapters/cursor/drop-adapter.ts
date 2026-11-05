import { join } from "node:path";

import { verifyPlanOps } from "../execute.ts";
import { copyTreeOps, jsonBytes, ownedPathHash, sha256, walkTree } from "../fs.ts";
import { hostPluginsRoot } from "../hosts.ts";
import { routeGate, supportReport } from "../support.ts";
import type {
  AdapterPlan,
  DestinationAdapter,
  Op,
  PlanInput,
  SupportReport,
  SupportRequest,
} from "../types.ts";
import {
  assertInsideRoot,
  assertSafePluginId,
  assertSafeSkillName,
  PLUGIN_MANIFEST,
} from "./drop.ts";
import { CURSOR_HOST } from "./host.ts";

const DROP_HOSTS = [CURSOR_HOST.id];

/**
 * Support for one Cursor tree-drop cell, with the recorded #584 deviation.
 */
function dropSupport(request: SupportRequest): SupportReport {
  const reason = routeGate(request, { hosts: DROP_HOSTS, mode: "native" });
  if (reason) {
    return supportReport("cursor-drop", request, { route: "unavailable", reason });
  }
  if (request.scope !== "project") {
    return supportReport("cursor-drop", request);
  }
  return supportReport("cursor-drop", request, {
    // Recorded evidence: project plugins/local loaded nothing after two restarts.
    state: "adapter-missing",
    reason: "Cursor 3.27.22 did not load <repo>/.cursor/plugins/local (docs/parity)",
    deviations: [
      {
        id: "cursor-project-path-unverified",
        detail:
          "--project still drops the tree under <cwd>/.cursor/plugins/local, a path " +
          "Cursor was not observed to load",
        issue: "#584",
      },
    ],
  });
}

/**
 * Cursor local plugin drop: assemble `<plugins>/<id>/` from the kept skills.
 *
 * The plan writes the manifest and every kept skill file, replaces owned
 * files under `skills/` (hash-checked) and never touches untracked files
 * outside `skills/`, matching the staging/`.bak` swap in `installCursorPlugin`.
 * An unowned, non-empty destination refuses the plan.
 */
export const cursorDropAdapter: DestinationAdapter = {
  id: "cursor-drop",
  hosts: DROP_HOSTS,
  mode: "native",
  opKinds: ["mkdir", "write-file", "symlink", "remove-owned"],
  hostExec: [],
  recovery: "reversible",
  support: dropSupport,
  async plan(input: PlanInput): Promise<AdapterPlan> {
    const support = dropSupport({ ...input, localSource: true });
    if (support.route === "unavailable") {
      throw new Error(`cursor-drop cannot plan ${input.host}: ${support.reason}`);
    }
    assertSafePluginId(input.kept.pluginId);
    const pluginsRoot = hostPluginsRoot(input.host, { ...input.env, scope: input.scope })!;
    const pluginDir = join(pluginsRoot, input.kept.pluginId);
    const existing = await walkTree(input.fs, pluginDir);
    const occupied = existing.some((entry) => entry.kind !== "dir");
    const replace = input.options?.replace ?? input.owned.length > 0;
    if (occupied && !replace) {
      throw new Error(`Refusing to overwrite unowned Cursor plugin at ${pluginDir}`);
    }
    const content: Op[] = [{ kind: "mkdir", path: pluginDir }];
    for (const skill of input.kept.skills) {
      // Same checks the engine applies before copying, so a plan never composes
      // a path outside the plugin's skills directory.
      assertSafeSkillName(skill.name);
      const dest = join(pluginDir, "skills", skill.name);
      assertInsideRoot(join(pluginDir, "skills"), dest);
      content.push(...(await copyTreeOps(input.fs, skill.source, dest)));
    }
    const manifest = jsonBytes({
      description: input.kept.description,
      name: input.kept.pluginId,
      version: input.kept.version,
    });
    content.push({ kind: "mkdir", path: join(pluginDir, ".claude-plugin") });
    content.push({
      kind: "write-file",
      path: join(pluginDir, PLUGIN_MANIFEST),
      content: manifest,
      hash: sha256(manifest),
    });
    const overwritten = new Set(
      content.flatMap((op) => (op.kind === "write-file" ? [op.path] : [])),
    );
    const removals: Op[] = [];
    for (const entry of existing) {
      if (entry.kind === "dir" || !entry.relative.startsWith("skills/")) {
        continue;
      }
      const path = join(pluginDir, entry.relative);
      if (entry.kind === "file" && overwritten.has(path)) {
        continue;
      }
      removals.push({
        kind: "remove-owned",
        path,
        expectHash: await ownedPathHash(input.fs, path),
      });
    }
    return {
      adapter: "cursor-drop",
      host: input.host,
      role: input.role,
      mode: input.mode,
      scope: input.scope,
      pluginId: input.kept.pluginId,
      recovery: "reversible",
      roots: [pluginDir],
      ops: [...removals, ...content],
      support,
      notes: [],
    };
  },
  verify(plan, env) {
    return verifyPlanOps(plan, env.fs);
  },
};
