# Sublime Project Environment

General-purpose deterministic execution environment resolution for Sublime Text.

This package applies deterministic project environments to Sublime Text plugin hosts.

## What it does

For a window/view/file, Project Environment:

1. determines the relevant project folder and start path inside Sublime,
2. starts from a clean allowlisted base environment instead of inheriting Sublime's possibly-contaminated `PATH`,
3. discovers `direnv` from configured bootstrap paths,
4. runs `direnv export json` in the nearest `.envrc` directory,
5. applies the resolved environment to Sublime Text's process-wide `os.environ`,
6. reports the resolved environment and deterministic tool paths for diagnostics.

Because Sublime has one process-wide environment per plugin host, the active view/project wins within that host. Build systems, LSP servers, linters, and other subprocess-spawning packages then inherit the active project environment through normal Sublime behavior when they run in the same host.

It does not use or depend on any existing Sublime direnv package.

## Commands

Command Palette:

- `Project Environment: Show Effective Environment`
- `Project Environment: Show Tool Paths`

The report commands open scratch views with formatted diagnostics.

Additional commands:

- `Project Environment: Reload`
- `Project Environment: Unload`

## Global environment integration

Project Environment does not modify SublimeLinter, LSP, build systems, or other packages individually. Instead, it updates Sublime Text's global process environment when the active view changes. Packages that launch subprocesses through normal Sublime/Python mechanisms inherit that environment.

When the active view has no `.envrc`, the previous Project Environment changes are rolled back.

### Plugin host scope

Sublime Text can run packages in separate Python plugin hosts. Build 4200 provides Python 3.3 and Python 3.8 hosts. Build 4213 replaces the Python 3.8 host with Python 3.14 and disables the Python 3.3 host by default. Each enabled host is a separate OS process with its own `os.environ`, so environment changes are process-local.

Project Environment declares Python 3.8 via `.python-version`. Build 4213 treats that value as the backward-compatible selector for Python 3.14, while older builds continue to select Python 3.8. This covers packages that run in the modern host, such as modern build execution (`Default.exec`), LSP, SublimeLinter, and many newer packages. It does not update Sublime's core application process.

To reach the legacy Python 3.3 host when it is enabled, Project Environment bootstraps a small companion package, **Project Environment Host py33** (named for the plugin host it targets). On load it materializes that package to disk (via `bootstrap.py`, from the bundled `payload/`) with its own `.python-version` of `3.3`, so Sublime loads it in the legacy host. The companion is self-contained (it cannot import this module across the host boundary) and re-resolves the environment from the shared `Project Environment.sublime-settings`.

When the Python 3.3 host is disabled, Sublime runs packages marked for Python 3.3 in the modern host. The companion detects the host's Python version and remains inactive there, preventing it from applying the environment a second time in the same process.

The companion is tool-agnostic: it reuses the same `shared/` environment-resolution and global-application modules to perform the **same** global `os.environ` application in the legacy host that the main package performs in the modern host. It modifies nothing else. Any legacy-host package that spawns subprocesses inherits the active project environment through normal Sublime behavior. The companion is auto-managed: it is created/updated on load and is not removed automatically when Project Environment is uninstalled.

## Current scope

This package provides deterministic resolution, inspection, and process-wide environment application for the active view/project.

See [`docs/lsp-integration.md`](docs/lsp-integration.md) for findings on Sublime LSP startup ordering.
