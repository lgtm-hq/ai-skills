// Match Renovate lib/util/yaml.ts defaults, including strict:false.
// This fixture runs only in Bun; describe its small runtime boundary locally.
declare const Bun: {
  argv: string[];
  stdin: { text(): Promise<string> };
};
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
const { parseAllDocuments } = (await import(Bun.argv[2])) as YamlParser;
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
