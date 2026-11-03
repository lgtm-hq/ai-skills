// Match Renovate lib/util/yaml.ts defaults, including strict:false.
// This fixture runs only in Bun; describe the locked external parser boundary.
interface ParsedDocument {
  errors: { message: string }[];
  toJS(options: { maxAliasCount: number }): unknown;
}
interface YamlParser {
  parseAllDocuments(
    source: string,
    options: { prettyErrors: boolean; uniqueKeys: boolean; strict: boolean }
  ): ParsedDocument[];
}
const parserPath = Bun.argv[2];
if (!parserPath) throw new Error('Missing prepared YAML parser path');
const { parseAllDocuments } = (await import(parserPath)) as YamlParser;
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
export {};
