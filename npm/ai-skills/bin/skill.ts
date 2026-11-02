#!/usr/bin/env node

import { resolvePackagedRuntime, runPackagedRuntime } from "../lib/runtime.ts";

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const runtime = resolvePackagedRuntime();
  if (runtime) {
    await runPackagedRuntime(runtime, argv);
    return;
  }
  const { runCli } = await import("../lib/cli.ts");
  await runCli(argv);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
