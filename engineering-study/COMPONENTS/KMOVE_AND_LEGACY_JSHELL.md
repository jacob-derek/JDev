# K-Move and the GTK/Python JShell prototype

These are independent tools in `tools/`, not the root JShell that runs inside JDesk. Their names can mislead: `tools/JShell/` is a small GTK shell prototype whose Python backend implements a short command set, while root `JShell.py` plus `jbash.py` is the full prompt_toolkit/persistent-Bash environment.

## K-Move — global keyboard pointer control

`kmove.py` connects to X11 through python-xlib and requires the X RECORD and XTEST extensions. An observer connection records global KeyPress events without consuming them; `← → ← →` within one second launches mouse mode ([tools/kmove.py:1-42](../../tools/kmove.py#L1), [tools/kmove.py:291-339](../../tools/kmove.py#L291)). The active mode grabs the keyboard, tracks pointer coordinates, warps pointer for arrows (18 px, Shift 65 px), emulates left/right/middle clicks with `a`/`d`/`s`, and maps Ctrl+PageUp/Down to repeated scroll clicks. Ctrl+L enters a window-selection mode; move pointer over a window and press `a` to raise/focus it ([tools/kmove.py:157-279](../../tools/kmove.py#L157)). The same arrow sequence exits active mode; Escape exits or cancels selection, Ctrl+Q stops the process. Signals disable the RECORD context and unblock its thread ([tools/kmove.py:340-435](../../tools/kmove.py#L340)).

This is a global input tool: while active, it intentionally captures keyboard input, so it is important to know the exit chord before enabling it. The observer is passive until activated. It sends optional notify-send notifications and generates tiny WAV tones in the system temp directory for mode transitions. It is not integrated into JWM’s keymap in the scanned source; launch it explicitly. No X11 input commands were run during this study.

## tools/JShell — GTK shell prototype backed by a tiny Python interpreter

The C GTK program builds a terminal-like window with text output, command entry, and status area. It starts `jshell-core.py` via `GSubprocess`, pipes stdin/stdout, and asynchronously reads lines so backend communication does not block GTK ([tools/JShell/jshell.c:1-21](../../tools/JShell/jshell.c#L1), [tools/JShell/jshell.c:48-160](../../tools/JShell/jshell.c#L48), [tools/JShell/jshell.c:270-345](../../tools/JShell/jshell.c#L270)). Its line protocol is `RESULT`, output lines, `END`; `__JSHELL_CLEAR__` is a special action. Commands are echoed in the UI and sent over stdin. Closing the window force-exits the backend ([tools/JShell/jshell.c:47-119](../../tools/JShell/jshell.c#L47), [tools/JShell/jshell.c:160-240](../../tools/JShell/jshell.c#L160)).

The Python backend is not a shell process. It reads one line at a time, uses `shlex.split`, and implements only exit, pwd, clear, cd, ls, mkdir, touch, ren, jcode, jfiles, and help ([tools/JShell/jshell-core.py:1-13](../../tools/JShell/jshell-core.py#L1), [tools/JShell/jshell-core.py:38-214](../../tools/JShell/jshell-core.py#L38)). It does not execute arbitrary external commands, pipelines, variables, or shell syntax. `cd` changes the backend process directory but the C status-path label is initialized from the GTK process and source does not show an update protocol. Backend path is built from the current working directory plus `jshell-core.py`, so launching the binary outside its tool directory may fail to find the script ([tools/JShell/jshell.c:124-173](../../tools/JShell/jshell.c#L124)).

The Makefile compiles only `jshell.c` and links GTK 3 via pkg-config; `clean` removes the generated binary ([tools/JShell/Makefile](../../tools/JShell/Makefile)). This is distinct from root JShell, which has command registry, completion, history, broader built-ins, and Bash delegation.

## CONVERTERPARAICO — PNG-to-ICO helper

`tools/CONVERTERPARAICO.py` is a minimal Pillow script that requires a PNG input and saves a sibling `.ico` with sizes 256, 128, 64, 48, 32, and 16 pixels ([tools/CONVERTERPARAICO.py:1-50](../../tools/CONVERTERPARAICO.py#L1)). Its `main()` expects `JFiles.png`, `JCode.png`, and `JShell.png` in the current working directory rather than resolving assets relative to the script, so invocation location matters. It is a helper, not part of install/startup.

## Developer notes

The most important distinction is between tool versions: when changing shell functionality, modify/document root JShell for the integrated environment; the tools/GTK version is separate and intentionally much smaller. For K-Move, keep RECORD observation and active XTEST injection separated; for the GTK prototype, preserve the line framing and nonblocking read loop if the backend changes. No compilation or tests were run.
