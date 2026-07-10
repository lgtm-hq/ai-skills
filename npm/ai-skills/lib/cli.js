import { loadVendors } from "./catalog.js";
import { install, installInteractively } from "./install.js";
import { parseArguments, validateUnattendedOptions } from "./options.js";

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
  validateUnattendedOptions(options);
  if (options.yes) {
    await install(options);
    return;
  }
  await installInteractively(options);
}
