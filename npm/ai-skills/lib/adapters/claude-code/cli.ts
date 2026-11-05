import { createCliAdapter } from "../shared/cli-adapter.ts";
import { CLAUDE_CODE_HOST } from "./host.ts";

/** `claude-cli`: native Claude Code plugins from the local envelope. */
export const claudeCliAdapter = createCliAdapter(CLAUDE_CODE_HOST);
