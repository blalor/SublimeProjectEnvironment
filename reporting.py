import sublime

from .shared.global_environment import applied_global_environment_snapshot
from .shared.utils import append_key_values, format_path, truncate


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
    lines.append(format_path(resolved.get("path", [])))

    if resolved.get("vars"):
        lines.append("")
        lines.append("Interesting variables")
        lines.append("---------------------")
        append_key_values(lines, resolved["vars"])

    if include_env and resolved.get("env"):
        lines.append("")
        lines.append("Full resolved environment")
        lines.append("-------------------------")
        append_key_values(lines, resolved["env"])

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
            append_key_values(lines, env)
        previous_keys = snapshot.get("previousKeys") or []
        if previous_keys:
            lines.append("")
            lines.append("Rollback keys")
            lines.append("-------------")
            for key in previous_keys:
                lines.append(key)

    return truncate("\n".join(lines) + "\n")


def show_report(window, title, text):
    window = window or sublime.active_window()
    view = window.new_file()
    view.set_name(title)
    view.set_scratch(True)
    view.assign_syntax("Packages/Text/Plain text.tmLanguage")
    view.run_command("append", {"characters": text})
    view.set_read_only(True)
    window.focus_view(view)
