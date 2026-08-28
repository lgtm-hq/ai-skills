import { adoptSkills } from "./adopt.js";
import { loadVendors } from "./catalog.js";
import { listSkills, removeSkills, updateSkills } from "./gateway-commands.js";
import { batchesFromCliOptions, install, installInteractively } from "./install.js";
import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "./options.js";
import { formatInstallCounts } from "./ui.js";

/**
 * Render vendor pins from baked package data.
 *
 * @returns {Promise<void>} Resolves after writing vendor rows.
 */
async function printVendors() {
  const { vendors } = await loadVendors();
  for (const vendor of vendors) {
    console.log(`${vendor.id}\t${vendor.repo}\t${vendor.sha}\t${vendor.license}`);
  }
}

/**
 * Render lock-managed plugin records, annotating missing or modified installs.
 *
 * @param {{global: boolean}} options - List command options.
 * @returns {Promise<void>} Resolves after writing lockfile rows.
 */
async function printLockedSkills(options) {
  const plugins = await listSkills(options);
  for (const plugin of plugins) {
    const status = plugin.status ? `\t${plugin.status}` : "";
    console.log(
      `${plugin.name}\t${plugin.vendor}\t${plugin.repo}\t${plugin.sha}\t${plugin.agentNames.join(",")}${status}`,
    );
  }
}

/**
 * Run the wrapper command.
 *
 * @param {string[]} argv - Command-line arguments after the executable name.
 * @returns {Promise<void>} Resolves when the requested command completes.
 */
export async function runCli(argv) {
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
  validateUnattendedOptions(options);
  if (options.yes) {
    const totals = { alreadyPresent: 0, installed: 0, repaired: 0 };
    for (const batch of await batchesFromCliOptions(options)) {
      const counts = await install({
        ...options,
        bundle: batch.vendor ? null : batch.pluginId,
        vendor: batch.vendor,
        skills: batch.skills,
      });
      totals.alreadyPresent += counts.alreadyPresent;
      totals.installed += counts.installed;
      totals.repaired += counts.repaired;
    }
    console.log(formatInstallCounts(totals));
    return;
  }
  await installInteractively(options);
}
