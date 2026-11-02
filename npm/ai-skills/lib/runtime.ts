import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { constants } from "node:os";
import { join, resolve } from "node:path";

import { DATA_ROOT } from "./paths.ts";

export const RUNTIME_TARGETS = [
  "linux-x64",
  "linux-arm64",
  "darwin-x64",
  "darwin-arm64",
  "windows-x64",
] as const;
export type RuntimeTarget = (typeof RUNTIME_TARGETS)[number];
export interface PackagedRuntime {
  interpreter: string;
  entryPoint: string;
}

/** Select only a local, self-contained payload; never search PATH or download. */
export function resolvePackagedRuntime({
  env = process.env,
  platform = process.platform,
  arch = process.arch,
}: { env?: NodeJS.ProcessEnv; platform?: string; arch?: string } = {}): PackagedRuntime | null {
  const runtimeRoot = env.AI_SKILLS_RUNTIME_ROOT ?? join(DATA_ROOT, "runtime");
  // Legacy releases retain their CLI until #386 ships the Python payloads.
  if (!env.AI_SKILLS_RUNTIME_ROOT && !existsSync(runtimeRoot)) {
    return null;
  }
  const target = `${platform === "win32" ? "windows" : platform}-${arch}`;
  if (!RUNTIME_TARGETS.some((supported) => supported === target)) {
    throw new Error(`Unsupported packaged runtime target: ${target}`);
  }
  const bundle = resolve(runtimeRoot, target);
  const interpreter = join(
    bundle,
    "python",
    ...(platform === "win32" ? ["python.exe"] : ["bin", "python3"]),
  );
  const entryPoint = join(bundle, "engine", "__main__.py");
  if (!existsSync(interpreter) || !existsSync(entryPoint)) {
    throw new Error(`Packaged runtime is incomplete: ${bundle}`);
  }
  return { interpreter, entryPoint };
}

/** Forward the process contract without interpreting Python command semantics. */
export async function runPackagedRuntime(runtime: PackagedRuntime, argv: string[]): Promise<void> {
  const child = spawn(runtime.interpreter, [runtime.entryPoint, ...argv], { stdio: "inherit" });
  const signals = ["SIGINT", "SIGTERM", "SIGHUP"] as const;
  const handlers = signals.map((signal) => {
    const forward = () => {
      child.kill(signal);
    };
    process.on(signal, forward);
    return { signal, forward };
  });
  const cleanup = () => {
    for (const { signal, forward } of handlers) {
      process.removeListener(signal, forward);
    }
  };
  let result: { code: number | null; signal: NodeJS.Signals | null };
  try {
    result = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
      (resolveExit, reject) => {
        child.once("error", reject);
        child.once("close", (code, signal) => resolveExit({ code, signal }));
      },
    );
  } finally {
    cleanup();
  }
  if (result.signal) {
    process.exitCode = 128 + (constants.signals[result.signal] ?? 1);
    // Only re-raise the termination signals we forward. Other signals may be
    // ignored (SIGPIPE) or activate runtime features (Node's SIGUSR1 debugger).
    if (signals.some((signal) => signal === result.signal)) {
      process.kill(process.pid, result.signal);
    }
  } else {
    process.exitCode = result.code ?? 1;
  }
}
