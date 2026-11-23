# Shared infrastructure — communication, themes, status, logging, and geometry

This chapter studies the small modules that give separate JDev programs common contracts. They are not one framework: each solves a narrow problem and most are imported optionally. The strongest shared seams are JIPC for messages, jtheme for color/measurements, jstatus for terminal status-bar formatting, and jtile for pure window geometry.

## JIPC: authenticated local message transport

JIPC is a loopback TCP request/notification channel owned by a JDesk session. JDesk starts `Servidor`, then gives child panes `JDESK_SOCK`, a random `JDESK_TOKEN`, workspace, and pane identity; clients outside that environment cleanly no-op ([jipc.py:1-30](../../jipc.py#L1), [jipc.py:40-71](../../jipc.py#L40)). Messages are JSON Lines. `enviar()` adds token/workspace/sender metadata, performs a short-lived connection with a default 300ms timeout, and returns true only if JDesk’s Tk-thread handler replies `ok` ([jipc.py:74-88](../../jipc.py#L74), [JDesk.py:386-414](../../JDesk.py#L386)). For `open` to a registered pane, that means `entregar()` wrote the push message to its socket; it does not mean the receiving app finished opening the file. `refresh` reports success after JDesk dispatches the broadcast branch, even if no file-manager receiver is connected.

`Receptor` registers a named, long-lived connection, invokes a callback on its own daemon thread, and retries after disconnect ([jipc.py:91-150](../../jipc.py#L91)). `Servidor` listens only on `127.0.0.1`, validates tokens with constant-time `hmac.compare_digest`, accepts bounded lines and queue size, and places commands in a queue for the Tk-owning JDesk thread to consume ([jipc.py:153-236](../../jipc.py#L153)). It tracks registered clients by `(workspace, name)`. Delivery is bounded to one second, and broadcast reaches same-named recipients in all workspaces ([jipc.py:238-276](../../jipc.py#L238)).

Important threading rule: receiver callbacks run off the UI thread. JCode’s callback only appends a requested path; JFiles’ callback only sets a `threading.Event`. UI mutation happens later in their own event loops. This is the right pattern to preserve: message callbacks should signal state, not manipulate Tk/prompt_toolkit objects from the socket thread.

The message types in use include `open`, `focus`, and `refresh`. JDesk interprets requests and routes them to panes; JFiles uses `open`/`refresh`, JCode receives `open` and sends focus back, and JShell sends open/focus. This is separate from JWM’s `jwm-state.json` and from EWMH desktop requests. JIPC is an authenticated session-local command path, not a general system bus.

Semantics caveat: a true result is more than raw queue acceptance because JDesk’s UI-thread handler has processed the command. The strength of the result depends on the command: `open` to an app confirms a socket write, viewer open confirms the JDesk viewer call returned true, and `refresh` confirms the dispatch branch ran. None gives an application-level completion acknowledgement. A stale receiver or a receiver that reads but fails to act can still leave the user without the intended result.

## jtheme and jwall: role-based theme state

`jtheme.py` defines named role palettes and exports stable role constants used by JWM, JDesk, JTerm, JBar, JCode, JFiles, JShell, and JRun. Selection precedence is environment `JTHEME`, config file `$XDG_CONFIG_HOME/jdev/theme` (or `~/.config/jdev/theme`), then Tokyo Night ([jtheme.py:1-20](../../jtheme.py#L1), [jtheme.py:148-179](../../jtheme.py#L148)). The chosen palette becomes module-level `T`, with constants such as `DESK_BG`, `PANE_BG`, `PILL_BG`, `FOCUS`, and `BAR_H`; UI code consumes roles rather than hardcoding a particular theme ([jtheme.py:217-276](../../jtheme.py#L217)).

Per-program style builders adapt the shared role dictionary to prompt_toolkit classes for JCode, JFiles, and JShell ([jtheme.py:282-387](../../jtheme.py#L282)). CLI commands list/set/show/check themes, and validation checks required color values and contrast ([jtheme.py:435-520](../../jtheme.py#L435)). A call to `set` persists the preference for later process/session imports; it does not hot-reload already-running processes.

`jwall.py` is an optional theme generator invoked when the selected theme is `wallpaper`. It selects `JWM_WALLPAPER` or a configured image under `~/.config/jdev`, samples a 96×96 RGB thumbnail, finds a weighted dominant hue, and derives only UI chrome colors. Syntax/ANSI colors stay with the base theme to protect readability ([jwall.py:33-64](../../jwall.py#L33), [jwall.py:98-117](../../jwall.py#L98)). It caches derived chrome by wallpaper path, mtime, size, and base label ([jwall.py:119-169](../../jwall.py#L119)). Missing Pillow/image/parse errors degrade to no generated theme. The design keeps image analysis out of normal imports except when wallpaper mode requests it.

## jstatus and jicons: consistent terminal UI fragments

`jstatus.py` provides a small language-extension/icon registry, branch lookup, palette adaptation, and shared status fragments. `montar_status()` accepts a data dictionary instead of knowing about JCode’s buffer; it lays out filename/save state, current mode, branch, cursor position, percentage, language, flags, and messages within a supplied width ([jstatus.py:13-77](../../jstatus.py#L13), [jstatus.py:82-104](../../jstatus.py#L82), [jstatus.py:135-220](../../jstatus.py#L135)). JCode creates the semantic status state and delegates rendering; JFiles uses palette/icon classes and `jfcore` composes its row view. The module’s inputs are presentation data, so callers remain authoritative about their own state.

`jicons.py` chooses Nerd Font, emoji, or ASCII according to `JICONES` and terminal/font capability, exporting common folder/file/link symbols ([jicons.py:1-90](../../jicons.py#L1)). Consumers generally retain emoji fallbacks when it is absent. This means icon mode is an environment-level appearance choice and fonts must support selected glyphs for alignment to look correct.

## jlog: bounded process logs

`jlog.py` centralizes an XDG-aware cache directory, a 1 MB default rotation threshold, child stdout/stderr append-file creation, and duplicate-message suppression ([jlog.py:13-50](../../jlog.py#L13)). Rotation retains one `.1` file by replacing the previous backup. `SemRepetir` normalizes X11 sequence/resource identifiers before deduplication so repeated benign warnings do not flood logs ([jlog.py:51-70](../../jlog.py#L51)). The JWM chapter covers how child processes use this; this module itself is intentionally small.

## jcursor: JCode-to-terminal cursor protocol

`jcursor.py` maps DEC private mode `DECSCUSR` values to cursor shape/blink preferences and back. Its JSON config lives at `$XDG_CONFIG_HOME/jdev/jcode.json` or `~/.config/jdev/jcode.json`; absent/corrupt/invalid values fall back to a bar cursor that blinks ([jcursor.py:18-55](../../jcursor.py#L18)). `sequencia()` emits `ESC [ Ps SP q` for JCode to write to the terminal ([jcursor.py:64-66](../../jcursor.py#L64)). JCode requests the code; JTerm interprets it into cursor drawing state. This is a good example of a protocol that crosses a terminal application boundary without a direct Python API call.

## jtile: pure tree tiling engine

`jtile.py` owns the geometric tree model used by JWM. `Folha` represents a window ID; `Divisao` represents a horizontal/vertical split with ratio; parent links permit local edits. `Arvore.inserir()` splits a target leaf (or most recently inserted leaf); `remover()` collapses the parent and promotes its sibling ([jtile.py:15-93](../../jtile.py#L15)). `layout()` recursively assigns external rectangles and subtracts gaps between children while enforcing minimum dimensions ([jtile.py:95-124](../../jtile.py#L95)). Split orientation toggle, window swapping, and resize adjust the nearest applicable division ratio ([jtile.py:126-163](../../jtile.py#L126)). `vizinho()` uses rectangle adjacency, distance, and overlap to find a directional neighbor ([jtile.py:165-199](../../jtile.py#L165)).

The module is pure geometry and has no X dependency. JWM is responsible for deciding which window IDs enter each workspace/monitor tree and applying returned rectangles to X windows. This boundary makes tree behavior testable without a live display and keeps geometry rules independent of X11 event ownership.

## Shared contracts and extension guidance

The ecosystem’s commonality is deliberately lighter than a single shared runtime: theme constants and status fragments are import-level libraries; JIPC is a session process protocol; jcursor is an escape-sequence protocol; JSON state files connect independently running processes; jtile is a pure data/geometry library. When adding a feature, choose the existing seam that matches the data and ownership. Avoid reaching into another app’s mutable state when a message or normalized data object already exists.

Known integration caveats: some clients fall back to embedded colors if jtheme is missing; JBar’s state-file polling is separate from JIPC; jwall cache is a snapshot and keyed by the image signature; theme changes are generally applied on next process/session startup. JIPC reports command-specific dispatch status, not user-visible completion in the recipient.
