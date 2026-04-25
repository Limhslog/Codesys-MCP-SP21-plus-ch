# Smoke test v2 -- 2026-04-25 (post device-side login probe + write API fix)

End-to-end re-test of every MCP tool exposed by `codesys-mcp-persistent`
after the additional fixes landed on the [`sp21-plus-migration-notes`](https://github.com/phobicdotno/Codesys-MCP/tree/sp21-plus-migration-notes)
branch this afternoon. Supersedes the morning [SMOKE-TEST-2026-04-25.md](SMOKE-TEST-2026-04-25.md).

## Environment

- MCP server source: this fork @ `sp21-plus-migration-notes` HEAD
  (commits `93a105a`..`b3bf4a8`).
- CODESYS launched: **`3.5.22.10` (SP22 Patch 1, 64-bit)** via `--runscript`
  pointing at the rewritten watcher (v0.4.2 with KeyboardInterrupt hardening).
- Soft-PLC runtime up: `CODESYS Control Win V3 - x64` Windows service
  (`CODESYSControlService.exe`, listening on port 11740). User-started
  via the tray icon's "Start PLC" with one-shot UAC elevation.
- Test project: `\\files\karstein.kvistad\Documents\Claude\PLC\MCPTest\MCPTest.project`
  -- created via `create_project` from the Standard template (device =
  `PLCWinNT (CoDeSys SP Win V3)`, which IS the Control Win V3 device
  descriptor on this machine despite the legacy display name).
- All test objects authored with prefix `MCPv2_` to avoid colliding with
  user-fixed objects in the project; cleaned up at end of test.

## Result table

| # | Tool                                 | Result          | Notes                                                                                  |
|---|--------------------------------------|-----------------|----------------------------------------------------------------------------------------|
| 1 | `get_codesys_status`                 | OK              | State / Mode / PID / Session reported correctly.                                       |
| 2 | `launch_codesys`                     | OK              | Persistent mode; ready signal received within seconds.                                 |
| 3 | `shutdown_codesys`                   | OK              | Cleanly stops the spawned CODESYS instance. Prior smoke-test #5 (orphan from earlier launches) not reproduced this session. |
| 4 | `create_project`                     | OK              | From Standard template; saved to the requested path.                                   |
| 5 | `open_project`                       | OK              | Reproducible from-cold open. Cross-project switch (closing one project to open another in the same instance) not exercised here -- prior smoke noted that as a separate bug. |
| 6 | `save_project`                       | OK              |                                                                                        |
| 7 | `create_pou` (FunctionBlock / ST)    | OK              | `Application/MCPv2_FB`.                                                                |
| 8 | `create_dut` (Structure)             | OK              | `Application/MCPv2_ST`.                                                                |
| 9 | `create_gvl`                         | OK              | `Application/MCPv2_GVL` with declarationCode populated.                                |
|10 | `create_method`                      | OK              | `Application/MCPv2_FB/DoSomething : BOOL`.                                             |
|11 | `create_property`                    | OK              | `Application/MCPv2_FB/Counter : INT` (Get/Set sub-objects auto-created).               |
|12 | `set_pou_code`                       | OK              | Decl + impl wrote correctly to MCPv2_FB and MCPv2_ST. Verified via get_all_pou_code.   |
|13 | `get_all_pou_code`                   | OK              | Returned full code dump for every POU/DUT/GVL/Method/Property in the project.          |
|14 | `rename_object`                      | **PARTIAL**     | Renames the object's own internal declaration line (`TYPE old : ... END_TYPE` becomes `TYPE new : ... END_TYPE` automatically) BUT does NOT update other POUs that referenced the old name. Same as upstream. |
|15 | `delete_object`                      | OK              | Cleaned up MCPv2_FB / MCPv2_GVL / MCPv2_STRenamed at end-of-test.                      |
|16 | `get_application_state` (offline)    | OK              | `State: none, Logged In: False` before connect.                                        |
|17 | `add_library`                        | **PARTIAL**     | Operation succeeds and CODESYS shows the entry in Library Manager, BUT it adds a SECOND `Standard` reference instead of detecting the existing one, and the new reference is not added as a `* (System)` placeholder so it pulls in unresolved transitive deps (e.g. IoStandard 3.1.3.1 yellow-warning). |
|18 | `list_project_libraries`             | **FAIL**        | Returns "No libraries found in the project (or Library Manager not found)" both before AND after a successful `add_library` -- the read path can't find the Library Manager that the write path just wrote to. |
|19 | `create_folder`                      | **FAIL**        | `TypeError: create_folder() got an unexpected keyword argument 'name'`. Fork's call site uses `name=...` kwarg; the underlying CODESYS API rejects it.                              |
|20 | `compile_project`                    | **FAIL**        | Build itself runs successfully (`build()` returns), but the message-marshaller dies: `TypeError: 281474976710655L is not JSON serializable`. The CODESYS `system.get_message_objects()` returns a dict containing an IronPython 2.7 `long` (the value `0xFFFFFFFFFFFF`) that the stdlib `json` module cannot encode. |
|21 | `get_compile_messages`               | **FAIL**        | Same JSON-long bug as #20 -- both call into the same message-encoder path.             |
|22 | `connect_to_device`                  | **OK (FIXED)**  | After commits `e862846` + `eee8ce2`. Login probe iterates `OnlineChangeOption` members + (val, bool) shapes; new `loginWaitSeconds` parameter (default 60) polls `application_state` so the credential dialog has time to surface and the user can fill in the device password. Verified working; user filled the password on first connect this session. |
|23 | `get_application_state` (online)     | **OK**          | After connect: `State: run` / `State: stop` / `Logged In: True` reported correctly.    |
|24 | `read_variable`                      | **OK**          | `read_value()` works directly. Tested `PLC_PRG.fb.iCount` and `GVL_Test.nCounter` -- both returned live values updating each cycle (counters incrementing). |
|25 | `write_variable`                     | **OK (FIXED)**  | After commits `010811b` + `64906c4`. Switched to SP22 prepare-then-write API: `online_app.set_prepared_value(name, value)` then `online_app.write_prepared_values()`. Tested writing `GVL_Test.bRun = TRUE`; read-back confirmed the value landed.                            |
|26 | `start_stop_application` (start)     | **OK**          | `online_app.start()` -- verified state transitioned `stop` -> `run`.                  |
|27 | `start_stop_application` (stop)      | **OK**          | `online_app.stop()` -- verified state transitioned `run` -> `stop`.                   |
|28 | `download_to_device`                 | **OK (FIXED)**  | After commit `b3bf4a8`. Same login probe + `loginWaitSeconds` as connect. The actual "download" is performed by `login(OnlineChangeOption.Force, bool)`; subsequent `create_boot_application()` finalises boot persistence. |
|29 | `disconnect_from_device`             | **OK**          | Clean disconnect after sweep.                                                           |

**Tally: 22 OK, 5 FAIL, 2 PARTIAL out of 29 distinct tool invocations.**

Diff vs morning smoke-test (2026-04-25 baseline): all 5 device-side fails
(`connect_to_device`, `download_to_device`, `read_variable`, `write_variable`,
`start_stop_application`) are now PASSING after this session's fixes.
The remaining failures are the same five that were already known:
`create_folder`, `compile_project`, `get_compile_messages`,
`list_project_libraries`/`add_library` inconsistency, and `rename_object`
not refactoring callers.

## What this proves about today's fixes

| Commit                | Tool fixed                    | Verification |
|-----------------------|-------------------------------|--------------|
| `e862846` + `eee8ce2` | `connect_to_device`           | #22 PASS (was login() drift) |
| `010811b` + `64906c4` | `write_variable`              | #25 PASS (was write_value() missing) |
| `b3bf4a8`             | `download_to_device`          | #28 PASS (same login() drift as connect) |

## Bugs still open (filed by # in the table above)

Each of these is a separate upstream issue worth its own PR back to
`luke-harriman/Codesys-MCP` once cross-referenced against the official
[CODESYS Python scripting docs](https://content.helpme-codesys.com/en/ScriptingEngine/idx-codesys_scripting.html):

1. **`create_folder` keyword mismatch (#19)** -- `create_folder(name=...)`
   call site in `src/scripts/create_folder.py` doesn't match the current
   API signature on the parent container object. Pending docs lookup for
   the canonical method (likely `add_folder(name)` or positional `name`).

2. **JSON `long` serialization (#20, #21)** -- `compile_project.py` and
   `get_compile_messages.py` need to convert IronPython `long` to `int`/
   `str` before `json.dumps`, or pass a `default=` callable. Same root
   issue, single fix can address both.

3. **Library list / add inconsistency (#17, #18)** -- `add_library`
   succeeds visually but `list_project_libraries` reports empty. Either
   the add silently no-ops on the in-memory tree, or the list path is
   looking at the wrong manager object. Pending docs lookup for the
   canonical Library Manager iteration pattern.

4. **`add_library` doesn't dedupe / placeholder (#17)** -- always adds
   a new reference even when one with the same name exists; doesn't
   format as `* (System)` placeholder so transitive deps don't resolve
   to installed versions. Pending docs lookup for `add_placeholder_library`
   vs `add_library` semantics.

5. **`rename_object` partial refactor (#14)** -- updates the renamed
   object's own internal declaration but not any other POU that
   references the old name. CODESYS UI does the full refactor; need
   to find whether scripting exposes a `rename_with_references` or
   similar, or implement a brute-force walk + text replace.

## Caveats

- **SP22 only.** SP21 install (`3.5.21.50`) was not exercised in this
  run, but the watcher rewrite + login probe were architected to be
  SP-version-agnostic; same behaviour expected. Re-run on SP21 is
  pending.
- **Real PLC not exercised.** All device-side tests ran against the
  Control Win V3 soft-PLC (port 11740), not against actual industrial
  hardware (e.g. WAGO PFC). Network/protocol-specific issues that only
  surface with a real device aren't covered.
- **Project state mid-test.** Local-side ops were exercised against an
  MCPTest project that the user had previously cleaned up by hand
  (after the morning sweep had left a duplicate Standard library and
  a dangling ST_Sample reference from a non-refactoring rename).
  Re-running from a virgin `create_project` would shake out any
  state-dependent variations.

---

*Smoke test executed against this fork @ `sp21-plus-migration-notes` HEAD on 2026-04-25.*
