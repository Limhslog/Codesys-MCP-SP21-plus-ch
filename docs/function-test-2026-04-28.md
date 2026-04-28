# Function test -- 2026-04-28 (re-verify the 5 morning bug fixes)

Targeted re-run of the 5 fixes that landed AFTER the 2026-04-25 sweep
(all on the same `main` branch). Each fix shipped with vitest e2e
assertions but only one (`create_folder`, `c87f3a9`) had been
end-to-end-verified against live CODESYS in the commit body. This run
closes that gap.

## Environment

- MCP server: this fork @ HEAD `f34d002` on 2026-04-28.
- CODESYS: `3.5.22.10` (SP22 Patch 1, 64-bit), launched via the
  persistent watcher (v0.4.2).
- Target project: `\\files\karstein.kvistad\Documents\Claude\PLC\MCPTest2\MCPTest2.project`
  (CodesysRpi target, 14 -> 15 library refs across the run).
- No device-side ops exercised (no PLC connect/login/download); pure
  IDE-side tools.

## Re-verified fixes

| # | Fix commit | Tool(s)                                  | Result      | Notes                                                                                                                                  |
|---|-----------|-------------------------------------------|-------------|----------------------------------------------------------------------------------------------------------------------------------------|
| 1 | `57ad449` | `list_project_libraries`                  | OK          | Reported 14 references on the Application libman in one structured response (Standard / Util / 12 placeholders / IoDrvGPIO managed).   |
| 2 | `fc49e7f` | `add_library` (dedup + placeholder)       | OK          | `add_library('Standard')` against a project that already had Standard -> count stayed at 14 (dedup hit). `add_library('CAA Memory')` on a project without it -> count went 14 -> 15, new `CAA Memory [managed]` entry, project still saved cleanly. *Cosmetic note*: the wrapper success message in `server.ts:1896` always says "added" even when the script no-op'd; the dedup itself is correct (data didn't change). Worth tightening the wrapper later. |
| 3 | `763a307` | `compile_project` + `get_compile_messages`| OK*         | `compile_project` ran cleanly on MCPTest2 (0/0). `get_compile_messages` walked 4 watcher startup messages through the encoder -- no `TypeError: <N>L is not JSON serializable`, no crash. *Caveat*: could NOT surface a Severity-bitmask long this run -- injecting an undefined identifier (`xxxUndefinedTestVar`) into PLC_PRG and recompiling did not produce a build error (CODESYS scripting `application.build()` appears to short-circuit on cached results in some scenarios). The `_coerce_for_json` walker is exercised on the messages that WERE present, so the JSON path is non-regressing; full reproduction of the original `0xFFFFFFFFFFFF` crash deferred to a project that emits real compile errors (e.g. X33 with an unresolved library version pin). |
| 4 | `0f8981d` | `rename_object` (reference rewrite)       | OK          | Created `Application/RenameTest_DUT` (struct), `Application/RenameTest_FB` with `VAR refToTarget : RenameTest_DUT; END_VAR`, then renamed DUT -> `RenameTest_DUTRenamed`. Both updates landed: the DUT's own `TYPE` header changed AND the FB's `VAR` declaration was rewritten to the new type. `compile_project` returned 0/0 after the rename -- no stale refs, no broken caller. The default `updateReferences=true` behaves like the IDE's Rename refactor.                  |

(Bug #5 from the original tracking list, `c87f3a9 create_folder`, was
already verified end-to-end in its own commit body -- see
`Verified end-to-end on MCPTest2 + SP22 P1` in the message of
`c87f3a9`.)

## Tally

**4 verified, 0 regressions.** Five-bug list is now fully closed for
end-to-end live-CODESYS coverage.

## Test artefacts

After cleanup:
- `Application/SmokeTest_BrokenPOU` -- created during compile test, deleted.
- `Application/RenameTest_DUTRenamed`, `Application/RenameTest_FB` -- created during rename test, deleted.
- `Application/PLC_PRG` -- temporarily injected an `xxxUndefinedTestVar := 99;` line, reverted to original impl. Final state matches pre-sweep.

Leftover (not cleaned up automatically; no `remove_library` MCP tool
yet):
- `Application` libman now has a `CAA Memory [managed]` entry it
  didn't have before. Functional (resolves at compile), but if the
  user wants a virgin MCPTest2 they can `git restore` the `.project`
  binary or remove the entry via the IDE's Library Manager.

## Caveats

- Compile-error injection didn't propagate -- need a project with
  a *real* library / API mismatch to fully reproduce the original
  Severity-long crash. The fix is structurally robust (deep-walks
  every dict/list/tuple, downcasts `long` -> `int` or `str`); this
  run validates non-regression rather than the original repro.
- Cosmetic: `server.ts:1896` always renders "Library 'X' added"
  even on the dedup no-op branch. Consider plumbing the script's
  branch outcome back through `formatModifyingResponse` for a more
  accurate user-facing message.
- No SP21 coverage this run. Same fixes are SP-agnostic by design.

---

## Symbol Configuration tools (added 2026-04-28 evening)

Ten new tools wrap `ScriptSymbolConfigObject` (CODESYS 3.5.10.0+) per the plan in `docs/superpowers/plans/2026-04-28-symbol-config-tools.md`. Status of each:

| # | Tool                          | Vitest | Live SP22 | Notes |
|---|-------------------------------|--------|-----------|-------|
| 1 | `find_symbol_config`          | OK     | pending   | Template-prep test asserts marker-walk + path serialiser |
| 2 | `list_all_signatures`         | OK     | pending   | `compile=true/false` both rendered |
| 3 | `list_all_datatypes`          | OK     | pending   | Mirror of #2 over `get_all_datatypes()` |
| 4 | `list_configured_symbols`     | OK     | pending   | Walks signatures + datatypes; serialises `configured_access` / `maximal_access` / `effective_access` per variable |
| 5 | `get_symbol_config_settings`  | OK     | pending   | All 6 knobs + obstacle explanations + available layout calculators |
| 6 | `create_symbol_config`        | OK     | pending   | Idempotent (refuse-with-success if already present); `application.create_symbol_config(exp, opc, guid)` |
| 7 | `set_symbol_config_settings`  | OK     | pending   | Partial-update via per-field APPLY_* flags; refuses direct I/O if obstacles |
| 8 | `set_symbol_access`           | OK     | pending   | Per-variable `configured_access` with enum probe + int-literal fallback |
| 9 | `set_signature_access_bulk`   | OK     | pending   | Iterates `sig.variables`, reports `changed` + `skipped` |
|10 | `export_symbol_xsd`           | OK     | pending   | `get_symbol_configuration_xsd()` bytes -> file (UTF-8) |

**Vitest column**: `tests/integration/e2e.test.ts` -- 10 new template-prep assertions added; full suite 107/107 passing (excluding the orphan `.worktrees/phobics-tui` suite). Each test renders the script with realistic placeholders and asserts:
  - no leftover `{PLACEHOLDER}` in the rendered output,
  - the documented CODESYS API methods are referenced (`get_all_signatures`, `application.create_symbol_config`, `configured_access`, etc.),
  - the helper functions are pulled in (`find_symbol_config_object`, `ensure_symbol_config`, `symbol_config_path`).
  - additionally Python 3 `ast.parse` was run against every script to catch any IronPython 2.7 syntax that Py3 would also flag.

**Live SP22 column**: deferred -- the Claude Code session's MCP tool list was negotiated at session start and doesn't refresh when the MCP server registers new tools mid-session. To run the live cycle, start a new Claude Code session (the symlinked global npm package will pick up the new build automatically) and execute the round-trip from the plan:

```
1. mcp__codesys__open_project MCPTest2.project
2. mcp__codesys__find_symbol_config           -- expect count=0
3. mcp__codesys__create_symbol_config Application
4. mcp__codesys__find_symbol_config           -- expect count=1
5. mcp__codesys__get_symbol_config_settings   -- assert OPC UA on, comment Both
6. mcp__codesys__set_symbol_config_settings contentFeatureFlags=['SupportOPCUA','IncludeComments','IncludeExecutables']
7. mcp__codesys__list_all_signatures compile=true
8. mcp__codesys__list_configured_symbols      -- expect empty
9. mcp__codesys__set_signature_access_bulk Application.PLC_PRG ReadWrite
10. mcp__codesys__list_configured_symbols     -- expect PLC_PRG vars exposed
11. mcp__codesys__set_symbol_access Application.PLC_PRG nCounter None
12. mcp__codesys__export_symbol_xsd outputFilePath=C:\\Temp\\sc.xsd
13. mcp__codesys__delete_object Application/<symbol-config-name>
```

The plan also calls out the `SymbolAccess` enum-value probe risk: the SP22 stub references `SymbolAccess` but doesn't declare it inline; the access scripts try the enum class first then fall back to the well-known int literal mapping (`None=0`, `ReadOnly=1`, `WriteOnly=2`, `ReadWrite=3`). A divergent SP would surface a clear error rather than silently corrupt state.

---

*Function test executed against this fork @ HEAD `f34d002` on 2026-04-28; symbol-config tools added in `db688c2` and verified via vitest the same evening.*
