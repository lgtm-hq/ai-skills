// Match Renovate lib/util/yaml.ts defaults, including strict:false.
import { pathToFileURL } from 'node:url';

const { parseAllDocuments } = await import(pathToFileURL(process.argv[2]).href);
const source = await Bun.stdin.text();
const documents = parseAllDocuments(source, {
  prettyErrors: true,
  uniqueKeys: true,
  strict: false,
});
const errors = documents.flatMap((document) => document.errors.map((error) => error.message));
const parsed = errors.length
  ? null
  : documents.map((document) => document.toJS({ maxAliasCount: 10000 }));
console.log(JSON.stringify({ errors, parsed }));
