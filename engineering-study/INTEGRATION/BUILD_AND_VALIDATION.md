# Dependencies, tests, and validation paths

This is the Stage B view of how the project is installed and checked. It records the declared setup and CI behavior; no tests or GUI programs were run as part of this study.

## Repository is script-oriented, with one packaged subproject

The repository root has a Ruff configuration but no root `[project]` packaging metadata in `pyproject.toml`; the README installs core dependencies from `requirements.txt` and runs programs from the checkout. Tests add the root and `tools/` to `sys.path` because code is not installed as a package (`tests/_paths.py:1-8`). In contrast, `chessyou/pyproject.toml` declares a Python package, console script, Python 3.10 minimum, and dependencies on Textual/python-chess (`chessyou/pyproject.toml:1-9`). This is an ecosystem of scripts with a separately packaged subproject rather than one uniformly installed distribution.

## Dependency boundaries

| Manifest / system dependency | Main consumers | Architectural consequence |
|---|---|---|
| Root `requirements.txt`: pyte | JTerm terminal screen emulation | Needed by both standalone JTerm and JDesk panes. |
| prompt_toolkit | JCode, JShell, JFiles, JAnalyzer, JClass | Shared terminal UI framework, including applications beyond the core runtime. |
| Pygments | JCode and JAnalyzer | Syntax lexing/highlighting. |
| python-xlib (Linux marker) | JWM, JBar workspace requests, X11 tools | X11 integration; not portable to a Wayland-only session. |
| Tkinter | JTerm, JDesk, JBar, JRun and GUI tools | System Python GUI module, documented as a system package rather than pip dependency. |
| psutil (recommended) | JBar metrics | CPU/RAM/network data can be absent when unavailable. |
| Pillow (recommended) | JFiles previews and wallpaper color analysis | Image preview/theme enhancement degrades without it. |
| pyperclip (recommended) | JCode clipboard | System clipboard bridge; internal clipboard fallback exists. |
| `requirements-tools.txt` | Google Classroom JClass, PyMuPDF/python-pptx JSlides | Optional tool-specific imports; LibreOffice is a system executable for conversions. |
| `chessyou/pyproject.toml` | Separate chess terminal app | Textual UI and chess rules engine are separate from root app dependencies. |

Root dependencies are generally unpinned (`requirements.txt:5-20`, `requirements-tools.txt:4-12`), and the Ruff CI install is also unpinned (`.github/workflows/ci.yml:40-44`). The root Ruff config ignores selected lint checks under `tools/**`, explicitly described as not yet reviewed (`pyproject.toml:13-15`).

## Current CI flow

`.github/workflows/ci.yml` runs on pushes to `main` and `dev` and on pull requests (`:1-7`). It has:

1. A unit-test job on Ubuntu with Python 3.10, 3.12, and 3.14; `allow-prereleases: true` is enabled for the matrix (`:8-20`).
2. Installation of root `requirements.txt`, then `python -m unittest discover -s tests -t . -v` (`:22-28`).
3. A second adjacent step with the same “Testes” name and the same unittest command (`:27-32`). Source inspection therefore shows the root suite is invoked twice per matrix entry. No test was run in this study, so this records workflow behavior rather than CI outcome.
4. A separate Ruff job on Python 3.12, installing the latest `ruff` and running `ruff check` (`:33-44`).

The test command targets only root `tests/`; it does not discover `chessyou/tests/`. The chess package’s own dependencies are not installed by root `requirements.txt`. Thus the separate package is outside the checked-in CI test path as currently configured.

## Test organization and contracts

Root tests use `unittest` and `tests/_paths.py` adds root and `tools/` to Python import search paths (`tests/_paths.py:1-8`). The suite has focused tests for tile geometry, IPC, file core/state, theme, status, wallpaper, scripts, notification core, JRun core, JCode search/editor, shell, screens, and popups (see [component map](../COMPONENT_MAP.md)).

The project also has `scripts/xephyr-test.sh` for a visual WM session nested in Xephyr (`scripts/xephyr-test.sh:1-33`). It launches JWM with supplied arguments, but its help comment says `--no-ui` means “only WM”; the actual JWM CLI behavior starts solo JBar in that mode, as traced in [JWM and tiling](../COMPONENTS/JWM_AND_TILING.md). The script requires an existing X display and Xephyr, and its current command uses `-ac`; treat it as a visual debugging convenience, not as a security boundary.

## Engineering implications and open questions

- Tests concentrate on helper logic; desktop process lifecycle and actual X interactions are less represented. JWM’s Xephyr script is manual, not shown as CI automation.
- CI covers three Python versions, including a prerelease-enabled newest version, but only Ubuntu. The README’s stated Void Linux environment and distro/system-package behavior are not matrix-tested here.
- The repeated unittest step appears redundant and consumes CI time; whether intentional is unknown.
- The chess package is independently declared but absent from root CI. Its intended install/release workflow remains to investigate.
- Unpinned requirements and Ruff can change without source edits; this affects reproducibility and historical comparisons.
- Optional-tools lint exclusions are a known quality boundary, not evidence that every tool currently has lint failures.

The Stage C deep dives should use tests as contracts where they exist, while identifying gaps between pure unit coverage and integrated GUI/process behavior. Do not infer that a test suite passed merely because CI configuration exists.
