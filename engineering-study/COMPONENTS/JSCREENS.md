# JScreens — graphical monitor layout editor

JScreens is a Tk tool for arranging XRandR outputs visually, choosing mode/rate/rotation/primary state, saving a JSON profile, and applying it. Its pure parsing, geometry, and command-building layer is intentionally separate from Tk and has unit coverage ([tools/JScreens.py:1-19](../../tools/JScreens.py#L1)). JWM’s `jwm-layout` calls `JScreens.py --apply` at startup/hotplug when the config exists; the UI is therefore both a user-facing editor and a reusable monitor policy engine.

## Data and command model

`Saida` models one X output, its connected/active/primary flags, current geometry, rotation, mode/rates, and xrandr-created mode aliases ([tools/JScreens.py:75-94](../../tools/JScreens.py#L75)). `parse_query()` parses `xrandr --query`, including mode refresh rates and rotation-adjusted active geometry ([tools/JScreens.py:96-146](../../tools/JScreens.py#L96)). Config is versioned JSON at `$JSCREENS_CONFIG` or `$XDG_CONFIG_HOME/jdev/screens.json`; writes use a sibling temporary file and `os.replace` ([tools/JScreens.py:42-72](../../tools/JScreens.py#L42)).

`montar_args()` turns saved profile plus current connected outputs into a single xrandr argument vector. Disconnected configured outputs are ignored; newly connected unconfigured outputs are auto-enabled at the right; coordinates are normalized so the active layout begins at (0,0); inactive/disconnected outputs are disabled ([tools/JScreens.py:177-239](../../tools/JScreens.py#L177)). `garantir_modos()` asks `cvt` for unsupported custom timings and registers them through `xrandr --newmode/--addmode`; then `aplicar_config()` queries, builds, and applies the single xrandr command, with status codes for success/no-op/failure ([tools/JScreens.py:242-294](../../tools/JScreens.py#L242)).

## Geometry editor

The pure geometry helpers snap dragged rectangles near other monitor edges, prevent overlap, guarantee connected monitor edges so the pointer does not fall into a desktop gap, and align edges/centers ([tools/JScreens.py:295-400](../../tools/JScreens.py#L295)). `App` renders scaled monitor rectangles and keeps a separate logical configuration model. The side panel edits enabled/primary, resolution, refresh, rotation, coordinates, and alignment; drag and arrow keys update logical positions ([tools/JScreens.py:418-519](../../tools/JScreens.py#L418), [tools/JScreens.py:536-780](../../tools/JScreens.py#L536)). Snap tolerance is 16 screen pixels, and arrows move 10 pixels or 100 with Shift.

Applying records the current layout first, applies the proposal, refreshes wallpaper, and presents a timed confirmation/revert path; the intent is to recover from an unusable display arrangement if the user does not confirm ([tools/JScreens.py:782-860](../../tools/JScreens.py#L782)). CLI supports UI, `--apply`, `--show`, and `--save`; it also avoids duplicate UI instances ([tools/JScreens.py:861-924](../../tools/JScreens.py#L861)).

## Practical use and developer guidance

Open `python tools/JScreens.py`, drag screens into a connected arrangement, select each output to adjust settings, then Apply and confirm while the display remains usable; Save persists the profile for future sessions. JWM’s layout wrapper attempts the saved profile and falls back to its default HDMI/VGA policy if JScreens fails. For programmatic changes, prefer testing `parse_query`, `montar_args`, and geometry functions independently before touching Tk behavior.

Engineering tradeoff: the editor models xrandr rectangles and chooses a connected topology, while xrandr remains the authority on available timings and actual application. Applying changes the live display immediately; the confirm/revert UI is therefore a core safety mechanism. The default fallback remains hardware-specific. No display command or tests were run in this study.
