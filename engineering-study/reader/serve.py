#!/usr/bin/env python3
"""Serve the JDev engineering study reader from the repository root."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = REPOSITORY_ROOT / "engineering-study"
DENIED_SEGMENTS = {".git", ".aws", ".codex", ".agents"}


def cited_source_files() -> set[str]:
    """Allow repository files linked from the study, plus study content."""
    allowed = set()
    link_pattern = re.compile(r"\]\(([^)]+)\)")
    for markdown in STUDY_ROOT.rglob("*.md"):
        source = markdown.read_text(encoding="utf-8", errors="replace")
        for match in link_pattern.finditer(source):
            target = match.group(1).strip().split()[0].strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:", "javascript:")):
                continue
            target_path = urlsplit(target).path
            if not target_path:
                continue
            resolved = (markdown.parent / unquote(target_path)).resolve()
            if resolved.is_relative_to(REPOSITORY_ROOT) and resolved.is_file():
                allowed.add(resolved.relative_to(REPOSITORY_ROOT).as_posix())
    return allowed


class StudyHandler(SimpleHTTPRequestHandler):
    """Serve study files and source citations without exposing the whole checkout."""

    repository_root = REPOSITORY_ROOT
    allowed_sources = cited_source_files()

    def _redirect_to_reader(self) -> bool:
        """Send requests for the server root to the reader's canonical URL."""
        path = urlsplit(self.path).path.rstrip("/")
        if path not in {"", "/engineering-study"}:
            return False
        self.send_response(302)
        self.send_header("Location", "/engineering-study/reader/")
        self.end_headers()
        return True

    def do_GET(self):
        if self._redirect_to_reader():
            return
        super().do_GET()

    def do_HEAD(self):
        if self._redirect_to_reader():
            return
        super().do_HEAD()

    def send_head(self):
        parsed = urlsplit(self.path)
        requested = unquote(parsed.path).lstrip("/")
        candidate = (self.repository_root / requested).resolve()
        if not candidate.is_relative_to(self.repository_root):
            self.send_error(404, "Not found")
            return None
        if any(part in DENIED_SEGMENTS for part in Path(requested).parts):
            self.send_error(404, "Not found")
            return None
        if candidate.is_dir():
            index = candidate / "index.html"
            if not index.is_file():
                self.send_error(404, "Not found")
                return None
            requested = f"{requested.rstrip('/')}/index.html"
            self.path = f"/{requested}" + (f"?{parsed.query}" if parsed.query else "")
            candidate = index.resolve()
        relative = candidate.relative_to(self.repository_root).as_posix()
        in_study = relative == "engineering-study" or relative.startswith("engineering-study/")
        if not candidate.is_file() or not (in_study or relative in self.allowed_sources):
            self.send_error(404, "Not found")
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404, "Directory listing disabled")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the static JDev study reader locally")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    parser.add_argument("--host", default="0.0.0.0", help="interface to listen on (default: all interfaces)")
    args = parser.parse_args()
    handler = partial(StudyHandler, directory=str(REPOSITORY_ROOT))
    address = (args.host, args.port)
    with ThreadingHTTPServer(address, handler) as server:
        print(f"This computer: http://127.0.0.1:{args.port}/engineering-study/reader/")
        if args.host == "0.0.0.0":
            print(f"On your tablet, open http://<this-computer-LAN-IP>:{args.port}/engineering-study/reader/")
            print("Find the LAN IP with: ip -brief -4 address")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
