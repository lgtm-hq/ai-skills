// Execute byte-verified upstream extraction and auto-replacement offline.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, posix } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const input = await Bun.stdin.json();
const metadata = JSON.parse(readFileSync(join(root, 'renovate/sources.json'), 'utf8'));
const external = input.modules;
const externalImport = (name) => pathToFileURL(external[name]).href;
const shims = {
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

const plugin = {
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
        const record = metadata.files[path];
        if (!record) throw Error(`Unreviewed production import: ${path}`);
        const bytes = readFileSync(join(root, 'renovate', record.file));
        if (createHash('sha256').update(bytes).digest('hex') !== record.sha256) throw Error(`Upstream snapshot changed: ${path}`);
        contents = bytes.toString();
      }
      contents = contents.replace(/(from\s*|import\s*)(['"])([^'"]+)\2/g, (match, prefix, quote, name) => {
        let target;
        if (name.startsWith('.')) target = 'renovate:' + posix.normalize(posix.join(posix.dirname(path), name));
        else if (name.startsWith('file:')) target = fileURLToPath(name);
        else if (name === 'zod/v4') target = join(dirname(external.zod), 'v4/index.js');
        else if (name === 'upath') target = 'node:path';
        else target = external[name];
        if (!target) throw Error(`Unprepared dependency: ${name}`);
        return prefix + quote + target + quote;
      });
      return { contents, loader: 'ts', resolveDir: root };
    });
  },
};
const bundle = await Bun.build({ entrypoints: ['renovate:entry'], plugins: [plugin], target: 'bun', write: false });
if (!bundle.success) throw new AggregateError(bundle.logs, 'Cannot bundle upstream test sources');
const { extractPackageFile, doAutoReplace, parseYaml } = await import(`data:text/javascript;base64,${Buffer.from(await bundle.outputs[0].text()).toString('base64')}`);
const { parseAllDocuments } = await import(externalImport('yaml'));
const config = input.config;
const managerName = `custom.${config.customType}`;
let content = input.text;
const extracted = await extractPackageFile(managerName, content, 'ai-skills.yaml', config);
const deps = extracted?.deps ?? [];
const documents = parseAllDocuments(content, { prettyErrors: true, uniqueKeys: true, strict: false });
const matches = deps.map((dep) => {
  const groups = Object.fromEntries(['depName', 'currentDigest', 'currentValue'].map((key) => [key, dep[key]]));
  const spans = {};
  // CST ranges only support assertions; production extraction/update use upstream code.
  for (const doc of documents) {
    const vendors = doc.get('vendors', true);
    if (!vendors?.items) continue;
    for (const vendor of vendors.items) {
      if (vendor.get?.('repo') !== dep.depName || vendor.get?.('sha') !== dep.currentDigest) continue;
      const scalar = vendor.get('sha', true);
      const raw = content.slice(scalar.range[0], scalar.range[1]);
      const offset = raw.indexOf(dep.currentDigest);
      if (offset >= 0) spans.currentDigest = [scalar.range[0] + offset, scalar.range[0] + offset + dep.currentDigest.length];
    }
  }
  return { groups, spans };
});
const updates = [];
const updateErrors = [];
for (const update of input.updates ?? []) {
  const current = await extractPackageFile(managerName, content, 'ai-skills.yaml', config);
  const dep = current?.deps[update.depIndex];
  let next;
  try {
    if (!dep) throw Error(`No dependency at index ${update.depIndex}`);
    next = await doAutoReplace({
    autoReplaceGlobalMatch: true,
    ...config, ...current, ...dep, ...update,
    newValue: dep.currentValue,
    manager: managerName, packageFile: 'ai-skills.yaml',
  }, content, false);
  } catch (error) {
    updateErrors.push(error.message);
    next = null;
  }
  updates.push(next);
  if (next !== null) content = next;
}
let parsed;
try { parsed = parseYaml(input.text); } catch { parsed = null; }
console.log(JSON.stringify({ matches, deps, updates, updateErrors, content, parsed }));
