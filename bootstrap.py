"""Materialize the Project Environment companion package for legacy hosts.

Project Environment runs in the modern (3.8) plugin host and cannot mutate the
process environment of hosts it does not target -- notably the legacy Python 3.3
host.

To reach those hosts, this writes a small companion package
("Project Environment Host py33") to disk, selected to the legacy host via its own
``.python-version`` file. Sublime then loads it there. The companion reuses the
same lowest-supported-Python-compatible implementation modules from
``shared/`` as the main package, plus a small host-specific entrypoint from
``payload/``. All files are read through the resource API, so this works whether
Project Environment is installed as a loose directory or a ``.sublime-package``.

The marker file makes repeated loads idempotent and prevents clobbering a
manually-created directory with the same name.
"""

import os

import sublime


PARENT_PACKAGE = "Project Environment"
PAYLOAD_DIR = "payload"
TARGET_PACKAGE = "Project Environment Host py33"

# Selects the legacy plugin host for the materialized companion package.
PYTHON_VERSION = "3.3\n"

# Bump to force existing installs to be rewritten.
BOOTSTRAP_VERSION = "7"
MARKER = ".bootstrap-version"

SHARED_DIR = "shared"

# Companion-specific files copied from <PARENT_PACKAGE>/<PAYLOAD_DIR>/.
PAYLOAD_FILES = [
    "project_environment_host.py",
    "README.md",
]


def _package_resource(relpath):
    return "Packages/{}/{}".format(PARENT_PACKAGE, relpath)


def _payload_resource(relpath):
    return "Packages/{}/{}/{}".format(PARENT_PACKAGE, PAYLOAD_DIR, relpath)


def _read_marker(target):
    try:
        with open(os.path.join(target, MARKER), "r", encoding="utf-8") as fobj:
            return fobj.read().strip()
    except OSError:
        return None


def _write_resource(target, relpath, resource):
    data = sublime.load_binary_resource(resource)
    dest = os.path.join(target, relpath.replace("/", os.sep))
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest, "wb") as fobj:
        fobj.write(data)


def _shared_files():
    prefix = _package_resource(SHARED_DIR + "/")
    files = []
    for resource in sublime.find_resources("*"):
        if resource.startswith(prefix):
            files.append(resource[len("Packages/{}/".format(PARENT_PACKAGE)):])
    return sorted(files)


def bootstrap():
    """Materialize the legacy-host companion package into Packages/.

    Safe to call repeatedly: it only writes when the target is missing or the
    bundled version differs, and refuses to touch a directory it did not create.
    """
    target = os.path.join(sublime.packages_path(), TARGET_PACKAGE)
    existing = _read_marker(target)

    if os.path.isdir(target) and existing is None:
        print(
            "{}: {!r} exists without a bootstrap marker; leaving it untouched".format(
                PARENT_PACKAGE, TARGET_PACKAGE
            )
        )
        return

    if existing == BOOTSTRAP_VERSION:
        return

    os.makedirs(target, exist_ok=True)

    # Write .python-version first so the legacy host is chosen when it loads.
    with open(os.path.join(target, ".python-version"), "w", encoding="utf-8") as fobj:
        fobj.write(PYTHON_VERSION)

    for relpath in _shared_files():
        _write_resource(target, relpath, _package_resource(relpath))

    for relpath in PAYLOAD_FILES:
        _write_resource(target, relpath, _payload_resource(relpath))

    with open(os.path.join(target, MARKER), "w", encoding="utf-8") as fobj:
        fobj.write(BOOTSTRAP_VERSION)

    action = "updated" if existing else "installed"
    print(
        "{}: {} companion package {!r} (v{})".format(
            PARENT_PACKAGE, action, TARGET_PACKAGE, BOOTSTRAP_VERSION
        )
    )
