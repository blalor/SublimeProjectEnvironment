import json
import os
import shutil
import subprocess
import threading
import traceback
import time
from collections import OrderedDict

import sublime
import sublime_plugin


PACKAGE = "Project Environment"
SETTINGS = "Project Environment.sublime-settings"

_LOCK = threading.RLock()
_ENV_CACHE_LOCK = threading.RLock()
_ENV_CACHE = {}

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
    env["PATH"] = os.pathsep.join(_dedupe_path(settings().get("bootstrap_path_dirs", []) or []))
    return env


def _find_command(command, path):
    expanded = _expand(command)
    if os.path.isabs(expanded) and os.path.exists(expanded):
        return expanded
    return shutil.which(expanded, path=path)


def find_direnv(env=None):
    """Return the direnv executable path, or None."""
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


def resolve_for_window(window, path=None, tools=None, include_env=True, interesting_vars=None):
    """Resolve the deterministic environment for a Sublime window.

    Returns a dict containing context, direnv diagnostics, selected variables,
    optional full env, and optional tool locations.
    """
    with _LOCK:
        context = _context_for_window(window, path)
        env = _clean_base_env()
        direnv = find_direnv(env)
        exported = {}
        result = OrderedDict(context)
        result["bootstrapPath"] = _split_path(env.get("PATH", ""))
        result["direnv"] = direnv
        result["direnvReturncode"] = None
        result["direnvStderr"] = ""

        if direnv and context.get("envrcDir"):
            returncode, exported, stderr = _run_direnv_export(direnv, context["envrcDir"], env)
            result["direnvReturncode"] = returncode
            result["direnvStderr"] = stderr
            if returncode != 0:
                result["error"] = "direnv export json failed with status {}".format(returncode)
            else:
                env.update({key: str(value) for key, value in exported.items() if value is not None})

        result["path"] = _split_path(env.get("PATH", ""))
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


def _cache_key_for_view(view):
    window = view.window() if view else sublime.active_window()
    folders = tuple(window.folders()) if window else ()
    return (
        window.id() if window else None,
        view.file_name() if view else None,
        folders,
    )


def resolve_for_view_cached(view, tools=None, include_env=True, interesting_vars=None):
    """Resolve a view environment with a short TTL cache."""
    ttl = float(settings().get("cache_seconds", 5))
    interesting_key = None if interesting_vars is None else tuple(interesting_vars)
    key = (_cache_key_for_view(view), tuple(tools or ()), bool(include_env), interesting_key)
    now = time.monotonic()
    with _ENV_CACHE_LOCK:
        cached = _ENV_CACHE.get(key)
        if cached and now - cached[0] <= ttl:
            return cached[1]

    resolved = resolve_for_view(view, tools=tools, include_env=include_env, interesting_vars=interesting_vars)
    with _ENV_CACHE_LOCK:
        _ENV_CACHE[key] = (now, resolved)
    return resolved


def clear_cache():
    with _ENV_CACHE_LOCK:
        _ENV_CACHE.clear()


def which_for_window(window, tools, path=None):
    resolved = resolve_for_window(window, path=path, tools=tools, include_env=False)
    return resolved.get("tools", {})


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
    """Make the resolved project environment Sublime's process environment.

    Sublime has a single process-wide environment. The active view wins; when a
    view with no .envrc is activated, the previous project environment is rolled
    back.
    """
    global _APPLIED_CONTEXT, _APPLIED_ENV, _PREVIOUS_ENV
    with _GLOBAL_ENV_LOCK:
        previous_context = _APPLIED_CONTEXT
        env = _environment_for_global_application(resolved)
        _rollback_global_environment_locked()

        if not env:
            if previous_context:
                sublime.status_message("Project Environment: unloaded {}".format(previous_context.get("envrcDir")))
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
            sublime.status_message("Project Environment: loaded {}".format(envrc))
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
        _rollback_global_environment_locked()
    if previous_context:
        sublime.status_message("Project Environment: unloaded {}".format(previous_context.get("envrcDir")))


def applied_global_environment_snapshot():
    with _GLOBAL_ENV_LOCK:
        return {
            "context": dict(_APPLIED_CONTEXT or {}),
            "env": dict(_APPLIED_ENV),
            "previousKeys": sorted(_PREVIOUS_ENV.keys()),
        }


def _format_path(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = _split_path(value)
    return "\n".join("  - " + part for part in parts)


def _truncate(text):
    limit = int(settings().get("max_output_bytes", 512 * 1024))
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "replace") + "\n\n<truncated at {} bytes>\n".format(limit)


def _append_key_values(lines, values):
    for key in sorted(values):
        if key == "PATH":
            lines.append("PATH=")
            lines.append(_format_path(values[key]))
        else:
            lines.append("{}={}".format(key, values[key]))


def format_report(resolved, include_env=False, include_applied=False):
    lines = []
    lines.append("Project Environment")
    lines.append("=" * 19)
    lines.append("")
    lines.append("Context")
    lines.append("-------")
    for key in ("windowId", "startPath", "folder", "envrcDir", "direnv", "direnvReturncode"):
        lines.append("{}: {}".format(key, resolved.get(key)))

    if resolved.get("error"):
        lines.append("")
        lines.append("Error")
        lines.append("-----")
        lines.append(resolved["error"])

    if resolved.get("direnvStderr"):
        lines.append("")
        lines.append("direnv stderr")
        lines.append("-------------")
        lines.append(resolved["direnvStderr"].rstrip())

    if resolved.get("tools"):
        lines.append("")
        lines.append("Tools")
        lines.append("-----")
        for tool, path in resolved["tools"].items():
            lines.append("{}: {}".format(tool, path or "<not found>"))

    lines.append("")
    lines.append("Resolved PATH")
    lines.append("-------------")
    lines.append(_format_path(resolved.get("path", [])))

    if resolved.get("vars"):
        lines.append("")
        lines.append("Interesting variables")
        lines.append("---------------------")
        _append_key_values(lines, resolved["vars"])

    if include_env and resolved.get("env"):
        lines.append("")
        lines.append("Full resolved environment")
        lines.append("-------------------------")
        _append_key_values(lines, resolved["env"])

    if include_applied:
        snapshot = applied_global_environment_snapshot()
        lines.append("")
        lines.append("Applied global environment")
        lines.append("--------------------------")
        context = snapshot.get("context") or {}
        if context:
            for key in ("windowId", "startPath", "folder", "envrcDir"):
                lines.append("{}: {}".format(key, context.get(key)))
        else:
            lines.append("<none>")
        env = snapshot.get("env") or {}
        if env:
            lines.append("")
            _append_key_values(lines, env)
        previous_keys = snapshot.get("previousKeys") or []
        if previous_keys:
            lines.append("")
            lines.append("Rollback keys")
            lines.append("-------------")
            for key in previous_keys:
                lines.append(key)

    return _truncate("\n".join(lines) + "\n")


def _show_report(window, title, text):
    window = window or sublime.active_window()
    view = window.new_file()
    view.set_name(title)
    view.set_scratch(True)
    view.assign_syntax("Packages/Text/Plain text.tmLanguage")
    view.run_command("append", {"characters": text})
    view.set_read_only(True)
    window.focus_view(view)


def _on_settings_changed():
    clear_cache()
    window = sublime.active_window()
    view = window.active_view() if window else None
    if view:
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


def plugin_loaded():
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
    clear_cache()


class ProjectEnvironmentEventListener(sublime_plugin.ViewEventListener):
    def _apply(self):
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(self.view), 0)

    def on_load(self):
        self._apply()

    def on_activated(self):
        self._apply()

    def on_post_save(self):
        clear_cache()
        self._apply()


class ProjectEnvironmentShowCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            resolved = resolve_for_window(
                self.window,
                tools=settings().get("default_tools", []) or [],
                include_env=True,
            )
            text = format_report(resolved, include_env=True, include_applied=True)
        except Exception:
            text = "Project Environment failed:\n\n" + traceback.format_exc()
        _show_report(self.window, "Project Environment", text)


class ProjectEnvironmentShowToolsCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            tools = settings().get("default_tools", []) or []
            resolved = resolve_for_window(self.window, tools=tools, include_env=False, interesting_vars=[])
            text = format_report(resolved, include_env=False, include_applied=True)
        except Exception:
            text = "Project Environment tool discovery failed:\n\n" + traceback.format_exc()
        _show_report(self.window, "Project Environment Tool Paths", text)


class ProjectEnvironmentReloadCommand(sublime_plugin.WindowCommand):
    def run(self):
        clear_cache()
        view = self.window.active_view()
        if view:
            sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


class ProjectEnvironmentUnloadCommand(sublime_plugin.WindowCommand):
    def run(self):
        unload_global_environment()
