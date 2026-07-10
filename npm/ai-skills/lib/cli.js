import { loadVendors } from "./catalog.js";
import { listSkills, removeSkills, updateSkills } from "./gateway-commands.js";
import { install, installInteractively } from "./install.js";
import {
  parseArguments,
  validateUnattendedCommandOptions,
  validateUnattendedOptions,
} from "./options.js";

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
 * Render lock-managed skill records.
 *
 * @param {{global: boolean}} options - List command options.
 * @returns {Promise<void>} Resolves after writing lockfile rows.
 */
async function printLockedSkills(options) {
  const skills = await listSkills(options);
  for (const skill of skills) {
    console.log(
      `${skill.name}\t${skill.vendor}\t${skill.repo}\t${skill.sha}\t${skill.agents.join(",")}`,
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
  validateUnattendedOptions(options);
  if (options.yes) {
    await install(options);
    return;
  }
  await installInteractively(options);
}
