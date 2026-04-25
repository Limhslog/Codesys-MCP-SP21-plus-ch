import sys, scriptengine as script_engine, os, traceback

TARGET_VERSION = "{TARGET_VERSION}"
INCLUDE_SYSTEM = {INCLUDE_SYSTEM}

try:
    print("DEBUG: update_all_libraries: TargetVersion='%s', IncludeSystem=%s, Project='%s'" % (
        TARGET_VERSION, INCLUDE_SYSTEM, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not TARGET_VERSION:
        raise ValueError("Target version is empty.")

    # Locate Library Manager (same pattern as add_library.py).
    lib_manager = None
    try:
        found = primary_project.find("Library Manager", True)
        if found:
            lib_manager = found[0]
    except Exception as e:
        print("DEBUG: find('Library Manager') failed: %s" % e)
    if lib_manager is None:
        try:
            for child in primary_project.get_children(True):
                nm = getattr(child, 'get_name', lambda: '')()
                if 'library' in nm.lower() and 'manager' in nm.lower():
                    lib_manager = child
                    break
        except Exception as e:
            print("DEBUG: child search for Library Manager failed: %s" % e)
    if lib_manager is None:
        raise RuntimeError("Library Manager not found in project.")

    # Enumerate library references. The exact method name varies across SP
    # versions, so probe several.
    refs = []
    for method_name in ('get_all_libraries', 'get_libraries', 'get_references', 'libraries', 'references'):
        attr = getattr(lib_manager, method_name, None)
        if attr is None:
            continue
        try:
            value = attr() if callable(attr) else attr
            refs = list(value)
            print("DEBUG: enumerated via %s -> %d refs" % (method_name, len(refs)))
            break
        except Exception as e:
            print("DEBUG: %s() failed: %s" % (method_name, e))
    if not refs:
        try:
            refs = list(lib_manager)
            print("DEBUG: enumerated via iter(lib_manager) -> %d refs" % len(refs))
        except Exception:
            pass
    if not refs:
        raise RuntimeError("Could not enumerate library references via any known API.")

    def _attr(obj, name, default=''):
        v = getattr(obj, name, None)
        if v is None:
            return default
        try:
            return v() if callable(v) else v
        except Exception:
            return default

    def _is_system(ref):
        v = getattr(ref, 'is_system', None)
        if v is None:
            return False
        try:
            return bool(v() if callable(v) else v)
        except Exception:
            return False

    results = []
    ok = 0
    skipped = 0
    failed = 0

    for ref in refs:
        try:
            name = _attr(ref, 'get_name', '?')
            if name == '?':
                name = _attr(ref, 'name', '?')
            old_version = str(_attr(ref, 'get_version', '?'))
            if old_version == '?':
                old_version = str(_attr(ref, 'version', '?'))
            namespace = _attr(ref, 'get_namespace', '')
            if not namespace:
                namespace = _attr(ref, 'namespace', '')

            if _is_system(ref) and not INCLUDE_SYSTEM:
                results.append((name, namespace, old_version, old_version, "skipped (system)"))
                skipped += 1
                continue

            # Try in-place update methods first.
            updated = False
            last_err = None
            for method_name in ('set_version', 'update_to_version', 'update', 'set_resolution'):
                if not hasattr(ref, method_name):
                    continue
                try:
                    getattr(ref, method_name)(TARGET_VERSION)
                    updated = True
                    print("DEBUG: %s.%s('%s') OK" % (name, method_name, TARGET_VERSION))
                    break
                except Exception as e:
                    last_err = e
                    print("DEBUG: %s.%s('%s') failed: %s" % (name, method_name, TARGET_VERSION, e))

            # Fallback: remove + re-add at the new version.
            if not updated:
                try:
                    if hasattr(lib_manager, 'remove_library'):
                        lib_manager.remove_library(ref)
                    elif hasattr(lib_manager, 'remove'):
                        lib_manager.remove(ref)
                    else:
                        raise RuntimeError("no remove_library / remove method")

                    added = False
                    for add_name in ('add_placeholder_library', 'add_library', 'insert_library'):
                        if not hasattr(lib_manager, add_name):
                            continue
                        try:
                            getattr(lib_manager, add_name)(name, TARGET_VERSION)
                            added = True
                            break
                        except TypeError:
                            try:
                                getattr(lib_manager, add_name)(name)
                                added = True
                                break
                            except Exception as e2:
                                last_err = e2
                        except Exception as e2:
                            last_err = e2
                    if added:
                        updated = True
                        print("DEBUG: remove + re-add for %s OK" % name)
                except Exception as e:
                    last_err = e
                    print("DEBUG: remove+add failed for %s: %s" % (name, e))

            if updated:
                results.append((name, namespace, old_version, TARGET_VERSION, "ok"))
                ok += 1
            else:
                results.append((name, namespace, old_version, old_version, "failed: %s" % last_err))
                failed += 1
        except Exception as e:
            results.append(("?", "?", "?", "?", "error: %s" % e))
            failed += 1

    try:
        primary_project.save()
    except Exception as save_err:
        print("ERROR: save failed: %s" % save_err)
        print("SCRIPT_ERROR: save failed after updates: %s" % save_err)
        sys.exit(1)

    print("Library update summary:")
    print("  total=%d  updated=%d  skipped=%d  failed=%d" % (len(refs), ok, skipped, failed))
    print("  target version: %s" % TARGET_VERSION)
    print("Per-library:")
    for name, ns, old, new, status in results:
        prefix = "%s.%s" % (ns, name) if ns else name
        print("  %-50s %s -> %s [%s]" % (prefix, old, new, status))

    if failed > 0:
        print("SCRIPT_ERROR: %d libraries failed to update; see lines above" % failed)
        sys.exit(1)
    print("SCRIPT_SUCCESS: %d libraries updated, %d skipped" % (ok, skipped))
    sys.exit(0)
except Exception as e:
    detailed = traceback.format_exc()
    msg = "Error updating libraries in '%s': %s\n%s" % (PROJECT_FILE_PATH, e, detailed)
    print(msg)
    print("SCRIPT_ERROR: %s" % msg)
    sys.exit(1)
