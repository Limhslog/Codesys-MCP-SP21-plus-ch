import sys, scriptengine as script_engine, os, traceback

VARIABLE_PATH = "{VARIABLE_PATH}"
VARIABLE_VALUE = "{VARIABLE_VALUE}"

try:
    print("DEBUG: write_variable script: Variable='%s', Value='%s', Project='%s'" % (
        VARIABLE_PATH, VARIABLE_VALUE, PROJECT_FILE_PATH))
    primary_project = ensure_project_open(PROJECT_FILE_PATH)
    if not VARIABLE_PATH:
        raise ValueError("Variable path empty.")

    online_app, target_app = ensure_online_connection(primary_project)
    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()

    # The write counterpart of read_value() has shifted across CODESYS SPs.
    # Some expose 'write_value(name, value)', some 'set_value(...)',
    # and some only the batch form 'write_values([(name, value), ...])'.
    # Probe each available method, then fall back to dumping the available
    # methods on online_app so future debug sessions know what's exposed.
    candidates = []

    # Single-write methods, (name, value) style
    for method_name in ('write_value', 'set_value', 'write', 'set'):
        if hasattr(online_app, method_name):
            candidates.append((method_name + '(name, value)', method_name, [(VARIABLE_PATH, VARIABLE_VALUE)]))

    # Batch-write methods, [(name, value), ...] style
    for method_name in ('write_values', 'set_values'):
        if hasattr(online_app, method_name):
            candidates.append((method_name + '([(name, value)])', method_name, [[(VARIABLE_PATH, VARIABLE_VALUE)]]))

    if not candidates:
        # No known method exposed. Dump diagnostic.
        attrs = sorted([a for a in dir(online_app) if not a.startswith('_')])
        raise TypeError(
            "Online application exposes no known write method "
            "(tried write_value/set_value/write/set/write_values/set_values).\n"
            "Available attributes: %s" % attrs
        )

    written = False
    last_err = None
    for desc, method_name, args_list in candidates:
        try:
            getattr(online_app, method_name)(*args_list)
            print("DEBUG: %s OK" % desc)
            written = True
            break
        except Exception as e:
            last_err = e
            print("DEBUG: %s failed: %s: %s" % (desc, type(e).__name__, e))

    if not written:
        # All known method names were exposed but every call failed. Dump
        # diagnostic + last error so we can iterate.
        attrs = sorted([a for a in dir(online_app) if not a.startswith('_')])
        raise RuntimeError(
            "All known write methods were rejected. Last error: %s\n"
            "Available attributes on online_app: %s" % (last_err, attrs)
        )

    print("Variable: %s" % VARIABLE_PATH)
    print("Value Written: %s" % VARIABLE_VALUE)
    print("Application: %s" % app_name)
    print("SCRIPT_SUCCESS: Variable written successfully.")
    sys.exit(0)
except Exception as e:
    detailed_error = traceback.format_exc()
    error_message = "Error writing variable '%s' in project %s: %s\n%s" % (
        VARIABLE_PATH, PROJECT_FILE_PATH, e, detailed_error)
    print(error_message)
    print("SCRIPT_ERROR: %s" % error_message)
    sys.exit(1)
