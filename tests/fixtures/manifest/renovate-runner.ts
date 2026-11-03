// Execute byte-verified upstream extraction and auto-replacement offline.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, posix } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

interface RunnerConfig extends Record<string, unknown> {
  customType: string;
}
interface DigestUpdate extends Record<string, unknown> {
  depIndex: number;
  newDigest: string;
}
interface RunnerInput {
  text: string;
  modules: Record<string, string>;
  config: RunnerConfig;
  updates: DigestUpdate[];
}
interface Snapshot {
  file: string;
  sha256: string;
}
interface Dependency extends Record<string, unknown> {
  depName?: string;
  currentDigest?: string;
  currentValue?: string;
}
interface Extraction extends Record<string, unknown> {
  deps: Dependency[];
}
// Only these exports cross the byte-verified, runtime-generated bundle boundary.
// Extra production fields stay unknown and pass through unchanged to the updater.
interface UpstreamRunner {
  extractPackageFile(
    manager: string,
    content: string,
    file: string,
    config: RunnerConfig,
  ): Promise<Extraction | null>;
  doAutoReplace(
    upgrade: Record<string, unknown>,
    content: string,
    dryRun: boolean,
  ): Promise<string | null>;
  parseYaml(source: string): unknown;
}
interface YamlMap {
  get(key: string, keepScalar?: boolean): unknown;
}
interface YamlParser {
  parseAllDocuments(
    source: string,
    options: { prettyErrors: boolean; uniqueKeys: boolean; strict: boolean },
  ): YamlMap[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readInput(value: unknown): RunnerInput {
  if (!isRecord(value) || typeof value.text !== 'string' ||
      !isRecord(value.modules) || !isRecord(value.config) ||
      typeof value.config.customType !== 'string') {
    throw new Error('Invalid runner input');
  }
  const modules: Record<string, string> = {};
  for (const [name, entry] of Object.entries(value.modules)) {
    if (typeof entry !== 'string') throw new Error(`Invalid module path: ${name}`);
    modules[name] = entry;
  }
  const updates: DigestUpdate[] = [];
  const rawUpdates: unknown = value.updates ?? [];
  if (!Array.isArray(rawUpdates)) throw new Error('Invalid runner updates');
  for (const update of rawUpdates as unknown[]) {
    if (!isRecord(update) || typeof update.depIndex !== 'number' ||
        !Number.isInteger(update.depIndex) || typeof update.newDigest !== 'string') {
      throw new Error('Invalid digest update');
    }
    updates.push({ ...update, depIndex: update.depIndex, newDigest: update.newDigest });
  }
  return {
    text: value.text, modules,
    config: { ...value.config, customType: value.config.customType }, updates,
  };
}

function readSnapshots(value: unknown): Record<string, Snapshot> {
  if (!isRecord(value) || !isRecord(value.files)) throw new Error('Invalid snapshot metadata');
  const files: Record<string, Snapshot> = {};
  for (const [name, record] of Object.entries(value.files)) {
    if (!isRecord(record) || typeof record.file !== 'string' || typeof record.sha256 !== 'string') {
      throw new Error(`Invalid snapshot metadata: ${name}`);
    }
    files[name] = { file: record.file, sha256: record.sha256 };
  }
  return files;
}

function isYamlMap(value: unknown): value is YamlMap {
  return isRecord(value) && typeof value.get === 'function';
}

const root = dirname(fileURLToPath(import.meta.url));
const input = readInput(await Bun.stdin.json());
const snapshots = readSnapshots(JSON.parse(readFileSync(join(root, 'renovate/sources.json'), 'utf8')));
const external = input.modules;
function externalPath(name: string): string {
  const entry = external[name];
  if (!entry) throw new Error(`Unprepared dependency: ${name}`);
  return entry;
}
const externalImport = (name: string): string => pathToFileURL(externalPath(name)).href;
const shims: Record<string, string> = {
  'lib/logger/index.ts': 'export const logger = {debug(){},trace(){},info(){},warn(){}};',
  'lib/util/common.ts': 'export function parseJson(){throw Error("Unused JSON parser");}',
  'lib/util/toml.ts': 'export function parse(){throw Error("Unused TOML parser");}',
  'lib/config/migrations/custom/datasource-migration.ts':
    'export function migrateDatasource(value){if(value!=="git-refs")throw Error("Unexpected datasource");return value;}',
  'lib/util/template/index.ts': `import Handlebars from ${JSON.stringify(externalImport('handlebars'))}; export function compile(text,data){return Handlebars.compile(text)(data);}`,
  'lib/util/url.ts': 'export function parseUrl(value){return new URL(value);}',
  // The old manager's RED controls use only the common RE2/RegExp subset.
  'lib/util/regex.ts': 'export function regEx(pattern, flags=""){if(pattern.startsWith("(?m)")){pattern=pattern.slice(4);flags+="m";}return new RegExp(pattern, flags);}',
  'lib/util/object.ts': 'export function coerceObject(value){return value ?? {};}',
  'lib/util/fs/index.ts': 'export async function writeLocalFile(){}',
  'lib/constants/error-messages.ts': 'export const WORKER_FILE_UPDATE_FAILED="worker-file-update-failed";',
  'lib/workers/repository/extract/manager-files.ts':
    'export function normalizeDepNames(){}',
  'lib/modules/manager/index.ts':
    'import { extractPackageFile as jsonata } from "../manager/custom/jsonata/index.ts"; import { extractPackageFile as regex } from "../manager/custom/regex/index.ts"; export async function extractPackageFile(manager,content,file,config){if(manager==="custom.jsonata")return jsonata(content,file,config);if(manager==="custom.regex")return regex(content,file,config);throw Error("Unexpected manager");}',
};

const plugin: Bun.BunPlugin = {
  name: 'verified-renovate-sources',
  setup(build) {
    build.onResolve({ filter: /^renovate:/ }, ({ path }) => ({
      path: path.slice('renovate:'.length),
      namespace: 'renovate-source',
    }));
    build.onLoad({ filter: /.*/, namespace: 'renovate-source' }, ({ path }) => {
      if (path === 'entry') return { contents: 'export { extractPackageFile } from "renovate:lib/modules/manager/index.ts"; export { doAutoReplace } from "renovate:lib/workers/repository/update/branch/auto-replace.ts"; export { parseYaml } from "renovate:lib/util/yaml.ts";', loader: 'ts' };
      let contents = shims[path];
      if (!contents) {
        const record = snapshots[path];
        if (!record) throw Error(`Unreviewed production import: ${path}`);
        const bytes = readFileSync(join(root, 'renovate', record.file));
        if (createHash('sha256').update(bytes).digest('hex') !== record.sha256) throw Error(`Upstream snapshot changed: ${path}`);
        contents = bytes.toString();
      }
      contents = contents.replace(/(from\s*|import\s*)(['"])([^'"]+)\2/g, (_match: string, prefix: string, quote: string, name: string): string => {
        let target;
        if (name.startsWith('.')) target = 'renovate:' + posix.normalize(posix.join(posix.dirname(path), name));
        else if (name.startsWith('file:')) target = fileURLToPath(name);
        else if (name === 'zod/v4') target = join(dirname(externalPath('zod')), 'v4/index.js');
        else if (name === 'upath') target = 'node:path';
        else target = externalPath(name);
        if (!target) throw Error(`Unprepared dependency: ${name}`);
        return prefix + quote + target + quote;
      });
      return { contents, loader: 'ts', resolveDir: root };
    });
  },
};
// With no outdir Bun returns in-memory artifacts and writes no bundle to disk.
const bundle = await Bun.build({ entrypoints: ['renovate:entry'], plugins: [plugin], target: 'bun' });
if (!bundle.success) throw new AggregateError(bundle.logs, 'Cannot bundle upstream test sources');
const output = bundle.outputs[0];
if (!output) throw new Error('Missing upstream test bundle');
const { extractPackageFile, doAutoReplace, parseYaml } = (await import(`data:text/javascript;base64,${Buffer.from(await output.text()).toString('base64')}`)) as UpstreamRunner;
// The exact locked YAML package is verified by the Python caller before launch.
const { parseAllDocuments } = (await import(externalImport('yaml'))) as YamlParser;
const config = input.config;
const managerName = `custom.${config.customType}`;
let content = input.text;
const extracted = await extractPackageFile(managerName, content, 'ai-skills.yaml', config);
const deps = extracted?.deps ?? [];
const documents = parseAllDocuments(content, { prettyErrors: true, uniqueKeys: true, strict: false });
const matches = deps.map((dep) => {
  const groups = Object.fromEntries(['depName', 'currentDigest', 'currentValue'].map((key) => [key, dep[key]]));
  const spans: Record<string, [number, number]> = {};
  // CST ranges only support assertions; production extraction/update use upstream code.
  for (const doc of documents) {
    const vendors = doc.get('vendors', true);
    if (!isRecord(vendors) || !Array.isArray(vendors.items)) continue;
    for (const vendor of vendors.items as unknown[]) {
      if (!isYamlMap(vendor) || vendor.get('repo') !== dep.depName || vendor.get('sha') !== dep.currentDigest) continue;
      const scalar = vendor.get('sha', true);
      if (!isRecord(scalar) || !Array.isArray(scalar.range) || typeof dep.currentDigest !== 'string') continue;
      const [start, end]: unknown[] = scalar.range;
      if (typeof start !== 'number' || typeof end !== 'number') continue;
      const raw = content.slice(start, end);
      const offset = raw.indexOf(dep.currentDigest);
      if (offset >= 0) spans.currentDigest = [start + offset, start + offset + dep.currentDigest.length];
    }
  }
  return { groups, spans };
});
const updates: (string | null)[] = [];
const updateErrors: string[] = [];
for (const update of input.updates ?? []) {
  const current = await extractPackageFile(managerName, content, 'ai-skills.yaml', config);
  const dep = current?.deps[update.depIndex];
  let next: string | null;
  try {
    if (!dep) throw Error(`No dependency at index ${update.depIndex}`);
    next = await doAutoReplace({
    autoReplaceGlobalMatch: true,
    ...config, ...current, ...dep, ...update,
    newValue: dep.currentValue,
    manager: managerName, packageFile: 'ai-skills.yaml',
  }, content, false);
  } catch (error: unknown) {
    updateErrors.push(error instanceof Error ? error.message : String(error));
    next = null;
  }
  updates.push(next);
  if (next !== null) content = next;
}
let parsed: unknown;
try { parsed = parseYaml(input.text); } catch { parsed = null; }
console.log(JSON.stringify({ matches, deps, updates, updateErrors, content, parsed }));
