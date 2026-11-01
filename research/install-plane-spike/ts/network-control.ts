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
    const finish = (outcome: string, error?: Error) => {
      socket.destroy();
      resolve([
        {
          address: endpoint.address,
          port: endpoint.port,
          outcome,
          ...(error ? { error: error.message } : {}),
        },
      ]);
    };
    socket.setTimeout(2000);
    socket.once("connect", () => finish("connected"));
    socket.once("timeout", () => finish("inconclusive"));
    socket.once("error", (error: NodeJS.ErrnoException) => {
      finish(
        ["EACCES", "EPERM", "ENETUNREACH", "EHOSTUNREACH"].includes(error.code ?? "")
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
