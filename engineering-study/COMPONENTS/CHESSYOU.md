# ChessYou! — PGN review with Stockfish analysis

ChessYou! is a separate Python package for reviewing a PGN game in a terminal UI. It uses Textual for the interface, python-chess for PGN/board/rules/engine protocol, and an external Stockfish executable for evaluation. It is not part of JDesk’s shell or window-management process tree; its `jtheme` integration is only optional color reuse ([chessyou/README.md](../../chessyou/README.md), [chessyou/pyproject.toml](../../chessyou/pyproject.toml)).

## Package layers and startup

`python -m chessyou` enters `__main__.py`, which calls `app.main()`. The CLI selects a PGN file/game or built-in demo, resolves Stockfish from `--stockfish`, `STOCKFISH`, or PATH, and opens the Textual app ([chessyou/chessyou/__main__.py](../../chessyou/chessyou/__main__.py), [chessyou/chessyou/app.py:225-273](../../chessyou/chessyou/app.py#L225)). The package separates:

- `analise.py`: pure evaluation-to-mistake classification.
- `formato.py`: move list, evaluation text, and advantage bar.
- `tabuleiro.py`: board geometry and color fragments.
- `cores.py`: optional role mapping from JDev’s jtheme.
- `motor.py`: Stockfish discovery and python-chess UCI bridge.
- `app.py`: PGN loading, Textual screen, navigation, background analysis.

## Board and navigation state

The app constructs a list of immutable-ish `chess.Board.copy()` snapshots, one before play and one after each mainline move, alongside SAN strings and move objects ([chessyou/chessyou/app.py:43-71](../../chessyou/chessyou/app.py#L43)). The current `ply` indexes this positions array and determines the highlighted last move, evaluation, move list, and critical-move panel. Left/right and Home/End navigate; `f` flips board; `n`/`p` jump critical moves; `q` exits. The board renderer emits 12 rows with coordinate borders and uses letters for pieces; `tabuleiro.grade()` receives square-indexed pieces and handles rotation/highlighting ([chessyou/chessyou/tabuleiro.py:1-42](../../chessyou/chessyou/tabuleiro.py#L1)).

## Evaluation and classification model

Stockfish returns centipawn scores from White’s perspective. `motor.analisar_posicoes()` starts one UCI engine process for the analysis session, evaluates each stored position sequentially to configured depth (default 14), handles mate/terminal positions, and records best move SAN ([chessyou/chessyou/motor.py:1-31](../../chessyou/chessyou/motor.py#L1)). Textual work runs this in a worker thread and uses `call_from_thread` for progress/results, keeping rendering responsive ([chessyou/chessyou/app.py:171-224](../../chessyou/chessyou/app.py#L171)).

`analise.chance_vitoria()` maps centipawns through a logistic curve into an estimated White win chance, clamped at ±10,000 cp. For each ply, `perda()` measures how much the side to move reduced its own win chance; favorable evaluations for the opponent do not produce negative “loss.” Thresholds are 10 percentage points for imprecision, 20 for error, and 30 for blunder ([chessyou/chessyou/analise.py:1-42](../../chessyou/chessyou/analise.py#L1)). This is a heuristic pedagogical classification; it depends on engine depth and the chosen win-probability curve and is not a formal probability guarantee.

The advantage bar places Black’s side at top and White’s at bottom, with fractional cells; evaluations use signed pawns and mate labels. The move list scrolls a window of eight full move pairs around the current ply ([chessyou/chessyou/formato.py:1-49](../../chessyou/chessyou/formato.py#L1)).

## Practical operation and dependencies

Use `python -m chessyou --demo` to explore without a PGN; open a file with `python -m chessyou game.pgn`, use `--partida N` for multi-game PGNs, and set `--stockfish /path/to/engine` or `STOCKFISH` if the executable is not on PATH. Press `a` once to analyze all stored positions; navigate the board afterward and use `n`/`p` to inspect classified critical moments. The README documents expected Void package setup and the same shortcuts ([chessyou/README.md](../../chessyou/README.md)).

Unit tests cover pure classification, color contrast, board geometry, move-list formatting, and advantage bars. The README explicitly says the Textual screen is not tested. Tests were not run during this study.

## Extension guidance and limitations

Keep score conversion and classification in `analise.py`, independent of the engine/UI. Keep board-coordinate mapping in `tabuleiro.py`; keep the engine process/context in `motor.py`; add UI actions through Textual bindings and worker-safe callbacks. Whole-game position-by-position analysis can take time proportional to game length × depth and has no caching of repeated positions in current code. The app stores all board snapshots in memory. It analyzes the mainline only; PGN variations are not part of the displayed move sequence. Theme lookup searches `$JDEV_DIR` then `~/JDev`, so relocated projects should set the environment variable.
