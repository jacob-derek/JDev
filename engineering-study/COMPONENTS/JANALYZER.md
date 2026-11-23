# JAnalyzer — interactive repository browser and Git comparison tool

JAnalyzer is a standalone prompt_toolkit console for inspecting a checkout. It indexes textual files under `JDEV_PATH` or `~/JDev`, excluding common VCS/build/cache directories, then offers statistics, file search/listing, recent Git changes, working-tree comparisons, history, and syntax-highlighted source viewing ([JAnalyzer.py:26-50](../../JAnalyzer.py#L26)).

## Data model and execution

`scan_files()` walks the root once, skips excluded subdirectories, ignores non-files and files with NUL bytes near the beginning, decodes UTF-8 with replacement, and records path, relative path, byte size, line count, and empty/nonempty counts ([JAnalyzer.py:89-133](../../JAnalyzer.py#L89)). The indexed records are held in a module-level `files` list; operations reuse it until `scan`/`refresh` rebuilds it. Startup fails clearly if the configured root is absent ([JAnalyzer.py:464-473](../../JAnalyzer.py#L464)).

Git operations run subprocesses rooted at the configured project and have a 15-second timeout. Recent view combines working-tree status and up to 20 commits from the last 30 days; compare reports tracked diff line counts and then compares each indexed file’s current size/lines to `HEAD`; history shows recent commit stats ([JAnalyzer.py:57-87](../../JAnalyzer.py#L57), [JAnalyzer.py:257-373](../../JAnalyzer.py#L257)). The source viewer lists path matches, prompts for an index, selects a Pygments lexer by filename, and prints ANSI-highlighted content ([JAnalyzer.py:380-424](../../JAnalyzer.py#L380)).

## Practical use and limitations

Commands are `help`, `scan`/`refresh`, `stats`, `files [query]`, `search <name>`, `recent`, `compare`, `history`, `show <query>`, and `exit` ([JAnalyzer.py:444-520](../../JAnalyzer.py#L444)). It is useful for a lightweight structural view and Git-oriented inspection without opening JFiles or JCode.

Source-level limitations: full contents of each textual file are read into memory during every scan (then only summary metadata is retained); ignore rules are a fixed directory-name set rather than `.gitignore`; binary detection only samples the first 4096 bytes; current binary file handling is conservative but not a complete encoding detector; compare iterates current indexed files and does not comprehensively model renames/deletions/untracked files. Git commands report repository status but do not modify it. JAnalyzer is separate from the engineering study’s own docs and is not a dependency of the desktop. No commands or tests were run.
