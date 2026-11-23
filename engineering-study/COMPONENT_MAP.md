# Component and repository map

This is the reconciled repository inventory for the completed static study. “Core” follows the integrated desktop and major apps in the README plus observed launch paths. Small helpers and optional applications are included for navigation; their presence does not imply each file is active or supported. Investigation detail is linked from the [Index](INDEX.md) and summarized in [Progress](PROGRESS.md).

## Core desktop and applications

| Component | Main source / entry | Kind and observed relationships |
|---|---|---|
| JWM | `JWM.py` | X11 window manager; uses `jtile`, optional `jtheme`; launches JDesk (which hosts JBar), or standalone JBar in clean mode, plus JTerm/JRun shortcuts. |
| JDesk | `JDesk.py` | Tk desktop/pane manager; embeds `JTerm.PtyPane`; imports JBar helpers; hosts JFiles, JShell, JCode, optional JClass/JSlides; owns JIPC server. |
| JBar | `JBar.py` | Tk status bar, metrics, audio/player/brightness controls; imported by JDesk; uses `jpopup`, optional theme/psutil. |
| JTerm | `JTerm.py` | Tk terminal emulator backed by PTY and pyte; standalone defaults to JShell; also provides JDesk pane widget. |
| JCode | `JCode.py` | prompt_toolkit code editor; uses Pygments, optional `jtheme`, `jstatus`, `jicons`, JIPC. |
| JShell | `JShell.py` | prompt_toolkit interactive shell; can launch JCode/JFiles/JClass and use JIPC; theme/icon optional. |
| JFiles | `JFiles.py` | prompt_toolkit file manager/picker; logic in `jfcore.py`; optional image previews, theme/status/icons and JIPC. |
| JRun | `JRun.py` | Tk application/command launcher; search, app discovery and arithmetic delegated to `jrcore.py`. |
| JToast | `JToast.py` | D-Bus notification service and Tk notification UI; started conditionally by `jwm-session`. |
| JAnalyzer | `JAnalyzer.py` | Terminal Git/source/repository inspection tool; uses prompt_toolkit and Pygments. |

## Shared root modules and small utilities

| File | Responsibility / consumers |
|---|---|
| `jtile.py` | Tree tiling data structure and directional neighbor selection; imported by JWM. |
| `jipc.py` | Authenticated loopback TCP messaging; JDesk server and app clients. |
| `jtheme.py` | Shared theme definitions, terminal styles, theme persistence and validation. Many apps import optionally. |
| `jstatus.py` | Shared terminal status formatting, language and Git branch lookup; JCode/JFiles. |
| `jfcore.py` | File listing, paths, operations helpers, recents, Git marks/options; JFiles. |
| `jrcore.py` | Desktop app discovery, ranking, caches, command parsing and safe arithmetic; JRun. |
| `jicons.py` | Shared icon selection/mode; JFiles/JShell/JCode. |
| `jlog.py` | Log path/rotation and repeated-message suppression helper. |
| `jwall.py` | Optional wallpaper-derived chrome theme and cache; invoked by `jtheme` for wallpaper mode. See [shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md#jtheme-and-jwall-role-based-theme-state). |
| `jpopup.py` | JBar calendar and volume popup widgets (current source includes uncommitted additions). |
| `jbash.py` | Persistent Bash process bridge used by root JShell; see [JShell/jbash](COMPONENTS/JSHELL_AND_JBASH.md). |
| `jcat.py` | Small pure animation/state model consumed optionally by JBar for its clickable cat decoration. It is not a separate user-facing program, so its behavior is covered in [JBar](COMPONENTS/JBAR.md) rather than a standalone chapter. |
| `jcursor.py` | Cursor preference and DECSCUSR protocol helper shared by JCode and JTerm; see [shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md#jcursor-jcode-to-terminal-cursor-protocol). |
| `jterm_diag.py` | JTerm diagnostic utility, listed with the terminal troubleshooting path in [JTerm](COMPONENTS/JTERM.md). |

## Shell entry points and desktop integration

| File | Role |
|---|---|
| `start-jwm` | X session launcher; supports `--no-ui`. |
| `jwm-session` | X session initialization, optional D-Bus/picom/JToast startup, then JWM. |
| `jwm-layout` | Applies saved JScreens monitor layout or fallback xrandr layout; calls wallpaper helper. |
| `jwm-wallpaper` | Applies per-monitor or shared wallpaper using xwallpaper/feh/hsetroot. |
| `jfiles-picker` | xdg-desktop-portal-termfilechooser bridge to JFiles, optionally wrapped in JTerm. |
| `scripts/xephyr-test.sh` | Starts JWM under Xephyr for isolated GUI testing. |

## Optional `tools/` programs

| Program/files | Purpose/dependencies evident from source |
|---|---|
| `tools/JScreens.py` | Tk screen layout UI plus `--apply`/`--show`/`--save`; called from `jwm-layout`; xrandr. |
| `tools/JClass/` | Google Classroom/Drive terminal app plus API/download/auth helpers; optional Google API dependencies; JIPC integration. |
| `tools/JSlides.py` | Tk slide/document viewer; LibreOffice conversion and optional PyMuPDF/python-pptx; JDesk recognizes it. |
| `tools/JCava.py` | Generates Cava configuration colored from JDev theme. |
| `tools/JGrab.py` | Album/track matching and download workflow; external network services and tools such as yt-dlp/ffmpeg. |
| `tools/JPlayer.py` | Terminal music player; subprocess/audio backend and metadata/cover reading. |
| `tools/JWrite.py` | Curses terminal game. |
| `tools/kmove.py` | X11 mouse accessibility/control utility using Python-Xlib record/xtest. |
| `tools/CONVERTERPARAICO.py` | Image-to-icon conversion script using Pillow. |
| `tools/JShell/` | Separate C/GTK terminal-like prototype with a constrained Python command interpreter; distinct from root `JShell.py`. See [K-Move and legacy GTK JShell](COMPONENTS/KMOVE_AND_LEGACY_JSHELL.md). |

The optional-tools manifest also mentions Google API, PyMuPDF, and python-pptx. These are not required by the core desktop according to the comments in `requirements-tools.txt`.

## Separate package and data

- `chessyou/`: standalone Python package (`chessyou/chessyou/`), CLI entry via `__main__.py`, app/motor/board/format/analysis modules, own dependency manifest and tests; includes a PGN game record.
- `games/`: game records/data.
- `docs/img/`: screenshots used by README.
- `tools/imagens/`: app icons/assets.
- `.github/`: CI configuration.
- `CHANGELOG.md`, `README.md`, `INSTALAR-SELETOR.md`, `PICOM-ANIMACOES.md`, `LICENSE`: project docs/legal material.
- `*.tar.gz` files: historical/package snapshots whose listed contents and Git provenance are recorded in [archive provenance](INTEGRATION/ARCHIVE_PROVENANCE.md); release-retention intent remains unknown.

## Tests

Root `tests/` has focused unittest modules for shared logic, shell, editor, file state, IPC, theme, tiling, status, notifications, wallpaper, scripts, and screens. Top-level `test_jbar_popup.py` plus `tests/jpopup.py`/`tests/test_jbar_popup.py` include current popup work. `chessyou/tests/` covers the separate package. No tests were run during this static study; CI scope and coverage boundaries are described in [build and validation](INTEGRATION/BUILD_AND_VALIDATION.md).

## Dependency and launch sketch

```text
JWM ──> jtile; optional jtheme; starts JDesk, JBar, JTerm, JRun
JDesk ──> JBar helpers + JTerm PTY widget + jipc server
JDesk panes ──> JFiles / JShell / JCode / optional JClass
JFiles ──> jfcore; optional jtheme/jicons/jstatus; jipc client
JCode ──> prompt_toolkit + Pygments; optional jtheme/jicons/jstatus; jipc client
JShell ──> prompt_toolkit; optional jtheme/jicons; jipc client
JRun ──> jrcore; optional jtheme
JBar ──> jpopup; optional jtheme/psutil
jwm-layout ──> optional tools/JScreens.py; jwm-wallpaper
```

This sketch summarizes direct imports and explicit launch relationships. The completed [architecture](ARCHITECTURE.md), [desktop runtime stack](INTEGRATION/DESKTOP_RUNTIME_STACK.md), [configuration/state map](INTEGRATION/CONFIGURATION_AND_STATE.md), and component chapters trace startup, reverse dependencies, failure behavior, and state ownership. Runtime-only questions remain listed separately in [Progress](PROGRESS.md) and the [technical audit](TECHNICAL_AUDIT.md).
