import { mock } from "bun:test";
import { mkdtemp, mkdir, readFile, readdir, readlink, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
process.env.npm_package_version = "0.0.0-dev";
const base = process.argv[2]!;
const extension = process.argv[3] === "dist" ? "js" : "ts";
const moduleRoot = process.argv[3] === "dist" ? `${base}/dist` : base;
const paths: typeof import("../lib/paths.ts") = await import(
  `${moduleRoot}/lib/paths.${extension}`
);
const catalogRoot = join(base, "test/fixtures/legacy-catalog");
// Pin the original inputs as well as outputs; release/vendor updates must not
// change the behavior comparison. Keep the real catalog reader in both modes.
mock.module(`${moduleRoot}/lib/paths.${extension}`, () => ({
  ...paths,
  DATA_ROOT: catalogRoot,
  CHECKOUT_ROOT: catalogRoot,
}));
const inst: typeof import("../lib/install.ts") = await import(
  `${moduleRoot}/lib/install.${extension}`
);
const gateway: typeof import("../lib/gateway-commands.ts") = await import(
  `${moduleRoot}/lib/gateway-commands.${extension}`
);
const doctor: typeof import("../lib/doctor.ts") = await import(
  `${moduleRoot}/lib/doctor.${extension}`
);
const originalInstall = inst.install,
  originalList = gateway.listSkills,
  originalUpdate = gateway.updateSkills,
  originalRemove = gateway.removeSkills,
  originalDoctor = doctor.runDoctor;
const receipts: typeof import("../lib/journal/receipts.ts") = await import(
  `${moduleRoot}/lib/journal/receipts.${extension}`
);
const root = await mkdtemp(join(tmpdir(), "566-golden-"));
const environment = { cwd: root, home: root };
// Managed installs explode a local artifact (#579); the skills CLI only runs
// for the explicit --unmanaged handoff below.
const sourceRoot = await mkdtemp(join(tmpdir(), "579-golden-catalog-"));
for (const name of ["lint", "test", "greptile", "coderabbit", "lintro-review"]) {
  await mkdir(join(sourceRoot, "skills", name), { recursive: true });
  await writeFile(
    join(sourceRoot, "skills", name, "SKILL.md"),
    `# ${name}\nfixture catalog output\n`,
  );
}
const calls: string[][] = [];
const run = async (args: string[]) => {
  calls.push(args);
  const names = args.slice(args.indexOf("--skill") + 1).filter((x) => !x.startsWith("-"));
  for (const name of names) {
    await mkdir(join(root, ".codex/skills", name), { recursive: true });
    await writeFile(
      join(root, ".codex/skills", name, "SKILL.md"),
      `# ${name}\nfixture upstream output\n`,
    );
  }
};
const now = () => new Date("2026-07-10T17:00:00.000Z");
const deps = {
  lockEnvironment: environment,
  run,
  now,
  sourceRoot,
};
mock.module(`${moduleRoot}/lib/install.${extension}`, () => ({
  ...inst,
  install: (options: Parameters<typeof originalInstall>[0]) =>
    originalInstall(options, run, now, environment, { sourceRoot }),
}));
mock.module(`${moduleRoot}/lib/gateway-commands.${extension}`, () => ({
  ...gateway,
  listSkills: (options: ReturnType<typeof import("../lib/options.ts").parseArguments>["options"]) =>
    originalList(options, deps),
  updateSkills: (
    options: ReturnType<typeof import("../lib/options.ts").parseArguments>["options"],
  ) => originalUpdate(options, deps),
  removeSkills: (
    options: ReturnType<typeof import("../lib/options.ts").parseArguments>["options"],
  ) => originalRemove(options, deps),
}));
mock.module(`${moduleRoot}/lib/doctor.${extension}`, () => ({
  ...doctor,
  runDoctor: (options: ReturnType<typeof import("../lib/options.ts").parseArguments>["options"]) =>
    originalDoctor(options, {
      ...deps,
      home: root,
      exec: async () => ({ status: 1, stdout: "", stderr: "not found" }),
    }),
}));
const { runCli }: typeof import("../lib/cli.ts") = await import(
  `${moduleRoot}/lib/cli.${extension}`
);
// Machine-local state (#580) holds transaction ids and timestamps; the golden
// records the committed plugin records instead of the raw files.
const STATE = ".ai-skills/state";
async function tree(dir: string, prefix = ""): Promise<Record<string, string>> {
  const output: Record<string, string> = {};
  if (prefix === "") {
    const receipt = await receipts.readReceipt("project", environment);
    if (receipt) {
      output["<receipt>"] = JSON.stringify({
        generation: receipt.generation,
        plugins: receipt.plugins,
      });
    }
  }
  for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name),
  )) {
    const key = prefix + entry.name;
    if (key === STATE) {
      continue;
    }
    if (entry.isDirectory()) Object.assign(output, await tree(join(dir, entry.name), key + "/"));
    else
      output[key] = entry.isSymbolicLink()
        ? `symlink:${await readlink(join(dir, entry.name))}`
        : await readFile(join(dir, entry.name), "utf8");
  }
  return output;
}
const results = [];
const originalLog = console.log,
  originalWarn = console.warn;
try {
  for (const args of [
    ["vendors"],
    ["install", "-y", "--project", "-a", "codex", "--bundle", "review"],
    ["list", "--project"],
    ["doctor", "-y", "--project", "-a", "codex"],
    ["update", "-y", "--project", "-a", "codex"],
    ["remove", "-y", "--project", "-a", "codex", "--skill", "review"],
    ["list", "--project"],
    ["install", "-y", "--project", "-a", "codex", "--bundle", "review", "--unmanaged"],
    ["list", "--project"],
    ["--bad-flag"],
  ]) {
    if (args[0] === "update") {
      const path = await receipts.receiptPath("project", environment);
      const receipt = JSON.parse(await readFile(path, "utf8"));
      receipt.plugins.review.sha = "outdated";
      receipt.plugins.review.version = "outdated";
      await writeFile(path, `${JSON.stringify(receipt, null, 2)}\n`);
    }
    const stdout: string[] = [],
      stderr: string[] = [];
    console.log = (...args) => stdout.push(args.join(" "));
    console.warn = (...args) => stderr.push(args.join(" "));
    let status = 0;
    try {
      await runCli(args);
    } catch (error) {
      status = 1;
      stderr.push(error instanceof Error ? error.message : String(error));
    }
    results.push({
      args,
      stdout: stdout.join("\n") + (stdout.length ? "\n" : ""),
      stderr: stderr.join("\n") + (stderr.length ? "\n" : ""),
      status,
      calls: calls.splice(0),
      tree: await tree(root),
    });
  }
} finally {
  console.log = originalLog;
  console.warn = originalWarn;
  await rm(root, { force: true, recursive: true });
  await rm(sourceRoot, { force: true, recursive: true });
}
console.log(
  JSON.stringify(results, null, 2).replaceAll(sourceRoot, "<CATALOG>").replaceAll(root, "<HOME>"),
);
