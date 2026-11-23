# Investigation progress

## Status

**Engineering book complete for static inspection of the supplied checkout.** Stage A reconnaissance, Stage B architecture reconstruction, Stage C component investigations, cross-component synthesis, developer/mastery guides, technical audit, glossary, archive provenance, and the final documentation consistency/link review are complete. No documentation stage remains unfinished.

“Complete” here means the planned documentation has been produced from source/config/history inspection. Runtime-only questions below remain intentionally open; no tests, builds, GUI sessions, or external network calls were run. The study did not modify existing source files.

## Completed investigations

- **Stage A — reconnaissance:** [System overview](SYSTEM_OVERVIEW.md), [component map](COMPONENT_MAP.md), [build and validation](INTEGRATION/BUILD_AND_VALIDATION.md).
- **Stage B — architecture:** [Architecture](ARCHITECTURE.md), [JWM and tiling](COMPONENTS/JWM_AND_TILING.md), [desktop runtime stack](INTEGRATION/DESKTOP_RUNTIME_STACK.md), [configuration and state](INTEGRATION/CONFIGURATION_AND_STATE.md), [shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md), [session integration](INTEGRATION/SESSION_AND_DESKTOP_INTEGRATION.md).
- **Stage C — core components:** [JDesk](COMPONENTS/JDESK.md), [JTerm](COMPONENTS/JTERM.md), [JBar](COMPONENTS/JBAR.md), [jpopup](COMPONENTS/JPOPUP.md), [JCode](COMPONENTS/JCODE.md), [JFiles/jfcore](COMPONENTS/JFILES_AND_JFCORE.md), [JShell/jbash](COMPONENTS/JSHELL_AND_JBASH.md), [JRun/jrcore](COMPONENTS/JRUN.md), [JAnalyzer](COMPONENTS/JANALYZER.md), [JToast](COMPONENTS/JTOAST.md).
- **Stage C — optional programs/tools:** [JScreens](COMPONENTS/JSCREENS.md), [JSlides and media tools](COMPONENTS/JSLIDES_AND_MEDIA_TOOLS.md), [JClass](COMPONENTS/JCLASS.md), [K-Move/legacy GTK JShell](COMPONENTS/KMOVE_AND_LEGACY_JSHELL.md), [ChessYou!](COMPONENTS/CHESSYOU.md).
- **Synthesis:** [integrated workflows](INTEGRATION/WORKFLOWS.md), [developer guide](DEVELOPER_GUIDE.md), [mastery guide](MASTERY_GUIDE.md), [technical audit](TECHNICAL_AUDIT.md), [glossary](GLOSSARY.md), [archive provenance](INTEGRATION/ARCHIVE_PROVENANCE.md).
- **Documentation review:** index inventory reconciled with existing chapters; component map and architecture status reconciled with the completed study; local links and source line references checked. References remain tied to the inspected checkout and may shift with code edits.

## Important discoveries

- The desktop session chain is `start-jwm` → `jwm-session` → `JWM.py`; JWM owns X windows while JDesk separately owns pane workspaces.
- JTerm is a PTY terminal emulator/widget, not the shell. JShell provides shell interaction and can delegate to persistent Bash.
- JIPC is authenticated loopback TCP JSON-lines messaging; sender success reflects JDesk’s command-specific dispatch result (for example, a push socket write), not completion in the receiving UI.
- JWM state JSON is a separate read-only snapshot consumed by JBar; it is distinct from JIPC.
- JCode’s resident service behavior is specific to its JDesk pane path; other launch paths are ephemeral. Its save path includes external-change and recovery safeguards.
- JFiles separates UI state from `jfcore`; it can route opens through JIPC and provides portal chooser mode with a file-based result contract.
- JBar metric sampling is separate from popup controls. The current `jpopup.py` appears to reference undefined `em_thread`/`toggle_mute` names; runtime impact is strongly indicated but not verified in a UI session.
- `jcat.py` is a small pure animation/state model optionally consumed by JBar; its behavior and integration are covered in the JBar chapter, so it does not warrant a separate program chapter.
- `start-jwm` help/comments describe `--no-ui` differently from JWM’s actual mode: the current WM starts standalone JBar for `--no-ui`; `--bare` suppresses both JDesk and JBar.
- JToast starts conditionally with D-Bus/jeepney. Its state file claims a JBar consumer, but no in-repository JBar reader was found.
- Root CI configuration repeats the root unittest discovery command and omits the separately packaged ChessYou test tree.
- Git history/archive listings show historical snapshots and alternate files; intent/release use cannot be inferred from names alone. The supplied working tree also contains pre-existing edits, deletions, and untracked popup files.

## Remaining questions / execution boundaries

These are not unfinished documentation tasks; they require runtime or external repository-owner evidence:

1. Verify JDesk PTY/child cleanup and JWM/optional-daemon shutdown in isolated Xephyr.
2. Exercise JIPC recipient disconnect, queue, acknowledgement, and reconnect lifecycle.
3. Determine whether an external process consumes `jtoast-state.json`.
4. Establish whether archive tarballs and alternate copies have an active release/retention purpose.
5. Verify supported optional dependency combinations and hardware-specific monitor behavior.
6. Confirm the apparent JPopup missing-helper failure in a controlled UI runtime.

No such runtime work was authorized/performed during this static study; these are suitable follow-up investigations if the user wants behavioral verification.

## Final status and optional follow-up

There is no remaining documentation task. The book is ready to be assembled into a unified book/PDF. The open items above are optional behavioral validation questions requiring runtime or external-state evidence; they are not missing chapters or unfinished static-analysis stages.

## Working-tree preservation note

Before study output, `git status` showed pre-existing modifications to `JBar.py` and `JBar (2).py`, deletions of `JWM (2).py` and `jtheme (2).py`, and untracked popup source/tests. These were preserved. New study material resides under `engineering-study/` only.
