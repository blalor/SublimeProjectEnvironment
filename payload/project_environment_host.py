"""Project Environment companion for Sublime's legacy (Python 3.3) plugin host.

Project Environment makes tools find the right project environment by writing
the resolved environment into the plugin host's process ``os.environ``. Every
subprocess-spawning package in that host then inherits it -- no per-tool
integration required.

That mechanism is process-local, and Sublime runs packages in separate plugin
host processes (notably 3.3 and 3.8), each with its own ``os.environ``. The main
package runs in the modern host and cannot touch the legacy host's environment.
This companion is selected to the legacy host (via its ``.python-version``) and
does the exact same global-environment application there, so legacy-host
packages -- the bundled ``Git`` package being the common one -- inherit the
active project environment too.

It is intentionally tool-agnostic: it applies ``os.environ`` and patches
nothing. It is also self-contained, since it cannot import the modern-host
module across the host boundary; it re-resolves from the shared
``Project Environment.sublime-settings``.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import json
from collections import OrderedDict

import sublime
import sublime_plugin


PACKAGE = "Project Environment Host py33"
SETTINGS = "Project Environment.sublime-settings"

_LOCK = threading.RLock()

_GLOBAL_ENV_LOCK = threading.RLock()
_APPLIED_CONTEXT = None
_APPLIED_ENV = {}
_PREVIOUS_ENV = {}
_LAST_APPLY_TOKEN = None

_MISSING = object()


def settings():
    return sublime.load_settings(SETTINGS)


def _expand(path):
    return os.path.expanduser(path) if isinstance(path, str) else path


def _split_path(value):
    return [part for part in (value or "").split(os.pathsep) if part]


def _dedupe_path(parts):
    seen = set()
    output = []
    for part in parts:
        if not part:
            continue
        expanded = _expand(part)
        if expanded in seen:
            continue
        seen.add(expanded)
        output.append(expanded)
    return output


def _clean_base_env():
    """Deterministic base environment, mirroring the modern-host package."""
    env = {}
    for key in settings().get("passthrough_vars", []) or []:
        if key in os.environ:
            env[key] = os.environ[key]
    env.setdefault("HOME", os.path.expanduser("~"))
    env["PATH"] = os.pathsep.join(_dedupe_path(settings().get("bootstrap_path_dirs", []) or []))
    return env


def _find_command(command, path):
    expanded = _expand(command)
    if os.path.isabs(expanded) and os.path.exists(expanded):
        return expanded
    return shutil.which(expanded, path=path)


def find_direnv(env=None):
    env = env or _clean_base_env()
    configured = settings().get("direnv_command")
    if configured:
        found = _find_command(configured, env.get("PATH"))
        if found:
            return found
    return shutil.which("direnv", path=env.get("PATH"))


def _window_start_path(window, path=None):
    if path:
        return path
    view = window.active_view() if window else None
    if view and view.file_name():
        return view.file_name()
    folders = window.folders() if window else []
    return folders[0] if folders else None


def _folder_for_path(window, path):
    folders = window.folders() if window else []
    if path:
        target = os.path.abspath(path)
        if os.path.isfile(target):
            target = os.path.dirname(target)
        matches = [folder for folder in folders if target == folder or target.startswith(folder + os.sep)]
        if matches:
            return max(matches, key=len)
    return folders[0] if folders else None


def find_envrc_dir(start):
    if not start:
        return None
    path = os.path.abspath(start)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(path, ".envrc")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _run_direnv_export(direnv, cwd, env):
    timeout = float(settings().get("direnv_timeout", 30))
    proc = subprocess.Popen(
        [direnv, "export", "json"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise TimeoutError("direnv export json timed out after {}s".format(timeout))
    stdout = stdout.decode("utf-8", "replace")
    stderr = stderr.decode("utf-8", "replace")
    exported = json.loads(stdout) if stdout.strip() else {}
    return proc.returncode, exported, stderr


def _context_for_window(window, path=None):
    start = _window_start_path(window, path)
    folder = _folder_for_path(window, start)
    envrc_dir = find_envrc_dir(start or folder)
    return OrderedDict([
        ("windowId", window.id() if window else None),
        ("startPath", start),
        ("folder", folder),
        ("envrcDir", envrc_dir),
    ])


def resolve_for_window(window, path=None):
    """Resolve the deterministic project environment for a window.

    Slimmed relative to the modern-host package: only the pieces needed to apply
    the global environment (context, env, direnv status).
    """
    with _LOCK:
        context = _context_for_window(window, path)
        env = _clean_base_env()
        direnv = find_direnv(env)
        exported = {}
        result = OrderedDict(context)
        result["direnvReturncode"] = None

        if direnv and context.get("envrcDir"):
            returncode, exported, stderr = _run_direnv_export(direnv, context["envrcDir"], env)
            result["direnvReturncode"] = returncode
            if returncode != 0:
                result["error"] = "direnv export json failed with status {}".format(returncode)
                print("{}: {}:\n{}".format(PACKAGE, result["error"], stderr))
            else:
                env.update({key: str(value) for key, value in exported.items() if value is not None})

        result["env"] = env
        return result


def resolve_for_view(view):
    window = view.window() if view else sublime.active_window()
    path = view.file_name() if view else None
    return resolve_for_window(window, path=path)


def _skip_global_vars():
    return set(settings().get("global_environment_skip_vars", []) or [])


def _rollback_global_environment_locked():
    global _APPLIED_CONTEXT, _APPLIED_ENV, _PREVIOUS_ENV
    for key, previous in _PREVIOUS_ENV.items():
        if previous is _MISSING:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
    _APPLIED_CONTEXT = None
    _APPLIED_ENV = {}
    _PREVIOUS_ENV = {}


def _environment_for_global_application(resolved):
    if not resolved.get("envrcDir"):
        return None
    if resolved.get("error"):
        return None
    if resolved.get("direnvReturncode") not in (None, 0):
        return None
    env = resolved.get("env") or {}
    skip = _skip_global_vars()
    return {key: str(value) for key, value in env.items() if key not in skip and value is not None}


def apply_global_environment(resolved):
    """Apply the resolved environment to this (legacy) host's ``os.environ``.

    The active view wins; when a view with no ``.envrc`` is activated, the
    previous project environment is rolled back.
    """
    global _APPLIED_CONTEXT, _APPLIED_ENV, _PREVIOUS_ENV
    with _GLOBAL_ENV_LOCK:
        previous_context = _APPLIED_CONTEXT
        env = _environment_for_global_application(resolved)
        _rollback_global_environment_locked()

        if not env:
            if previous_context:
                print("{}: unloaded {}".format(PACKAGE, previous_context.get("envrcDir")))
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
            print("{}: loaded {}".format(PACKAGE, envrc))
        return True


def apply_global_environment_for_view(view):
    global _LAST_APPLY_TOKEN
    token = time.monotonic()
    _LAST_APPLY_TOKEN = token

    try:
        resolved = resolve_for_view(view)
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
        _rollback_global_environment_locked()
    if previous_context:
        print("{}: unloaded {}".format(PACKAGE, previous_context.get("envrcDir")))


def _on_settings_changed():
    window = sublime.active_window()
    view = window.active_view() if window else None
    if view:
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


def plugin_loaded():
    print("{}: loaded in plugin host Python {}".format(PACKAGE, sys.version.split()[0]))
    settings().add_on_change(PACKAGE, _on_settings_changed)
    window = sublime.active_window()
    view = window.active_view() if window else None
    if view:
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


def plugin_unloaded():
    try:
        settings().clear_on_change(PACKAGE)
    except Exception:
        pass
    unload_global_environment()


class ProjectEnvironmentHostEventListener(sublime_plugin.ViewEventListener):
    def _apply(self):
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(self.view), 0)

    def on_load(self):
        self._apply()

    def on_activated(self):
        self._apply()

    def on_post_save(self):
        self._apply()
