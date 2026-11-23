# JCat, J Doodles, and the desktop’s ambient animation

This chapter records the character animations added around the JDev desktop: the cat in JBar, occasional desktop creatures, and the bird opening transition. They share a visual direction, but have different owners and lifecycles. JBar owns the resident cat widget; `jdoodles.py` and `jbirds.py` are separate session processes. Main sources: [`jcatsprite.py`](../../jcatsprite.py), [`JBar.py`](../../JBar.py), [`jdoodles.py`](../../jdoodles.py), [`jcat.py`](../../jcat.py), [`jbirds.py`](../../jbirds.py), and [`jwm-session`](../../jwm-session).

## The cat’s visual design and model

`jcatsprite.py` separates cat behavior from pixel art. Each frame is a 16×12 character grid; a palette maps letters to colors, and `Gato.pixels()` converts the current frame into colored pixel coordinates. The default `gatinha` skin is a kitten with tortoiseshell markings: charcoal gray, caramel, brown, and beige fur, a dark face, amber eyes, pale markings around the eyes, white chest and neck, dark paws, and one beige front paw. A legacy `cinza` skin remains available. Both skins provide paired frames for walking, sitting, sleeping, and being held; the held pose has its own frame pair.

`Gato` is a small state machine rather than a renderer. Sitting can transition to walking or sleeping; walking pauses and may reverse direction; sleeping wakes when music is active. Clicking calls `carinho()`, which briefly sits the cat and displays a heart above its head. The heart rises slightly as it fades. The model accepts an injected random generator, which makes sprite and transition tests repeatable ([`tests/test_jcat.py`](../../tests/test_jcat.py)).

## JBar integration

JBar creates the cat model inside `StatusBar` when `jcatsprite` imports and `JGATO` is not `0` ([`JBar.py:51-55`](../../JBar.py#L51), [`JBar.py:577-578`](../../JBar.py#L577)). It draws the sprite directly on the existing Tk canvas, so the normal JBar cat is not a separate X window or process. The bar’s scheduled refresh advances the model and redraws when its animation signature changes. Clicking its hit box gives the cat carinho; music state is passed to the model so a sleeping cat wakes and a sitting cat animates faster ([`JBar.py:482-497`](../../JBar.py#L482), [`JBar.py:890-924`](../../JBar.py#L890)).

The skin comes from `JGATO_SKIN` (JBar defaults to `gatinha`), and `JGATO=0` hides the decoration while leaving the rest of the bar available. The `JCAT` variable mentioned in the legacy `jcat.py` module docstring is not the switch used by JBar; the current JBar implementation checks `JGATO`. `JGATO_ESCALA` is read by the separate X11 runner in `jcat.py`, but that runner’s `main()` currently returns without starting it. Treat that runner and its file-event bridge as retained implementation code, not the active session path.

## `jcat.py`: retained X11 runner and surface model

The module also contains a more ambitious X11 cat runner. `Tela` uses python-xlib and the X SHAPE extension to create a shaped, override-redirect window; `Passeio` maps visible window tops to walkable surfaces, moves between them, and handles pickup, dragging, release, and a short bounce. Right-click pickup grabs the pointer; release at a chosen location creates a temporary ledge so the cat can walk there briefly. The runner can read a cache-file event written by `avisar("coracao")`.

This path is not launched by `jwm-session`, and `jcat.main()` is a no-op in the inspected source. JBar embeds the `Gato` sprite model directly in its canvas. The X11 code is relevant to implementation history and model tests, but should not be described as a currently running free-roaming cat without a later launcher change.

## J Doodles: occasional desktop visitors

`jwm-session` starts `jdoodles.py` in the background when the file exists, python-xlib is importable, and `JDOODLES` is not `0` ([`jwm-session:52-55`](../../jwm-session#L52)). The process uses `jcat.Tela` to inspect the current EWMH work area and visible windows, then creates temporary shaped X11 windows for each animation. `JDOODLES_ESCALA` controls pixel scale; `JDOODLES_RARIDADE` scales waiting intervals, so `2` makes butterfly appearances roughly half as frequent. The `--teste` option forces one effect and exits when it finishes.

The three effects use separate schedules:

- **Butterfly:** by day, enters from a screen edge in a fluttering zigzag, lands on a sufficiently wide window top, pauses for 20–45 seconds, then flies away. Its first appearance waits 300–900 seconds; later waits are 480–1080 seconds, scaled by rarity.
- **Fireflies:** between 19:00 and 05:00, a group of four to seven lights drifts and pulses for 35–75 seconds. Their shaped window has an empty input region, so it does not intercept clicks. The next group waits 70–180 seconds.
- **Ghost:** between 03:00 and 03:09, enters from the right, waves for four seconds, and floats away. A date marker under the JDev cache prevents another appearance on the same day. A JToast notification is attempted as an optional extra.

When no creature is animating, the loop sleeps for one second; active butterfly/ghost and firefly paths use shorter intervals. The process is optional: the session wrapper redirects its output to the session log, and `JDOODLES=0` disables it. Unit tests cover pure sprites, timing rules, and movement models without requiring a live X server ([`tests/test_jdoodles.py`](../../tests/test_jdoodles.py)).

## JBirds: startup reveal

`jbirds.py` is a short-lived Tk overlay started by `jwm-session` before JWM. Seven pixel-art birds fly across the primary monitor while an opaque dark curtain waits, then fades to reveal the wallpaper. `JBIRDS=0` disables it; `--janela` runs a small test window, and `--sem-ui` selects the no-JDesk variant. Fade transparency depends on a running compositor such as picom; without one, the overlay still exits but a smooth reveal is unavailable.

In the normal path, `jwm-session` removes a stale `$XDG_CACHE_HOME/jdev/pronto` marker (or `~/.cache/jdev/pronto`) before launching the birds. JDesk writes the marker after its first idle callback once its initial UI has been built ([`JDesk.py:525-533`](../../JDesk.py#L525)); JBirds then starts the reveal. A 45-second maximum wait prevents a missing marker from leaving the curtain up indefinitely. In `--no-ui` mode, the wrapper passes `--sem-ui`, so the overlay uses the maximum-wait path instead of waiting for JDesk. This is a file-based readiness handshake, not a JIPC request.

The opening effect coordinates the JDesk first paint and wallpaper reveal without making startup depend on the animation succeeding. `jwm-session` starts it in the background, and `jbirds.py` treats its own errors as a reason to close the overlay rather than block JWM.

## JRelogio: jungle clock and timer

`tools/jrelogio.py` is a standalone Tk window, not a session daemon; `jwm-session` does not launch it. JWM manages it like any other application window. Its fixed 52×64 logical-pixel scene is drawn from pure pixel-art functions and scaled by `JRELOGIO_ESCALA` (default 5). The jungle scene contains a framed hourglass, vines and leaves, a branch, and a toucan facing the sand. The toucan breathes, blinks, occasionally looks outward during the day, and sleeps with floating “zZ” marks from 21:00 through 05:59.

In clock mode, the window shows local `HH:MM`; the sand progresses through a 60-second cycle and the hourglass flips at the cycle boundary. `--rapido` shortens the cycle to 10 seconds for visual inspection, while `--ciclo` accepts seconds, unit forms such as `5m` or `1h30m`, and colon forms such as `1:30`. In timer mode (`--timer 25m`), the sand counts down, the text shows remaining time, and a completion notification is attempted through `jhello`; the hourglass does not flip as a clock. `--sem-borda` removes the window frame, `--pos x,y` sets its position, and Escape or `q` closes it.

Rendering and time calculations are separate: `cena_pixels()` composes a frame from timestamp and mode, and `agrupar()` merges same-color horizontal pixels into canvas rectangles while preserving paint order. Tk redraws every 150 ms normally and every 50 ms during the 0.8-second flip. Unit tests cover the sprites, hourglass sand/flip, text bounds, cycle and timer formatting, and night behavior without opening a GUI ([`tools/tests/test_jrelogio.py`](../../tools/tests/test_jrelogio.py)).

## Ownership and extension notes

| Effect | Owner | Rendering surface | Lifetime |
|---|---|---|---|
| Resident cat | JBar | Existing Tk canvas | Lives with the bar; optional via `JGATO` |
| Butterfly, fireflies, ghost | `jdoodles.py` | Temporary shaped X11 windows | Session process; optional via `JDOODLES` |
| Birds and curtain | `jbirds.py` | Temporary full-screen Tk window | Startup animation; optional via `JBIRDS` |
| Free-roaming cat model | `jcat.py` | Shaped X11 window | Runner currently not launched; `main()` is a no-op |
| Jungle clock/timer | `tools/jrelogio.py` | Independent Tk canvas window | Launched by the user; JWM manages the window |

Keep sprite/state logic testable without a display, and keep X11/Tk window creation at the outer boundary. These decorations are optional session polish: startup, JBar controls, and the core WM should remain usable when an effect is disabled or unavailable.
