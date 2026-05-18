import json
import os
import shutil
import subprocess
import threading
import traceback
import time
from collections import ChainMap, OrderedDict

import sublime
import sublime_plugin


PACKAGE = "Project Environment"
SETTINGS = "Project Environment.sublime-settings"
PANEL = "project_environment"

_LOCK = threading.RLock()
_ENV_CACHE_LOCK = threading.RLock()
_ENV_CACHE = {}


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
    """Resolve a view environment with a short TTL cache.

    SublimeLinter can ask for executable paths and environment multiple times
    during a single lint pass.  A short cache avoids re-running direnv for each
    method while still picking up environment changes quickly.
    """
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


def _sublime_linter_status():
    try:
        from SublimeLinter.lint import linter as sl_linter
    except Exception:
        return "unavailable"
    patched = getattr(sl_linter.Linter, "_project_environment_patched", False)
    enabled = _sublime_linter_integration_enabled()
    return "enabled, patched" if enabled and patched else "enabled, not patched" if enabled else "disabled"


def format_report(resolved, include_env=False):
    lines = []
    lines.append("Project Environment")
    lines.append("===================")
    lines.append("")
    lines.append("Context")
    lines.append("-------")
    for key in ("windowId", "startPath", "folder", "envrcDir", "direnv", "direnvReturncode"):
        lines.append("{}: {}".format(key, resolved.get(key)))
    lines.append("")
    lines.append("Integrations")
    lines.append("------------")
    lines.append("SublimeLinter: {}".format(_sublime_linter_status()))
    if resolved.get("error"):
        lines.append("error: " + resolved["error"])
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
    lines.append("PATH")
    lines.append("----")
    lines.append(_format_path(resolved.get("path", [])))
    if resolved.get("vars"):
        lines.append("")
        lines.append("Interesting variables")
        lines.append("---------------------")
        for key, value in resolved["vars"].items():
            if key == "PATH":
                continue
            lines.append("{}={}".format(key, value))
    if include_env and resolved.get("env"):
        lines.append("")
        lines.append("Full environment")
        lines.append("----------------")
        for key in sorted(resolved["env"]):
            lines.append("{}={}".format(key, resolved["env"][key]))
    return _truncate("\n".join(lines) + "\n")


def _show_panel(window, text):
    panel = window.create_output_panel(PANEL)
    panel.set_read_only(False)
    panel.run_command("select_all")
    panel.run_command("right_delete")
    panel.run_command("append", {"characters": text})
    panel.set_read_only(True)
    window.run_command("show_panel", {"panel": "output." + PANEL})


def _sublime_linter_integration_enabled():
    return bool(settings().get("sublime_linter_integration", True))


def _project_environment_for_linter_instance(linter):
    try:
        return resolve_for_view_cached(linter.view, include_env=True, interesting_vars=[])
    except Exception:
        print("{}: failed to resolve SublimeLinter environment:\n{}".format(PACKAGE, traceback.format_exc()))
        return None


def _patch_sublime_linter():
    if not _sublime_linter_integration_enabled():
        return True

    try:
        from SublimeLinter.lint import linter as sl_linter
    except Exception:
        return False

    linter_class = sl_linter.Linter
    if getattr(linter_class, "_project_environment_patched", False):
        return True

    original_which = linter_class.which
    original_get_environment = linter_class.get_environment

    def project_environment_which(self, cmd):
        resolved = _project_environment_for_linter_instance(self)
        if resolved and resolved.get("env"):
            found = shutil.which(str(cmd), path=resolved["env"].get("PATH", ""))
            if found:
                try:
                    self.logger.info("{}: resolved '{}' to '{}'".format(PACKAGE, cmd, found))
                except Exception:
                    pass
                return found
        return original_which(self, cmd)

    def project_environment_get_environment(self, settings_arg=None):
        resolved = _project_environment_for_linter_instance(self)
        if resolved and resolved.get("env"):
            utf8_env = getattr(sl_linter, "UTF8_ENV_VARS", {})
            return ChainMap({}, self.settings.get("env", {}), self.env, utf8_env, resolved["env"])
        return original_get_environment(self, settings_arg)

    linter_class._project_environment_original_which = original_which
    linter_class._project_environment_original_get_environment = original_get_environment
    linter_class.which = project_environment_which
    linter_class.get_environment = project_environment_get_environment
    linter_class._project_environment_patched = True
    print("{}: SublimeLinter integration enabled".format(PACKAGE))
    return True


def _unpatch_sublime_linter():
    try:
        from SublimeLinter.lint import linter as sl_linter
    except Exception:
        return

    linter_class = sl_linter.Linter
    if not getattr(linter_class, "_project_environment_patched", False):
        return

    original_which = getattr(linter_class, "_project_environment_original_which", None)
    original_get_environment = getattr(linter_class, "_project_environment_original_get_environment", None)
    if original_which:
        linter_class.which = original_which
    if original_get_environment:
        linter_class.get_environment = original_get_environment
    for attr in (
        "_project_environment_original_which",
        "_project_environment_original_get_environment",
        "_project_environment_patched",
    ):
        try:
            delattr(linter_class, attr)
        except AttributeError:
            pass
    print("{}: SublimeLinter integration disabled".format(PACKAGE))


def _schedule_sublime_linter_patch(attempt=0):
    def run():
        if _patch_sublime_linter():
            return
        if attempt < int(settings().get("sublime_linter_patch_attempts", 30)):
            _schedule_sublime_linter_patch(attempt + 1)
        else:
            print("{}: SublimeLinter integration unavailable after retries".format(PACKAGE))

    sublime.set_timeout_async(run, 1000 if attempt else 0)


def _on_settings_changed():
    clear_cache()
    if _sublime_linter_integration_enabled():
        _schedule_sublime_linter_patch()
    else:
        _unpatch_sublime_linter()


def plugin_loaded():
    settings().add_on_change(PACKAGE, _on_settings_changed)
    _schedule_sublime_linter_patch()


def plugin_unloaded():
    try:
        settings().clear_on_change(PACKAGE)
    except Exception:
        pass
    _unpatch_sublime_linter()
    clear_cache()


class ProjectEnvironmentShowCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            resolved = resolve_for_window(
                self.window,
                tools=settings().get("default_tools", []) or [],
                include_env=False,
            )
            text = format_report(resolved)
        except Exception:
            text = "Project Environment failed:\n\n" + traceback.format_exc()
        _show_panel(self.window, text)


class ProjectEnvironmentShowToolsCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            tools = settings().get("default_tools", []) or []
            resolved = resolve_for_window(self.window, tools=tools, include_env=False, interesting_vars=[])
            text = format_report(resolved)
        except Exception:
            text = "Project Environment tool discovery failed:\n\n" + traceback.format_exc()
        _show_panel(self.window, text)
