# AGENTS.md

Guidance for coding agents working on this Sublime Text package.

## Project layout

- Source package: `sublime-package/Project Environment/`
- Main plugin: `sublime-package/Project Environment/project_environment.py`
- Default settings: `sublime-package/Project Environment/Project Environment.sublime-settings`
- Command palette entries: `sublime-package/Project Environment/Default.sublime-commands`
- Developer install script: `scripts/install-dev.sh`

## Development workflow

1. Edit files in this repository, not directly in Sublime's Packages directory.
2. Validate Python syntax:

   ```bash
   python3 -m py_compile 'sublime-package/Project Environment/project_environment.py'
   ```

3. Install the package into Sublime Text:

   ```bash
   ./scripts/install-dev.sh
   ```

4. Restart Sublime Text when changing plugin load-time behavior. Sublime does not always reliably hot-reload already-loaded package modules.

## Sublime troubleshooting tools

Prefer checking behavior inside the running Sublime Text process, not just from the terminal.

- Use **Sublime Agent Bridge** when available to inspect running windows, views, output panels, and command behavior.
- Use **Env Doctor** from inside Sublime to compare:
  - Sublime's process `PATH`
  - the deterministic bootstrap `PATH`
  - `direnv export json` results
  - the active window/view/folder context
- Use Project Environment command palette commands:
  - `Project Environment: Show Effective Environment`
  - `Project Environment: Show Tool Paths`

Expected diagnostics for a direnv/Flox project should show tools such as `actionlint`, `yamllint`, `shellcheck`, `uv`, and `node` resolving from the project environment when they are supplied there.

## SublimeLinter integration

Project Environment patches SublimeLinter at the subprocess launch boundary. When troubleshooting linters:

1. Run `Project Environment: Show Tool Paths` for the affected window.
2. Confirm the `Integrations` section says `SublimeLinter: enabled, patched`.
3. Confirm the relevant tool is found in the resolved project `PATH`.
4. If needed, disable with `"sublime_linter_integration": false` in Project Environment settings.

Do not assume SublimeLinter uses the same environment as the terminal. Dock-launched Sublime Text often has a different process environment.

## LSP and file watcher notes

Project Environment currently includes a SublimeLinter adapter, not a general LSP adapter. LSP subprocess environment work should happen at the LSP process-launch boundary; see `docs/lsp-integration.md` before implementing.

Errors mentioning `FSEventStreamStart` are more likely related to Sublime/LSP file watching (for example `LSP-file-watcher-chokidar`) than to Project Environment itself. Project Environment does not create filesystem watchers.

## Design constraints

- Keep environment resolution deterministic.
- Do not inherit arbitrary Sublime process `PATH`, `DIRENV_*`, `FLOX_*`, or virtualenv state into project resolution.
- Use a clean allowlisted base environment and explicit bootstrap paths.
- Resolve per window/view/file immediately before launching subprocesses.
- Preserve explicit user/package overrides where possible.
- Keep runtime code independent of agent-only tooling such as Sublime Agent Bridge.
