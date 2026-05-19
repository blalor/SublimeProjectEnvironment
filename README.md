# Sublime Project Environment

General-purpose deterministic execution environment resolution for Sublime Text.

This package owns reusable environment discovery for Sublime plugins, LSP servers, linters, build systems, and commands.

## What it does

For a window/view/file, Project Environment:

1. determines the relevant project folder and start path inside Sublime,
2. starts from a clean allowlisted base environment instead of inheriting Sublime's possibly-contaminated `PATH`,
3. discovers `direnv` from configured bootstrap paths,
4. runs `direnv export json` in the nearest `.envrc` directory,
5. applies the resolved environment to Sublime Text's process-wide `os.environ`,
6. returns the resolved environment and deterministic tool paths for diagnostics and package integrations.

Because Sublime has one process-wide environment, the active view/project wins. Build systems, LSP servers, linters, Git integration, and other subprocess-spawning packages then inherit the active project environment through normal Sublime behavior.

It does not use or depend on any existing Sublime direnv package.

## Install for local development

```bash
./scripts/install-dev.sh
```

Then restart Sublime Text, or let Package Control reload the copied package files.

## Commands

Command Palette:

- `Project Environment: Show Effective Environment`
- `Project Environment: Show Tool Paths`

The report commands open scratch views with formatted diagnostics.

Additional commands:

- `Project Environment: Reload`
- `Project Environment: Unload`

## Public Python API

Other Sublime packages can import the module:

```python
import project_environment

resolved = project_environment.resolve_for_window(window, tools=["shellcheck", "uv"])
env = resolved["env"]
shellcheck = resolved["tools"]["shellcheck"]
```

Useful functions:

- `resolve_for_window(window, path=None, tools=None, include_env=True, interesting_vars=None)`
- `resolve_for_view(view, tools=None, include_env=True, interesting_vars=None)`
- `which_for_window(window, tools, path=None)`

## Global environment integration

Project Environment does not patch SublimeLinter, LSP, build systems, or other packages individually. Instead, it updates Sublime Text's global process environment when the active view changes. Packages that launch subprocesses through normal Sublime/Python mechanisms inherit that environment.

When the active view has no `.envrc`, the previous Project Environment changes are rolled back.

## Current scope

This version provides deterministic resolution, inspection, and process-wide environment application for the active view/project.

## Future considerations

- Consider an opt-in way to derive the initial bootstrap `PATH` from the user's shell dotfiles/login shell, while preserving deterministic behavior and avoiding inherited Sublime launch-environment contamination.

See [`docs/lsp-integration.md`](docs/lsp-integration.md) for findings on Sublime LSP startup ordering, available hooks, and integration options.
