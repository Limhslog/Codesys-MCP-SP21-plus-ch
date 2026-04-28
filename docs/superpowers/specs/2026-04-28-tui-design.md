# In-fork TUI for CODESYS exported ST

**Date:** 2026-04-28
**Author:** Karstein Phobic Nyvold Kvistad
**Status:** Draft, awaiting review
**Repo:** lives inside `Codesys-MCP-SP21-plus` — no separate package

## Purpose

A small interactive TUI that ships **inside this fork** alongside the MCP
server. It serves three roles:

1. **Browser** — at-a-glance overview of a CODESYS project's structured-text
   source as exported by the existing `mirror_export` tool.
2. **Approve gate** — human-in-the-loop diff prompt that the MCP `set_pou_code`
   tool (and any other modifying tool) calls before writing into the binary
   `.project` file.
3. **Selection beacon** — broadcasts the user's current cursor position
   (device, POU, line) via a state file so MCP tool calls grounded in
   "the thing the user is looking at" become possible.

It consumes the synced `.st` files under `<projectDir>/mcp-mirror/`. It does
not talk to CODESYS, does not require the MCP server to be running for the
browser mode, and does not parse the binary `.project`.

## Implementation choice

- **Language:** TypeScript (same as the rest of the fork; one toolchain).
- **TUI library:** `ink` (React-for-terminal). Mature, used by GitHub's CLI
  tooling, Prisma, and others. Compositional in a way that makes the
  multi-pane layouts drawn in the v0.4 mockup tractable.
- **Diff:** `diff` npm package (well-trodden) for unified-diff hunks.
- **Syntax coloring:** `cli-highlight` with a small custom IEC 61131-3 grammar
  added on top, or — if the existing `iecst` highlight.js grammar is good
  enough out of the box — that. Confirm in plan step.
- **Lives at:** `src/tui/` in this repo.

The earlier draft (under `csmirror/` in the user's `repos/` dir) targeted Go
+ Bubble Tea. That is now abandoned; this spec replaces it.

## Phases

The design is split into four increments so each can land independently.
Only v0.1 and v0.2 are intended for immediate implementation.

- **v0.1 — read-only TUI.** Browser + approve modes. Current selection is
  persisted to a state file. No live PLC values.
- **v0.2 — MCP-side hook.** New MCP tool `get_user_selection` reads the
  state file at tool-call time so Claude knows what POU the user is looking
  at. Same fork, same process tree, no new infrastructure.
- **v0.3 — live values inline.** Variable values shown next to declarations
  in the source viewer, polled via the existing `read_variable` tool. Blocked
  on the fork's `connect_to_device` bug being fixed first — see the separate
  "connect_to_device fix" track below.
- **v0.4 — online dashboard.** Optional separate mode (`--online`) with a
  full operator dashboard: tree, live variable table, task list, log panel,
  online/login controls. Mockup retained below for reference. Depends on
  v0.3 plus new MCP tools for task profiling and log streaming that don't
  exist today.

## Modes (v0.1)

The TUI is invoked through a new bin entry on the fork's `package.json`,
called `phobiCS-tui`. (Naming bikeshed welcome — current placeholder.)

### 1. Browser mode (default)

`phobiCS-tui [<projectDir>]`

Interactive split-pane explorer. Read-only with respect to the project
files; the only side effect is updating the state file so external tools
(e.g. the MCP server in the same fork) can see the current selection.

### 2. Approve mode

`phobiCS-tui approve <existingFile> <proposedFile>`

Single-screen diff viewer. The user accepts or rejects with a single key.

- Exit `0` — user accepted. Caller may proceed to write `proposedFile`.
- Exit `1` — user rejected. Caller must abort.
- Exit `2` — TUI error (file unreadable, terminal too small, etc.).

The TUI itself does not write either file — it only reports the user's
decision via exit code. The caller (typically the fork's `set_pou_code`
implementation) does the actual write.

A typical caller:

```ts
// inside src/server.ts when set_pou_code is invoked
const tmp = await stagePoU(proposedCode);
const code = await runApproveTui(mirrorPath, tmp);
if (code !== 0) {
  return { content: [{ type: 'text', text: 'User rejected the change.' }], isError: false };
}
await commitPoU(tmp);
```

A new MCP-server-level config flag `--approve-edits` (default off) gates
this. Off by default so existing batch / scripted usage doesn't break;
the user opts in when they want a human in the loop.

## Architecture

```
Codesys-MCP-SP21-plus/
  src/
    tui/
      index.tsx          — bin entry, argv parsing, mode dispatch
      app.tsx            — top-level ink component
      browser/
        Tree.tsx         — collapsible POU tree
        Viewer.tsx       — source viewer with syntax coloring
        Filter.tsx       — / filter input
      approve/
        Approve.tsx      — diff view + y/n keybind
      shared/
        scan.ts          — walks mcp-mirror/, classifies *.st files
        diff.ts          — wraps the `diff` package, returns hunks
        state.ts         — atomic write of selection state
        keymap.ts        — central keybinding table
    server.ts            — adds get_user_selection tool, optional approve hook
  package.json           — new bin: "phobiCS-tui"
  tests/
    tui/                 — ink-test-rendering snapshots
```

Each TUI source file should stay below ~300 LOC. The `app.tsx` decides
which sub-tree to mount (browser vs approve) based on argv; everything
else is leaf-component or pure data.

## Components

- **`scan.ts`** — walks `mcp-mirror/`, classifies every `.st` by name prefix
  and path:
  - `FB_*.st` → `FB`
  - `GVL_*.st` → `GVL`
  - `ST_*.st` → `STRUCT`
  - `e*.st` (lowercase `e` followed by uppercase) → `ENUM`
  - `PLC_PRG.st` → `PRG`
  - `_MCP_PROJECT_VERSION.st` → `META`
  - File whose parent dir has the same stem as a sibling `.st` → `METHOD`
  - File named `Get.st` / `Set.st` under such a parent → `PROPERTY_GETTER` /
    `PROPERTY_SETTER`
  - Anything else → `OTHER` (still listed, just unclassified)
  Counts non-blank LOC, captures `mtime`, identifies the device (top-level
  subdir under `mcp-mirror/`). Returns a `Project` with nested
  `Device → Folder → POU`.

- **`Tree.tsx`** — collapsible tree. Tracks `expandedPaths: Set<string>`,
  `cursor: string`, supports filter (hide non-matching leaves, keep matching
  ancestors visible). ink doesn't ship a tree, so this is hand-rolled with
  ink-text + box.

- **`Viewer.tsx`** — wraps a scrolling Box. On selection change, reads the
  file, runs it through `cli-highlight` with the IEC 61131-3 grammar, sets
  the content. Falls back to plain text on highlight error.

- **`Approve.tsx`** — renders unified diff with line numbers and ±gutter.
  `y` accepts (exit 0), `n` / `q` / Esc / Ctrl-C reject (exit 1). All
  uncaught errors → exit 2. No "escape without deciding".

- **`scan.ts` + `state.ts`** — `scan` is a pure read; `state` writes the
  selection JSON atomically (`tmp + rename`). State-write failures are
  logged via the fork's logger and swallowed — never crash the TUI on a
  state-write error.

## Browser mode UX

```
┌─ MCPTest2 ─────────── mirror 2h ago · 25 POUs · 1 218 LOC ──────────────┐
│ Tree                        │ PLC_PRG.st                  CodesysRpi 42L│
│ ▾ CodesysRpi       12 POUs  │   1  PROGRAM PLC_PRG                      │
│   ▾ Plc Logic/App           │   2  VAR                                  │
│     PLC_PRG    PRG    42 L  │   3      fb        : FB_Test;             │
│   ▸ FB_Test     FB    87 L  │   4      count     : INT := 0;            │
│     FB_Position FB    31 L  │   5      pos       : FB_Position;         │
│     GVL_Test   GVL     8 L  │   6  END_VAR                              │
│ ▸ PLCWinNT         13 POUs  │   7                                       │
│ Filter: ▮                   │   8  count := count + 1;                  │
├─────────────────────────────┴───────────────────────────────────────────┤
│ j/k nav  ⏎ expand  / filter  d diff devices  o open VSCode  ? help  q   │
└─────────────────────────────────────────────────────────────────────────┘
```

| Key       | Action                                                       |
|-----------|--------------------------------------------------------------|
| `j`/`k`   | Move cursor down/up                                          |
| `h`/`l`   | Collapse / expand current node                               |
| `⏎`       | Toggle expand or load POU into viewer                        |
| `g`/`G`   | Top / bottom of tree                                         |
| `/`       | Enter filter mode                                            |
| `Esc`     | Clear filter / exit current mode                             |
| `d`       | Diff this POU against its counterpart in another device      |
| `o`       | `code <abs-path>` — open in VSCode (best-effort)             |
| `r`       | Re-scan the mirror dir                                       |
| `?`       | Toggle help overlay                                          |
| `q`       | Quit                                                         |

## Approve mode UX

```
┌─ Approve change? FB_Test.st ─── + 4 lines, − 2 lines ───────────────────┐
│   1   FUNCTION_BLOCK FB_Test                                             │
│   2   VAR_INPUT                                                          │
│   3       in : INT;                                                      │
│   4   END_VAR                                                            │
│   5   VAR                                                                │
│ - 6       counter : INT := 0;                                            │
│ + 6       counter : DINT := 0;                                           │
│ + 7       overflow : BOOL;                                               │
│   8   END_VAR                                                            │
│   …                                                                      │
├──────────────────────────────────────────────────────────────────────────┤
│ y accept   n reject   ↑/↓ scroll   v split-pane view   q reject & quit   │
└──────────────────────────────────────────────────────────────────────────┘
```

Defaults to unified diff. `v` toggles a side-by-side split. There is no
"escape without deciding" — `q`, `Esc`, `Ctrl-C`, and SIGTERM all map to
"reject" so a caller never silently auto-accepts on a TUI crash.

## MCP integration (v0.2)

The TUI writes its current selection to a small JSON state file every time
the cursor moves to a different POU:

```
%LOCALAPPDATA%/codesys-mcp/tui-state.json   (Windows)
~/.local/state/codesys-mcp/tui-state.json   (Linux/Mac)
```

```json
{
  "version": 1,
  "updated_at": "2026-04-28T15:32:11Z",
  "project_dir": "C:\\Users\\karstein.kvistad\\Documents\\Claude\\PLC\\MCPTest2",
  "device": "CodesysRpi",
  "selection": {
    "kind": "POU",
    "name": "FB_Test",
    "path": "Plc Logic/Application/FB_Test.st",
    "abs_path": "C:\\...\\mcp-mirror\\CodesysRpi\\Plc Logic\\Application\\FB_Test.st"
  },
  "viewer_line": 12
}
```

Writes are atomic (`tmp + rename`). Stale state files are tolerated — the
MCP-side reader checks `updated_at` is recent (< 60 s) and the file is
nonempty before trusting it; otherwise it returns "no active selection".

The MCP server gets a small new tool, `get_user_selection()`, that returns
this struct. Claude can call it before any modifying tool to ground its
action in what the user is actually looking at.

This is the entire IPC surface for v0.2. No socket, no named pipe, no
process discovery. A flat file is plenty for a single-user dev tool, and
it's trivially debuggable (`Get-Content`).

## v0.4 online dashboard UX (target end-state)

```
┌──────────────────────────────────────────────────────────────────┐
│ ┌─ Devices ────────┐ ┌─ PRG_Main ──────────────────────────────┐ │
│ │                  │ │                                         │ │
│ │ ▼ PLC_PRG        │ │  Variable           Type      Value     │ │
│ │   ▼ Application  │ │  ─────────────────────────────────────  │ │
│ │     ▼ PRGs       │ │  bMotorRun          BOOL      ● TRUE    │ │
│ │     > PRG_Main   │ │  rSetpoint          REAL      72.5      │ │
│ │       PRG_Alarms │ │  rActual            REAL      71.8      │ │
│ │       PRG_HMI    │ │  iState             INT       3         │ │
│ │     ▶ FBs        │ │  sLastError         STRING    ""        │ │
│ │     ▶ DUTs       │ │  tCycleTime         TIME      T#8ms     │ │
│ │   ▶ Library Mgr  │ │                                         │ │
│ │ ▶ Task Config    │ │  [space] toggle  [w] write  [/] filter  │ │
│ │                  │ │                                         │ │
│ └──────────────────┘ └─────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ Tasks ─────────────────────────────────────────────────────┐  │
│ │ MainTask    cyclic   10ms   ████████░░  82%   jitter 0.3ms  │  │
│ │ AlarmTask   event    ─      ██░░░░░░░░  18%   ─             │  │
│ │ VisuTask    cyclic   50ms   ████░░░░░░  41%   jitter 1.1ms  │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─ Log ────────────────────────────────────────── tail -f ────┐  │
│ │ 14:22:01  INFO   Application started                        │  │
│ │ 14:22:14  WARN   PRG_Alarms: tag THP_03 quality bad         │  │
│ │ 14:23:02  INFO   Online change applied (rev 47)             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ [tab] panel  [enter] drill  [o]nline  [l]ogin  [?]help  [q]uit   │
└──────────────────────────────────────────────────────────────────┘
```

### What v0.4 needs that we don't have today

- **Working `connect_to_device`.** Investigated 2026-04-28; root cause is
  in `src/scripts/connect_to_device.py` (lines 46–48 + 76–92) and
  `src/scripts/ensure_online_connection.py` (lines 133–135 + 161–168).
  Two bugs:
  1. The script probes for `OnlineChangeOption.TryOnlineChange` — that
     member never existed. The real members are `Never`, `Try`, `Force`
     ([helpme-codesys.com — Using Scripts to Access CODESYS](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_access_cds_func_in_python_scripts.html)).
  2. The fallback ladder calls `login()` with zero args; the documented
     SP21+ signature is `login(OnlineChangeOption, bool)`. The no-arg
     call is what surfaces the misleading
     `TypeError: login() takes exactly 2 arguments (0 given)`.
  Fix: change the probe order to `('Try', 'Force', 'Never')` and replace
  the bool/no-arg fallbacks with `login(<member>, True)` /
  `login(<member>, False)` / `login(<member>)` only. **Tracked as a
  separate fork PR — not part of this spec.**
- **`connect_to_device` MCP arg surface change (recommended).** Add
  `onlineChangeMode: 'try' | 'force' | 'never'` (default `'try'`) and
  `loginSecondArg: bool` (default `true`) so callers get a deterministic
  login instead of a probe. Same args should land on `download_to_device`
  for symmetry.
- **Task profiling tool.** The MCP has no `list_tasks` / `get_task_stats`
  tool today. CODESYS scripting can read `IECTask` objects via the
  online application. New MCP tool needed.
- **Log streaming tool.** No `tail_log` tool today. Two viable sources:
  CODESYS device log (online; via scripting), or PLC application log over
  SSH (Linux PLCs only). New MCP tool needed.
- **`write_variable` confirmation flow.** v0.4 binds `w` to it but should
  require an explicit confirm prompt before any write — operator safety,
  not an "oops" key.

## Data flow

### Browser mode
1. `index.tsx` resolves project dir (argv or auto-discover by walking up
   from cwd for a `mcp-mirror/` sibling next to a `*.project` file).
2. `scan.walk(dir)` returns `Project`.
3. ink renders `<App project={...} />`. Cursor is local React state.
4. Keypress → state update → React re-renders. If POU selection changed,
   `state.write(...)` runs (debounced 200 ms) and the viewer re-reads the
   file.
5. `r` re-runs `scan.walk()`. `o` shells out to `code` (or `$EDITOR`).

### Approve mode
1. `index.tsx` reads both files into memory.
2. `diff.compute` produces hunks.
3. ink renders `<Approve />`.
4. Keypress → exit with the appropriate code. No file writes.

## Error handling

- Mirror dir absent → before mounting ink, print
  `No mcp-mirror/ found at <path>. Run mirror_export in CODESYS first.`
  to stderr and exit 1. No splash screen, no broken renders.
- Mirror dir mtime older than the sibling `*.project` mtime → orange
  "stale mirror" tag in the top statusbar; doesn't block usage.
- Per-file read error during browse → in-pane red banner; the rest of the
  TUI keeps working.
- Terminal smaller than 80×20 → dedicated "please resize" screen.
- In approve mode, any panic / signal / I/O error → exit 2 (so the caller
  can distinguish "user said no" from "TUI broke").

## Testing

- **`scan` unit tests.** Commit a trimmed copy of MCPTest2's `mcp-mirror/`
  and a hand-curated subset of X33's MRLib under `tests/tui/fixtures/`.
  Assert classification, LOC, device, and `mtime`-relative-to-fixture for
  every file.
- **ink component tests.** `ink-testing-library` with snapshot output for
  Tree / Viewer / Approve. Driven keypress sequences for navigation tests.
- **`diff` tests.** Standard add/del/ctx hunk assertions on hand-crafted
  before/after pairs.
- **End-to-end approve test.** Spawn the built binary with
  `approve <a> <b>` against tmp files; assert exit codes for accept/reject
  paths. Use a PTY-aware test helper since ink needs a TTY.
- **No CODESYS-in-the-loop tests.** The fork already has those for MCP
  tooling; the TUI doesn't add any new CODESYS interactions in v0.1/v0.2.

## Distribution

- New bin entry in the fork's `package.json`:
  `"phobiCS-tui": "dist/tui/index.js"`.
- Same npm install path as the MCP server. Users who already have the fork
  installed get the TUI for free on next `npm i -g`.
- No prebuilt binaries, no separate release. The fork is the single
  distribution unit.

## Explicit YAGNI cuts

These were considered and deferred:

- **No write-back to `.st` files in browser mode.** Editing happens via
  `o` → external editor → next `r` rescan.
- **No fsnotify live watch on the mirror dir.** Manual `r` only. (The
  fork's existing `--auto-mirror` already keeps the mirror current
  whenever Claude touches it; the user just hits `r` after their own edits.)
- **No theming / config file.** Sane defaults, follow `NO_COLOR` and
  `CLICOLOR_FORCE` env vars but nothing else.
- **No git-history diff.** Cross-device diff (browser mode `d`) and
  before/after diff (approve mode) only.
- **No project-wide ST text search.** The tree filter (`/`) covers POU
  names; full-text search is deferred.
- **Approve gate is opt-in.** Existing automation flows that don't want a
  human in the loop are not regressed by default.

## Decisions (locked 2026-04-28)

1. **Bin name:** `phobiCS-tui`. Confirmed.
2. **Approve-mode invocation contract:** **two file paths**, not stdin.
   See "Approve-mode invocation — chosen contract" below.
3. **v0.4 scope:** documented future direction only. Writing-plans covers
   v0.1 + v0.2 only.
4. **Live values shape (v0.3):** inline next to `VAR` declarations.
   Dedicated table reserved for v0.4 dashboard.
5. **Approve gate default:** **off by default**. Opt in via
   `--approve-edits` on the MCP server CLI. Scripted / batch flows are
   not regressed. The user turns on the human-in-the-loop explicitly
   when they want it. Confirmed.

## Approve-mode invocation — chosen contract

Two file paths:

```
phobiCS-tui approve <existing> <proposed>
```

- `<existing>` — current on-disk file (typically the mirror `.st`).
- `<proposed>` — staged candidate. Caller writes this to disk before
  invoking the TUI.

Why not stdin: stdin breaks debuggability (the proposed content isn't
viewable from another shell while the TUI is open), brings PowerShell vs
bash encoding/line-ending differences into the contract, and complicates
the test harness. The marginal "no temp file" win isn't worth those
costs for a single-user dev tool.

The caller pattern in the fork's `set_pou_code` becomes:

```ts
// inside set_pou_code handler
const stagedPath = path.join(mirrorDir, `${poUName}.staged.st`);
await fs.writeFile(stagedPath, proposedCode, 'utf8');
try {
  const exit = await runApproveTui(currentPath, stagedPath);
  if (exit === 0) {
    await fs.rename(stagedPath, currentPath);   // commit to mirror
    await applyToProject(currentPath);          // and into .project
  } else if (exit === 1) {
    return userRejectedResponse();              // graceful no-op
  } else {
    throw new Error(`phobiCS-tui errored (exit ${exit})`);
  }
} finally {
  await fs.rm(stagedPath, { force: true });     // best-effort cleanup
}
```

The user can also `Get-Content $stagedPath` mid-prompt if they want to
inspect the candidate outside the TUI.
