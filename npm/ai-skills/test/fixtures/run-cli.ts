// Drive the launcher's parsed CLI path (not the bin pre-parse forward).
import { runCli } from "../../lib/cli.ts";

await runCli(process.argv.slice(2));
