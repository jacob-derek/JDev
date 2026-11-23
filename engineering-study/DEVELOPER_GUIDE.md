# Developer guide: navigate, debug, and extend JDev

This guide is a code-navigation map for the architecture documented in the component chapters. It emphasizes the first file to inspect, the state owner, and the handoff to follow. Source paths are repository-relative.

## Start from the user-visible symptom

| Symptom | Follow this path |
|---|---|
| Desktop does not start | `start-jwm` prerequisite/display selection → `jwm-session` setup log → `JWM.py` X connection/initialization → child launch and `~/.cache/jwm.log`. See [session integration](INTEGRATION/SESSION_AND_DESKTOP_INTEGRATION.md). |
| Window is placed/focused incorrectly | `JWM.manage()` / focus handlers → `Workspace` membership → `_sync_tree()` → `jtile.Arvore.layout()` → JWM `_place()` and stacking. Separate X focus from JDesk pane focus. See [JWM](COMPONENTS/JWM_AND_TILING.md). |
| Pane has wrong size or output | `JDesk` pane layout → `JTerm.PtyPane` `<Configure>` → `calc_size()` → PTY resize; for missing output follow reader thread → bounded queue → Tk `Pump.tick()` → pyte → dirty-row render. See [JTerm](COMPONENTS/JTERM.md). |
| Shell key does not work | JTerm host key handling and terminal sequence → JShell prompt_toolkit binding / Bash subprocess policy. Distinguish a terminal’s key encoding from a shell command binding. See [JShell](COMPONENTS/JSHELL_AND_JBASH.md). |
| Open/focus request is lost | Client request → JIPC socket/token → server queue → JDesk UI-thread consumer → target pane state/event loop. Sender success reports JDesk dispatch status, not recipient completion. See [shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md). |
| File unexpectedly changed or cannot save | JFiles navigation/operation state and `jfcore` helpers, or JCode buffer snapshot → external-file check → atomic write/recovery path. See [JFiles](COMPONENTS/JFILES_AND_JFCORE.md) and [JCode](COMPONENTS/JCODE.md). |
| Theme differs between programs | Check `JTHEME`, XDG config theme, process start time, and optional-import fallback. Existing processes do not automatically reconstruct widgets. See [configuration/state](INTEGRATION/CONFIGURATION_AND_STATE.md). |
| Monitor or wallpaper is wrong | JScreens saved configuration → `jwm-layout` application/fallback → XRandR geometry → `jwm-wallpaper`; then compare JWM’s own monitor snapshot. See [JScreens](COMPONENTS/JSCREENS.md). |
| JBar control does not apply | Inspect popup callback, external command selection, worker thread, optimistic local state, then the next metrics sample. Verify the popup module’s actual imports before assuming helpers resolve. See [JBar](COMPONENTS/JBAR.md) and [jpopup](COMPONENTS/JPOPUP.md). |

This order follows state ownership. Do not start with rendering if the data or process event never arrived.

## Repository navigation by responsibility

### Session and windowing

- `start-jwm`, `jwm-session`, `jwm-layout`, `jwm-wallpaper`: OS/session boundary and child setup.
- `JWM.py`: X event ownership, clients, workspaces, focus, process launch, and teardown.
- `jtile.py`: pure split-tree geometry; it should not acquire Xlib responsibilities.
- `JDesk.py`: desktop composition and pane/workspace lifecycle.
- `JTerm.py`: reusable terminal emulator/PTY plus standalone window mode.

### Interactive applications and their libraries

- `JCode.py`: editor buffer, input bindings, file lifecycle, rendering/status integration.
- `JFiles.py` + `jfcore.py`: UI/navigation state versus normalized file operations and selection helpers.
- `JShell.py` + `jbash.py`: interactive shell UI, command dispatch, optional persistent Bash process.
- `JRun.py` + `jrcore.py`: launcher UI versus search/cache/ranking logic.
- `JBar.py` + `jpopup.py`: persistent status/metrics versus anchored popups.
- `JToast.py`: optional D-Bus service and notification policy.

### Shared modules and tools

- `jipc.py`: local session command transport.
- `jtheme.py`, `jwall.py`, `jicons.py`, `jstatus.py`: appearance and status presentation contracts.
- `jcursor.py`: terminal escape-sequence cursor contract between JCode and JTerm.
- `jlog.py`: bounded child logs and duplicate suppression.
- `tools/`: optional applications; inspect each tool’s manifest/import guards before assuming it is installed.
- `chessyou/`: independently packaged Textual app, with separate dependencies and tests.

The [component map](COMPONENT_MAP.md) is the inventory; the [architecture chapter](ARCHITECTURE.md) describes boundaries. Begin with the component chapter before editing a shared module: a small utility can affect several programs.

## A safe reasoning method for a feature change

1. **Name the owning state.** Identify which process/module is authoritative (for example, JWM owns X window membership; JDesk owns pane selection; JCode owns its editor buffer).
2. **Trace the current entry point.** Start at the callback/CLI/event handler that users invoke, then follow synchronous calls, queues, timers, and child-process boundaries.
3. **Identify the contract.** Decide whether the seam is a Python import, JIPC message, environment/CLI argument, terminal escape sequence, file protocol, or JSON snapshot. These contracts have different failure and timing behavior.
4. **Preserve thread ownership.** In particular, do not mutate Tk widgets from JIPC receiver threads; signal the owning event loop instead. Keep blocking subprocess work away from interactive callbacks where the component already uses workers.
5. **Preserve fallback semantics.** Optional imports and external commands intentionally degrade in several paths. Follow both the preferred and fallback branches before changing them.
6. **Update the right documentation and tests.** Root helper tests do not automatically exercise GUI lifecycle, X events, or optional services. `chessyou/` has a separate test/package boundary. The validation map documents what CI covers.
7. **Inspect process ownership and shutdown.** Every new `Popen`, PTY, thread, timer, socket, or file descriptor needs an owner and a teardown path; verify error and early-exit paths as well as normal operation.

This method is derived from recurring implementation patterns in the studies, not a claim that all programs follow one framework.

## Debugging with the least context switching

- Check the source of truth before the display: config file/environment for settings; state owner for live state; view/widget only for presentation.
- For cross-process behavior, write down PID, parent, environment variables, cwd, log path, and protocol payload. JDev’s integration frequently depends on those details.
- Use `~/.cache/jwm-session.log`, `~/.cache/jwm.log`, and component-specific logs/state locations described in [configuration/state](INTEGRATION/CONFIGURATION_AND_STATE.md). Honor XDG overrides where the code does.
- For pure helpers such as `jtile`, `jfcore`, `jrcore`, and ChessYou’s game logic, reason at the helper boundary first. For GUI and process issues, helper tests alone cannot establish the behavior.
- Treat repository history and current working tree separately. This checkout has pre-existing edits, deleted alternate files, and untracked popup files. The [archive provenance note](INTEGRATION/ARCHIVE_PROVENANCE.md) records which claims are about `HEAD` versus the working tree.

## Extension seams that fit existing design

- New geometry rule: keep it in `jtile` if it is pure; let JWM adapt its output to X.
- New pane action: keep UI state inside JDesk or the pane; use the existing JIPC request when another process must ask for it.
- New file-manager operation: put filesystem semantics in `jfcore` when they are independent of widget state; keep selection/result protocol behavior consistent for portal mode.
- New appearance: add semantic roles through `jtheme` and verify consumers/fallback behavior, instead of introducing unrelated literal colors in one program.
- New terminal status fragment: provide normalized presentation data to `jstatus`; do not make shared formatting inspect an application’s private buffer.
- New optional application: state its dependencies and launcher path explicitly. The root repository is script-oriented; do not assume the tool is installed as a package.

These are existing seams. Broader packaging, service supervision, or a unified plugin API would require future design work.
