import traceback

import sublime
import sublime_plugin

from .shared.environment import resolve_for_window
from .shared.global_environment import apply_global_environment_for_view, unload_global_environment
from .reporting import format_report, show_report
from .shared.utils import PACKAGE, settings



def _bootstrap_host_package():
    try:
        from . import bootstrap
        # Defer off the plugin_loaded hook: load_binary_resource() can fail when
        # called directly from it.
        sublime.set_timeout_async(bootstrap.bootstrap, 0)
    except Exception:
        print("{}: host bootstrap failed:\n{}".format(PACKAGE, traceback.format_exc()))


def _on_settings_changed():
    window = sublime.active_window()
    view = window.active_view() if window else None
    if view:
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


def plugin_loaded():
    _bootstrap_host_package()
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


class ProjectEnvironmentEventListener(sublime_plugin.ViewEventListener):
    def _apply(self):
        sublime.set_timeout_async(lambda: apply_global_environment_for_view(self.view), 0)

    def on_load(self):
        self._apply()

    def on_activated(self):
        self._apply()

    def on_post_save(self):
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
        show_report(self.window, "Project Environment", text)


class ProjectEnvironmentShowToolsCommand(sublime_plugin.WindowCommand):
    def run(self):
        try:
            tools = settings().get("default_tools", []) or []
            resolved = resolve_for_window(self.window, tools=tools, include_env=False, interesting_vars=[])
            text = format_report(resolved, include_env=False, include_applied=True)
        except Exception:
            text = "Project Environment tool discovery failed:\n\n" + traceback.format_exc()
        show_report(self.window, "Project Environment Tool Paths", text)


class ProjectEnvironmentReloadCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        if view:
            sublime.set_timeout_async(lambda: apply_global_environment_for_view(view), 0)


class ProjectEnvironmentUnloadCommand(sublime_plugin.WindowCommand):
    def run(self):
        unload_global_environment()
