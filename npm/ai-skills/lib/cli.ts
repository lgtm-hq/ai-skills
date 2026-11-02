import { adoptSkills } from "./adopt.ts";
import { loadVendors } from "./catalog.ts";
import { runDoctor } from "./doctor.ts";
import { listSkills, removeSkills, updateSkills } from "./gateway-commands.ts";
import { batchesFromCliOptions, install, installInteractively } from "./install.ts";
import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "./options.ts";
import { formatInstallCounts } from "./ui.ts";

/**
 * Render vendor pins from baked package data.
 */
async function printVendors(): Promise<void> {
  const { vendors } = await loadVendors();
  for (const vendor of vendors) {
    console.log(`${vendor.id}\t${vendor.repo}\t${vendor.sha}\t${vendor.license}`);
  }
}

/**
 * Render lock-managed plugin records, annotating missing or modified installs.
 */
async function printLockedSkills(options: { global: boolean; project: boolean }): Promise<void> {
  const plugins = await listSkills(options);
  for (const plugin of plugins) {
    const status = plugin.status ? `\t${plugin.status}` : "";
    const agents = plugin.agentNames
      .map((agent) => {
        const agentStatus = plugin.agentStatus?.[agent];
        return agentStatus ? `${agent}:${agentStatus}` : agent;
      })
      .join(",");
    const skills = (plugin.skills ?? []).join(",");
    console.log(
      `${plugin.name}\t${plugin.vendor}\t${plugin.repo}\t${plugin.sha}\t${agents}\t${skills}${status}`,
    );
  }
}

/**
 * Run the wrapper command.
 */
export async function runCli(argv: string[]): Promise<void> {
  const { command, options } = parseArguments(argv);
  if (command === "vendors") {
    await printVendors();
    return;
  }
  if (command === "list") {
    validateUnattendedCommandOptions(options, { requireAgents: false });
    await printLockedSkills(options);
    return;
  }
  if (command === "remove") {
    validateUnattendedCommandOptions(options);
    await removeSkills(options);
    return;
  }
  if (command === "update") {
    validateUnattendedCommandOptions(options);
    await updateSkills(options);
    return;
  }
  if (command === "adopt") {
    validateUnattendedCommandOptions(options, { requireAgents: false });
    await adoptSkills(options);
    return;
  }
  if (command === "doctor") {
    validateUnattendedCommandOptions(options, { requireAgents: false });
    const result = await runDoctor(options);
    if (result.repaired.length > 0) {
      console.log(`repaired\t${result.repaired.join(",")}`);
    }
    if (result.migrated.length > 0) {
      console.log(`migrated\t${result.migrated.join(",")}`);
    }
    return;
  }
  validateUnattendedOptions(options);
  if (options.yes) {
    const totals = { alreadyPresent: 0, installed: 0, repaired: 0 };
    const finished = [];
    for (const batch of await batchesFromCliOptions(options)) {
      try {
        const counts = await install({
          ...options,
          bundle: batch.pluginId,
          vendor: batch.vendor,
          skills: batch.skills,
        });
        totals.alreadyPresent += counts.alreadyPresent;
        totals.installed += counts.installed;
        totals.repaired += counts.repaired;
        finished.push(batch.pluginId);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        throw new Error(
          `Install failed for "${batch.pluginId}" after completing: ` +
            `${finished.length > 0 ? finished.join(", ") : "none"}. ${detail}`,
        );
      }
    }
    console.log(formatInstallCounts(totals));
    return;
  }
  await installInteractively(options);
}
