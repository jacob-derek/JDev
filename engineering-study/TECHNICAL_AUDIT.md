# Technical audit: verified findings and follow-up areas

This is a source-review audit, not a runtime validation report. Findings below are limited to observed code paths, test/configuration coverage, and repository history. Severity describes likely user or maintenance impact if the behavior is as traced; confidence records how directly the source establishes the point.

## Findings

| Priority | Finding | Evidence and confidence | Practical impact / follow-up |
|---|---|---|---|
| High | `VolumePopup` references `em_thread` and `toggle_mute` without a definition/import visible in `jpopup.py`; the current bar imports the popup module before any injection is visible. | Direct source inspection in [jpopup chapter](COMPONENTS/JPOPUP.md#volumepopup); high confidence for the missing module bindings, runtime impact inferred. | Mute/sink control callbacks appear to raise `NameError`. Confirm in isolated UI/runtime before changing; tests cover helper calculations, not these control actions. |
| Medium | JWM launcher/help text says `--no-ui` omits JBar, while actual JWM mode starts solo JBar; `--bare` omits both. | CLI parse and launch path documented in [JWM chapter](COMPONENTS/JWM_AND_TILING.md#launch-chain-and-modes); high confidence. | User expectation and script help disagree. Update documentation/CLI contract only after deciding intended semantics. |
| Medium | JToast writes a count state whose documentation says JBar consumes it, but no reader was found in current repository/JBar source. | Cross-repository read/search documented in [configuration/state](INTEGRATION/CONFIGURATION_AND_STATE.md#state-inventory) and [JToast](COMPONENTS/JTOAST.md); high confidence for in-repo absence, external consumer unknown. | Notification count may not appear in JBar; external consumer remains possible. Determine whether the claim is stale or another program consumes it. |
| Medium | JIPC command success is not uniform end-to-end confirmation: pane `open` confirms a socket write, while `refresh` reports success without checking recipient count. | `JDesk.tratar_ipc()` and `Servidor.entregar()` paths are traced in [desktop runtime](INTEGRATION/DESKTOP_RUNTIME_STACK.md#thread-ownership-and-requestresponse) and [shared infrastructure](INTEGRATION/SHARED_INFRASTRUCTURE.md#jipc-authenticated-local-message-transport); high confidence. | Callers cannot infer that the receiving UI completed the action. Preserve this distinction in diagnostics and any future retry policy to avoid duplicate actions. |
| Medium | Root CI runs the same unittest discovery command twice, while ChessYou’s separate test tree and dependencies are outside that path. | Workflow configuration documented in [build and validation](INTEGRATION/BUILD_AND_VALIDATION.md#current-ci-flow); high confidence. | Redundant CI time and a coverage boundary. The reason may be accidental or intentional; no CI run was performed. |
| Medium | Several GUI/process lifecycle areas are not established by helper-only tests or static review, including JDesk PTY teardown and JWM shutdown with optional daemons. | Component/test-path coverage map in [build and validation](INTEGRATION/BUILD_AND_VALIDATION.md); [JWM shutdown](COMPONENTS/JWM_AND_TILING.md#process-launch-errors-and-shutdown); high confidence that no runtime verification occurred, behavior unknown. | Prioritize isolated Xephyr/manual lifecycle investigation before changing cleanup ownership. No process leak is asserted. |
| Low | The repository has archive snapshots and duplicate-looking alternate files with uncertain retention intent. | Git and archive listing in [provenance](INTEGRATION/ARCHIVE_PROVENANCE.md); high confidence for observed history and contents, intent unknown. | Risk of editing the wrong copy or confusing release artifacts with active source. Resolve policy with repository maintainers. |
| Low | The `jfiles-picker` contract and install instructions may be environment-specific. | Script and `INSTALAR-SELETOR.md` reviewed in [session integration](INTEGRATION/SESSION_AND_DESKTOP_INTEGRATION.md#file-chooser-portal-bridge); high confidence for current script, user-specific setup scope. | Deployment may need local paths/config; do not treat one machine’s example as universal. |
| Low | Optional dependency behavior differs by feature, and root dependencies are largely unpinned. | Manifests/import paths documented in [build and validation](INTEGRATION/BUILD_AND_VALIDATION.md); high confidence. | Reproducibility and fallback differences across systems. Static source review cannot establish all installed combinations. |

## Strengths supported by implementation

- Pure helper boundaries (`jtile`, `jfcore`, `jrcore`, ChessYou game logic) separate some core decisions from UI and permit focused tests.
- JCode’s save flow includes external-change checks, atomic replacement, and recovery handling; JFiles has a pure helper layer; JRun caches launcher data and usage separately.
- JIPC authenticates local senders using a session token and bounds message/queue handling; callbacks are handed off so UI owners can mutate their own state.
- JWM’s state projection and JCode/JFiles saves use atomic-file patterns in important paths, limiting partial reads/writes.
- Optional services generally have startup prerequisites and fallback paths rather than being required for basic JWM startup.

These observations describe specific mechanisms; they do not prove the whole ecosystem is failure-free.

## Questions that require runtime or external-state evidence

1. Under an isolated Xephyr session, do JDesk’s PTYs and descendants exit on normal JWM shutdown, forced WM termination, and pane restart?
2. What exactly happens when JIPC enqueues a command and the recipient disconnects, unregisters, or never handles it? Is a server reply sent before or after queue insertion, and what does the caller do on timeout?
3. Is `jtoast-state.json` consumed outside the repository? Does JBar count integration reflect an earlier implementation?
4. Are `.tar.gz` snapshots used by a packaging/release workflow or retained only as historical artifacts?
5. Which optional dependency combinations are supported in practice, especially the root script tools and the separately packaged ChessYou/JClass/JSlides apps?
6. Does monitor hotplug reconciliation preserve intended workspace/monitor assignments when screens disappear and return?

## Limits of this audit

No tests, builds, GUI sessions, external service calls, or archive extraction were performed. The study did not alter existing source files. Repository state includes pre-existing edits, deletions, and untracked popup files; provenance is recorded separately so source-branch findings are not conflated with working-tree-only findings.
