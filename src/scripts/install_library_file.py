import sys, scriptengine as script_engine, os, traceback

LIBRARY_FILE_PATH = r"{LIBRARY_FILE_PATH}"

try:
    print("DEBUG: install_library_file: File='%s'" % LIBRARY_FILE_PATH)
    if not LIBRARY_FILE_PATH:
        raise ValueError("Library file path is empty.")
    if not os.path.exists(LIBRARY_FILE_PATH):
        raise IOError("Library file not found: %s" % LIBRARY_FILE_PATH)

    # Locate a writable Library Repository handle.
    # CODESYS scripting exposes libraries either as a top-level alias
    # (script_engine.libraries) or under the system module
    # (script_engine.system.libraries). Both shapes have been observed
    # across SP19/SP21/SP22.
    repo = None
    repo_name = "?"

    candidates = []
    try:
        if hasattr(script_engine, 'libraries'):
            candidates.append(("script_engine.libraries", script_engine.libraries))
    except Exception as e:
        print("DEBUG: probing script_engine.libraries failed: %s" % e)
    try:
        sys_mod = getattr(script_engine, 'system', None)
        if sys_mod is not None and hasattr(sys_mod, 'libraries'):
            candidates.append(("script_engine.system.libraries", sys_mod.libraries))
    except Exception as e:
        print("DEBUG: probing script_engine.system.libraries failed: %s" % e)

    for src_name, libs in candidates:
        print("DEBUG: candidate %s -> %s" % (src_name, type(libs).__name__))
        # Case A: object exposes install_library() directly (acts as a single repo)
        if hasattr(libs, 'install_library') or hasattr(libs, 'install'):
            repo = libs
            repo_name = src_name
            break
        # Case B: object exposes a 'repositories' collection. Pick the first
        # non-system, writable-looking repository.
        if hasattr(libs, 'repositories'):
            try:
                rlist = list(libs.repositories)
            except Exception:
                rlist = []
            print("DEBUG: %s.repositories -> %d repos" % (src_name, len(rlist)))
            chosen = None
            for r in rlist:
                is_sys = False
                try:
                    flag = getattr(r, 'is_system', None)
                    if callable(flag):
                        is_sys = bool(flag())
                    elif flag is not None:
                        is_sys = bool(flag)
                except Exception:
                    pass
                if not is_sys:
                    chosen = r
                    break
            if chosen is None and rlist:
                chosen = rlist[0]
            if chosen is not None:
                repo = chosen
                try:
                    nm = getattr(repo, 'get_name', None)
                    repo_name = nm() if callable(nm) else getattr(repo, 'name', '?')
                except Exception:
                    repo_name = "?"
                break

    if repo is None:
        raise RuntimeError("Could not locate a Library Repository via scripting API. Tried script_engine.libraries and script_engine.system.libraries.")

    print("DEBUG: target repository: %s" % repo_name)

    # Try install methods in order of likelihood. Some accept (path, overwrite),
    # some accept just (path). Try both arities for each name.
    installed = None
    last_err = None
    for method_name in ('install_library', 'install', 'add_library', 'add'):
        if not hasattr(repo, method_name):
            continue
        method = getattr(repo, method_name)
        for args in ((LIBRARY_FILE_PATH,), (LIBRARY_FILE_PATH, False), (LIBRARY_FILE_PATH, True)):
            try:
                installed = method(*args)
                print("DEBUG: %s%s succeeded" % (method_name, args))
                break
            except TypeError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                print("DEBUG: %s%s failed: %s" % (method_name, args, e))
                break
        if installed is not None:
            break

    if installed is None:
        raise RuntimeError("Install failed via all known method patterns. Last error: %s" % last_err)

    # Best-effort name/version extraction
    def _attr(obj, name, default='?'):
        try:
            v = getattr(obj, name, None)
            if callable(v):
                return v()
            if v is not None:
                return v
        except Exception:
            pass
        return default

    lib_name = _attr(installed, 'get_name')
    if lib_name == '?':
        lib_name = _attr(installed, 'name')
    lib_version = _attr(installed, 'get_version')
    if lib_version == '?':
        lib_version = _attr(installed, 'version')

    print("Installed: %s %s" % (lib_name, lib_version))
    print("Repository: %s" % repo_name)
    print("File: %s" % LIBRARY_FILE_PATH)
    print("SCRIPT_SUCCESS: Library installed.")
    sys.exit(0)
except Exception as e:
    detailed = traceback.format_exc()
    msg = "Error installing library file '%s': %s\n%s" % (LIBRARY_FILE_PATH, e, detailed)
    print(msg)
    print("SCRIPT_ERROR: %s" % msg)
    sys.exit(1)
