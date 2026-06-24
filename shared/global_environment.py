"""Process-wide environment application shared by all plugin hosts.

Keep this module source-compatible with the lowest supported Sublime Text
plugin-host Python version (currently Python 3.3).
"""

import os
import threading
import time
import traceback
from collections import OrderedDict

import sublime

from .environment import resolve_for_view
from .utils import PACKAGE, _MISSING, settings


_GLOBAL_ENV_LOCK = threading.RLock()
_APPLIED_CONTEXT = None
_APPLIED_ENV = {}
_PREVIOUS_ENV = {}
_LAST_APPLY_TOKEN = None


def skip_global_vars():
    return set(settings().get("global_environment_skip_vars", []) or [])


def rollback_global_environment_locked():
    global _APPLIED_CONTEXT, _APPLIED_ENV, _PREVIOUS_ENV
    for key, previous in _PREVIOUS_ENV.items():
        if previous is _MISSING:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
    _APPLIED_CONTEXT = None
    _APPLIED_ENV = {}
    _PREVIOUS_ENV = {}


def environment_for_global_application(resolved):
    if not resolved.get("envrcDir"):
        return None
    if resolved.get("error"):
        return None
    if resolved.get("direnvReturncode") not in (None, 0):
        return None
    env = resolved.get("env") or {}
    skip = skip_global_vars()
    return {key: str(value) for key, value in env.items() if key not in skip and value is not None}


def apply_global_environment(resolved):
    """Make the resolved project environment Sublime's process environment.

    Sublime has a single process-wide environment. The active view wins; when a
    view with no .envrc is activated, the previous project environment is rolled
    back.
    """
    global _APPLIED_CONTEXT, _APPLIED_ENV, _PREVIOUS_ENV
    with _GLOBAL_ENV_LOCK:
        previous_context = _APPLIED_CONTEXT
        env = environment_for_global_application(resolved)
        rollback_global_environment_locked()

        if not env:
            if previous_context:
                sublime.status_message("{}: unloaded {}".format(PACKAGE, previous_context.get("envrcDir")))
            return False

        previous = {}
        for key, value in env.items():
            previous[key] = os.environ[key] if key in os.environ else _MISSING
            if os.environ.get(key) != value:
                os.environ[key] = value

        _APPLIED_CONTEXT = OrderedDict((key, resolved.get(key)) for key in ("windowId", "startPath", "folder", "envrcDir"))
        _APPLIED_ENV = env
        _PREVIOUS_ENV = previous

        envrc = resolved.get("envrcDir")
        if not previous_context or previous_context.get("envrcDir") != envrc:
            sublime.status_message("{}: loaded {}".format(PACKAGE, envrc))
        return True


def apply_global_environment_for_view(view):
    global _LAST_APPLY_TOKEN
    token = time.monotonic()
    _LAST_APPLY_TOKEN = token

    try:
        resolved = resolve_for_view(view, include_env=True)
    except Exception:
        print("{}: failed to resolve global environment:\n{}".format(PACKAGE, traceback.format_exc()))
        return

    def apply_if_current():
        if _LAST_APPLY_TOKEN == token:
            apply_global_environment(resolved)

    sublime.set_timeout(apply_if_current, 0)


def unload_global_environment():
    with _GLOBAL_ENV_LOCK:
        previous_context = _APPLIED_CONTEXT
        rollback_global_environment_locked()
    if previous_context:
        sublime.status_message("{}: unloaded {}".format(PACKAGE, previous_context.get("envrcDir")))


def applied_global_environment_snapshot():
    with _GLOBAL_ENV_LOCK:
        return {
            "context": dict(_APPLIED_CONTEXT or {}),
            "env": dict(_APPLIED_ENV),
            "previousKeys": sorted(_PREVIOUS_ENV.keys()),
        }
