"""Materialize the Project Environment companion package for legacy hosts.

Project Environment runs in the modern (3.8) plugin host and cannot run code in
hosts it does not target -- notably the legacy Python 3.3 host, where packages
such as ``Git`` still run and cannot be patched from another host.

To reach those hosts, this writes a small companion package
("Project Environment Host py33") to disk, selected to the legacy host via its own
``.python-version`` file. Sublime then loads it there. The companion's source
ships inside this package under ``payload/`` (a subdirectory Sublime does not
load as plugins) and is read through the resource API, so this works whether
Project Environment is installed as a loose directory or a ``.sublime-package``.

The structural pattern follows Package Control's generated loader: defer the
work off ``plugin_loaded``, guard with a marker file for idempotency, and never
clobber a directory we did not create.
"""

import os

import sublime


PARENT_PACKAGE = "Project Environment"
PAYLOAD_DIR = "payload"
TARGET_PACKAGE = "Project Environment Host py33"

# Selects the legacy plugin host for the materialized companion package.
PYTHON_VERSION = "3.3\n"

# Bump to force existing installs to be rewritten.
BOOTSTRAP_VERSION = "2"
MARKER = ".bootstrap-version"

# Files copied verbatim from <PARENT_PACKAGE>/<PAYLOAD_DIR>/ to the target root.
PAYLOAD_FILES = [
    "project_environment_host.py",
    "README.md",
]


def _resource(relpath):
    return "Packages/{}/{}/{}".format(PARENT_PACKAGE, PAYLOAD_DIR, relpath)


def _read_marker(target):
    try:
        with open(os.path.join(target, MARKER), "r", encoding="utf-8") as fobj:
            return fobj.read().strip()
    except OSError:
        return None


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

    for relpath in PAYLOAD_FILES:
        data = sublime.load_binary_resource(_resource(relpath))
        dest = os.path.join(target, relpath.replace("/", os.sep))
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest, "wb") as fobj:
            fobj.write(data)

    with open(os.path.join(target, MARKER), "w", encoding="utf-8") as fobj:
        fobj.write(BOOTSTRAP_VERSION)

    action = "updated" if existing else "installed"
    print(
        "{}: {} companion package {!r} (v{})".format(
            PARENT_PACKAGE, action, TARGET_PACKAGE, BOOTSTRAP_VERSION
        )
    )
