import sys, scriptengine as script_engine, os, traceback

LIBRARY_FILE_PATH = r"{LIBRARY_FILE_PATH}"

def _is_system_repo(r):
    try:
        flag = getattr(r, 'is_system', None)
        if callable(flag):
            return bool(flag())
        if flag is not None:
            return bool(flag)
    except Exception:
        pass
    try:
        nm = getattr(r, 'get_name', None)
        if callable(nm):
            n = nm()
        else:
            n = getattr(r, 'name', '')
        return 'system' in str(n).lower()
    except Exception:
        return False

def _try_install(target, path):
    """Try every plausible install method on `target` with various arities.
    Returns the result object, or raises the last exception."""
    last_err = None
    for method_name in ('install_library', 'install', 'add_library', 'add'):
        if not hasattr(target, method_name):
            continue
        method = getattr(target, method_name)
        for args in ((path,), (path, False), (path, True)):
            try:
                r = method(*args)
                print("DEBUG: %s%s OK" % (method_name, args))
                return r
            except TypeError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                print("DEBUG: %s%s failed: %s" % (method_name, args, e))
                break
    if last_err is None:
        raise RuntimeError("No install method on %s" % type(target).__name__)
    raise last_err

try:
    print("DEBUG: install_library_file: File='%s'" % LIBRARY_FILE_PATH)
    if not LIBRARY_FILE_PATH:
        raise ValueError("Library file path is empty.")
    if not os.path.exists(LIBRARY_FILE_PATH):
        raise IOError("Library file not found: %s" % LIBRARY_FILE_PATH)

    # Build candidate list of repository-or-collection objects to try.
    # Different SP versions expose this through different attribute paths.
    candidates = []
    def _push(name, obj):
        if obj is None:
            return
        candidates.append((name, obj))

    # Direct attributes on the scriptengine top-level module. On SP21+/22
    # the official entry point is 'librarymanager' (single lowercase word).
    # Older SPs and parallel-product builds variously expose 'libraries',
    # 'Libraries', a 'library_repository' module, etc -- try them all.
    for attr in ('librarymanager', 'LibraryManager', 'library_manager',
                 'libraries', 'Libraries', 'library_repository',
                 'LibraryRepository', 'repositories', 'Repositories'):
        _push("script_engine.%s" % attr, getattr(script_engine, attr, None))

    # Under script_engine.system
    sys_mod = getattr(script_engine, 'system', None)
    if sys_mod is not None:
        for attr in ('libraries', 'Libraries', 'library_repository',
                     'LibraryRepository', 'repositories', 'Repositories'):
            _push("script_engine.system.%s" % attr, getattr(sys_mod, attr, None))

    # Under script_engine.online (rare but seen)
    online = getattr(script_engine, 'online', None)
    if online is not None:
        for attr in ('libraries', 'library_repository', 'repositories'):
            _push("script_engine.online.%s" % attr, getattr(online, attr, None))

    # Try to import dedicated submodules (some SPs expose libraries here).
    for modname in ('scriptengine.libraries', 'scriptengine.repositories',
                    'scriptengine.LibraryRepository'):
        try:
            mod = __import__(modname, globals(), locals(), ['*'], 0)
            _push(modname, mod)
        except ImportError:
            pass
        except Exception as e:
            print("DEBUG: import %s failed: %s" % (modname, e))

    if not candidates:
        # Final diagnostic: dump scriptengine top-level attribute names so the
        # user/agent can see what IS exposed.
        attrs = sorted([a for a in dir(script_engine) if not a.startswith('_')])
        sys_attrs = sorted([a for a in dir(sys_mod) if not a.startswith('_')]) if sys_mod else []
        raise RuntimeError(
            "No library-repository candidates found.\n"
            "scriptengine attrs: %s\n"
            "scriptengine.system attrs: %s" % (attrs, sys_attrs)
        )

    # For each candidate, try direct install or repository-iteration.
    repo_used = None
    repo_used_name = None
    installed = None
    last_err = None

    for cand_name, cand_obj in candidates:
        cand_type = type(cand_obj).__name__
        print("DEBUG: candidate %s -> %s" % (cand_name, cand_type))
        # Case A: candidate has install_library / install directly.
        if any(hasattr(cand_obj, m) for m in ('install_library', 'install', 'add_library', 'add')):
            try:
                installed = _try_install(cand_obj, LIBRARY_FILE_PATH)
                repo_used = cand_obj
                repo_used_name = cand_name
                break
            except Exception as e:
                last_err = e
                print("DEBUG: %s direct install failed: %s" % (cand_name, e))

        # Case B: candidate exposes a repositories collection.
        for repos_attr in ('repositories', 'Repositories', 'all_repositories'):
            repos = getattr(cand_obj, repos_attr, None)
            if repos is None:
                continue
            try:
                rlist = list(repos)
            except Exception:
                rlist = []
            print("DEBUG: %s.%s -> %d repos" % (cand_name, repos_attr, len(rlist)))
            # Prefer a non-system repository for install
            ordered = [r for r in rlist if not _is_system_repo(r)] + \
                      [r for r in rlist if _is_system_repo(r)]
            for r in ordered:
                try:
                    installed = _try_install(r, LIBRARY_FILE_PATH)
                    repo_used = r
                    nm = getattr(r, 'get_name', None)
                    repo_used_name = "%s.%s[%s]" % (cand_name, repos_attr,
                                                     nm() if callable(nm) else getattr(r, 'name', '?'))
                    break
                except Exception as e:
                    last_err = e
                    print("DEBUG: install on %s failed: %s" % (type(r).__name__, e))
            if installed is not None:
                break
        if installed is not None:
            break

    if installed is None:
        raise RuntimeError("No install candidate succeeded. Last error: %s" % last_err)

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
    print("Repository: %s" % repo_used_name)
    print("File: %s" % LIBRARY_FILE_PATH)
    print("SCRIPT_SUCCESS: Library installed.")
    sys.exit(0)
except Exception as e:
    detailed = traceback.format_exc()
    msg = "Error installing library file '%s': %s\n%s" % (LIBRARY_FILE_PATH, e, detailed)
    print(msg)
    print("SCRIPT_ERROR: %s" % msg)
    sys.exit(1)
