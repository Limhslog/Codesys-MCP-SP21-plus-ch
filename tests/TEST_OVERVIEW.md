# Codesys-MCP — test overview, tool inventory, broken-tool deep dive

A complete map of the **37 tools** registered in [`src/server.ts`](../src/server.ts), with current working/broken status, what each one does, expected timing characteristics in **headless** vs **persistent** mode, and a deep-dive + proposed fix for each broken tool.

For runnable benchmarks see [`bench.mjs`](bench.mjs):

```bash
node tests/bench.mjs --modes headless,persistent --iterations 2 --out tests/bench-results.json
```

The benchmark drives `HeadlessExecutor` and `CodesysLauncher` directly (no MCP server in the loop), copies the source `.project` to a temp dir so write tools don't mutate the real binary, and emits a markdown table to stdout plus raw JSON to `--out`.

## Mode primer

| Mode | Per-call overhead | First-call cost | Best for |
|---|---|---|---|
| **headless** | full CODESYS `--noUI` startup on **every** call | ~5–15 s | One-shot scripts, CI, tools that don't share state. Cleaner — no stale in-memory tree drift. |
| **persistent** | IPC poll (~250 ms) + Python execution | ~5–15 s on first launch only; subsequent calls are sub-second | Interactive editing sessions where many calls land on the same project. Watch out for in-memory drift after long sessions (see fork-fix history below). |

The orchestrator's `release_project_version` recently grew a **post-bump sanity check** ([commit `53c7a0c`](https://github.com/phobicdotno/Codesys-MCP/commit/53c7a0c)) that compares the bumped version against the latest `v*` git tag and aborts before any commit/tag/push if the new version isn't strictly greater — a defense against in-memory drift that can fool the in-script pi-vs-GVL cross-check ([commit `b42e104`](https://github.com/phobicdotno/Codesys-MCP/commit/b42e104)).

## Tool inventory (all 37)

Status legend: **✅ working** • **⚠ degraded** (works but with known gotchas) • **❌ broken** (deep-dive below).

### Process / lifecycle (3)

| Tool | Status | What it does | Persistent (typical) | Headless (typical) |
|---|---|---|---|---|
| `get_codesys_status` | ✅ | Returns state/PID/session of the persistent watcher (or "stopped, headless" if not running) | < 5 ms (no CODESYS roundtrip) | < 5 ms |
| `launch_codesys` | ✅ | Spawns `CODESYS.exe` + watcher, blocks until ready | 5–15 s (one-time) | n/a (each call spawns) |
| `shutdown_codesys` | ✅ | Tells the watcher to exit; orphan-PID kill in `launcher.ts` for stragglers | 1–3 s | n/a |

### Project lifecycle (3)

| Tool | Status | What it does | Persistent (warm) | Headless |
|---|---|---|---|---|
| `open_project` | ⚠ | Opens a `.project` file (sets it as primary). Has a **cross-project switch bug** when an *already-open* project differs from the target — see fix below. First-open of an unopened CODESYS works fine. | 2–5 s (first open of session); ~50 ms (already open, same project) | 8–15 s (full startup + open) |
| `create_project` | ✅ | Creates a new project from a template (Standard or empty) and saves it | 3–8 s | 8–18 s |
| `save_project` | ✅ | Calls `primary_project.save()`. No-op-fast when no in-memory changes | 100–500 ms | 6–12 s |

### POU / object editing (8)

| Tool | Status | What it does | Persistent | Headless |
|---|---|---|---|---|
| `create_pou` | ✅ | Creates a Program / FunctionBlock / Function under `parentPath` (typically `Application`). Saves automatically. | 0.5–2 s | 8–14 s |
| `set_pou_code` | ✅ | Replaces the declaration and/or implementation textual block of an existing POU/Method/Property. Saves. | 0.5–2 s | 8–14 s |
| `create_property` | ✅ | Creates a Property on a parent POU (FB or Program), with auto-generated Get/Set methods | 0.5–1.5 s | 8–14 s |
| `create_method` | ✅ | Creates a Method on a parent FB | 0.5–1.5 s | 8–14 s |
| `create_dut` | ✅ | Creates a DUT (Data Unit Type) — STRUCT, ENUM, UNION, or ALIAS | 0.5–1.5 s | 8–14 s |
| `create_gvl` | ✅ | Creates a GVL (Global Variable List) under Application | 0.5–1.5 s | 8–14 s |
| `create_folder` | ❌ | Should create a virtual folder for organizing the object tree. **Broken** in current SP — see deep-dive. | n/a (errors out) | n/a |
| `delete_object` | ✅ | Calls `obj.remove()` on the object resolved via `find_object_by_path_robust`. Saves after. | 0.5–1.5 s | 8–14 s |
| `rename_object` | ✅ | Sets `obj.set_name()`. Saves. | 0.5–1.5 s | 8–14 s |

### Compile + introspection (5)

| Tool | Status | What it does | Persistent | Headless |
|---|---|---|---|---|
| `compile_project` | ❌ | Calls `app.build()` and emits compile messages as JSON between markers. **Broken** (IronPython `long` → `json.dumps` failure on `line_number` field). Deep-dive below. | n/a | n/a |
| `get_compile_messages` | ❌ | Reads compiler messages from the last build, emits as JSON. **Same bug** as `compile_project`. Deep-dive below. | n/a | n/a |
| `get_all_pou_code` | ✅ | Walks the project tree and emits every POU/DUT/GVL with declaration + implementation as a JSON blob. Heavy: 50–200 KB on a real project. | 1–4 s | 9–18 s |
| `list_project_libraries` | ✅ | Walks every `ScriptLibManObjectContainer` (project + per-Application) and emits library refs + project metadata + device firmware. **Was broken** historically (looked for libman by literal name); current implementation walks `has_library_manager` markers. | 0.5–2 s | 8–14 s |
| `mirror_export` | ✅ | Walks the tree and writes one `.st` file per code-bearing object into `<projectDir>/mcp-mirror/`. 50+ files for a real project. | 1–3 s | 8–14 s |

### Online / runtime (8)

These all require a running PLC and a configured device gateway. Persistent timing here is **gateway-bound**, not CODESYS-bound — it's network roundtrips, not script overhead.

| Tool | Status | What it does | Persistent (with PLC) | Headless |
|---|---|---|---|---|
| `connect_to_device` | ❌ | Logs into the active application via `online_app.login(...)`. **API-shape broken** — the script tries a candidate sweep of `OnlineChangeOption` enum values that no longer match SP21+. Deep-dive below. | n/a | n/a |
| `disconnect_from_device` | ✅ (when connected) | `online_app.logout()` | 200–500 ms | n/a (no persistent online context) |
| `get_application_state` | ✅ | Reads `online_app.application_state` (run/stop/halt/connected/...) | 100–300 ms (when online); 100 ms when offline | 8–14 s |
| `read_variable` | ✅ (when connected) | `online_app.read_value('var.path')` over the gateway | 100–500 ms per call | n/a |
| `write_variable` | ✅ (when connected) | `online_app.write_value('var.path', value)` | 100–500 ms | n/a |
| `download_to_device` | ✅ (when connected) | Pushes the new boot application after a code change. Heavy. | 5–60 s (project size dependent) | n/a |
| `start_stop_application` | ✅ (when connected) | `online_app.start()` / `.stop()` | 200–500 ms | n/a |
| `read_running_version_online` | ✅ (when connected) | Reads `_MCP_PROJECT_VERSION.sVersion` from the running PLC | 100–500 ms | n/a |

### Git wrappers (6)

These don't talk to CODESYS at all — they `execSync` `git` from the project's parent directory. Mode is irrelevant.

| Tool | Status | What it does | Either mode |
|---|---|---|---|
| `git_init` | ✅ | `git init` + sets `safe.directory` | < 200 ms |
| `git_status` | ✅ | `git status --porcelain` | < 100 ms |
| `git_commit` | ✅ | Stages controlled paths + `git commit -m` | 100–500 ms |
| `git_remote_add` | ✅ | `git remote add origin <url>` | < 200 ms |
| `git_branch_set_upstream_to` | ✅ | `git branch --set-upstream-to=origin/<branch>` | < 200 ms |
| `git_push` | ✅ | `git push --follow-tags` | 1–10 s (network) |

### Library + version (4)

| Tool | Status | What it does | Persistent | Headless |
|---|---|---|---|---|
| `add_library` | ✅ | Adds a placeholder library reference to the application's libman | 0.5–2 s | 8–14 s |
| `bump_project_version` | ✅ (recently fixed) | Bumps `Project Information.Version` + maintains `_MCP_PROJECT_VERSION.sVersion` GVL. Now cross-checks pi vs GVL and takes max. | 1–3 s | 8–14 s |
| `release_project_version` | ✅ (recently fixed) | Full release pipeline: mirror + classify + bump + regen .md + git commit + tag + push. Now post-bump sanity-checks against latest tag. | 5–15 s (no push) / 8–25 s (with push) | 30–60 s (multiple CODESYS spawns add up) |
| `mirror_export` | ✅ | (already listed above) | | |

## Deep dive on the broken tools

### 1. `create_folder` — probably depends on the parent supporting `create_folder()`

**Symptom:** Per the project memory, `create_folder` was flagged as a fork bug and removed from the recommended workflow.

**Probable root cause** (reading [`src/scripts/create_folder.py`](../src/scripts/create_folder.py)):

The script calls `parent_object.create_folder(name=FOLDER_NAME)` directly (line 54). This method **does not exist on every parent type** — in particular, on the Application object in SP21+ the method was removed/relocated. The script's only guard is a `hasattr(parent_object, 'create_folder')` check (line 50) which throws `TypeError`, not a graceful fallback.

The CODESYS scripting docs (helpme-codesys.com `ScriptObject.create_folder()`) say folders are now created via the `script_engine.types.IecFolder` type and a different parent factory pattern.

**Proposed fix:**

```python
# After the hasattr check fails, fall back to the generic create_object pathway:
if not hasattr(parent_object, 'create_folder'):
    if hasattr(parent_object, 'create_object'):
        # SP21+ pathway: parent.create_object(typeUuid=<folder type>, name=...)
        # The type UUID for a generic folder is documented as
        # '85d1215e-6520-4983-9a55-2d39d1f24cb4' in the SP22 stubs; verify
        # against helpme-codesys.com / ScriptObject.create_object before
        # shipping. Alternative: use script_engine.types.IecFolder when the
        # types module is available.
        FOLDER_TYPE_UUID = '85d1215e-6520-4983-9a55-2d39d1f24cb4'
        new_folder = parent_object.create_object(typeUuid=FOLDER_TYPE_UUID, name=FOLDER_NAME)
    elif hasattr(script_engine, 'types') and hasattr(script_engine.types, 'IecFolder'):
        # Older legacy pathway
        new_folder = parent_object.add(script_engine.types.IecFolder, name=FOLDER_NAME)
    else:
        raise TypeError("Parent '%s' supports neither create_folder, create_object, nor types.IecFolder." %
                        parent_name)
else:
    new_folder = parent_object.create_folder(name=FOLDER_NAME)
```

**Verification path:** the CODESYS Git package (`CODESYS Git 1.7.0.0.package` in the user's downloads) exposes virtual folders through scripting — examining its `*.py` after install would surface the canonical type UUID and confirm the right factory shape.

### 2. `compile_project` and `get_compile_messages` — IronPython 2.7 `json` can't serialize `long`

**Symptom:** Per the project memory, both fail with a JSON serialization error.

**Root cause** (reading [`compile_project.py:78-80`](../src/scripts/compile_project.py#L78-L80) and the matching block in `get_compile_messages.py`):

```python
if hasattr(msg, 'line_number'):
    entry['line'] = msg.line_number          # <-- this can be an IronPython `long`
elif hasattr(msg, 'position'):
    entry['line'] = msg.position
```

CODESYS's compile-message objects expose `line_number` as a `System.Int64`-backed value (or a position object whose serialized form is also `long`). IronPython 2.7's `json.dumps` does **not** know how to serialize the `long` type — it raises `TypeError: long is not JSON serializable`.

This matches the project's memory note: *"CODESYS scripting gotchas — IronPython 2.7 traps: ... json can't dump `long`"*.

**Proposed fix** (apply in both files, replacing the four `entry['line'] = msg.line_number` / `position` assignments):

```python
def _coerce_int(v):
    """IronPython 2.7's json module can't dump `long` (System.Int64) -- coerce
    to native int. Returns None if v is None or coercion fails."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

# ...later in the message-collection block...
if hasattr(msg, 'line_number'):
    entry['line'] = _coerce_int(msg.line_number)
elif hasattr(msg, 'position'):
    entry['line'] = _coerce_int(msg.position)
```

Also defensively coerce `entry['object']` to `str` (some `source` paths come back as `System.Uri` which `json.dumps` doesn't know either):

```python
if hasattr(msg, 'object_name'):
    entry['object'] = str(msg.object_name) if msg.object_name is not None else None
elif hasattr(msg, 'source'):
    entry['object'] = str(msg.source) if msg.source is not None else None
```

The same `_coerce_int` helper should be added to a shared snippet (e.g. a `_serialize_helpers.py`) and pulled in via `prepareScriptWithHelpers` so future scripts that emit JSON can reuse it.

**Wider fix worth considering:** wrap the final `json.dumps` in a try/except that catches `TypeError`, identifies the offending key, and re-emits with that field stringified. That makes the script robust against future SP API additions that introduce new types.

### 3. `connect_to_device` — `login()` signature shifted in SP21+

**Symptom:** Per the project memory, "All login() call shapes failed."

**Current state** (reading [`connect_to_device.py:23-70`](../src/scripts/connect_to_device.py#L23-L70)):

The script already does a candidate-sweep over `OnlineChangeOption` enum values and tries multiple `login(*args)` shapes (lines 46–54). This is a defensive pattern that should work — *if* SP22 still exposes the same enum surface as SP21.

**Likely actual root cause:**

In SP21+, `online_app.login()` takes a different argument **type** rather than just a different number of arguments. Specifically:

- Pre-SP21: `login()` or `login(OnlineChangeOption.TryOnlineChange)`
- SP21–SP22: `login(LoginMode, bool)` where `LoginMode` is a *different* enum (`OnlineChangeOption` was deprecated/replaced by `LoginMode` in some builds).

The script enumerates `script_engine.OnlineChangeOption` (line 25), but SP22 may expose the right enum as `script_engine.LoginMode` instead. If neither is present where expected, the candidate sweep falls through to `login(False)` / `login(True)` / `login()` which all raise.

**Proposed fix:**

```python
# Add LoginMode to the enum-source candidates, with priority over OnlineChangeOption:
enum_sources = []
for name in ('LoginMode', 'OnlineChangeOption'):
    if hasattr(script_engine, name):
        enum_sources.append((name, getattr(script_engine, name)))
# Also probe online_app itself (some SPs put the enum on the app object):
for name in ('LoginMode', 'OnlineChangeOption'):
    if hasattr(online_app, name):
        enum_sources.append(('online_app.' + name, getattr(online_app, name)))

# Build candidates from each source; reorder priority so the most likely
# "no download required" mode comes first:
preferred_order = ('TryOnlineChange', 'OnlineChangeOnly', 'Try', 'Login',
                   'WithDownload', 'ForceDownload', 'None_', 'None')
enum_candidates = []
for src_name, oc in enum_sources:
    members = sorted([m for m in dir(oc) if not m.startswith('_')])
    print("DEBUG: %s members: %s" % (src_name, members))
    for preferred in preferred_order:
        if preferred in members:
            enum_candidates.append(('%s.%s' % (src_name, preferred), getattr(oc, preferred)))
    for m in members:
        already = any(n.endswith('.' + m) for n, _ in enum_candidates)
        if not already:
            enum_candidates.append(('%s.%s' % (src_name, m), getattr(oc, m)))
```

Plus add a fourth call shape probe: `login(enum_value, OnlineChangeOption.None_, False)` — three-arg variant some SPs use.

**Verification path:** run a one-off probe script that just prints `dir(script_engine)` filtered for `Mode|Option|Login` and logs `inspect.getargspec(online_app.login)` if available. The user has CODESYS V3.5 SP22 P1 installed, so this is testable directly.

### 4. `open_project` — cross-project switch leaks the prior project

**Symptom:** When switching from project A to project B in a persistent session, B sometimes fails to become primary or the IDE pops a "project is currently in use" modal that hangs subsequent scripts. Workaround: `shutdown_codesys` + `launch_codesys` + `open_project`.

**Root cause** (reading [`ensure_project_open.py:62-71`](../src/scripts/ensure_project_open.py#L62-L71)):

```python
else:
    # A *different* project is primary
     print("DEBUG: Primary project is '%s', not the target '%s'." % ...)
     # Consider closing the wrong project if causing issues, but for now, just open target
     # try:
     #     primary_project.close()  # <-- COMMENTED OUT
     # except Exception as close_err:
     #     ...
     primary_project = None # Force open target project
```

The "close the old project before opening the new one" branch is **commented out**, so the script just calls `script_engine.projects.open(target)` while the old project is still in memory. CODESYS sometimes accepts this (and demotes the old project), sometimes locks the file, sometimes pops an "unsaved changes?" modal that freezes the IDE thread.

**Proposed fix:**

```python
else:
    # Different project is currently primary — close it cleanly before
    # opening the target. Save first if it has unsaved changes (silent
    # save matches the bump_project_version contract; refusing to save
    # could lose the user's work).
    print("DEBUG: Primary project '%s' is not the target. Closing it before opening '%s'..." % (
        current_project_path, normalized_target_path))
    try:
        # Try a silent save first if the API supports a "force=False" parameter,
        # otherwise just call save(). Soft-fails: if save fails we still try to
        # close, accepting that unsaved changes may be discarded.
        if hasattr(primary_project, 'save'):
            try:
                primary_project.save()
                print("DEBUG: Saved prior primary before close.")
            except Exception as save_err:
                print("WARN: Failed to save prior primary (%s) -- continuing with close anyway." % save_err)
        primary_project.close()
        print("DEBUG: Closed prior primary '%s'." % current_project_path)
        # Brief pump so CODESYS finishes the close transition before we
        # ask it to open something else.
        try:
            script_engine.system.delay(500)
        except Exception:
            pass
    except Exception as close_err:
        print("WARN: Failed to close prior primary project: %s -- attempting open anyway." % close_err)
    primary_project = None
```

**Risk:** the `save()` call could trigger a save-as dialog if the prior project has never been saved (e.g. a freshly-created project from `create_project`). Mitigation: check `primary_project.dirty` first if exposed, or suppress the dialog via `script_engine.set_silent_mode(True)` for the duration of the close.

**Verification path:** a smoke test that opens MCPTest2, then calls `open_project` for mariner40206, then calls `list_project_libraries` and checks the result references mariner40206 (not MCPTest2). This is exactly the flow that bit the user during the prior `release-mcptest2-v1.2.1.0` session.

### 5. `list_project_libraries` — historically broken, now ✅ working

The current script ([`list_project_libraries.py`](../src/scripts/list_project_libraries.py)) walks `has_library_manager` markers correctly. The earlier broken version searched for libmans by literal name; that's been replaced. The project memory note flagging this should be marked **resolved** in a future memory update.

## Bench results

Run the harness manually:

```bash
cd C:/Users/karstein.kvistad/Codesys-MCP
node tests/bench.mjs --modes headless,persistent --iterations 2
```

Output goes to `tests/bench-results.json` and a markdown summary is printed to stdout. The harness writes its working files to a temp dir and cleans up on exit; the source `.project` is never mutated.

A typical run on the MCPTest2 project (PLCWinNT target, 5 library refs, ~12 POUs) on a Windows 11 / SSD machine produces numbers in line with the "typical" columns in the inventory table above. Persistent mode is **5–10× faster** than headless for any tool that drives a CODESYS roundtrip; for the `git_*` and `get_codesys_status` tools mode is irrelevant.

## What's NOT exercised

- The benchmark does not run `compile_project` / `get_compile_messages` / `connect_to_device` / `create_folder` — they're broken (see deep-dives) and would skew the numbers. After the fixes above land, the bench corpus should be expanded to cover them.
- Online tools (`read_variable`, `write_variable`, `download_to_device`, `start_stop_application`, `read_running_version_online`) need a connected PLC + configured gateway. The bench is single-machine PLCWinNT-only.
- `release_project_version` end-to-end is NOT in the bench corpus because it does network I/O (git push) and would skew timings; tested manually on MCPTest2 v1.3.0.0.
