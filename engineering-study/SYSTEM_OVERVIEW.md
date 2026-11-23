# JDev: reconnaissance overview

## What is present

JDev is an X11-oriented personal Linux desktop environment implemented primarily in Python, with shell launch/session helpers. The README describes the intended integrated desktop as JWM plus JDesk/JBar and terminal-based programming/file tools ([`README.md`](../README.md), especially its “O que tem aqui” and “Iniciar” sections). The implementation confirms an actual launch chain: `start-jwm` validates X prerequisites and selects a display, `jwm-session` prepares the session and starts optional services, and then executes `JWM.py` ([`start-jwm`](../start-jwm#L1), [`jwm-session`](../jwm-session#L1)).

This is not one application or one Python package. It is a coordinated collection of:

- an X11 window manager and tree tiling engine;
- an optional Tk desktop composed of terminal-backed panes and a status bar;
- standalone Tk and terminal applications;
- shared modules for IPC, themes, file operations, status rendering, logs, icons, and launch/search logic;
- shell integration for monitors, wallpaper, session startup, testing, and file chooser portal integration;
- ambient visual details: the JBar kitten, session doodles, startup bird/reveal overlay, and standalone jungle clock/timer;
- optional tools, a separate `chessyou` Python package, tests, assets, and data/archive files.

## Preliminary scale

Reconnaissance identifies **10 core desktop/application programs** (JWM, JDesk, JBar, JTerm, JCode, JShell, JFiles, JRun, JToast, JAnalyzer), **13 shared/root helper modules or utilities**, **10 optional tool scripts/programs** under `tools/` (counting the JClass group as one user-facing program plus its three support scripts, and the other six tools), and a separate `chessyou` package. These are inventory groupings, not a definitive count of every executable: small diagnostics, game scripts, portal adapters, and duplicate/alternate files are listed separately in [Component map](COMPONENT_MAP.md).

## First architectural impression

The strongest boundary is between the X11 desktop/session layer and independently runnable applications. JWM owns X11 window management and, in the normal mode, launches JDesk; JDesk contains JBar and creates persistent application panes using JTerm’s embedded PTY widget. In JWM’s `--no-ui`/`--no-jdesk` mode, JDesk is omitted and a standalone JBar is launched; `--bare` omits both. The shell launcher’s help text currently describes `--no-ui` differently from the behavior wired through the Python CLI (documented in [JWM and tiling](COMPONENTS/JWM_AND_TILING.md)). Other programs can run in their own terminal or Tk window. JDesk-mediated coordination uses `jipc.py` over authenticated loopback TCP, including open/focus/refresh requests; shell commands and filesystem state provide other forms of integration. Theme values are shared through `jtheme.py`, while optional imports/fallback palettes show that several applications can also run outside the full ecosystem.

## Notable reconnaissance findings

1. **Monitor configuration has a reusable GUI/control path.** `jwm-layout` applies saved JScreens configuration when available, otherwise its own fallback layout; it then applies orientation-sensitive wallpaper selection (`jwm-layout:43-53`, `:115-146`, `jwm-wallpaper:1-12`). The JScreens implementation is in `tools/JScreens.py`, not at the root, and is invoked with `--apply`.
2. **JFiles participates in workflows beyond browsing.** It has a portal adapter (`jfiles-picker`), pick/save modes in `JFiles.py`, and sends IPC requests to refresh/open/focus panes. This creates browser file-dialog and JDesk/editor integration points.
3. **JTerm is both a standalone terminal and a UI substrate.** JDesk imports `PtyPane`/`Pump` from it (`JDesk.py:44-46`); standalone mode defaults to JShell (`JTerm.py:15-17`, `:1547-1559`).
4. **“Optional” does not mean “unrelated.”** JScreens, JClass, JSlides, JCava, and file selection can integrate with core applications despite residing under `tools/` or using optional dependencies.
5. **Working tree caution:** the checkout contains existing modifications, additions, and deletions (`git status --short` at reconnaissance): changes to JBar files and several popup/test files, and deletions of `JWM (2).py` and `jtheme (2).py`. These were not altered. A study finding about duplicates or file state must not mistake this current working tree for a pristine commit.
