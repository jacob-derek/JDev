# JDesk: desktop composition and pane coordinator

JDesk is the Tk application that turns the JDev tools into a single desktop surface. It owns one X window, four in-process pane workspaces, the embedded JBar, terminal PTYs, an optional JSlides viewer, and the JIPC server used by pane applications. This chapter builds on [Desktop runtime stack](../INTEGRATION/DESKTOP_RUNTIME_STACK.md), focusing on JDesk’s own state and interaction model.

## Identity and role

JDesk solves a specific composition problem: keep separate interactive programs (JFiles, JShell, JCode) visible and usable together, while giving them shared navigation, sizing, focus, status, and file-open behavior. It is not a conventional desktop shell full of independently managed windows. JWM sees one JDesk desktop window; JDesk internally places Tk frames and terminal widgets (`JDesk.py:110-138`, `:300-328`; `JWM.py:502-554`).

The division of responsibility is:

- JWM controls top-level X windows and reserves space for JDesk’s bar.
- JDesk controls its internal workspace and pane geometry, Alt shortcuts, file routing, and app coordination.
- JTerm owns terminal emulation and PTY lifecycle for each pane.
- JBar renders shared metrics and WM state.
- JIPC transports commands between pane apps and JDesk.

## Execution and initialization

The entry point `main()` enables DPI awareness, creates a Tk root, constructs `JDesk`, then enters `root.mainloop()` (`JDesk.py:519-527`). `JDesk.__init__()` establishes title/geometry/minimum size/theme, starts JIPC before panes exist, launches metrics collection, builds the bar and content area, initializes a four-slot list of lazy workspaces, starts the JTerm Pump and bar timers, creates workspace 1, installs the close protocol, and schedules IPC polling (`:300-328`).

The ordering matters: pane construction reads `desk.ipc.env()` and passes the dynamic port/token into child environment. Starting the IPC server after workspace construction would leave the first pane processes without the session endpoint (`JDesk.py:308-309`, `:130-138`).

The module resolves application script paths in this order: `JDev/<program-stem>/<filename>`, repository root, `tools/<program-stem>/<filename>`, then `tools/<filename>` (`JDesk.py:83-99`). This accommodates optional programs such as JClass without hard-coding every tool’s directory. A missing program resolves to the expected root path; JTerm’s restart-mode pane can show a process-start error and permit retry.

## Workspace and pane model

JDesk has four internal workspaces. A workspace is created only at first visit; each one creates exactly three panes: JFiles, JShell, JCode (`JDesk.py:53-54`, `:102-107`, `:110-138`, `:340-352`). The process model is therefore three PTY child programs per created JDesk workspace, plus the JDesk process itself. First switching through all four can start twelve pane programs. They remain alive when hidden and are closed only when their workspace shuts down or their pane is explicitly ended.

Each workspace stores:

- `slots`: ordered pane names; the initial order is JFiles on top, JShell lower-left, JCode lower-right.
- `row_split`: top-row height ratio (initially 0.60).
- `col_w`: lower-row column fractions (initially 0.50/0.50).
- `maximized`: pane name temporarily occupying the full workspace.
- `active`, `last_slot`: focus navigation state.
- optional `viewer`/`viewer_aberto` and the pane to return focus to (`JDesk.py:110-138`).

Geometry is normalized to the workspace frame rather than stored in pixels. `rects()` maps each slot to fractional `(x,y,width,height)` coordinates; `layout()` applies those fractions and a 4-pixel inset (`GAP_PX`/`INSET`) to each pane (`JDesk.py:60-62`, `:154-177`). This lets Tk naturally recalculate positions when the JDesk window changes size.

Focus movement uses a fixed three-slot topology, not a general graph search: top moves down to the last focused lower slot; lower slots move up to the top or sideways if a neighbor exists (`JDesk.py:207-226`). Moving a pane swaps slot contents, not widget/process identity (`:228-240`). Resizing changes row ratio when focus is top/bottom, or transfers width between a lower pane and its neighbor; bounds prevent rows below 20%/above 80% and lower columns below 12% (`:242-259`). Pane processes and their state survive all these geometry operations.

### Practical example

Start with JFiles above the two coding panes. Focus JShell and use Alt+Shift+Left/Right to move that pane’s slot; the JShell process does not restart. Use Alt+R, then `j` or `k` to alter the vertical division; `h` or `l` changes the focused lower pane’s width at the expense of its neighbor. Alt+F or Alt+Z makes the focused pane fill the workspace; pressing it again restores the fractional layout.

## Workspace creation and visibility lifecycle

`switch(i)` validates the index and no-ops if already there. It exits JDesk resize mode, constructs a `Workspace` the first time, hides the old workspace, shows the target, updates JBar’s “created” indicators, and schedules focus restoration after 60 ms (`JDesk.py:340-352`).

`Workspace.hide()` calls `place_forget()` on the frame and marks its panes invisible; it does not suspend or terminate their PTYs (`:146-149`). `show()` places the frame over the workspace and relayouts unless an embedded viewer is open (`:141-144`). The Pump’s pane provider iterates every created workspace (`JDesk.py:336-337`), so hidden pane output continues to be drained; JTerm suppresses redraw when a pane is invisible. This trades some ongoing child CPU for continuity of shell/editor state while avoiding hidden widget rendering.

The JDesk workspace state (created slots, layout ratios, active panes, maximize state) is entirely in memory. No serializer/load path appears in this component; restarting JDesk resets it to the default slot layout and only workspace 1 is immediately created.

## Input ownership and shortcuts

Every pane receives `key_filter=desk.on_key`. JTerm calls this filter before translating the key into terminal bytes, so JDesk gets first refusal over Alt shortcuts and media keys (`JDesk.py:133-138`, `:435-493`; `JTerm.py:1084-1105`).

| Input | Action |
|---|---|
| Alt+H/J/K/L or arrows | Move focus between pane slots. |
| Alt+Shift+H/J/K/L or arrows | Swap focused pane with neighboring slot. |
| Alt+1..4 or JBar tab | Switch JDesk’s internal workspace. |
| Alt+F / Alt+Z | Toggle focused pane maximize. |
| Alt+R then H/J/K/L or arrows | Resize current pane region; Enter/Escape exits the mode. While active, keys are consumed. |
| Alt+Shift+R | Restart focused pane process. |
| Alt+Shift+Q | Stop focused pane and leave it awaiting Enter/restart. |
| Alt+Shift+E | Ask before closing JDesk and live pane programs. |
| Media volume/mute/brightness keys; Alt+=/-/M | Run audio/brightness controls. |

The handler ignores Ctrl+Alt (AltGr) as a JDesk modifier so characters on layouts such as ABNT2 can reach the terminal (`JDesk.py:446-449`). Media keysyms are handled before viewer/pane logic, and global workspace/audio/close shortcuts continue to work while JSlides is focused (`:435-471`).

Resize mode is a JDesk-local mode, distinct from JWM’s Super+R mode. It displays a status message via JBar and intercepts all key events for ordinary panes until Enter/Escape (`JDesk.py:416-432`). It does not grab the X keyboard at the root; it works because JTerm routes focused pane key events through `on_key`.

## Optional embedded viewer

JDesk imports `SlidesPane` from JSlides inside a `try/except ImportError`; without it, other JDesk behavior continues and requests to open in the viewer fail with a clear message (`JDesk.py:48-51`, `:262-277`, `:397-400`). PDF, PPT, PPTX, and ODP extensions default to the viewer; other paths default to JCode (`:64-65`, `:390-405`).

The viewer is a single lazily created widget per JDesk workspace. Opening it stores the currently active pane as the return destination, marks underlying terminal panes invisible (but does not stop them), stretches the viewer over the frame, loads the requested path, and optionally focuses its canvas. Closing it restores pane layout and returns focus to the remembered pane (`JDesk.py:262-284`). This creates a useful preview workflow without spawning a separate top-level window.

## JIPC command dispatch from JDesk

JIPC’s server threads enqueue incoming app requests. JDesk’s `_poll_ipc()` drains the queue on the Tk thread every 30 ms, where `tratar_ipc()` can safely open a viewer, focus widgets, or route commands (`JDesk.py:354-364`, `:386-414`). Supported command handling:

- `open`: validates a nonempty path; routes to `viewer` by extension or `jcode` by default, with a `target` override. Viewer opens in JDesk; editor requests go to the named JCode receiver for the specified workspace. `focus` defaults true.
- `focus`: focuses a named pane only when its workspace is currently on screen.
- `refresh`: broadcasts to every registered JFiles pane.

`ws_da_msg()` interprets the request’s 1-based workspace field. If it is invalid or refers to a workspace not yet created, it falls back to current workspace (`JDesk.py:366-371`). `focar()` refuses a noncurrent workspace rather than silently switching workspaces; it closes an obstructing viewer or exits maximize mode if necessary before focus (`:373-384`). This is deliberate: a tool-originated request does not unexpectedly change the user’s current JDesk workspace.

Transport success has a limit: when JDesk pushes `open` to JCode, it treats a successful socket send as success; it does not wait for JCode to finish loading the document. See the integration chapter for protocol details and end-to-end trace.

## Status bar and metrics integration

JDesk embeds `StatusBar` from JBar inside its root, passes `switch` as the workspace-tab callback, and passes `_bar_visivel` so state-file changes pack/unpack the widget (`JDesk.py:313-334`). Metrics are shared with the bar, which starts periodic UI refresh. JDesk also forwards media shortcuts to JBar’s audio/brightness helpers in background threads, preventing slow system commands from blocking Tk (`JDesk.py:67-74`, `:435-469`; `JBar.py:189-191`).

The normal JDesk bar’s workspace tabs use JDesk’s own callback. In standalone-bar mode the same JBar widget API asks JWM to switch top-level workspaces via EWMH. Same visual component; different workspace owner.

## Shutdown and failures

Closing from the user invokes `close()`. It builds a list of active pane programs across all created workspaces and asks for confirmation; cancel leaves the app running. On acceptance it marks shutdown, closes JIPC server sockets, stops Pump and bar timers, stops metrics worker events, shuts down each existing workspace’s panes/viewer, then destroys the Tk root (`JDesk.py:287-297`, `:499-516`). Each `PtyPane.shutdown()` is responsible for its PTY process-group close path.

This cleanup guarantee applies to JDesk’s own close path. JWM’s Super+Shift+Q process termination bypasses it; see the runtime-stack chapter for the unresolved child-process behavior. An unexpected exception partway through `close()` is not caught around the cleanup sequence, so a failure in one subsystem could prevent later teardown steps; actual incidence is not established from source alone.

Dependency failures are mostly optionalized at composition boundaries: JSlides import failure disables embedded viewing; JTerm pane process-start failure is visible in the pane and can be retried; absent metrics libraries reduce bar data rather than preventing JDesk startup. JIPC starts before the rest of the UI and binds loopback; if socket creation itself fails, `JDesk.__init__()` currently has no local fallback around `Servidor()`.

## Developer navigation and extension guidance

- Change pane membership or default order: `ORDER`, `comandos()`, and `Workspace.__init__()` (`JDesk.py:53`, `:83-107`, `:130-138`). Ensure the new pane gets its environment identity and input/focus callbacks.
- Change geometry constraints: `MIN_ROW`, `MAX_ROW`, `MIN_COL`, `STEP`, `rects()`, and `redimensionar()` (`:56-62`, `:154-162`, `:242-259`). Keep lower widths summing to 1 and ensure bounds leave enough usable layout.
- Change key behavior: update `on_key()` and any terminal key-filter assumptions together; return `True` only when the host consumed the key.
- Add a new IPC operation: update dispatch in `tratar_ipc()`, its request schema/callers, and tests for validation and workspace visibility. Keep Tk operations on the Tk thread.
- Add a viewer file type: extend `VIEWER_EXT` and confirm JSlides can open it. Missing optional viewer remains a supported state.
- Debug “pane didn’t start”: inspect path resolution, child argv/environment, PTY widget’s actual-size gate, then JTerm backend creation.
- Debug “action went to wrong pane”: log sender workspace/pane fields, `ws_da_msg()` fallback, receiver registration key, and current workspace check in `focar()`.

## Engineering assessment

**Effective choices:** lazy workspaces avoid launching all twelve pane programs at session start; retaining hidden panes preserves work in progress; normalized layout means simple resize handling; host key filtering gives the desktop global shortcuts without making applications aware of them; Tk ownership is preserved by queuing cross-thread IPC to the main loop; optional viewer and fallback paths keep the core usable.

**Tradeoffs:** lazy initialization is only per workspace, but opening all four workspaces can multiply app/resource usage. All panes remain live while hidden. Layout and JDesk workspace state reset every session. Focus and IPC routing deliberately refuse some requests to nonvisible workspaces. The large top-level `JDesk.py` combines window setup, layout, input, viewer, IPC, and lifecycle, so future changes should follow its boundaries carefully.

**Remember:** JDesk orchestrates, JTerm runs terminal programs, JBar renders system/WM state, and JWM manages the single outer window. When a behavior feels wrong, identify which of those layers owns it before changing code.
