# LSP Integration Findings

Project Environment should be the real Sublime Text solution for deterministic project environments. Agent bridges and other external tools are only useful for development/debugging and must not be part of runtime architecture.

## Problem

Sublime Text packages often launch subprocesses: language servers, linters, formatters, build tools, etc. Those subprocesses need the environment for the relevant project/window/view.

For projects that use `direnv`/Flox, tools such as `shellcheck` and `uv` may only exist after evaluating the project's `.envrc`.

A common failure mode is startup ordering:

1. Sublime starts.
2. Packages load.
3. An environment package asynchronously resolves or mutates environment state.
4. LSP or another package may already have resolved/started a subprocess.
5. The subprocess starts with the wrong `PATH`.

This is especially visible with Sublime LSP providers because language server binaries and tools used by those servers can be resolved before any custom environment package has finished setup.

## What Project Environment currently solves

Project Environment provides a deterministic environment-resolution primitive:

1. Determine the relevant Sublime window/view/file/folder.
2. Start from a clean allowlisted base environment.
3. Do **not** inherit Sublime's arbitrary process `PATH`, `DIRENV_*`, `FLOX_*`, `VIRTUAL_ENV`, etc.
4. Discover `direnv` from an explicit bootstrap path.
5. Run `direnv export json` in the nearest `.envrc` directory.
6. Return a resolved environment and deterministic tool paths.

This avoids launch-history and cross-window contamination. During experimentation, inheriting Sublime/Pi's process environment caused `uv` for one project to resolve from an unrelated Flox environment. Starting from a clean base fixed that.

## What this does not solve by itself

The package does not yet make LSP/SublimeLinter/build systems use the resolved environment. It only exposes the correct environment and tool paths.

To solve subprocess startup races, integration must happen at the process-launch boundary: immediately before the target package calls `subprocess.Popen` or equivalent.

The goal is not to globally mutate `os.environ` earlier. The goal is:

```text
about to launch subprocess for view/window -> resolve env for that view/window -> launch subprocess with resolved env
```

## Sublime LSP findings

Sublime LSP has a per-server hook with the right timing:

```python
AbstractPlugin.on_pre_start(window, initiating_view, workspace_folders, configuration)
```

This hook runs before the language server subprocess is started and can mutate `configuration.env` or return a working directory.

However, it is exposed per LSP helper package/server, not as a public global hook for every language server configuration. Therefore it does not by itself provide a single general Project Environment integration point.

Relevant LSP internals inspected:

- `LSP.plugin.api.AbstractPlugin.on_pre_start(...)`
- `LSP.plugin.core.windows` calls `plugin_class.on_pre_start(...)` before creating the transport.
- `LSP.plugin.core.transports.TransportConfig.resolve_launch_config(command, env, variables)` builds the process launch env.
- `LSP.plugin.core.transports._start_subprocess(...)` ultimately calls `subprocess.Popen(...)`.

Current LSP launch behavior constructs process env from `os.environ.copy()` plus configured `env` overrides. This means it can inherit Sublime's contaminated launch environment unless explicitly corrected.

## Integration options

### 1. Upstream/global LSP hook — preferred long term

Add a global environment-provider/pre-launch hook to Sublime LSP itself.

Desired shape:

```text
LSP is about to launch a language server
LSP asks registered environment providers for env for window/view/workspace
Project Environment returns resolved env
LSP launches server with that env
```

Pros:

- Clean public API.
- No monkeypatching.
- Works for all LSP providers and user/project configs.
- Could become the standard solution for Sublime LSP.

Cons:

- Requires upstream changes and release cycle.

### 2. Per-LSP adapter classes

Create adapter packages/classes for individual LSP providers using `AbstractPlugin.on_pre_start`.

Example behavior:

```python
resolved = project_environment.resolve_for_view(initiating_view)
configuration.env.update(resolved["env"])
```

Pros:

- Uses public LSP API.
- Correct timing.
- Avoids monkeypatching.

Cons:

- Requires one adapter/cooperation point per server package.
- Does not automatically cover user-defined/project-only LSP configurations.
- Operationally noisy.

### 3. Command wrapper

Configure LSP commands through a wrapper executable/script, e.g.:

```json
"command": ["project-environment-exec", "bash-language-server", "start"]
```

Pros:

- No monkeypatching.
- Race-free for configured commands.
- General pattern can work outside LSP too.

Cons:

- Requires editing every command/config.
- Does not help tools discovered by packages before invoking the wrapper.
- Less integrated with Sublime context unless the wrapper is given enough metadata.

### 4. Narrow monkeypatch of LSP launch config — practical fallback

Patch one central LSP internal function used by language server subprocess launches, likely:

```python
LSP.plugin.core.transports.TransportConfig.resolve_launch_config
```

That function receives:

```python
command, env, variables
```

and returns the launch config used by LSP transports. A Project Environment LSP adapter could patch it to use a resolved project environment as the base env, then apply LSP's explicit `env` overrides.

Pros:

- One integration point for many/all LSP server launches.
- Solves the race at process-launch time.
- Does not require per-server packages.

Cons:

- Private API / monkeypatch risk.
- Need a reliable way to map `variables`/cwd/command launch to the correct window/view/project context.
- Must track LSP internal changes.

If used, the adapter should be conservative:

- separate package/module from core Project Environment,
- disabled by default or clearly configurable,
- patch idempotently,
- verify expected function signatures before patching,
- preserve explicit per-server `env` settings,
- fail open rather than breaking LSP,
- log diagnostics clearly.

## Recommended architecture

Keep layers separate:

```text
Project Environment                 # deterministic env resolver + public API
Project Environment - LSP Adapter   # optional LSP integration
Project Environment - Linter Adapter# optional SublimeLinter integration
project-environment-exec            # optional command-line wrapper
```

The core package should remain general-purpose and not depend on LSP, SublimeLinter, or agent tooling.

## Open questions

- Can Sublime LSP provide enough public context for a global environment provider without upstream changes?
- Is there a stable context key in LSP `variables` that maps back to window/view/project reliably?
- Should Project Environment cache `direnv export json` results, and if so what invalidates the cache (`.envrc`, `.envrc.local`, parent `.envrc`, Flox files, direnv watches)?
- How should secrets from `direnv`/envchain be handled in logs and panels?
- Should explicit LSP `env` override Project Environment, or vice versa? Initial recommendation: Project Environment provides base env, explicit LSP config wins.
- How should user/project opt-out be represented?
