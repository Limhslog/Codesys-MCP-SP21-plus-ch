#!/usr/bin/env node
/**
 * Runs after `npm install [-g] codesys-mcp-sp21-plus`.
 *
 * Goals:
 *   - Confirm to the user that the install worked + show the version
 *   - Dump the FULL ready-to-paste .mcp.json snippet for every detected install
 *   - Stay silent during dev (`npm install` inside a clone of the repo) and
 *     during CI to avoid polluting output.
 *
 * Failure-tolerant: any error (no Windows, no CODESYS, fs perms) is caught
 * and downgraded to a friendly note. We never block the install.
 */

function shouldSkip(): boolean {
  // Skip in CI -- banners pollute build logs.
  if (process.env.CI === 'true') return true;
  if (process.env.npm_config_ci === 'true') return true;

  // Skip when running inside the package's own dev clone (developer ran
  // `npm install` on a checkout of this repo). Detect by checking whether
  // INIT_CWD (npm sets this to the user's invocation cwd) appears to be
  // a checkout of THIS package, vs a global install or a downstream consumer.
  // Heuristic: if INIT_CWD contains a package.json whose name matches ours,
  // it's the dev clone.
  if (process.env.INIT_CWD) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const fs = require('fs');
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const path = require('path');
      const pkgPath = path.join(process.env.INIT_CWD, 'package.json');
      if (fs.existsSync(pkgPath)) {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
        if (pkg.name === 'codesys-mcp-sp21-plus') return true;
      }
    } catch {
      // Not a dev clone or unreadable -- fall through and print the banner.
    }
  }

  return false;
}

async function main(): Promise<void> {
  if (shouldSkip()) {
    return;
  }

  let version = 'unknown';
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    version = require('../package.json').version;
  } catch {
    // ignore
  }

  process.stdout.write(`\n=== codesys-mcp-sp21-plus v${version} installed ===\n\n`);

  if (process.platform !== 'win32') {
    process.stdout.write(
      `(CODESYS detection only runs on Windows -- this server requires Windows + CODESYS.)\n\n`
    );
    return;
  }

  let installs: Array<{ serverName: string; profileName: string }>;
  let printConfig: (
    installs: unknown[],
    opts?: Record<string, unknown>
  ) => string;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const detectMod = require('./detect');
    installs = detectMod.detectInstalls();
    printConfig = detectMod.printConfig;
  } catch (err) {
    process.stdout.write(
      `(CODESYS install detection failed: ${(err as Error).message})\n\n`
    );
    return;
  }

  if (installs.length === 0) {
    process.stdout.write(
      `No CODESYS installations detected under "C:\\Program Files" / "C:\\Program Files (x86)".\n` +
      `Install CODESYS first, then run \`codesys-mcp-sp21-plus --print-config\` to generate\n` +
      `the .mcp.json snippet.\n\n`
    );
    return;
  }

  process.stdout.write(`Add the following to your Claude Code MCP configuration:\n\n`);
  try {
    process.stdout.write(printConfig(installs) + '\n\n');
  } catch (err) {
    process.stdout.write(`(printConfig failed: ${(err as Error).message})\n\n`);
    return;
  }

  const userScope = process.env.USERPROFILE
    ? process.env.USERPROFILE + '\\.claude.json'
    : '~/.claude.json';

  process.stdout.write(
    `Where to put it:\n` +
    `  - Project-scoped (recommended, shareable via git):\n` +
    `      <your-project-root>\\.mcp.json\n` +
    `      Create the file if it doesn't exist; if it does, merge the "mcpServers"\n` +
    `      entries into the existing object.\n` +
    `  - User-scoped (applies to every Claude Code session):\n` +
    `      ${userScope}\n` +
    `      Or use the CLI:  claude mcp add codesys-sp22-patch1 codesys-mcp-sp21-plus -- --codesys-path ... --codesys-profile ...\n` +
    `\n` +
    `After editing, restart Claude Code so it re-reads the MCP config.\n` +
    `\n` +
    `Re-run anytime:               codesys-mcp-sp21-plus --print-config\n` +
    `Filter to one SP family:      codesys-mcp-sp21-plus --print-config --sp 22\n\n`
  );
}

main().catch((err) => {
  // Never fail the install over a banner.
  process.stdout.write(`\n(post-install banner failed: ${(err as Error).message})\n\n`);
});
