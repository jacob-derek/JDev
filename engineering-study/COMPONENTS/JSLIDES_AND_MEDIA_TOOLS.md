# JSlides and media/visual utilities

This chapter covers tools that attach to the JDev desktop but are not core session processes: JSlides, JPlayer, JCava, JGrab, JWrite, and the icon converter. Their integration strength varies: JSlides is a JDesk viewer extension; JPlayer/JCava are standalone terminal programs; JGrab is a network/download utility; JWrite and the converter are small standalone utilities.

## JSlides — PDF and presentation viewer

JSlides exposes `SlidesPane`, a Tk frame that JDesk can host as a viewer (`es_viewer=True`). JDesk selects it dynamically for PDF/office extensions; the pane’s key-filter callback lets the host reserve global shortcuts. It can open PDFs through PyMuPDF, convert office files to PDF via LibreOffice, or show extracted text from `.pptx` when the rendering stack is unavailable ([tools/JSlides.py:1-58](../../tools/JSlides.py#L1), [tools/JSlides.py:133-180](../../tools/JSlides.py#L133), [tools/JSlides.py:572-593](../../tools/JSlides.py#L572)).

The PDF render path keeps a small Tk image cache keyed by page and canvas size. Presentation conversion runs in a daemon worker; a generation counter invalidates stale completion callbacks after another file opens or the pane closes ([tools/JSlides.py:161-255](../../tools/JSlides.py#L161), [tools/JSlides.py:256-355](../../tools/JSlides.py#L256)). Cached office-to-PDF conversions use source signature and a bounded cache (40 items) under XDG cache ([tools/JSlides.py:49-115](../../tools/JSlides.py#L49)). `python-pptx` extracts slide title/body/table text/notes for fallback and note display ([tools/JSlides.py:117-159](../../tools/JSlides.py#L117)).

Keyboard: arrows/PageUp/PageDown/space/hjkl move slides; Home/End jump ends; `g` enters a slide number; `o` opens thumbnail grid; `n` toggles notes; `f` toggles clean/fullscreen presentation; `r` reloads; `q`/Escape closes. The grid supports directional selection and Enter/Space to open. Scrolling also changes slide. In text-only fallback, thumbnail grid is unavailable ([tools/JSlides.py:296-410](../../tools/JSlides.py#L296), [tools/JSlides.py:465-568](../../tools/JSlides.py#L465)).

## JPlayer — terminal audio player

JPlayer is a standalone terminal UI for audio files. The source includes recursive library scanning, natural sort, cover extraction from ID3/FLAC/MP4 tags and folder artwork, ANSI half-block image rendering, and an audio backend abstraction implemented with pygame ([tools/JPlayer.py:34-310](../../tools/JPlayer.py#L34), [tools/JPlayer.py:311-397](../../tools/JPlayer.py#L311)). `App` owns playback/library/selection state and raw-key navigation; `main()` parses launch arguments and enters the terminal UI ([tools/JPlayer.py:398-752](../../tools/JPlayer.py#L398)).

Practical capabilities include directory/library navigation, track selection, playback controls, cover display, and metadata extraction. It depends on optional pygame and Pillow for audio/art rendering; without them it cannot provide the complete experience. JBar’s `playerctl` controls are separate: JPlayer’s integration with JBar depends on exposing an MPRIS player through its backend, which must be verified in the relevant backend implementation before promising that the bar can control it.

## JCava — theme-aware CAVA configuration generator

JCava generates a CAVA config from a selected style/theme. It parses theme colors, creates gradients, chooses an audio source, writes a JDev config under `~/.config/jdev/cava.conf`, and preserves/backs up an existing CAVA configuration according to its write policy ([tools/JCava.py:30-170](../../tools/JCava.py#L30)). The actual visualization is CAVA; JCava configures it rather than implementing audio analysis. Review generated source path/theme and CAVA installation when debugging missing bars.

## JGrab — album acquisition planner/downloader

JGrab reads an `Artist | Album | optional playlist URL` list. It queries MusicBrainz for canonical release track order and Cover Art Archive for artwork; uses yt-dlp to find/download candidates; estimates matches from normalized title similarity, duration, channel, and noisy-title penalties; then uses ffmpeg to tag output audio with metadata and attached cover art ([tools/JGrab.py:92-175](../../tools/JGrab.py#L92), [tools/JGrab.py:198-328](../../tools/JGrab.py#L198)). `plan_album()` can produce a report without downloads via `--scan`; without an explicit playlist, it attempts to identify a YouTube playlist or searches for each track. The downloader writes organized output under `--out`, defaults to `~/Musicas`, and emits `jgrab-relatorio.txt` beside the list ([tools/JGrab.py:329-462](../../tools/JGrab.py#L329), [tools/JGrab.py:463-536](../../tools/JGrab.py#L463)).

This utility reaches external services and writes downloaded media; this study only inspected its source and did not invoke it. Its scoring is heuristic, and even a high match score cannot prove a recording is the intended official release; the report’s uncertain/missing flags need human review. It depends on yt-dlp, ffmpeg, network access, and potentially a JavaScript runtime for current YouTube extraction.

## JWrite and CONVERTERPARAICO

JWrite is a compact curses typing game: a built-in word corpus is presented, key input is measured/colored, and the game loop draws centered UI ([tools/JWrite.py:7-136](../../tools/JWrite.py#L7)). The icon converter uses Pillow to resize a source image to a fixed set of icon sizes and writes outputs ([tools/CONVERTERPARAICO.py:1-50](../../tools/CONVERTERPARAICO.py#L1)). These programs are independent of JDesk’s runtime. Their small size makes their entrypoint and central loop the best navigation points.

## Relationships and extension guidance

JSlides is the only tool in this group directly embedded into JDesk’s pane lifecycle. It signals viewer identity and callbacks rather than owning a separate persistent window. JCava shares theme roles with the rest of JDev but delegates rendering to CAVA. JPlayer and JGrab can complement each other: JGrab organizes/tag downloads into a library, and JPlayer scans/plays it. That workflow is based on implemented behavior, though JPlayer’s supported format set and JGrab’s default output format should be checked before assuming every downloaded format is playable.

Do not conflate JBar’s `playerctl` support with JPlayer unless the audio backend exports the player-control protocol; inspect that capability before extending the cross-component workflow. For JSlides work, preserve generation invalidation and keep document conversion off Tk’s event loop. For JGrab, preserve report/scan mode as a non-download planning path.
