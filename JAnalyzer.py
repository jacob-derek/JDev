#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.formatted_text import ANSI

from pygments import highlight
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.formatters import Terminal256Formatter


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(
    os.environ.get("JDEV_PATH", Path.home() / "JDev")
).expanduser().resolve()

EXCLUDED = {
    ".git", "__pycache__", ".venv", "venv",
    ".ruff_cache", ".pytest_cache", "node_modules",
    "dist", "build"
}

COMMANDS = [
    "help", "scan", "stats", "files",
    "recent", "compare", "history",
    "show", "search", "refresh", "exit"
]

style = Style.from_dict({
    "prompt": "bold #d7af87",
    "": "#d4d4d4",
})

session = PromptSession(
    style=style,
    completer=WordCompleter(COMMANDS, ignore_case=True)
)


# ============================================================
# GIT
# ============================================================

def git(*args):
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            return None

        return result.stdout

    except (OSError, subprocess.TimeoutExpired):
        return None


def git_available():
    return git("rev-parse", "--is-inside-work-tree") is not None


def git_content(path):
    relative = path.relative_to(ROOT).as_posix()

    return git("show", f"HEAD:{relative}")


# ============================================================
# FILE SCANNER
# ============================================================

def scan_files():
    result = []

    for directory, dirs, filenames in os.walk(ROOT):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED
        ]

        for filename in filenames:
            path = Path(directory) / filename

            try:
                if not path.is_file():
                    continue

                content = path.read_bytes()

                if b"\0" in content[:4096]:
                    continue

                text = content.decode("utf-8", errors="replace")
                lines = text.splitlines()

                result.append({
                    "path": path,
                    "relative": path.relative_to(ROOT),
                    "size": len(content),
                    "lines": len(lines),
                    "empty": sum(
                        not line.strip() for line in lines
                    ),
                    "nonempty": sum(
                        bool(line.strip()) for line in lines
                    ),
                })

            except (OSError, PermissionError):
                continue

    return sorted(
        result,
        key=lambda x: str(x["relative"]).lower()
    )


# ============================================================
# DISPLAY HELPERS
# ============================================================

def title(text):
    print()
    print_formatted_text(
        HTML(f"<b><style fg='#d7af87'>{text}</style></b>")
    )
    print("─" * 65)


def size_format(size):
    units = ["B", "KB", "MB", "GB"]

    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size:.2f} TB"


def signed(value):
    return f"+{value}" if value > 0 else str(value)


def get_file(path):
    return next(
        (f for f in files if f["relative"] == path),
        None
    )


# ============================================================
# STATISTICS
# ============================================================

def show_stats():
    total_files = len(files)
    total_lines = sum(f["lines"] for f in files)
    total_empty = sum(f["empty"] for f in files)
    total_size = sum(f["size"] for f in files)

    title("PROJECT STATISTICS")

    print(f"Root:          {ROOT}")
    print(f"Files:         {total_files}")
    print(f"Total lines:   {total_lines:,}")
    print(f"Code/content:  {total_lines - total_empty:,}")
    print(f"Empty lines:   {total_empty:,}")
    print(f"Disk usage:    {size_format(total_size)}")

    print("\nLargest files:")

    for f in sorted(
        files,
        key=lambda x: x["size"],
        reverse=True
    )[:10]:
        print(
            f"  {str(f['relative']):45}"
            f"{size_format(f['size']):>12}"
            f"{f['lines']:>9} lines"
        )

    print("\nExtensions:")

    extensions = {}

    for f in files:
        ext = f["path"].suffix or "[no extension]"

        if ext not in extensions:
            extensions[ext] = {
                "files": 0,
                "lines": 0,
                "size": 0
            }

        extensions[ext]["files"] += 1
        extensions[ext]["lines"] += f["lines"]
        extensions[ext]["size"] += f["size"]

    for ext, data in sorted(
        extensions.items(),
        key=lambda x: x[1]["lines"],
        reverse=True
    ):
        print(
            f"  {ext:15} "
            f"{data['files']:4} files | "
            f"{data['lines']:8,} lines | "
            f"{size_format(data['size'])}"
        )


# ============================================================
# FILE LIST
# ============================================================

def show_files(query=""):
    title("PROJECT FILES")

    for f in files:
        relative = str(f["relative"])

        if query.lower() not in relative.lower():
            continue

        print(
            f"{relative:48} "
            f"{f['lines']:7} lines  "
            f"{size_format(f['size']):>10}"
        )


# ============================================================
# RECENT CHANGES
# ============================================================

def show_recent():
    title("RECENT GIT CHANGES")

    if not git_available():
        print("Git repository not available.")
        return

    output = git(
        "status", "--short", "--untracked-files=all"
    )

    print("Working tree:\n")

    if output and output.strip():
        print(output)
    else:
        print("No uncommitted changes.")

    print("\nLast 30 days:\n")

    log = git(
        "log",
        "--since=30 days ago",
        "--date=short",
        "--pretty=format:%h | %ad | %s",
        "--name-status",
        "-20"
    )

    print(log or "No recent commits.")


# ============================================================
# SIZE COMPARISON
# ============================================================

def compare_files():
    title("WORKING TREE vs HEAD")

    if not git_available():
        print("Git repository not available.")
        return

    changes = git(
        "diff",
        "--numstat",
        "HEAD",
        "--",
    )

    if changes is None:
        print("Unable to compare against HEAD.")
        return

    print("Modified tracked files:\n")

    if not changes.strip():
        print("No tracked differences.")
    else:
        for line in changes.splitlines():
            parts = line.split("\t", 2)

            if len(parts) != 3:
                continue

            added, removed, filename = parts

            print(
                f"{filename}\n"
                f"  Added: {added} | Removed: {removed}"
            )

    print("\nFile size comparison:\n")

    for f in files:
        old = git_content(f["relative"])

        if old is None:
            continue

        old_size = len(old.encode("utf-8"))
        old_lines = len(old.splitlines())

        size_diff = f["size"] - old_size
        line_diff = f["lines"] - old_lines

        if size_diff or line_diff:
            print(
                f"{f['relative']}\n"
                f"  Size:  {size_format(old_size)}"
                f" -> {size_format(f['size'])}"
                f" ({signed(size_diff)} B)\n"
                f"  Lines: {old_lines} -> {f['lines']}"
                f" ({signed(line_diff)})\n"
            )


# ============================================================
# HISTORY
# ============================================================

def show_history():
    title("GIT HISTORY")

    if not git_available():
        print("Git repository not available.")
        return

    output = git(
        "log",
        "-15",
        "--stat",
        "--date=short",
        "--pretty=format:%n%h | %ad | %an%n%s"
    )

    print(output or "No commits found.")


# ============================================================
# SOURCE VIEWER
# ============================================================

def show_source(query):
    title("SOURCE VIEWER")

    matches = [
        f for f in files
        if query.lower() in str(f["relative"]).lower()
    ]

    if not matches:
        print("File not found.")
        return

    for index, f in enumerate(matches):
        print(f"[{index}] {f['relative']}")

    try:
        choice = input("\nFile index: ").strip()
        selected = matches[int(choice)]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    try:
        source = selected["path"].read_text(
            encoding="utf-8",
            errors="replace"
        )

        try:
            lexer = get_lexer_for_filename(
                selected["path"].name
            )
        except Exception:
            lexer = TextLexer()

        colored = highlight(
            source,
            lexer,
            Terminal256Formatter()
        )

        print_formatted_text(ANSI(colored))

    except OSError as error:
        print(f"Error: {error}")


# ============================================================
# INTERACTIVE INTERFACE
# ============================================================

def banner():
    print_formatted_text(HTML(
        "<b><style fg='#d7af87'>"
        "       JDEV ANALYZER"
        "</style></b>"
    ))

    print("Project inspection and analysis tool")
    print(f"Repository: {ROOT}")
    print(f"Files indexed: {len(files)}")
    print("Type 'help' for commands.\n")


def help_menu():
    title("AVAILABLE COMMANDS")

    commands = {
        "scan": "Rebuild project index",
        "stats": "Project statistics",
        "files": "List all indexed files",
        "search": "Search files by name",
        "recent": "Recent Git changes",
        "compare": "Compare current files against HEAD",
        "history": "Display commit history",
        "show": "Open source file with syntax highlighting",
        "refresh": "Refresh project index",
        "exit": "Close analyzer",
    }

    for command, description in commands.items():
        print(f"  {command:12} {description}")


def main():
    global files

    if not ROOT.is_dir():
        print(f"Project directory not found: {ROOT}")
        return

    files = scan_files()

    banner()

    while True:
        try:
            command = session.prompt(
                HTML("<ansiyellow>JDEV</ansiyellow> <b>></b> ")
            ).strip()

            if not command:
                continue

            parts = command.split(maxsplit=1)
            action = parts[0].lower()
            argument = parts[1] if len(parts) > 1 else ""

            if action in ("exit", "quit"):
                break

            elif action == "help":
                help_menu()

            elif action in ("scan", "refresh"):
                files = scan_files()
                print(f"Indexed {len(files)} files.")

            elif action == "stats":
                show_stats()

            elif action == "files":
                show_files(argument)

            elif action == "search":
                if argument:
                    show_files(argument)
                else:
                    print("Usage: search <filename>")

            elif action == "recent":
                show_recent()

            elif action == "compare":
                compare_files()

            elif action == "history":
                show_history()

            elif action == "show":
                if argument:
                    show_source(argument)
                else:
                    print("Usage: show <filename>")

            else:
                print("Unknown command. Type 'help'.")

        except KeyboardInterrupt:
            print("\nUse 'exit' to quit.")

        except EOFError:
            break

    print("\nJAnalyzer closed.")


if __name__ == "__main__":
    main()
