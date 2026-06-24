# AGENTS.md

Guidance for coding agents working on this Sublime Text package.

## Project layout

- Source package: this directory
- Main plugin entrypoint: `project_environment.py` (Python 3.8 host); keep this limited to Sublime lifecycle hooks, event listeners, and command classes
- Shared implementation package: `shared/` (copied into the materialized legacy-host companion; keep source-compatible with the lowest supported Sublime Text plugin-host Python version, currently Python 3.3)
  - Deterministic environment resolution: `shared/environment.py`
  - Process-wide environment application: `shared/global_environment.py`
  - Shared constants/path/report helpers: `shared/utils.py`
- Report formatting / scratch-view display: `reporting.py`
- Default settings: `Project Environment.sublime-settings`
- Command palette entries: `Default.sublime-commands`
- Legacy-host bootstrap: `bootstrap.py` materializes the `Project Environment Host py33` companion package (Python 3.3 host) from shared modules plus `payload/`
- Legacy-host entrypoint: `payload/project_environment_host.py` (edit here, not the materialized copy in `Packages/Project Environment Host py33/`)

The materialized `Packages/Project Environment Host py33/` directory is generated and must not be hand-edited; bump `BOOTSTRAP_VERSION` in `bootstrap.py` to force a rewrite. The companion reuses modules from `shared/`; keep everything there source-compatible with the lowest supported Sublime Text plugin-host Python version (currently Python 3.3). Files under `payload/` are not loaded as plugins in the main package (they live in a subdirectory).

The companion package name encodes the host Python version as `py33`, not `3.3`, on purpose: Sublime loads a plugin as the module `<package name>.<file>`, and a `.` in the package name is parsed as a Python package separator (so `Project Environment Host 3.3.project_environment_host` fails to import). Package names may contain spaces but must not contain a dot.

## Development workflow

1. Edit files in this repository.
2. Validate Python syntax:

   ```bash
   python3 - <<'PY'
   import ast
   for path in (
       'project_environment.py',
       'bootstrap.py',
       'reporting.py',
       'payload/project_environment_host.py',
       'shared/__init__.py',
       'shared/environment.py',
       'shared/global_environment.py',
       'shared/utils.py',
   ):
       ast.parse(open(path).read())
       print('ok:', path)
   PY
   ```

3. Restart Sublime Text when changing plugin load-time behavior. Sublime does not always reliably hot-reload already-loaded package modules.

## Sublime troubleshooting tools

Prefer checking behavior inside the running Sublime Text process, not just from the terminal.

- Use **Sublime Agent Bridge** when available to inspect running windows, views, output panels, and command behavior.
- Use Project Environment command palette commands:
  - `Project Environment: Show Effective Environment`
  - `Project Environment: Show Tool Paths`

Expected diagnostics for a direnv/Flox project should show tools such as `actionlint`, `yamllint`, `shellcheck`, `uv`, and `node` resolving from the project environment when they are supplied there.

## Global environment integration

Project Environment applies the active view's resolved environment to Sublime Text's process-wide `os.environ`. When troubleshooting linters, LSP servers, build systems, or other subprocess users:

1. Activate a view in the affected project.
2. Run `Project Environment: Show Tool Paths` or `Project Environment: Show Effective Environment`.
3. Confirm the `Applied global environment` section matches the expected project and that the relevant tool is found in the resolved project `PATH`.
4. Restart already-running subprocesses such as LSP servers if they were started before the environment was applied.

Do not assume SublimeLinter, LSP, or build systems use the same environment as the terminal. Dock-launched Sublime Text often has a different process environment.

## LSP and file watcher notes

Project Environment does not modify LSP internals. LSP servers inherit the active global process environment when they start. Restart servers after changing projects or `.envrc` content.

Errors mentioning `FSEventStreamStart` are more likely related to Sublime/LSP file watching (for example `LSP-file-watcher-chokidar`) than to Project Environment itself. Project Environment does not create filesystem watchers.

## Design constraints

- Keep environment resolution deterministic.
- Do not inherit arbitrary Sublime process `PATH`, `DIRENV_*`, `FLOX_*`, or virtualenv state into project resolution.
- Use a clean allowlisted base environment and explicit bootstrap paths.
- Resolve per window/view/file immediately before applying the process environment.
- Keep runtime code independent of agent-only tooling such as Sublime Agent Bridge.
