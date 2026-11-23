# JDev Engineering Study Reader

A local, static reading interface for the Markdown study. The original files in `engineering-study/` remain the source of truth; this reader loads them directly at runtime.

## Run locally

From the repository root:

```sh
python3 engineering-study/reader/serve.py
```

Open <http://127.0.0.1:8765/engineering-study/reader/> on this computer. By default the server listens on all interfaces, so a tablet on the same local network can open `http://<computer-LAN-IP>:8765/engineering-study/reader/`. Find the computer's IPv4 address with `ip -brief -4 address`. Use `--port 9000` to choose another port or `--host 127.0.0.1` to restrict access to this computer. Stop the server with Ctrl+C.

If launching from another working directory, pass the full path to `engineering-study/reader/serve.py`.

The server uses Python’s standard-library HTTP server; there is no application backend, database, build step, or package installation. For tablet access, the host firewall must permit the selected TCP port. The handler serves study files and repository files explicitly linked as source citations; directory listings and unrelated repository paths are not served.

## Reader features

- Chapter order and section grouping follow `engineering-study/INDEX.md`; `chapters.json` is the navigation manifest.
- Source Markdown is fetched when a chapter is opened. Markdown chapter links route inside the reader; source-code citations open the corresponding repository file.
- Search fetches and indexes the existing study chapters in the browser.
- Theme, sidebar state, reading position, and completed chapters are stored in local browser storage.
- Mermaid code blocks are shown as diagrams when the Mermaid CDN is reachable; if not, their original source remains readable in a code panel.

Use the light/dark control in the top bar and the contents button to collapse or reopen the chapter sidebar. The layout adapts from a persistent landscape sidebar to an overlay sidebar on narrower portrait screens.

## Offline notes

The reader and Markdown renderer are local. Ordinary chapters, navigation, search, reading progress, and preferences work without a network connection once the static server is available. Diagram rendering uses Mermaid from jsDelivr on demand; without that network access, the diagram source is displayed instead. Browser storage is local to the browser/profile and is not synchronized across devices.
