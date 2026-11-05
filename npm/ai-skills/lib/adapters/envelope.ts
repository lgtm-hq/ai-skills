import { join } from "node:path";

import { copyTreeOps, existsNoFollow, jsonBytes, ownedPathHash, sha256, walkTree } from "./fs.ts";
import { FIRST_PARTY_MARKETPLACE } from "./shared/native-cli.ts";
import type { KeptSet, Op, ReadOnlyFs } from "./types.ts";

/**
 * Marketplace name the local envelope registers. It matches the published
 * catalog's name so `<plugin>@ai-skills` identities (and uninstall) carry over.
 */
export const ENVELOPE_MARKETPLACE = FIRST_PARTY_MARKETPLACE;

const MARKETPLACE_FILE = join(".claude-plugin", "marketplace.json");
const PLUGIN_FILE = join(".claude-plugin", "plugin.json");

/**
 * Directory a host's local envelope is rendered into.
 *
 * Host CLIs register it as a local marketplace, so it must outlive the
 * install; it sits under the gateway's own `~/.ai-skills` state directory.
 */
export function envelopeRoot(host: string, env: { home: string }): string {
  return join(env.home, ".ai-skills", "native", host);
}

/**
 * Ops that render the kept set as a local plugin marketplace.
 *
 * Layout follows the recorded local-marketplace probe fixture
 * (`tests/fixtures/host-probe`): `<root>/.claude-plugin/marketplace.json`
 * listing `./<plugin>` and `<root>/<plugin>/.claude-plugin/plugin.json` with
 * `skills/<name>/`. Only kept skills are written; files a previous render left
 * under this plugin are removed (hash-checked). Other plugins' entries in the
 * marketplace stay listed.
 */
export async function renderEnvelopeOps(
  fs: ReadOnlyFs,
  root: string,
  kept: KeptSet,
  marketplace: string = ENVELOPE_MARKETPLACE,
): Promise<Op[]> {
  const pluginDir = join(root, kept.pluginId);
  const content: Op[] = [
    { kind: "mkdir", path: join(root, ".claude-plugin") },
    writeJson(join(root, MARKETPLACE_FILE), {
      name: marketplace,
      owner: { name: "lgtm-hq" },
      plugins: await mergedPluginEntries(fs, join(root, MARKETPLACE_FILE), kept),
    }),
    { kind: "mkdir", path: join(pluginDir, ".claude-plugin") },
    writeJson(join(pluginDir, PLUGIN_FILE), {
      description: kept.description,
      name: kept.pluginId,
      version: kept.version,
    }),
  ];
  for (const skill of kept.skills) {
    content.push(...(await copyTreeOps(fs, skill.source, join(pluginDir, "skills", skill.name))));
  }
  const written = new Set(content.flatMap((op) => (op.kind === "write-file" ? [op.path] : [])));
  const removals: Op[] = [];
  for (const entry of await walkTree(fs, pluginDir)) {
    const path = join(pluginDir, entry.relative);
    if (entry.kind === "dir" || (entry.kind === "file" && written.has(path))) {
      continue;
    }
    removals.push({ kind: "remove-owned", path, expectHash: await ownedPathHash(fs, path) });
  }
  return [...removals, ...content];
}

/**
 * Marketplace plugin entries after replacing this plugin's entry, sorted by name.
 */
async function mergedPluginEntries(
  fs: ReadOnlyFs,
  path: string,
  kept: KeptSet,
): Promise<Array<Record<string, unknown>>> {
  const entries: Array<Record<string, unknown>> = [];
  if (await existsNoFollow(fs, path)) {
    // Read errors (EACCES, EIO) propagate: the plan fails before any write.
    const text = new TextDecoder().decode(await fs.readFile(path));
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      if (!(error instanceof SyntaxError)) {
        throw error;
      }
      // Fail closed: rewriting from this plugin alone would drop the others.
      throw new Error(
        `Refusing to rewrite malformed marketplace index ${path} (${error.message}); ` +
          "repair or remove it, then reinstall",
      );
    }
    for (const entry of Array.isArray(parsed?.plugins) ? parsed.plugins : []) {
      if (entry && typeof entry.name === "string" && entry.name !== kept.pluginId) {
        entries.push(entry);
      }
    }
  }
  entries.push({
    description: kept.description,
    name: kept.pluginId,
    source: `./${kept.pluginId}`,
    version: kept.version,
  });
  return entries.sort((left, right) =>
    String(left.name) < String(right.name) ? -1 : String(left.name) > String(right.name) ? 1 : 0,
  );
}

function writeJson(path: string, value: unknown): Op {
  const content = jsonBytes(value);
  return { kind: "write-file", path, content, hash: sha256(content) };
}
