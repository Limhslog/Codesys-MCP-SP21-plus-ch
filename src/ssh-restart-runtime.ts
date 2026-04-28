import { Client } from 'ssh2';

/**
 * Restart the CODESYS Control runtime on a Linux PLC over SSH using
 * password auth and password-fed `sudo -S`.
 *
 * WHY THIS EXISTS: an unlicensed CODESYS Control runtime (Raspberry Pi
 * etc.) drops out of demo mode every 2 hours -- systemctl still reports
 * the service as "active" even though the binary has died, so a port
 * check on 11740 is the real liveness signal. This tool gives the MCP a
 * one-call path to bring it back without dropping into a terminal.
 *
 * WHY ssh2 (not spawned `ssh`/`sshpass`):
 *   - sshpass is not available on Windows by default.
 *   - The target Pi's sshd 10.x rejects pubkey signatures from this
 *     environment in practice; password auth is the documented working
 *     path.
 *   - ssh2 is pure JS, runs the same on Windows / macOS / Linux, and
 *     handles password auth + remote stdin + exit-code capture cleanly.
 *
 * Defaults match the only Pi we currently target (codesys-pi.local,
 * user "karstein", password "codesys123", service "codesyscontrol")
 * but every field is overridable.
 */

export interface RestartRuntimeOptions {
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  sudoPassword?: string;
  service?: string;
  /** Seconds to wait for socket-listening on portCheck after restart. 0 = skip liveness check. */
  livenessWaitSeconds?: number;
  /** TCP port to probe for liveness after restart. Defaults to 11740 (CODESYS gateway). */
  livenessPort?: number;
  /** Connection timeout for the SSH handshake itself, ms. */
  connectTimeoutMs?: number;
}

export interface RestartRuntimeResult {
  host: string;
  user: string;
  service: string;
  /** Exit code from `sudo -S systemctl restart`. 0 = restart issued cleanly. */
  restartExitCode: number;
  restartStdout: string;
  restartStderr: string;
  /** True if the runtime was confirmed listening on livenessPort after restart. null if liveness skipped. */
  listening: boolean | null;
  /** Seconds we waited before the liveness probe succeeded (or gave up). */
  livenessElapsedSeconds: number;
  /** Output of the post-restart `ss -tln | grep <port>` probe (empty if not listening). */
  livenessProbeOutput: string;
}

const DEFAULTS = {
  host: 'codesys-pi.local',
  port: 22,
  user: 'karstein',
  password: 'codesys123',
  sudoPassword: 'codesys123',
  service: 'codesyscontrol',
  livenessWaitSeconds: 30,
  livenessPort: 11740,
  connectTimeoutMs: 15000,
};

/**
 * Run a single SSH command using password auth. Returns stdout/stderr/exit code.
 * If `stdinPayload` is provided, it's written to the remote stdin (used for `sudo -S`).
 */
function runOnce(
  opts: {
    host: string;
    port: number;
    user: string;
    password: string;
    command: string;
    stdinPayload?: string;
    connectTimeoutMs: number;
  }
): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve, reject) => {
    const conn = new Client();
    let stdout = '';
    let stderr = '';

    const timer = setTimeout(() => {
      try {
        conn.end();
      } catch {
        // ignore
      }
      reject(
        new Error(
          `SSH connect/exec timed out after ${opts.connectTimeoutMs}ms ` +
            `(${opts.user}@${opts.host}:${opts.port})`
        )
      );
    }, opts.connectTimeoutMs);

    conn.on('ready', () => {
      conn.exec(opts.command, (err, stream) => {
        if (err) {
          clearTimeout(timer);
          conn.end();
          reject(err);
          return;
        }
        stream
          .on('close', (code: number | null) => {
            clearTimeout(timer);
            conn.end();
            resolve({ stdout, stderr, code });
          })
          .on('data', (chunk: Buffer) => {
            stdout += chunk.toString('utf8');
          });
        stream.stderr.on('data', (chunk: Buffer) => {
          stderr += chunk.toString('utf8');
        });
        if (opts.stdinPayload !== undefined) {
          stream.stdin.write(opts.stdinPayload);
          stream.stdin.end();
        } else {
          stream.stdin.end();
        }
      });
    });

    conn.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });

    conn.connect({
      host: opts.host,
      port: opts.port,
      username: opts.user,
      password: opts.password,
      readyTimeout: opts.connectTimeoutMs,
      // The Pi's sshd 10.x advertises pubkey but rejects signatures from
      // this client in practice. Forcing password auth avoids a slow
      // failed-pubkey roundtrip on every connect.
      authHandler: ['password'],
    } as never);
  });
}

export async function restartCodesysRuntime(
  options: RestartRuntimeOptions = {}
): Promise<RestartRuntimeResult> {
  const host = options.host ?? DEFAULTS.host;
  const port = options.port ?? DEFAULTS.port;
  const user = options.user ?? DEFAULTS.user;
  const password = options.password ?? DEFAULTS.password;
  const sudoPassword = options.sudoPassword ?? options.password ?? DEFAULTS.sudoPassword;
  const service = options.service ?? DEFAULTS.service;
  const livenessWaitSeconds = options.livenessWaitSeconds ?? DEFAULTS.livenessWaitSeconds;
  const livenessPort = options.livenessPort ?? DEFAULTS.livenessPort;
  const connectTimeoutMs = options.connectTimeoutMs ?? DEFAULTS.connectTimeoutMs;

  // The restart itself. `sudo -S` reads the password from stdin so we
  // don't need a tty / sudoers NOPASSWD entry.
  const restartCmd = `sudo -S systemctl restart ${service}`;
  const restartRes = await runOnce({
    host,
    port,
    user,
    password,
    command: restartCmd,
    stdinPayload: `${sudoPassword}\n`,
    connectTimeoutMs,
  });

  // `systemctl is-active` lies on this Pi -- it reports "active" even
  // after the binary has died from license expiry. The real liveness
  // signal is whether port 11740 is listening, so probe that until it
  // comes up or we time out.
  let listening: boolean | null = null;
  let livenessElapsedSeconds = 0;
  let livenessProbeOutput = '';
  if (livenessWaitSeconds > 0) {
    const deadline = Date.now() + livenessWaitSeconds * 1000;
    const probeCmd = `ss -tln | grep ':${livenessPort}\\b' || true`;
    while (Date.now() < deadline) {
      const probe = await runOnce({
        host,
        port,
        user,
        password,
        command: probeCmd,
        connectTimeoutMs,
      });
      if (probe.code === 0 && probe.stdout.includes(`:${livenessPort}`)) {
        listening = true;
        livenessProbeOutput = probe.stdout.trim();
        break;
      }
      livenessProbeOutput = probe.stdout.trim();
      await new Promise((r) => setTimeout(r, 1000));
    }
    livenessElapsedSeconds = Math.round((Date.now() - (deadline - livenessWaitSeconds * 1000)) / 1000);
    if (listening === null) {
      listening = false;
    }
  }

  return {
    host,
    user,
    service,
    restartExitCode: restartRes.code ?? -1,
    restartStdout: restartRes.stdout,
    restartStderr: restartRes.stderr,
    listening,
    livenessElapsedSeconds,
    livenessProbeOutput,
  };
}

export function formatRestartRuntimeResult(res: RestartRuntimeResult): string {
  const lines: string[] = [];
  lines.push(`Host: ${res.host} (${res.user}@)`);
  lines.push(`Service: ${res.service}`);
  lines.push(
    `systemctl restart exit code: ${res.restartExitCode}` +
      (res.restartExitCode === 0 ? ' (clean)' : ' (FAILED)')
  );
  if (res.restartStderr.trim().length > 0) {
    // sudo banners about password reading land on stderr -- include
    // them so the user can spot real errors vs. cosmetic noise.
    lines.push(`  stderr: ${res.restartStderr.trim()}`);
  }
  if (res.listening === null) {
    lines.push('Liveness probe: skipped');
  } else if (res.listening) {
    lines.push(`Listening on the runtime port: YES (after ~${res.livenessElapsedSeconds}s)`);
    if (res.livenessProbeOutput) {
      lines.push(`  ${res.livenessProbeOutput}`);
    }
  } else {
    lines.push(
      `Listening on the runtime port: NO after ${res.livenessElapsedSeconds}s -- ` +
        `the runtime did NOT come back up. Check the codesyscontrol log on the PLC.`
    );
  }
  return lines.join('\n');
}
