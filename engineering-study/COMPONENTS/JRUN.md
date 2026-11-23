# JRun and jrcore — application launcher and command palette

JRun is a small Tk application launcher for X11 sessions. `jrcore.py` contains app discovery, matching/ranking, persistence, terminal wrapping, command parsing, and a constrained calculator. The UI opens centered on the monitor under the pointer, shows cached applications immediately, and refreshes discovery in a background thread ([JRun.py:25-40](../../JRun.py#L25), [JRun.py:105-205](../../JRun.py#L105)).

## Discovery and ranking

`pastas_de_aplicativos()` searches user, Flatpak, system, and XDG application directories ([jrcore.py:19-35](../../jrcore.py#L19)). `ler_aplicativos()` recursively reads visible `.desktop` application entries, filters hidden/nodisplay/non-application entries, checks `TryExec`/executable availability, strips desktop field codes, and records display name, argv, terminal requirement, categories, and working directory ([jrcore.py:37-91](../../jrcore.py#L37)). Duplicate desktop filenames are resolved by earlier search-directory precedence.

`buscar()` scores exact name, prefix, word prefix, substring, subsequence, executable basename, comment, and category matches. Every query word must match; the lowest word score determines relevance, with usage count as a tie-breaker. With an empty query, most-used apps rise first ([jrcore.py:93-139](../../jrcore.py#L93)). Cache is under XDG cache; use counts under XDG state. Both JSON writes use a temporary file plus `os.replace` ([jrcore.py:141-200](../../jrcore.py#L141)).

## Launch and interaction

The UI maintains a simple queue from the loader thread; Tk polls it with `after(80ms)` and updates the app list only on the Tk thread ([JRun.py:179-223](../../JRun.py#L179)). Enter launches the selected desktop app, records usage, and closes the palette. Terminal-required apps are wrapped with JTerm when available, otherwise the first known terminal emulator. Launches use `Popen`, a fresh session, and detached standard streams ([JRun.py:42-50](../../JRun.py#L42)).

The search entry also supports direct commands. `!command` or `>command` runs shell syntax through `sh -c`; Ctrl+Enter runs a command directly. Prefix `=...` invokes the restricted calculator. Up/down and Ctrl+N/P move through matches; Page keys jump eight entries; Escape closes ([JRun.py:250-302](../../JRun.py#L250)). `jrcore.calcular()` parses Python expression AST but evaluates only numeric constants, unary signs, and a whitelist of arithmetic operators; it rejects names/calls and limits input length and exponent size ([jrcore.py:252-276](../../jrcore.py#L252)).

JRun prevents duplicate instances with a PID lock file in `$XDG_RUNTIME_DIR` or `/tmp`, checks that the PID is alive and still looks like JRun on Linux, optionally focuses a matching window with xdotool, then removes only its own lock on shutdown ([JRun.py:53-95](../../JRun.py#L53), [jrcore.py:202-217](../../jrcore.py#L202)).

## Engineering notes

The cache-plus-background-rescan approach makes launch UI responsive even if scanning desktop entries is slow. The Tk thread owns all widgets; the worker sends immutable-ish results through a `Queue`. Limitations: executable discovery and `.desktop` parsing are Linux/XDG-centric; command mode deliberately invokes a shell for metacharacters; stale cache can appear until discovery completes; and `start_new_session` means the launcher does not supervise launched app lifetime. JWM invokes JRun as its app launcher, but JRun is otherwise independent of JDesk/JIPC. No runtime or tests were run in this study.
