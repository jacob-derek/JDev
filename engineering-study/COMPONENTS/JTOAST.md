# JToast — freedesktop notification daemon and Tk toast UI

JToast implements the `org.freedesktop.Notifications` D-Bus service so clients using `notify-send` or compatible libraries can display notifications through a small Tk overlay. It refuses to claim the service name if another notification daemon already owns it; `--demo` exercises the visuals without D-Bus ([JToast.py:3-19](../../JToast.py#L3), [JToast.py:266-284](../../JToast.py#L266), [JToast.py:481-511](../../JToast.py#L481)).

## Notification core and safety boundaries

`Gerente` is the in-memory, lock-protected notification model. It sanitizes app/summary/body strings, removes markup-like tags/control characters, caps length/line count, normalizes urgency, assigns/reuses IDs, applies expiry, limits retained notifications to 50, and shows the five newest at once ([JToast.py:60-152](../../JToast.py#L60)). A per-app flood guard drops excess new notifications after 20 in two seconds. `replaces_id` updates an existing live notification and increments its version so the UI rebuilds its toast ([JToast.py:100-123](../../JToast.py#L100)). Expiry uses monotonic time; default normal and low urgency durations are six and four seconds, while critical notifications persist until explicitly closed. Explicit positive timeouts are capped at 60 seconds ([JToast.py:182-190](../../JToast.py#L182)).

The manager collects closure events so the D-Bus thread can emit `NotificationClosed` signals. Dispatch handles server info, capabilities, Notify, CloseNotification, Introspect, and Ping ([JToast.py:203-264](../../JToast.py#L203)). D-Bus runs in a dedicated thread; Tk polls the manager every 200ms and owns all window operations ([JToast.py:286-323](../../JToast.py#L286), [JToast.py:345-480](../../JToast.py#L345)).

## Toast placement and UI behavior

The UI displays at most five borderless, always-on-top notification windows at the top-right of the primary monitor. It uses `xrandr --current`, caches monitor geometry for five seconds, and falls back to Tk’s screen size ([JToast.py:193-200](../../JToast.py#L193), [JToast.py:345-363](../../JToast.py#L345)). Clicking anywhere in a toast closes it. The theme is adapted from jtheme with a fallback palette; urgency colors appear as a narrow side stripe ([JToast.py:364-480](../../JToast.py#L364)).

## Relationship to JWM/JBar and discrepancy

JToast windows are override-redirect notification windows: JWM does not tile, focus, or decorate them. On exit, JToast atomically writes a `jtoast-state.json` snapshot containing PID and notification count, as described by the module’s implementation ([JToast.py:324-343](../../JToast.py#L324)). However, repository inspection of current `JBar.py` found no consumer of this file, despite the JToast comment saying JBar reads it. Treat the count integration as unconnected in this checkout unless an external component consumes the file. This was verified by source search and documented as a finding; no files were modified to bridge it.

## Developer notes

For notification behavior, start with `Gerente.notificar` / `_expiracao`, then D-Bus dispatch, then UI reconciliation. The thread boundary is important: D-Bus callbacks update only the locked model; Tk polls and renders. The manager is comparatively easy to reason about independently of D-Bus/Tk because the policy is concentrated in a plain Python object. Failure to install `jeepney`, missing session bus, or a competing daemon produces a clear startup error; demo mode still supports visual inspection. Tests for manager/protocol behavior exist but were not run in this study.
