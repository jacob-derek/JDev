# JDev engineering glossary

Terms are defined in the way they are used in this codebase.

| Term | Meaning in JDev |
|---|---|
| **JDesk workspace** | A JDesk-managed set/arrangement of embedded panes. It is separate from the X window manager’s workspace. |
| **JWM workspace** | One of the X11 window manager’s four top-level client groups, with focus and tiling state. |
| **Pane** | A JDesk region hosting a child program, often through an embedded JTerm PTY terminal. |
| **PTY** | Pseudo-terminal pair connecting a terminal emulator to an interactive child process. JTerm owns the terminal-facing side. |
| **Terminal emulator** | JTerm’s model and rendering of terminal cells/control sequences, backed by pyte and a Tk view. It is not itself a shell. |
| **Shell** | JShell’s command interface and dispatch logic; optionally it delegates command execution to persistent Bash through `jbash`. |
| **X11 window manager (WM)** | JWM’s role: manage top-level X windows, focus, workspace membership, stacking, and geometry. |
| **Compositor** | Optional picom process started by the session script for X visual effects; it is not JWM’s window layout engine. |
| **Tiling tree** | `jtile.Arvore`’s binary split structure, mapping window IDs to rectangles. JWM applies those rectangles through Xlib. |
| **Floating client** | A managed X window excluded from the tiling tree and placed with independent geometry. |
| **EWMH** | Extended Window Manager Hints, the X property/message conventions JWM exposes for interoperability. |
| **JIPC** | JDev’s authenticated loopback TCP JSON-lines channel, normally started by JDesk for session-local app requests. |
| **JIPC dispatch result** | `enviar()`’s boolean reflects JDesk’s command-specific handler result; for pane `open`, it confirms a socket write, not that the receiving UI finished opening the file. |
| **JIPC receiver** | A long-lived client connection registering a name and callback; callbacks run on a worker thread and should hand off UI work. |
| **State projection** | A file snapshot written by one process for another to read, such as JWM’s bar state JSON. It is not necessarily authoritative state. |
| **XDG config/cache/state** | Standard user directories used by many JDev modules for preferences, runtime cache, or durable usage data; some older modules use different locations. |
| **Atomic replacement** | Write a temporary sibling file and rename it into place so readers see the old or new complete file rather than a partial write. |
| **Event loop** | The UI/process loop that serializes callbacks and rendering; Tk widgets must be mutated from their owning Tk loop. |
| **Dirty row** | A terminal screen row pyte marks changed; JTerm can redraw it without repainting the entire terminal. |
| **DECSCUSR** | A DEC terminal escape sequence that requests cursor shape/blink. JCode emits it through `jcursor`; JTerm interprets it. |
| **Status role/palette role** | Semantic color names from `jtheme`, allowing consumers to share visual intent without sharing widget state. |
| **Portal chooser** | The `xdg-desktop-portal-termfilechooser` integration boundary implemented by `jfiles-picker`; result paths are returned via an output file. |
| **Optional dependency** | A package/program checked conditionally so the associated feature can be unavailable while other JDev paths continue. |
| **Working-tree fact** | A behavior observed in files present locally, including untracked/modified files; it may not exist in the current Git commit. |
| **Historical archive** | A committed tarball snapshot. Its name/content does not make it an active runtime module or prove current release use. |

For component-specific vocabulary and examples, see [Index](INDEX.md) and the relevant chapter.
