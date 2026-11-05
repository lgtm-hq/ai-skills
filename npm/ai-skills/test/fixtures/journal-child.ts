// Child process for crash-injection tests: run one gateway command in a world
// and SIGKILL itself after op `crashAt` is durably done ("after") or inside it,
// before its done record ("during").
import { runWorldCommand } from "./journal-world.ts";
import type { World } from "./journal-world.ts";

const [worldJson, command, crashText, phase = "after"] = process.argv.slice(2);
const world = JSON.parse(worldJson!) as World;
const crashAt = crashText === undefined ? -1 : Number(crashText);
const crash = (index: number) => {
  if (index === crashAt) {
    process.kill(process.pid, "SIGKILL");
  }
};
await runWorldCommand(world, command as "install" | "remove" | "update", {
  journal: phase === "during" ? { duringOp: crash } : { afterOp: crash },
});
