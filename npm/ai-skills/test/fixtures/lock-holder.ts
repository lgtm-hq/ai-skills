// Child process for lock-contention tests: take the state lock, report it on
// stdout, hold it for `holdMs` (or until killed), then release it.
import { acquireStateLock } from "../../lib/journal/journal.ts";

const [path, holdText] = process.argv.slice(2);
const release = await acquireStateLock(path!, { waitMs: 0 });
process.stdout.write("locked\n");
await new Promise((resolve) => setTimeout(resolve, Number(holdText ?? "600000")));
await release();
