# Sublime Project Environment

General-purpose deterministic execution environment resolution for Sublime Text.

This package is intentionally separate from Sublime Agent Bridge. The bridge is only for interactive agent work; this package owns reusable environment discovery for Sublime plugins, LSP servers, linters, build systems, and commands.

## What it does

For a window/view/file, Project Environment:

1. determines the relevant project folder and start path inside Sublime,
2. starts from a clean allowlisted base environment instead of inheriting Sublime's possibly-contaminated `PATH`,
3. discovers `direnv` from configured bootstrap paths,
4. runs `direnv export json` in the nearest `.envrc` directory,
5. returns the resolved environment and deterministic tool paths.

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

Both commands write to the `output.project_environment` panel and do not modify open projects/windows.

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

## Current scope

This first version provides deterministic resolution and inspection. LSP/SublimeLinter adapters can be layered on top of this package without coupling that functionality to agent tooling.

See [`docs/lsp-integration.md`](docs/lsp-integration.md) for findings on Sublime LSP startup ordering, available hooks, and integration options.
