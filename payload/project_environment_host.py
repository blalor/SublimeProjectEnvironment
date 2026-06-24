"""Sublime plugin entrypoint for the Python 3.3 host companion.

The shared implementation package (``shared/``) is copied from the main Project
Environment package into this materialized companion package by ``bootstrap.py``.
This file only implements the public Sublime Text plugin surface for the legacy
host.
"""

import sys

import sublime
import sublime_plugin

from .shared.global_environment import apply_global_environment_for_view, unload_global_environment
from .shared.utils import PACKAGE, settings


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
