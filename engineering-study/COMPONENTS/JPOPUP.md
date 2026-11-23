# jpopup — calendar and audio popups for JBar

`jpopup.py` contains the two secondary windows opened from JBar, plus small pure functions for calendar generation, slider mapping, and screen-bound placement. It is a support module, not a process or a general popup framework. JBar imports `CalendarioPopup` and `VolumePopup` directly ([JBar.py:33](../../JBar.py#L33)) and creates them from its clock/volume click handler ([JBar.py:765-783](../../JBar.py#L765)).

## Pure logic

`grade_mes(year, month, hoje=None)` returns six rows of seven cells, Sunday first, including adjacent-month days ([jpopup.py:6-16](../../jpopup.py#L6)). Each cell is `(day_number, belongs_to_month, is_today)`. `mouse_para_percentual()` maps a horizontal coordinate into a clamped integer interval and handles zero-width inputs ([jpopup.py:19-23](../../jpopup.py#L19)). `limitar_popup()` clamps x/y to screen bounds and prefers a location above the anchor pill when possible ([jpopup.py:25-30](../../jpopup.py#L25)). These functions are independently understandable and are the natural places to reason about calendar/geometry correctness.

## Shared popup lifecycle

`PopupBase` is a borderless, always-on-top `tk.Toplevel`; it records the owning bar and anchor pill, starts withdrawn, binds Escape and global mouse clicks, computes screen coordinates from the bar/pill, then grabs input ([jpopup.py:49-76](../../jpopup.py#L49)). A click outside both popup and bar closes it; Escape closes and returns `break`; `fechar()` releases the grab, removes the global bindings, then destroys the popup ([jpopup.py:78-102](../../jpopup.py#L78)). JBar holds at most one popup and toggles it closed when the same pill is clicked again.

This is a lightweight modal interaction model: `grab_set()` directs interaction to the popup until dismissed. The implementation catches `TclError` around grab/release and destruction to tolerate window teardown races. A maintenance concern is that `unbind_all()` removes bindings by sequence globally on the Tk interpreter; if another component also owns handlers for those sequences, closing this popup may remove them. This is an inference from Tk’s global binding API and the local calls, so validate against the application’s binding architecture before changing it.

## CalendarPopup

The calendar starts at the local current month, uses Portuguese month/day labels, and is a fixed 252×286 popup ([jpopup.py:105-111](../../jpopup.py#L105)). `_montar()` redraws a header, weekday row, six-week grid, and “hoje” button; adjacent-month dates are dimmed and today uses the focus accent ([jpopup.py:116-132](../../jpopup.py#L116)). Previous/next buttons adjust year boundaries; the today action resets to the current month ([jpopup.py:133-140](../../jpopup.py#L133)). It is a read-only calendar: clicking dates does not select or launch anything.

## VolumePopup

The volume popup initializes its displayed value from JBar’s last collected snapshot and draws a 0–100 slider ([jpopup.py:142-165](../../jpopup.py#L142)). Mouse click/drag maps to an integer percentage and dispatches `_set_volume` on a daemon thread ([jpopup.py:166-174]). Mute toggles through JBar’s helper and updates the button label locally ([jpopup.py:175-178]). On Linux with `pactl`, it enumerates sinks, resolves friendly descriptions when possible, and offers buttons to set the default sink ([jpopup.py:179-203]). Without `pactl`, sink selection is unavailable; the slider setter still has an `amixer` fallback.

There is a practical consistency caveat: slider changes update the popup’s local value immediately, but the bar’s `Metrics` snapshot is refreshed on its own cadence. Mute state is also optimistically toggled in the popup. A failed system command may therefore make the popup temporarily display a requested state that the system did not accept. This is source-level inference from asynchronous calls and local state updates.

## Relationships and extension guidance

JBar owns popup creation, one-popup-at-a-time policy, and the anchor hitbox. `jpopup` owns window construction and domain-specific controls. The theme is imported optionally and duplicates the same fallback palette used by JBar ([jpopup.py:40-45](../../jpopup.py#L40)); the font is taken from the parent bar. Shared audio helpers (`em_thread`, `toggle_mute`) are imported from JBar in the current source context only if injected? **Source verification required:** this file refers to both names but the visible module contains no import or local definition. Since JBar imports this module before defining either name, clicking mute/listener controls appears to raise `NameError`. This is a concrete unresolved integration defect to record and revisit against the full checkout/version state.

To extend a popup, preserve the anchor and lifecycle contract, keep slow external calls away from Tk callbacks, and account for popup placement on small screens. Pure calculation should remain outside widget code where practical. The project contains popup-related tests under `tests/jpopup.py`, but no test command was run as part of this study.
