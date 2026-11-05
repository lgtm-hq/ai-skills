import { createCliAdapter } from "../shared/cli-adapter.ts";
import { COPILOT_HOST } from "./host.ts";

/** `copilot-cli`: native Copilot plugins from the local envelope (records the tag-strip deviation). */
export const copilotCliAdapter = createCliAdapter(COPILOT_HOST);
