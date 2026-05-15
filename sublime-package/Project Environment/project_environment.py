import json
import os
import shutil
import subprocess
import threading
import traceback
from collections import OrderedDict

import sublime
import sublime_plugin


PACKAGE = "Project Environment"
SETTINGS = "Project Environment.sublime-settings"
PANEL = "project_environment"

_LOCK = threading.RLock()


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
        interesting = interesting_vars or settings().get("interesting_vars", []) or []
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


def format_report(resolved, include_env=False):
    lines = []
    lines.append("Project Environment")
    lines.append("===================")
    lines.append("")
    lines.append("Context")
    lines.append("-------")
    for key in ("windowId", "startPath", "folder", "envrcDir", "direnv", "direnvReturncode"):
        lines.append("{}: {}".format(key, resolved.get(key)))
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
