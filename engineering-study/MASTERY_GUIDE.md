# JDev mastery guide

This chapter turns implemented features into practical routines. “Existing” means directly supported by the inspected checkout. “Combination” means a workflow assembled from existing programs. “Future” marks a capability that would need implementation.

## Learn the environment by operating its ownership model

The most useful mental model is two layers of workspaces and multiple cooperating processes. Use JWM workspaces to organize top-level windows; use JDesk workspaces to change the set of embedded panes. Use JTerm as the terminal emulator and PTY host, JShell as the shell interface, and `jbash` when persistent Bash state is wanted. This avoids misattributing focus, sizing, or process-lifetime behavior to the wrong component.

Suggested exploration sequence:

1. Start from the [JWM key map](COMPONENTS/JWM_AND_TILING.md#practical-operator-and-developer-guide) and learn directional focus, split choice, resizing, float/fullscreen, and workspace actions.
2. Inside JDesk, identify each pane’s process and workspace behavior. Observe which panes remain alive while hidden.
3. Open JFiles and use its selection/navigation operations; open a text file into JCode through the integrated path.
4. Use JShell for commands, noting which state persists only while a `jbash` process is alive and which command path runs outside it.
5. Use JRun for named/recent launch choices and JAnalyzer to inspect a code tree without confusing that inspection with a build.

## Existing capabilities worth using deliberately

### Programming

- **Edit with recovery-aware saving:** JCode preserves detected encoding/newline details, checks for external edits, and uses atomic replacement/recovery paths documented in its chapter. This is valuable when another process may rewrite a file.
- **Move between navigation and editing:** JFiles’ JDesk integration routes supported open requests into the editor pane; use the local fallback behavior when JDesk is absent.
- **Keep shell state:** use the persistent Bash integration when directory/environment state must survive multiple commands; choose ephemeral dispatch for commands that should not depend on that session.
- **Inspect before running:** JAnalyzer is useful for understanding file/import structure. It is a repository inspection aid, not a static analyzer that proves correctness.
- **Launch repeat commands efficiently:** JRun’s search/cache/usage behavior can reduce repeated command entry; use its configured app definitions as the source of launch behavior.

### System and desktop management

- **Choose display layouts:** use JScreens to save/apply monitor arrangements; `jwm-layout` consumes the configured saved layout and has a fallback policy.
- **Separate wallpaper and chrome color:** `jwm-wallpaper` paints the X root; `jtheme` sets role palettes; wallpaper mode can derive chrome colors using `jwall`. Coordinate both if a unified visual setup is desired.
- **Use JBar as persistent feedback:** workspace/title/system indicators are sampled separately from popup actions. Treat system controls as requests and allow the next metrics refresh to reflect actual state.
- **Use JToast for incoming events:** it is an optional session service with D-Bus requirements. Its state-count integration into JBar is not established in this checkout.

### Files and productivity

- **Use portal chooser integration:** applications that invoke the configured term-file-chooser portal can present JFiles without embedding a second file UI; selected paths return through the wrapper output file.
- **Use media utilities for conversion/preview workflows:** JSlides and its neighboring tools support their documented PDF/presentation/media tasks when optional Python packages and system executables are present.
- **Use JClass where Classroom data is the task:** it has its own authentication/dependency assumptions and chunked Drive download path. It is an optional program, not a core session dependency.
- **Use ChessYou as a separate terminal learning tool:** it is independently packaged and does not participate in the JWM/JDesk runtime.

## Useful combinations already available

| Goal | Combination | Boundary to remember |
|---|---|---|
| Browse, edit, and run a project | JFiles → JCode → JShell or JRun → JAnalyzer | Not an automatic build/debug pipeline; cwd and process environments remain explicit. |
| Configure a workstation display | JScreens saved layout → `jwm-layout` → JWM monitor refresh → `jwm-wallpaper` | Saved monitor state, XRandR state, and JWM geometry are separate stages. |
| Select a file from a terminal-first app | portal → `jfiles-picker` → JTerm/JFiles → output path | Result is a file protocol; cancellation yields no selected path. |
| Move an open file into the editor pane | JFiles/JShell → JIPC → JDesk queue → JCode | Successful `open` confirms JDesk wrote the push to JCode’s socket; it does not prove JCode finished opening the file. |
| Apply a consistent visual setup | set jtheme + choose wallpaper → restart consumers | Theme import is process-time selection; root wallpaper is a separate operation. |
| Keep transient alerts and persistent context | JToast notifications + JBar state | The JToast count is not currently shown by a discovered JBar consumer. |

## Shortcuts and discovery

Use the component chapters as the source of truth for implemented bindings, since shortcuts can differ by program and context. The JWM shortcut list is documented centrally in [JWM and tiling](COMPONENTS/JWM_AND_TILING.md). JCode, JFiles, JShell, JTerm, and JDesk each have their own input model; a key seen by a shell may first be intercepted or translated by JTerm. When a shortcut appears inconsistent, trace the event from X/WM to widget to child terminal before changing a binding.

Use `jtheme`’s CLI for theme listing/selection/checking and JScreens’ CLI for layout inspect/apply operations as documented in their chapters. Do not assume a command-line interface exists merely because a module is importable; the component document identifies actual entry points.

## Limits: what combinations do not magically provide

- Existing JDev tools do not constitute a unified package manager, service supervisor, or declarative automation engine.
- JIPC does not provide end-to-end transaction completion or durable delivery.
- JAnalyzer does not replace a language server, compiler, test runner, or security analyzer.
- JRun does not imply sandboxing of launched commands.
- A JFiles chooser portal does not make JFiles a general filesystem permissions broker.
- A saved monitor profile does not guarantee hardware-specific modes exist on every machine.
- UI state and process state can diverge if an external command fails or a child exits unexpectedly; inspect the component’s refresh/lifecycle behavior.

These are architectural boundaries inferred from the implemented responsibilities and protocols. Future development could add richer orchestration, acknowledgements, lifecycle supervision, or package-wide automation, but those are not current features.
