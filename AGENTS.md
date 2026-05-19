# AGENTS.md

Guidance for coding agents working on this Sublime Text package.

## Project layout

- Source package: this directory
- Main plugin: `project_environment.py`
- Default settings: `Project Environment.sublime-settings`
- Command palette entries: `Default.sublime-commands`

## Development workflow

1. Edit files in this repository.
2. Validate Python syntax:

   ```bash
   python3 -m py_compile 'project_environment.py'
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

Project Environment applies the active view's resolved environment to Sublime Text's process-wide `os.environ`. When troubleshooting linters, LSP servers, build systems, Git integration, or other subprocess users:

1. Activate a view in the affected project.
2. Run `Project Environment: Show Tool Paths` or `Project Environment: Show Effective Environment`.
3. Confirm the `Applied global environment` section matches the expected project and that the relevant tool is found in the resolved project `PATH`.
4. Restart already-running subprocesses such as LSP servers if they were started before the environment was applied.

Do not assume SublimeLinter, LSP, or build systems use the same environment as the terminal. Dock-launched Sublime Text often has a different process environment.

## LSP and file watcher notes

Project Environment does not patch LSP internals. LSP servers inherit the active global process environment when they start. Restart servers after changing projects or `.envrc` content.

Errors mentioning `FSEventStreamStart` are more likely related to Sublime/LSP file watching (for example `LSP-file-watcher-chokidar`) than to Project Environment itself. Project Environment does not create filesystem watchers.

## Design constraints

- Keep environment resolution deterministic.
- Do not inherit arbitrary Sublime process `PATH`, `DIRENV_*`, `FLOX_*`, or virtualenv state into project resolution.
- Use a clean allowlisted base environment and explicit bootstrap paths.
- Resolve per window/view/file immediately before launching subprocesses.
- Preserve explicit user/package overrides where possible.
- Keep runtime code independent of agent-only tooling such as Sublime Agent Bridge.
