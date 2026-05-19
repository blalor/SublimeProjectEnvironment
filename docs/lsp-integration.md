# LSP Integration Findings

Project Environment should be the real Sublime Text solution for deterministic project environments. Agent bridges and other external tools are only useful for development/debugging and must not be part of runtime architecture.

## Problem

Sublime Text packages often launch subprocesses: language servers, linters, formatters, build tools, Git helpers, etc. Those subprocesses need the environment for the relevant project/window/view.

For projects that use `direnv`/Flox, tools such as `shellcheck` and `uv` may only exist after evaluating the project's `.envrc`.

A common failure mode is startup ordering:

1. Sublime starts.
2. Packages load.
3. An environment package asynchronously resolves or mutates environment state.
4. LSP or another package may already have resolved/started a subprocess.
5. The subprocess starts with the wrong `PATH`.

This is especially visible with Sublime LSP providers because language server binaries and tools used by those servers can be resolved before any custom environment package has finished setup.

## What Project Environment currently solves

Project Environment now provides deterministic environment resolution and applies the active view's resolved environment to Sublime Text's process-wide `os.environ`:

1. Determine the relevant Sublime window/view/file/folder.
2. Start from a clean allowlisted base environment.
3. Do **not** inherit arbitrary Sublime launch `PATH`, `DIRENV_*`, `FLOX_*`, `VIRTUAL_ENV`, etc. into project resolution.
4. Discover `direnv` from an explicit bootstrap path.
5. Run `direnv export json` in the nearest `.envrc` directory.
6. Apply the resolved environment globally for the active view/project.
7. Roll back the previous applied environment when the active view has no `.envrc`.

Because many Sublime packages launch subprocesses from `os.environ.copy()`, global application makes LSP servers, linters, build systems, Git integration, and other subprocess users inherit the active project environment without package-specific adapters.

## Important limitations

Sublime Text has a single process-wide environment. Therefore:

- the active view/project wins,
- multiple windows cannot have independent global environments at the same time,
- already-running subprocesses keep the environment they started with,
- LSP servers generally need to be restarted after switching projects or changing `.envrc` content.

This tradeoff is intentional: it matches the behavior needed by built-in and third-party integrations that only consult the global process environment.

## Sublime LSP findings

Sublime LSP launch behavior constructs process env from `os.environ.copy()` plus configured `env` overrides. With Project Environment's global application, LSP servers inherit the active project environment when they start.

Relevant LSP internals inspected:

- `LSP.plugin.api.AbstractPlugin.on_pre_start(...)`
- `LSP.plugin.core.windows` calls `plugin_class.on_pre_start(...)` before creating the transport.
- `LSP.plugin.core.transports.TransportConfig.resolve_launch_config(command, env, variables)` builds the process launch env.
- `LSP.plugin.core.transports._start_subprocess(...)` ultimately calls `subprocess.Popen(...)`.

Project Environment does not patch LSP internals. If an LSP server was started before the correct environment was applied, restart that server.

## Open questions

- Should Project Environment cache `direnv export json` results beyond the short runtime TTL, and if so what invalidates the cache (`.envrc`, `.envrc.local`, parent `.envrc`, Flox files, direnv watches)?
- How should secrets from `direnv`/envchain be handled in logs and reports?
- Are additional `global_environment_skip_vars` defaults needed beyond noisy/internal direnv variables?
