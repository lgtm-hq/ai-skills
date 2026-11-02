import { Socket } from "node:net";
import endpoint from "../network-control.json";
import { windowsNetworkControl } from "./windows-network-control";

// Diagnostic only: never called by installation. Keep the endpoint identical to
// scripts/network_control.py; do not accept a caller-selected destination.
export async function networkControl({
  platform = process.platform,
  isBun = Boolean(process.versions.bun),
  arch = process.arch,
  windows = windowsNetworkControl,
  createSocket = () => new Socket(),
  completionBudgetMs = 3000,
} = {}): Promise<unknown[]> {
  if (platform === "win32" && isBun) {
    if (arch !== "x64")
      return [{ ...endpoint, outcome: "inconclusive", error: "Winsock diagnostic requires Win64" }];
    return windows();
  }
  return new Promise((resolve) => {
    let socket: Socket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const settle = () => {
      clearTimeout(timer);
      resolve([observation]);
    };
    let stage = "create";
    let finishing = false;
    const observation: Record<string, unknown> = { ...endpoint, outcome: "inconclusive" };
    const failure = (error: unknown, operation: string) => {
      const raw = error instanceof Error ? (error as NodeJS.ErrnoException) : undefined;
      return {
        stage: operation,
        error: raw?.message ?? String(error),
        raw_error: { code: raw?.code, errno: raw?.errno, syscall: raw?.syscall },
      };
    };
    const cleanupFailure = (error: unknown) => {
      const raw = failure(error, "close");
      observation.outcome_before_cleanup ??= observation.outcome;
      observation.cleanup_error = raw;
      if (!observation.error) Object.assign(observation, raw);
      observation.outcome = "inconclusive";
    };
    const finish = (outcome: string, error?: unknown) => {
      if (finishing) {
        if (error !== undefined) cleanupFailure(error);
        return;
      }
      finishing = true;
      observation.outcome = outcome;
      if (error !== undefined) Object.assign(observation, failure(error, stage));
      if (!socket) {
        settle();
        return;
      }
      stage = "close";
      try {
        socket.destroy();
        // Resolve on close, so an asynchronous destroy error also invalidates proof.
      } catch (error: unknown) {
        cleanupFailure(error);
        settle();
      }
    };
    const connectionError = (error: unknown) => {
      const raw = error instanceof Error ? (error as NodeJS.ErrnoException) : undefined;
      // Only an actual connect permission failure proves denial. Node's EACCES
      // is structured permission evidence, never an observed native WinError 10013.
      const denied =
        stage === "connect" &&
        raw?.syscall === "connect" &&
        (raw.code === "EACCES" || (platform !== "win32" && raw.code === "EPERM"));
      finish(denied ? "explicit-denial" : "inconclusive", error);
    };
    timer = setTimeout(() => {
      cleanupFailure(new Error("socket diagnostic completion deadline exceeded"));
      try {
        socket?.destroy();
      } catch (error: unknown) {
        cleanupFailure(error);
      }
      settle();
    }, completionBudgetMs);
    try {
      socket = createSocket();
      socket.once("close", settle);
      socket.on("error", connectionError);
      stage = "settimeout";
      socket.setTimeout(2000);
      socket.once("connect", () => finish("connected"));
      socket.once("timeout", () => finish("inconclusive"));
      stage = "connect";
      socket.connect({ host: endpoint.address, port: endpoint.port, family: 4 });
    } catch (error: unknown) {
      connectionError(error);
    }
  });
}

// build.py emits this TypeScript as a Node-compatible module for the exact Node
// executable used to launch npm. The compiled prototype calls the same function.
if (process.argv.length === 3 && process.argv[2] === "--spike-network-control") {
  console.log(JSON.stringify(await networkControl()));
}
