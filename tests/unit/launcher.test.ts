import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { spawn, ChildProcess } from 'child_process';
import { CodesysLauncher, pathsEqual } from '../../src/launcher';

// These tests use the mock watcher directly (not CODESYS)
// They validate the launcher's IPC integration behavior

describe('CodesysLauncher', () => {
  it('rejects launch when CODESYS exe not found', async () => {
    const launcher = new CodesysLauncher({
      codesysPath: 'C:\\nonexistent\\CODESYS.exe',
      profileName: 'Test Profile',
      workspaceDir: os.tmpdir(),
    });

    await expect(launcher.launch()).rejects.toThrow(/not found/);
    const status = launcher.getStatus();
    expect(status.state).toBe('error');
  });

  it('getStatus reports stopped initially', () => {
    const launcher = new CodesysLauncher({
      codesysPath: 'C:\\nonexistent\\CODESYS.exe',
      profileName: 'Test Profile',
      workspaceDir: os.tmpdir(),
    });

    const status = launcher.getStatus();
    expect(status.state).toBe('stopped');
    expect(status.pid).toBeNull();
    expect(status.sessionId).toBeNull();
  });

  it('isRunning returns false when not launched', () => {
    const launcher = new CodesysLauncher({
      codesysPath: 'C:\\nonexistent\\CODESYS.exe',
      profileName: 'Test Profile',
      workspaceDir: os.tmpdir(),
    });

    expect(launcher.isRunning()).toBe(false);
  });

  it('executeScript rejects when not ready', async () => {
    const launcher = new CodesysLauncher({
      codesysPath: 'C:\\nonexistent\\CODESYS.exe',
      profileName: 'Test Profile',
      workspaceDir: os.tmpdir(),
    });

    await expect(launcher.executeScript('print("hi")')).rejects.toThrow(/state is 'stopped'/);
  });
});

describe('pathsEqual', () => {
  it('matches identical paths', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS 3.5.21.50\\CODESYS\\Common\\CODESYS.exe',
      'C:\\Program Files\\CODESYS 3.5.21.50\\CODESYS\\Common\\CODESYS.exe'
    )).toBe(true);
  });

  it('is case-insensitive (Windows semantics)', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS 3.5.22.10\\CODESYS\\Common\\CODESYS.exe',
      'c:\\program files\\codesys 3.5.22.10\\codesys\\common\\codesys.exe'
    )).toBe(true);
  });

  it('normalises forward and back slashes', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS 3.5.22.10\\CODESYS\\Common\\CODESYS.exe',
      'C:/Program Files/CODESYS 3.5.22.10/CODESYS/Common/CODESYS.exe'
    )).toBe(true);
  });

  it('trims trailing separators', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS\\',
      'C:\\Program Files\\CODESYS'
    )).toBe(true);
  });

  it('distinguishes different installs', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS 3.5.21.50\\CODESYS\\Common\\CODESYS.exe',
      'C:\\Program Files\\CODESYS 3.5.22.10\\CODESYS\\Common\\CODESYS.exe'
    )).toBe(false);
  });

  it('distinguishes different drives', () => {
    expect(pathsEqual(
      'C:\\Program Files\\CODESYS\\Common\\CODESYS.exe',
      'D:\\Program Files\\CODESYS\\Common\\CODESYS.exe'
    )).toBe(false);
  });
});
