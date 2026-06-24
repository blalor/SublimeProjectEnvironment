"""Deterministic environment resolution shared by all plugin hosts.

Keep this module source-compatible with the lowest supported Sublime Text
plugin-host Python version (currently Python 3.3).
"""

import json
import os
import shutil
import subprocess
import threading
from collections import OrderedDict

import sublime

from .utils import dedupe_path, expand, find_command, settings, split_path


_LOCK = threading.RLock()


def clean_base_env():
    """Return a deterministic base environment for evaluating env managers.

    Sublime can be launched from Finder, a shell, or another activated toolchain.
    Inheriting PATH/DIRENV/FLOX variables makes environment resolution depend on
    that launch history. This package keeps a small allowlist of process vars and
    supplies an explicit bootstrap PATH.
    """
    env = {}
    for key in settings().get("passthrough_vars", []) or []:
        if key in os.environ:
            env[key] = os.environ[key]
    env.setdefault("HOME", os.path.expanduser("~"))
    env["PATH"] = os.pathsep.join(dedupe_path(settings().get("bootstrap_path_dirs", []) or []))
    return env


def find_direnv(env=None):
    """Return the direnv executable path, or None."""
    env = env or clean_base_env()
    configured = settings().get("direnv_command")
    if configured:
        found = find_command(configured, env.get("PATH"))
        if found:
            return found
    return shutil.which("direnv", path=env.get("PATH"))


def window_start_path(window, path=None):
    if path:
        return path
    view = window.active_view() if window else None
    if view and view.file_name():
        return view.file_name()
    folders = window.folders() if window else []
    return folders[0] if folders else None


def folder_for_path(window, path):
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
    """Return the nearest .envrc directory at or above start, or None."""
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


def run_direnv_export(direnv, cwd, env):
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


def context_for_window(window, path=None):
    start = window_start_path(window, path)
    folder = folder_for_path(window, start)
    envrc_dir = find_envrc_dir(start or folder)
    return OrderedDict([
        ("windowId", window.id() if window else None),
        ("startPath", start),
        ("folder", folder),
        ("envrcDir", envrc_dir),
    ])


def resolve_for_window(window, path=None, tools=None, include_env=True, interesting_vars=None):
    """Resolve the deterministic environment for a Sublime window.

    Returns a dict containing context, direnv diagnostics, selected variables,
    optional full env, and optional tool locations.
    """
    with _LOCK:
        context = context_for_window(window, path)
        env = clean_base_env()
        direnv = find_direnv(env)
        exported = {}
        result = OrderedDict(context)
        result["bootstrapPath"] = split_path(env.get("PATH", ""))
        result["direnv"] = direnv
        result["direnvReturncode"] = None
        result["direnvStderr"] = ""

        if direnv and context.get("envrcDir"):
            returncode, exported, stderr = run_direnv_export(direnv, context["envrcDir"], env)
            result["direnvReturncode"] = returncode
            result["direnvStderr"] = stderr
            if returncode != 0:
                result["error"] = "direnv export json failed with status {}".format(returncode)
            else:
                env.update({key: str(value) for key, value in exported.items() if value is not None})

        result["path"] = split_path(env.get("PATH", ""))
        result["exportedKeys"] = sorted(exported.keys())
        if interesting_vars is None:
            interesting = settings().get("interesting_vars", []) or []
        else:
            interesting = interesting_vars
        result["vars"] = {key: env[key] for key in interesting if key in env}
        if tools:
            result["tools"] = {tool: shutil.which(tool, path=env.get("PATH")) for tool in tools}
        if include_env:
            result["env"] = env
        return result


def resolve_for_view(view, tools=None, include_env=True, interesting_vars=None):
    window = view.window() if view else sublime.active_window()
    path = view.file_name() if view else None
    return resolve_for_window(window, path=path, tools=tools, include_env=include_env, interesting_vars=interesting_vars)

