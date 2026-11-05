import { verifyPlanOps } from "../execute.ts";
import { ENVELOPE_MARKETPLACE, envelopeRoot, renderEnvelopeOps } from "../envelope.ts";
import { routeGate, supportReport } from "../support.ts";
import type {
  AdapterId,
  AdapterPlan,
  Deviation,
  DestinationAdapter,
  HostDefinition,
  PlanInput,
  SupportReport,
  SupportRequest,
} from "../types.ts";
import { stripGitTag } from "./native-cli.ts";

const USER_SCOPE: Deviation = {
  id: "cli-user-scope",
  detail:
    "The host CLI install is user-scoped even when --project is passed; the gateway " +
    "lock still records the requested scope",
  issue: "#584",
};

const MARKETPLACE_REUSED: Deviation = {
  id: "existing-marketplace-kept",
  detail:
    `An already registered "${ENVELOPE_MARKETPLACE}" marketplace is accepted as is ` +
    "(already exists), so the host may still resolve plugins from that registration",
  issue: "#584",
};

const SOURCE_TAG: Deviation = {
  id: "source-tag-stripped",
  detail: "The marketplace source has any trailing @<tag> removed before marketplace add",
  issue: "#584",
};

/**
 * Native plugin delivery through a host's plugin CLI.
 *
 * The plan renders the kept set as a local marketplace envelope under
 * `~/.ai-skills/native/<host>` and registers that directory. It never passes
 * a remote repository: with no local source the support report makes native
 * unavailable. The marketplace registration is disclosed as irreversible (v1
 * never removed it); the plugin install is compensated by uninstall unless the
 * host reported it already present.
 */
export function createCliAdapter(host: HostDefinition): DestinationAdapter {
  const route = host.native;
  if (route?.kind !== "cli") {
    throw new Error(`${host.id} has no CLI native route`);
  }
  const id: AdapterId = route.adapter;
  const hosts = [host.id];
  const deviations = [
    USER_SCOPE,
    MARKETPLACE_REUSED,
    ...(route.stripSourceTag ? [SOURCE_TAG] : []),
  ];
  const support = (request: SupportRequest): SupportReport => {
    const reason = routeGate(request, { hosts, mode: "native" });
    return supportReport(id, request, reason ? { route: "unavailable", reason } : { deviations });
  };
  return {
    id,
    hosts,
    mode: "native",
    opKinds: ["mkdir", "write-file", "remove-owned", "symlink", "host-exec"],
    hostExec: [
      {
        id: "marketplace-add",
        compensated: false,
        irreversible: "the local marketplace registration stays after rollback",
      },
      { id: "plugin-install", compensated: true },
    ],
    recovery: "compensating",
    support,
    async plan(input: PlanInput): Promise<AdapterPlan> {
      const report = support({ ...input, localSource: true });
      if (report.route === "unavailable") {
        throw new Error(`${id} cannot plan ${input.host}: ${report.reason}`);
      }
      const root = envelopeRoot(input.host, input.env);
      const source = route.stripSourceTag ? stripGitTag(root) : root;
      const plugin = `${input.kept.pluginId}@${ENVELOPE_MARKETPLACE}`;
      return {
        adapter: id,
        host: input.host,
        role: input.role,
        mode: input.mode,
        scope: input.scope,
        pluginId: input.kept.pluginId,
        recovery: "compensating",
        roots: [root],
        ops: [
          ...(await renderEnvelopeOps(input.fs, root, input.kept)),
          {
            kind: "host-exec",
            step: "marketplace-add",
            argv: [route.binary, "plugin", "marketplace", "add", source],
            compensate: null,
            tolerateAlreadyPresent: true,
          },
          {
            kind: "host-exec",
            step: "plugin-install",
            argv: [route.binary, "plugin", "install", plugin],
            compensate: [route.binary, "plugin", "uninstall", plugin],
            tolerateAlreadyPresent: true,
          },
        ],
        support: report,
        notes: [],
      };
    },
    verify(plan, env) {
      return verifyPlanOps(plan, env.fs);
    },
  };
}
