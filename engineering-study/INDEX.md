# JDev Engineering Study

This directory contains the staged, source-grounded engineering study of the JDev repository. Component chapters trace actual implementations; integration chapters describe cross-process contracts and end-to-end workflows. Findings distinguish committed-source facts, working-tree facts, and inferences.

## Recommended reading order

1. [System overview](SYSTEM_OVERVIEW.md) — repository identity and top-level capabilities.
2. [Architecture](ARCHITECTURE.md) — completed system synthesis: startup path, boundaries, data flow, and dependency model.
3. [Component map](COMPONENT_MAP.md) — inventory of programs, libraries, tools, tests, and artifacts.
4. [JWM and tiling](COMPONENTS/JWM_AND_TILING.md) — Stage B runtime backbone deep dive.
5. [Desktop runtime stack](INTEGRATION/DESKTOP_RUNTIME_STACK.md) — JDesk/JTerm/JBar/JIPC and their process boundaries.
6. [Configuration and state](INTEGRATION/CONFIGURATION_AND_STATE.md) — precedence, persistent files, runtime snapshots, and XDG behavior.
7. [Dependencies and validation](INTEGRATION/BUILD_AND_VALIDATION.md) — install boundaries, CI, tests, and manual Xephyr path.
8. [JDesk](COMPONENTS/JDESK.md), [JTerm](COMPONENTS/JTERM.md), [JBar](COMPONENTS/JBAR.md), and [jpopup](COMPONENTS/JPOPUP.md) — interactive desktop components.
9. [JCode](COMPONENTS/JCODE.md), [JFiles and jfcore](COMPONENTS/JFILES_AND_JFCORE.md), and [JShell/jbash](COMPONENTS/JSHELL_AND_JBASH.md) — terminal applications and their integration paths.
10. [Shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md) — IPC, theme, status, logging, cursor, and geometry contracts.
11. [JRun](COMPONENTS/JRUN.md), [JAnalyzer](COMPONENTS/JANALYZER.md), and [JToast](COMPONENTS/JTOAST.md) — launcher, repository inspector, and notification daemon.
12. [Session integration](INTEGRATION/SESSION_AND_DESKTOP_INTEGRATION.md) — startup scripts, monitors, wallpaper, chooser portal.
13. [JScreens](COMPONENTS/JSCREENS.md), [JSlides and media utilities](COMPONENTS/JSLIDES_AND_MEDIA_TOOLS.md), [JClass](COMPONENTS/JCLASS.md), [K-Move and legacy GTK JShell](COMPONENTS/KMOVE_AND_LEGACY_JSHELL.md), and [ChessYou!](COMPONENTS/CHESSYOU.md) — remaining tools and package.
14. [Integrated workflows](INTEGRATION/WORKFLOWS.md) — end-to-end scenarios and guarantees.
15. [Developer guide](DEVELOPER_GUIDE.md) — source navigation, debugging, and extension seams.
16. [Mastery guide](MASTERY_GUIDE.md) — practical workflows and capabilities already present.
17. [Technical audit](TECHNICAL_AUDIT.md) — source-level findings, confidence, and unresolved runtime questions.
18. [Archive provenance](INTEGRATION/ARCHIVE_PROVENANCE.md) and [glossary](GLOSSARY.md) — historical artifacts and vocabulary.
19. [Progress tracker](PROGRESS.md) — completion record, limitations, and handoff state.

## Study chapters

- [System overview](SYSTEM_OVERVIEW.md)
- [Architecture](ARCHITECTURE.md)
- [Component map](COMPONENT_MAP.md)
- [Progress tracker](PROGRESS.md)
- [JWM and tiling](COMPONENTS/JWM_AND_TILING.md)
- [JDesk](COMPONENTS/JDESK.md)
- [JTerm](COMPONENTS/JTERM.md)
- [JBar](COMPONENTS/JBAR.md)
- [jpopup](COMPONENTS/JPOPUP.md)
- [JCode](COMPONENTS/JCODE.md)
- [JFiles and jfcore](COMPONENTS/JFILES_AND_JFCORE.md)
- [JShell and jbash](COMPONENTS/JSHELL_AND_JBASH.md)
- [Shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md)
- [JRun](COMPONENTS/JRUN.md)
- [JAnalyzer](COMPONENTS/JANALYZER.md)
- [JToast](COMPONENTS/JTOAST.md)
- [Session and desktop integration](INTEGRATION/SESSION_AND_DESKTOP_INTEGRATION.md)
- [JScreens](COMPONENTS/JSCREENS.md)
- [JSlides and media tools](COMPONENTS/JSLIDES_AND_MEDIA_TOOLS.md)
- [JClass](COMPONENTS/JCLASS.md)
- [K-Move and GTK JShell](COMPONENTS/KMOVE_AND_LEGACY_JSHELL.md)
- [ChessYou!](COMPONENTS/CHESSYOU.md)
- [Integrated workflows](INTEGRATION/WORKFLOWS.md)
- [Archive provenance](INTEGRATION/ARCHIVE_PROVENANCE.md)
- [Developer guide](DEVELOPER_GUIDE.md)
- [Mastery guide](MASTERY_GUIDE.md)
- [Technical audit](TECHNICAL_AUDIT.md)
- [Glossary](GLOSSARY.md)
- [Desktop runtime stack](INTEGRATION/DESKTOP_RUNTIME_STACK.md)
- [Configuration and state](INTEGRATION/CONFIGURATION_AND_STATE.md)
- [Dependencies and validation](INTEGRATION/BUILD_AND_VALIDATION.md)
- `COMPONENTS/` — one document per significant program/subsystem.
- `INTEGRATION/` — runtime boundaries, shared infrastructure, workflows, and provenance.

All project references are relative to the repository root. Line references are pinned to the inspected checkout and may shift as the code changes. Static analysis cannot establish runtime-only behavior; those questions remain explicit in the audit. The study did not modify existing project source files.
