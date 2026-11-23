# JWM and the tree tiling engine

This chapter traces the first runtime backbone from process launch through X11 window management, keyboard operations, geometry, and shutdown. It is based on the checked-out source at `JWM.py`, `jtile.py`, `start-jwm`, and `jwm-session`; line references may move with later edits.

## Identity and boundary

JWM is an X11 window manager: it claims control of the root window, receives requests/events for top-level windows, chooses their geometry/stacking/focus, and publishes several EWMH properties. It is not a Wayland compositor and expects exclusive X11 WM ownership (`JWM.py:1-8`, `:197-207`). JWM delegates the purely geometric split tree to `jtile.py`; this separation makes the tiling structure testable without an X server and keeps Xlib concerns in JWM (`jtile.py:1-6`; `tests/test_jtile.py`).

JDesk is a managed desktop-background window, not a child surface rendered by JWM. JWM launches it as a separate process and recognizes its X window by type/class/title predicates in `manage()` (`JWM.py:230-243`, `:529-554`). The bar is ordinarily part of JDesk; the “clean” mode can instead start JBar as a separate process/window.

## Launch chain and modes

```mermaid
sequenceDiagram
  participant U as User / TTY
  participant S as start-jwm
  participant X as startx + Xorg
  participant JS as jwm-session
  participant W as JWM
  participant D as JDesk
  participant B as JBar (clean mode)
  U->>S: jwm [--no-ui]
  S->>S: check startx + python Xlib; select free :0..:9
  S->>X: exec startx jwm-session ...
  X->>JS: start session script
  JS->>JS: optional dbus-run-session; cursor; monitors/wallpaper; optional picom/JToast
  JS->>W: exec python JWM.py args
  W->>W: connect X; claim root; publish EWMH; scan windows
  alt normal (no args)
    W->>D: spawn JDesk
  else --no-ui / --no-jdesk
    W->>B: spawn JBar --solo --wm-pid PID
  else --bare
    W->>W: no JDesk and no solo JBar
  end
```

`start-jwm` checks `startx` and imports Xlib, scans the X socket paths `/tmp/.X11-unix/X0..X9`, and calls `startx` with `jwm-session`, forwarding arguments (`start-jwm:15-38`). `jwm-session` makes a session D-Bus bus when absent and possible, applies cursor and monitor setup, starts picom only when both executable and config exist, starts JToast only when a D-Bus address and `jeepney` import exist, then `exec`s JWM (`jwm-session:5-9`, `:16-51`).

JWM’s own CLI has three effective configurations (`JWM.py:1485-1495`):

| Invocation | Effective behavior |
|---|---|
| `JWM.py` | JWM starts JDesk; JDesk normally contains JBar. |
| `JWM.py --no-ui` or `--no-jdesk` | No JDesk; starts standalone JBar in solo mode. |
| `JWM.py --bare` | No JDesk and no solo JBar. |

**Important doc/source discrepancy:** `start-jwm` comments/help and README currently describe `--no-ui` as omitting both JDesk and JBar. But it forwards `--no-ui`, which JWM parses as `clean`; `clean` starts solo JBar (`start-jwm:7-12`, `:38`; `JWM.py:1488-1495`, `:245-260`). Thus `--no-ui` means “no JDesk, standalone JBar present” in the actual Python implementation. `--bare` is the actual both-omitted mode when invoking JWM directly. The current startup shell’s help contract does not expose `--bare` as an option. This is a verified behavioral mismatch, not a recommendation or source change.

## Initialization and state ownership

`JWM.__init__()` initializes the X display/root and monitor geometry, process handles, clients, four workspaces, focus/MRU state, drag/resize state, bar state, X atoms, and cached colors (`JWM.py:119-182`). It then claims the root window, publishes EWMH metadata, grabs keys, queries root size and xrandr monitors, scans existing windows, and starts the selected desktop process.

Important in-memory records:

- `Client` is the WM’s per-window model: X window handle/ID, title/class, workspace, float/fullscreen flags, monitor, geometry, and border/fade state (`JWM.py:94-109`).
- `Workspace` owns the ordered client IDs, per-monitor tiling trees, and the next split orientation chosen by Super+B/V (`JWM.py:111-117`).
- `JWM.clients` maps X IDs to `Client`; `workspaces` is fixed to four; `active` and `mru` represent current focus and focus recency (`JWM.py:135-150`).
- The state file is an output view for JBar rather than a source of WM state. `_write_state()` serializes the current title/workspace/bar/split and used workspace numbers to a temporary file then atomically replaces the state JSON only when the text changes (`JWM.py:387-408`). Exact path constants are near the top of `JWM.py` and should be checked when tuning cache locations.

The root-window claim subscribes to substructure redirect/notify, property changes, key presses, and structure changes. `BadAccess` means another WM already owns the display, so startup exits with an explicit diagnostic (`JWM.py:197-207`). JWM sets a `WM_CHECK` window and EWMH properties including supported atoms, four workspaces named `J|WEB|CODE|MISC`, current workspace, work area, and client lists (`JWM.py:209-228`). These properties are the interoperability surface for panels and applications; the implementation supports a deliberate subset rather than claiming complete EWMH coverage.

## How new windows enter the model

The X server sends `MapRequest`; `_handle()` calls `manage()` (`JWM.py:1342-1360`). `manage()`:

1. Ignores windows already managed or `override_redirect` windows (the latter manage themselves, typical for certain transient UI).
2. Reads title/class and detects JDesk specially. JDesk is placed on the primary monitor, marked as `_NET_WM_WINDOW_TYPE_DESKTOP`, lowered, and causes JWM to reserve the bar strip (`JWM.py:535-554`).
3. For ordinary windows, reads transient status and current geometry. It assigns a monitor based on the pointer, except a transient whose managed parent exists inherits the parent’s monitor (`:556-568`).
4. Dialogs/transients start floating; off-screen floating geometry is centered and clamped to the monitor/bar area (`:569-579`).
5. Adds the Client and workspace membership, subscribes to client property/focus events, configures the border and EWMH desktop/WM_STATE, maps or hides it as appropriate, arranges, and focuses it (`:580-597`).

When the WM itself unmaps windows during workspace changes, it increments `ignored_unmaps`; the next `UnmapNotify` is consumed instead of being mistaken for the app closing its window (`:619-624`, `:1347-1358`). This distinction prevents workspace switching from deleting clients from the model.

## Tiling model: why a tree

`jtile.Arvore` stores `Folha` leaves for window IDs and `Divisao` internal nodes holding orientation, ratio, and two children. Parent pointers allow edits to walk upward; each node caches its last rectangle (`jtile.py:15-43`). A workspace keeps one tree per monitor, so each workspace/monitor pair has an independent tiling arrangement (`JWM.py:111-116`).

When arranging a workspace, JWM groups visible clients by monitor. Floating clients are excluded from tree membership; fullscreen clients remain in the tree so leaving fullscreen restores their previous split position (`JWM.py:672-692`). `_sync_tree()` prunes IDs no longer tiling and inserts newly tiled clients by splitting the currently active leaf when possible (`:650-670`). If Super+B/V provided a one-shot orientation it is consumed; otherwise the split follows the target region’s aspect ratio (`:662-669`).

`Arvore.layout()` recursively divides a rectangle and returns a map of window ID to `(x,y,width,height)`. For horizontal splits it subtracts one gap, applies the node’s ratio, clamps the first side to minimum width, and recurses; vertical splits do the equivalent with height (`jtile.py:102-125`). JWM supplies the usable monitor rectangle after outer margin and bar reservation (`JWM.py:676-692`). Thus the geometry engine returns outer rectangles; JWM later applies X border widths (`jtile.py:5-6`, `JWM.py:744-762`).

Adding a window splits a target leaf into a new division and a new leaf (default ratio 0.5); removing a leaf replaces its parent division with its sibling, so a closed window’s space is reclaimed without rebuilding unrelated branches (`jtile.py:52-97`). `trocar()` swaps window IDs between leaves, preserving each leaf’s position in the split topology (`:136-141`). `alternar_divisao()` flips the immediate parent split (`:128-134`). `redimensionar()` walks upward from a leaf until finding the nearest ancestor split with the requested axis, then adjusts that ratio by pixel delta and clamps it to 10–90% (`:143-162`).

### Example

Suppose workspace 1 has one tiled window A. Its tree is a single leaf. Opening B with horizontal orientation wraps A in a new horizontal division and adds B as the second child; the layout function gives each roughly half the available width with a gap. Opening C focused on B vertically splits B’s leaf, so the final layout is A in one column and B/C stacked in the other. Resizing C upward finds its nearest vertical split and adjusts that division’s ratio; it does not alter the higher horizontal division.

## Focus, rearrangement, floating, and fullscreen

Directional focus and reorder use actual rectangles, not tree traversal order. `vizinho()` searches candidates in the requested direction that overlap on the perpendicular axis, then chooses nearest distance and greatest overlap (`jtile.py:165-187`). For floating windows or when no tiled neighbor exists, JWM falls back to a center-distance heuristic and finally cycles focus (`JWM.py:887-925`). Reorder swaps leaves, arranges, then restores focus on the same window ID (`:927-942`).

Toggling float centers a window at about 60% monitor width and 2/3 monitor height; toggling back re-enters tiling (`JWM.py:964-978`). The arrange pass clamps floats into the overall multi-monitor bounding box, keeps their center on a real monitor, and prevents them covering the JDesk bar strip (`:694-720`). Fullscreen toggles the EWMH state and places the window over the entire monitor; while fullscreen it is excluded from visible tree placement but retained in tree membership (`:680-692`, `:980-994`).

Focus bookkeeping includes active ID, active monitor, MRU order, input focus, EWMH `_NET_ACTIVE_WINDOW`, and border color (`JWM.py:823-873`). Notably, clicking JDesk can give keyboard focus to the desktop without clearing JWM’s remembered active client; focusing that same client later explicitly restores X input focus (`:843-853`). This separates “last active managed client” from “current X input focus,” an important detail when debugging focus behavior.

## Input and event loop

JWM translates keysyms to keycodes when grabbing shortcuts. It registers combinations with NumLock/CapsLock mask variants and leaves Alt unclaimed so JDesk/JTerm can use it (`JWM.py:434-460`). In normal mode only Super-modified keypresses are acted on (`:1149-1160`). The source implements launch, close, full-screen, float, focus cycle, bar visibility, one-shot split orientation, split toggle, resize mode, workspace switching/sending, directional focus/reorder, and movement of floating windows (`:1161-1210`). Resize mode grabs the keyboard at the root and consumes h/j/k/l/arrows until Enter/Escape releases it (`:1122-1147`).

Mouse focus uses synchronous button grabs for buttons 1 and 3. Normal clicks are replayed to the client so its controls still receive the original click; Super+button switches to asynchronous pointer events and starts move/resize (`JWM.py:603-617`, `:1267-1290`). Dragging a tiled window first marks it floating; button 1 moves and button 3 changes dimensions (`:1228-1265`).

`run()` drains pending X events, catches/logs per-event exceptions, publishes changed bar state, advances border animations, and periodically checks monitor outputs. It blocks in `select()` on the X socket instead of spinning; short polling intervals support hotplug and optional color animation (`JWM.py:1393-1425`). `_handle()` dispatches map/configure/destroy/unmap/key/button/motion/property/client messages and root configure notifications (`:1342-1391`).

## Monitor hotplug and desktop/bar coordination

`_refresh_monitors()` reads xrandr geometry and primary output, falling back to the X screen if querying fails. It sorts by x/y, records which monitor holds JDesk, and recomputes client monitor assignment (`JWM.py:277-312`). `_poll_outputs()` compares connected-output signatures twice before acting (avoids reacting to transient hotplug states), runs `jwm-layout` asynchronously, and then refreshes size/monitors, places JDesk, and arranges windows (`:314-370`).

In normal mode, JDesk occupies the primary monitor and JWM reserves a bottom strip only there. In clean mode, standalone JBar supplies that strip; if the bar process exits, JWM releases the strip and rearranges (`:380-385`, `:245-268`). JWM writes the solo bar’s target rectangle in its state file, allowing JBar to position itself without becoming a tiling client (`:387-408`). This is a useful example of cross-process coordination via a small filesystem state projection rather than JIPC.

## Process launch, errors, and shutdown

JWM launches major UI children with `Popen`, a new session, no stdin, and output appended to `~/.cache/jwm.log` (`JWM.py:230-260`, `:1042-1047`). Super+Enter prefers JTerm and falls back through other terminals; Super+E searches common file managers and `xdg-open`; Super+D launches JRun (`:1049-1079`). These launch helpers do not retain handles for ordinary transient apps, while JDesk/solo JBar do have retained `Popen` handles.

Super+Q sends `WM_DELETE_WINDOW` when supported, allowing a graceful app close; otherwise it calls XKillClient (`JWM.py:1081-1096`). Destroy/unmap events remove clients from all workspace lists/MRU and trigger rearrangement (`:1098-1113`). X `BadWindow`/`BadDrawable` races are ignored; other protocol errors are logged (`:184-189`). Per-event failures are logged and skipped so one bad window event need not kill the WM (`:1399-1405`).

Super+Shift+Q sets the loop’s running flag false; finalization calls `shutdown()`. Shutdown removes the JWM state file, releases pointer grab, resets borders, terminates and waits up to 1.5 seconds for JDesk and solo JBar before killing them, clears selected EWMH focus/check properties, syncs and closes the X connection (`JWM.py:1427-1467`). `jwm-session` starts JToast and possibly picom as background processes before replacing itself with JWM; JWM’s explicit shutdown tracks only JDesk and the solo bar. The X server/session wrapper’s exact cleanup of those optional background processes is not fully established by this source trace and is a follow-up question.

## Practical operator and developer guide

- Use `Super+H/J/K/L` or arrows for directional focus; `Super+Shift+...` swaps tiled positions (or resizes floats); `Super+Ctrl+arrows` resizes the closest split.
- `Super+B`/`Super+V` chooses the next new split orientation; `Super+T` toggles the focused window’s parent split; `Super+R` enters repeated resize mode.
- `Super+Space` toggles float, `Super+F` fullscreen, `Super+1..4` switches workspace, and `Super+Shift+1..4` sends the active window.
- `Super+Shift+Q` exits JWM; `Super+Q` requests a client close.
- To understand a geometry bug, inspect in this order: `JWM.arrange()` usable rectangles and client grouping → `_sync_tree()` membership → `Arvore.layout()` rectangles → `_place()` X geometry/border → stacking/focus.
- To understand a disappearing client, follow its MapRequest/UnmapNotify/DestroyNotify path and `ignored_unmaps`; distinguish WM-generated unmaps from client destruction.
- The geometry module can be reasoned about/tested without X; changes to it should preserve parent links, dictionary/leaf IDs, ratio bounds, and geometry coverage. The existing unit tests in `tests/test_jtile.py` are the executable contract (not run for this study).

## Engineering assessment and open questions

**Observed strengths:** state is split between a small pure geometry module and the X11 adapter; the WM handles normal window destruction races; tree insertion/removal keeps local edits local; clients map to per-monitor workspace trees; hotplug and optional services degrade without blocking main startup; file-backed JBar state is written atomically and only when changed.

**Tradeoffs/risks visible in code:** JWM is a large single module, and window state is duplicated across X properties, `Client`, workspace lists, tree membership, and MRU ordering, so consistency depends on centralized mutation paths. `shutdown()` is wrapped in one broad `try`; an unexpected exception early in cleanup can skip later cleanup. Child-process ownership for optional session daemons is not explicit in JWM. The `--no-ui` help/README mismatch is an operator-facing contract bug. These are code-reading observations; impact should be checked against real session behavior before deciding any change.

**Not yet answered:** whether X clients are reliably reparented/left usable after WM exit; EWMH client stacking order accuracy; whether JToast/picom terminate in all `startx` exits; complete hotplug semantics for window-to-monitor reassignment; modal and urgency behavior beyond the inspected paths. These are deferred for future test/code investigation, not guessed here.
