import { mock } from "bun:test";
import { mkdtemp, mkdir, readFile, readdir, readlink, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
process.env.npm_package_version = "0.0.0-dev";
const base = process.argv[2]!;
const extension = process.argv[3] === "dist" ? "js" : "ts";
const moduleRoot = process.argv[3] === "dist" ? `${base}/dist` : base;
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
const locks: typeof import("../lib/lockfile.ts") = await import(
  `${moduleRoot}/lib/lockfile.${extension}`
);
const root = await mkdtemp(join(tmpdir(), "566-golden-"));
const environment = { cwd: root, home: root };
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
  readLock: (scope: "global" | "project") => locks.readLockfile(scope, environment),
  writeLock: (lock: import("../lib/lockfile.ts").GatewayLock) =>
    locks.writeLockfile(lock, environment),
  run,
  now,
  sourceRoot: null,
};
mock.module(`${moduleRoot}/lib/install.${extension}`, () => ({
  ...inst,
  install: (options: Parameters<typeof originalInstall>[0]) =>
    originalInstall(options, run, now, environment, { sourceRoot: null }),
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
async function tree(dir: string, prefix = ""): Promise<Record<string, string>> {
  const output: Record<string, string> = {};
  for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name),
  )) {
    const key = prefix + entry.name;
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
    ["--bad-flag"],
  ]) {
    if (args[0] === "update") {
      const lock = await locks.readLockfile("project", environment);
      lock.plugins.review!.sha = "outdated";
      lock.plugins.review!.version = "outdated";
      await locks.writeLockfile(lock, environment);
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
}
console.log(JSON.stringify(results, null, 2).replaceAll(root, "<HOME>"));
