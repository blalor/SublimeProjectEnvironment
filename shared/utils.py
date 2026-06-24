"""Shared utilities for all Project Environment plugin hosts.

Keep this module source-compatible with the lowest supported Sublime Text
plugin-host Python version (currently Python 3.3).
"""

import os

import sublime


PACKAGE = (__package__ or "Project Environment").split(".", 1)[0]
SETTINGS = "Project Environment.sublime-settings"
_MISSING = object()


def settings():
    return sublime.load_settings(SETTINGS)


def expand(path):
    return os.path.expanduser(path) if isinstance(path, str) else path


def split_path(value):
    return [part for part in (value or "").split(os.pathsep) if part]


def dedupe_path(parts):
    seen = set()
    output = []
    for part in parts:
        if not part:
            continue
        expanded = expand(part)
        if expanded in seen:
            continue
        seen.add(expanded)
        output.append(expanded)
    return output


def find_command(command, path):
    import shutil

    expanded = expand(command)
    if os.path.isabs(expanded) and os.path.exists(expanded):
        return expanded
    return shutil.which(expanded, path=path)


def format_path(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = split_path(value)
    return "\n".join("  - " + part for part in parts)


def truncate(text):
    limit = int(settings().get("max_output_bytes", 512 * 1024))
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "replace") + "\n\n<truncated at {} bytes>\n".format(limit)


def append_key_values(lines, values):
    for key in sorted(values):
        if key == "PATH":
            lines.append("PATH=")
            lines.append(format_path(values[key]))
        else:
            lines.append("{}={}".format(key, values[key]))
