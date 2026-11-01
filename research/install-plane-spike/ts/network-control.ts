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
} = {}): Promise<unknown[]> {
  if (platform === "win32" && isBun) {
    if (arch !== "x64")
      return [{ ...endpoint, outcome: "inconclusive", error: "Winsock diagnostic requires Win64" }];
    return windows();
  }
  return new Promise((resolve) => {
    const socket = new Socket();
    const finish = (outcome: string, error?: NodeJS.ErrnoException) => {
      socket.destroy();
      resolve([
        {
          address: endpoint.address,
          port: endpoint.port,
          outcome,
          ...(error
            ? {
                error: error.message,
                raw_error: { code: error.code, errno: error.errno, syscall: error.syscall },
              }
            : {}),
        },
      ]);
    };
    socket.setTimeout(2000);
    socket.once("connect", () => finish("connected"));
    socket.once("timeout", () => finish("inconclusive"));
    socket.once("error", (error: NodeJS.ErrnoException) => {
      finish(
        // Node maps Winsock access denial to EACCES. Keep that permission code
        // structured for the exact npm Node launcher; never infer native 10013.
        // Lost routes, refusal and timeouts cannot prove denial on any platform.
        error.code === "EACCES" || (platform !== "win32" && error.code === "EPERM")
          ? "explicit-denial"
          : "inconclusive",
        error,
      );
    });
    socket.connect({ host: endpoint.address, port: endpoint.port, family: 4 });
  });
}

// build.py emits this TypeScript as a Node-compatible module for the exact Node
// executable used to launch npm. The compiled prototype calls the same function.
if (process.argv.length === 3 && process.argv[2] === "--spike-network-control") {
  console.log(JSON.stringify(await networkControl()));
}
