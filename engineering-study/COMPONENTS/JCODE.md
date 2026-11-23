# JCode — terminal editor, analysis loop, and resident JDesk pane

JCode is a full-screen terminal editor built on `prompt_toolkit`, with local editing behavior, syntax highlighting, completion, outline/minimap features, robust file-format handling, and an optional JIPC receiver. It has two lifecycles: a one-file command-line editor, and a resident idle editor in JDesk’s `jcode` pane that accepts file-open requests. The source states its core goals at [JCode.py:2-11](../../JCode.py#L2), and `main()` makes the resident distinction explicit at [JCode.py:2124-2176](../../JCode.py#L2124).

## Architecture and execution

The module separates into four practical layers:

1. Pure editing/analysis helpers: indentation, line navigation, outline extraction, completion search, auto-pair decisions, search parsing, and minimap calculations ([JCode.py:180-647](../../JCode.py#L180)).
2. File/clipboard boundaries: decoding, encoding, atomic save, external/internal clipboard selection, and error logging ([JCode.py:687-888](../../JCode.py#L687)).
3. Terminal UI: `editar(path)` creates the buffer, UI state, key bindings, processors, margins, outline, status, and `Application` ([JCode.py:1042-2042](../../JCode.py#L1042)).
4. Application lifecycle: idle screen, JIPC receiver, CLI modes, resident loop, and shutdown ([JCode.py:2044-2177](../../JCode.py#L2044)).

`main()` first handles help/setup/map commands. The `-map` command produces a textual Braille-style structural overview without opening the editor. Otherwise, only a process with a live JIPC connection and `JDESK_PANE=jcode` becomes resident. It starts `jipc.Receptor("jcode", _receber)`; all other invocations need a filename and exit after editing ([JCode.py:2111-2176](../../JCode.py#L2111)). The resident idle view waits for a requested path or Ctrl+Q ([JCode.py:2044-2108](../../JCode.py#L2044)).

```mermaid
sequenceDiagram
  participant D as JDesk / JIPC
  participant C as resident JCode
  participant E as editor buffer
  participant F as filesystem
  D->>C: {cmd: open, path}
  C->>C: queue path from receiver thread
  C->>E: exit idle / request file switch
  E->>F: read file; preserve encoding and newline metadata
  Note over E: edits, completion, async analysis
  E->>F: Ctrl+S guarded atomic write
  E-->>C: editor exits
  C->>D: focus JFiles; return to idle
```

## Editing model and interaction states

The editor is a `prompt_toolkit.Buffer` with dynamic completion. `editar()` keeps save state, disk signature, confirmation flags, command/search state, line selection, explore mode, outline state, wrap mode, auto-close mode, and CSI-sequence discard state in small mutable dictionaries ([JCode.py:1060-1090](../../JCode.py#L1060)). Key filters describe which mode owns a key: normal editing, line selection, explore, command/search prompt, outline focus, and auto-pair mode ([JCode.py:1114 onward](../../JCode.py#L1114)). The wrapper around most key handlers logs exceptions and shows a temporary status message rather than allowing a callback exception to crash the UI ([JCode.py:1114-1131](../../JCode.py#L1114)).

Useful implemented shortcuts (the source header is the concise reference, [JCode.py:8-12](../../JCode.py#L8)):

- Ctrl+S save; Ctrl+Q guarded exit; Ctrl+Z / Ctrl+Y (also Ctrl+R) undo/redo.
- Ctrl+G line/column jump; Ctrl+F incremental search; Ctrl+O outline; Ctrl+E explore mode.
- Ctrl+L selects lines; Ctrl+K deletes current/selected lines; Ctrl+A selects all.
- Tab / Shift+Tab indent and dedent; Alt+Backspace deletes a word.
- F3 toggles soft wrapping; F4 toggles automatic pair completion.
- Ctrl+Up/Down scrolls the viewport without moving the insertion point.

`calcular_indentacao_enter()` retains current leading indentation and adds one indent unit after a trailing colon ([JCode.py:188-194](../../JCode.py#L188)). Pair completion is a separate pure decision function that considers the character before/after the cursor and extension policy ([JCode.py:364-418](../../JCode.py#L364)). Line-based selection/exploration are explicit modes, so arrows can navigate without fighting the completion menu. Search uses a live compiled expression and capped match positions, and the outline uses regex rather than AST so incomplete Python code remains navigable ([JCode.py:289-333](../../JCode.py#L289), [JCode.py:1535-1602](../../JCode.py#L1535)).

## Analysis, responsiveness, and scale limits

The editor’s key performance rule is that text-change handling does constant-size bookkeeping, not parsing. A monotonically increasing document version is incremented; a debounced task submits analysis to a single-worker `ThreadPoolExecutor`; only a result whose version still matches is applied. If edits arrive during a running analysis, it records one pending rerun rather than building an unbounded queue ([JCode.py:1963-2004](../../JCode.py#L1963)). The result supplies syntax diagnostics, identifier completion index, outline, and other derived data ([JCode.py:649-684](../../JCode.py#L649)).

Explicit limits prevent expensive analysis from dominating an interactive terminal: files over 30 MiB are refused; AST parsing is skipped above 400,000 characters; all analysis is disabled above 2,000,000 characters; synchronous lexer refresh has a 2,000-line bound; minimap computation has a 600,000-character limit ([JCode.py:137-166](../../JCode.py#L137)). Undo history is trimmed to an approximate character budget ([JCode.py:1995-2002](../../JCode.py#L1995)). The status can communicate disabled analysis, syntax errors, encoding/newline mode, Git branch, cursor, and unsaved state; `jstatus` centralizes rendering when present ([JCode.py:1815-1924](../../JCode.py#L1815)).

## File integrity and recovery

`ler_arquivo()` distinguishes new files from non-regular, too-large, binary, unreadable, and failed reads; a read failure sets `leitura_falhou`, which blocks saving rather than replacing content with an empty buffer ([JCode.py:728-745](../../JCode.py#L728), [JCode.py:1295-1300](../../JCode.py#L1295)). `decodificar_bytes()` tries UTF-8, CP1252, then Latin-1; detects a UTF-8 BOM and dominant CRLF/CR/LF style, normalizing in-memory text to LF ([JCode.py:696-725](../../JCode.py#L696)). Saving restores the remembered newline/BOM and falls back to UTF-8 if the original encoding cannot represent newly entered characters ([JCode.py:748-760](../../JCode.py#L748)).

Before save, JCode compares `(mtime_ns, size)` with the read/save baseline. If the file changed externally, the first Ctrl+S warns and a second explicit Ctrl+S authorizes overwrite ([JCode.py:1301-1305](../../JCode.py#L1301)). Existing files use a same-directory temporary file, flush/fsync, permission-mode copy, then `os.replace`; the original is preserved if the temporary write fails ([JCode.py:771-802](../../JCode.py#L771)). On an unexpected top-level error, the current buffer is written to a `.jcode-recover` sibling and the log path is reported ([JCode.py:2010-2041](../../JCode.py#L2010)).

## Relationships and practical workflows

JDesk sends open requests over JIPC to the resident pane; JFiles and JShell can also launch separate ephemeral JCode processes for ordinary file editing. In the JDesk pane, closing an edited file returns the process to its idle screen and asks JDesk to focus JFiles ([JCode.py:2050-2108](../../JCode.py#L2050), [JCode.py:2150-2173](../../JCode.py#L2150)). This lets an editor remain available without turning every `jcode file` command into a resident daemon.

Practical use: open a source file from JFiles with Enter, use Ctrl+O to navigate declarations and Ctrl+F to search, Ctrl+G for a known diagnostic line, and save with the external-change guard in mind. Use `jcode -map file` for a quick structural preview when you want to stay in a shell. For format-sensitive files, note the status flags and rely on save’s newline/encoding preservation. Clipboard can use `pyperclip`, platform commands, or an internal fallback depending on availability ([JCode.py:804-864](../../JCode.py#L804)).

## Developer navigation and engineering assessment

When extending JCode, locate the pure decision/helper first, then its UI handler, then its status/processor rendering. Keep file operations out of keystroke handlers where they can stall the terminal. Respect the existing mode predicates so a new shortcut cannot accidentally insert text into a prompt or steal outline navigation.

The engineering strengths are concrete: atomic replacement, optimistic external-change detection, safe read-failure behavior, loss-recovery output, versioned asynchronous analysis, bounded undo, and separate visual/process control modes. Tradeoffs include reliance on prompt_toolkit internals for undo-stack trimming; size/line thresholds that intentionally reduce feature richness on large files; a simple mtime+size signature that can miss same-size/same-timestamp replacement; and a single analysis worker that favors bounded resource use over parallel throughput. Those are source-level properties, not claims about untested runtime behavior. No tests were run during this study.
