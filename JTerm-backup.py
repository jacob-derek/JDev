#!/usr/bin/env python3
"""
JTerminal - janela de terminal (TTY) simples para o JShell.

Roda o JShell dentro de um pseudo-terminal real, então o JShell, o JCode e o
JFiles (que o JShell abre via subprocess) funcionam normalmente, inclusive
programas de tela cheia, cores, setas, cursor, redimensionamento etc.

Dependências:
    pip install pyte prompt_toolkit
    pip install pywinpty        # somente no Windows

Uso:
    python JTerminal.py                  -> abre o JShell.py (mesma pasta)
    python JTerminal.py outro_comando    -> abre outro comando no terminal
"""
import codecs
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import font

import pyte

IS_WINDOWS = os.name == "nt"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Tema Tokyo Night ─────────────────────────────────────────────────────────
DEFAULT_FG = "#a9b1d6"
DEFAULT_BG = "#1a1b26"
SELECT_BG = "#33467c"
PAD = 8

COLOR_NAMES = {
    "black": "#15161e", "red": "#f7768e", "green": "#9ece6a", "brown": "#e0af68",
    "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#a9b1d6",
    "brightblack": "#565f89", "brightred": "#f7768e", "brightgreen": "#9ece6a",
    "brightbrown": "#e0af68", "brightyellow": "#e0af68", "brightblue": "#7aa2f7",
    "brightmagenta": "#bb9af7", "brightcyan": "#7dcfff", "brightwhite": "#c0caf5",
}

FONT_CANDIDATES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono",
                   "Menlo", "Liberation Mono", "Courier New"]

# ── Teclas especiais -> sequências de terminal ───────────────────────────────
ARROWS = {"Up": "A", "Down": "B", "Right": "C", "Left": "D"}
KEYMAP = {
    "Return": "\r", "KP_Enter": "\r", "BackSpace": "\x7f", "Tab": "\t",
    "Escape": "\x1b", "ISO_Left_Tab": "\x1b[Z",
    "Insert": "\x1b[2~", "Delete": "\x1b[3~", "Prior": "\x1b[5~", "Next": "\x1b[6~",
    "F1": "\x1bOP", "F2": "\x1bOQ", "F3": "\x1bOR", "F4": "\x1bOS",
    "F5": "\x1b[15~", "F6": "\x1b[17~", "F7": "\x1b[18~", "F8": "\x1b[19~",
    "F9": "\x1b[20~", "F10": "\x1b[21~", "F11": "\x1b[23~", "F12": "\x1b[24~",
}
HOME_END = {"Home": "H", "End": "F"}

ALT_SCREEN_RE = re.compile(r"\x1b\[\?(?:1049|1047|47)([hl])")


# ── Backends de PTY ──────────────────────────────────────────────────────────
class UnixPty:
    def __init__(self, argv, rows, cols, env, cwd):
        import fcntl, pty, struct, subprocess, termios
        self._fcntl, self._termios, self._struct = fcntl, termios, struct
        self.master, slave = pty.openpty()
        self.set_size(rows, cols)

        def preexec():
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)  # vira o terminal controlador

        self.proc = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave,
            env=env, cwd=cwd, start_new_session=True, preexec_fn=preexec,
        )
        os.close(slave)
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read(self):
        try:
            data = os.read(self.master, 65536)
        except OSError:
            return None
        if not data:
            return None
        return self.decoder.decode(data)

    def write(self, text):
        try:
            os.write(self.master, text.encode("utf-8"))
        except OSError:
            pass

    def set_size(self, rows, cols):
        winsz = self._struct.pack("HHHH", rows, cols, 0, 0)
        self._fcntl.ioctl(self.master, self._termios.TIOCSWINSZ, winsz)

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.close(self.master)
        except OSError:
            pass


class WinPty:
    def __init__(self, argv, rows, cols, env, cwd):
        from winpty import PtyProcess
        self.proc = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))

    def read(self):
        while True:
            try:
                data = self.proc.read(65536)
            except EOFError:
                return None
            except Exception:
                return None
            if data:
                return data
            if not self.proc.isalive():
                return None

    def write(self, text):
        try:
            self.proc.write(text)
        except Exception:
            pass

    def set_size(self, rows, cols):
        try:
            self.proc.setwinsize(rows, cols)
        except Exception:
            pass

    def close(self):
        try:
            self.proc.terminate(force=True)
        except Exception:
            pass


# ── Tela do terminal (responde consultas como "posição do cursor") ───────────
class TermScreen(pyte.Screen):
    def __init__(self, cols, rows, on_reply):
        super().__init__(cols, rows)
        self.on_reply = on_reply

    def write_process_input(self, data):
        self.on_reply(data)


# ── Janela ───────────────────────────────────────────────────────────────────
class JTerminal:
    def __init__(self, root, argv):
        self.root = root
        root.title("JShell")
        root.geometry("900x580")
        root.configure(bg=DEFAULT_BG)

        families = set(font.families())
        family = next((f for f in FONT_CANDIDATES if f in families), "TkFixedFont")
        self.font = font.Font(family=family, size=12)
        self.font_bold = self.font.copy()
        self.font_bold.configure(weight="bold")
        self.font_italic = self.font.copy()
        self.font_italic.configure(slant="italic")
        self.font_bold_italic = self.font_bold.copy()
        self.font_bold_italic.configure(slant="italic")
        self.cw = self.font.measure("0")
        self.lh = self.font.metrics("linespace")

        self.text = tk.Text(
            root, bg=DEFAULT_BG, fg=DEFAULT_FG, font=self.font, wrap="none",
            bd=0, highlightthickness=0, padx=PAD, pady=PAD, insertwidth=0,
            selectbackground=SELECT_BG, selectforeground=DEFAULT_FG,
            spacing1=0, spacing2=0, spacing3=0, cursor="xterm",
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.focus_set()

        self.tags = {}
        self.alt_saved = None
        self.last_cursor = (0, 0)
        self.exited = False
        self.queue = queue.Queue()

        root.update()
        rows, cols = self.calc_size()
        self.rows, self.cols = rows, cols

        self.screen = TermScreen(cols, rows, self.send)
        self.stream = pyte.Stream(self.screen)
        self.reset_text_lines()

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        Backend = WinPty if IS_WINDOWS else UnixPty
        self.pty = Backend(argv, rows, cols, env, os.getcwd())

        threading.Thread(target=self.reader, daemon=True).start()

        self.text.bind("<Key>", self.on_key)
        self.text.bind("<Button-1>", lambda e: self.text.focus_set())
        self.text.bind("<Button-3>", self.paste)
        self.text.bind("<Configure>", self.on_configure)
        self.resize_job = None
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.root.after(15, self.pump)

    # ── tamanho ──
    def calc_size(self):
        w = self.text.winfo_width() - 2 * PAD
        h = self.text.winfo_height() - 2 * PAD
        return max(5, h // self.lh), max(20, w // self.cw)

    def reset_text_lines(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n" * (self.rows - 1))
        self.screen.dirty.update(range(self.rows))

    def on_configure(self, _event):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(60, self.apply_resize)

    def apply_resize(self):
        self.resize_job = None
        rows, cols = self.calc_size()
        if (rows, cols) == (self.rows, self.cols):
            return
        self.rows, self.cols = rows, cols
        self.screen.resize(rows, cols)
        self.pty.set_size(rows, cols)
        self.reset_text_lines()
        self.render()

    # ── leitura do processo ──
    def reader(self):
        while True:
            data = self.pty.read()
            if data is None:
                self.queue.put(None)
                return
            self.queue.put(data)

    def send(self, text):
        self.pty.write(text)

    def pump(self):
        changed = False
        try:
            for _ in range(200):
                item = self.queue.get_nowait()
                if item is None:
                    self.close()
                    return
                self.feed(item)
                changed = True
        except queue.Empty:
            pass
        if changed:
            self.render()
        self.root.after(15, self.pump)

    # ── emulação ──
    def feed(self, data):
        pos = 0
        for m in ALT_SCREEN_RE.finditer(data):
            self.stream.feed(data[pos:m.start()])
            self.set_alt_screen(m.group(1) == "h")
            pos = m.end()
        self.stream.feed(data[pos:])

    def set_alt_screen(self, enable):
        """Simula o buffer alternativo (usado por apps de tela cheia)."""
        s = self.screen
        if enable and self.alt_saved is None:
            rows = [[s.buffer[y][x] for x in range(s.columns)] for y in range(s.lines)]
            self.alt_saved = (rows, s.cursor.x, s.cursor.y)
            s.erase_in_display(2)
            s.cursor_position()
        elif not enable and self.alt_saved is not None:
            rows, cx, cy = self.alt_saved
            self.alt_saved = None
            s.erase_in_display(2)
            for y, row in enumerate(rows):
                if y >= s.lines:
                    break
                for x, ch in enumerate(row):
                    if x >= s.columns:
                        break
                    s.buffer[y][x] = ch
            s.cursor.x = min(cx, s.columns - 1)
            s.cursor.y = min(cy, s.lines - 1)
            s.dirty.update(range(s.lines))

    # ── renderização ──
    @staticmethod
    def resolve(color, default):
        if color == "default":
            return default
        if color in COLOR_NAMES:
            return COLOR_NAMES[color]
        if re.fullmatch(r"[0-9a-fA-F]{6}", color):
            return "#" + color
        return default

    def style_key(self, ch, is_cursor):
        fg = self.resolve(ch.fg, DEFAULT_FG)
        bg = self.resolve(ch.bg, DEFAULT_BG)
        if ch.reverse != is_cursor:  # XOR: reverse do app e/ou cursor
            fg, bg = bg, fg
        return (fg, bg, bool(ch.bold), bool(ch.italics),
                bool(ch.underscore), bool(ch.strikethrough))

    def tag_for(self, key):
        name = self.tags.get(key)
        if name:
            return name
        fg, bg, bold, italic, under, strike = key
        name = f"s{len(self.tags)}"
        f = {(False, False): self.font, (True, False): self.font_bold,
             (False, True): self.font_italic, (True, True): self.font_bold_italic}[(bold, italic)]
        self.text.tag_configure(name, foreground=fg, background=bg, font=f,
                                underline=under, overstrike=strike)
        self.tags[key] = name
        return name

    def draw_line(self, y):
        s = self.screen
        line = s.buffer[y]
        cursor = s.cursor
        cx = cursor.x if (not cursor.hidden and cursor.y == y) else -1
        runs = []
        for x in range(s.columns):
            ch = line[x]
            if ch.data == "":  # segunda metade de caractere largo
                continue
            key = self.style_key(ch, x == cx)
            if runs and runs[-1][0] == key:
                runs[-1][1] += ch.data
            else:
                runs.append([key, ch.data])
        default_key = (DEFAULT_FG, DEFAULT_BG, False, False, False, False)
        if runs and runs[-1][0] == default_key:
            runs[-1][1] = runs[-1][1].rstrip(" ")
        start, end = f"{y + 1}.0", f"{y + 1}.end"
        self.text.delete(start, end)
        for key, chunk in runs:
            if chunk:
                self.text.insert(f"{y + 1}.end", chunk, self.tag_for(key))

    def render(self):
        s = self.screen
        dirty = set(s.dirty)
        s.dirty.clear()
        dirty.add(self.last_cursor[1])
        dirty.add(s.cursor.y)
        self.last_cursor = (s.cursor.x, s.cursor.y)
        for y in sorted(dirty):
            if 0 <= y < s.lines:
                self.draw_line(y)
        self.text.yview_moveto(0)

    # ── teclado ──
    def on_key(self, e):
        ctrl = bool(e.state & 0x4)
        shift = bool(e.state & 0x1)
        ks = e.keysym

        if ctrl and shift and ks in ("C", "c"):
            self.copy()
            return "break"
        if ctrl and shift and ks in ("V", "v"):
            self.paste()
            return "break"

        app_cursor = pyte.modes.DECAWM in self.screen.mode
        seq = None
        if ks in ARROWS:
            if ctrl:
                seq = f"\x1b[1;5{ARROWS[ks]}"
            else:
                seq = ("\x1bO" if app_cursor else "\x1b[") + ARROWS[ks]
        elif ks in HOME_END:
            seq = ("\x1bO" if app_cursor else "\x1b[") + HOME_END[ks]
        elif ks in KEYMAP:
            seq = KEYMAP[ks]
        elif e.char:
            seq = e.char
            alt = (e.state & 0x20000) if IS_WINDOWS else (e.state & 0x8)
            if alt and not ctrl:
                seq = "\x1b" + seq

        if seq:
            self.send(seq)
        return "break"

    def copy(self):
        try:
            sel = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(sel)

    def paste(self, _event=None):
        try:
            data = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        self.send(data.replace("\r\n", "\r").replace("\n", "\r"))
        return "break"

    # ── encerramento ──
    def close(self):
        if self.exited:
            return
        self.exited = True
        self.pty.close()
        self.root.destroy()


def main():
    if len(sys.argv) > 1:
        argv = sys.argv[1:]
    else:
        argv = [sys.executable, os.path.join(BASE_DIR, "JShell.py")]

    root = tk.Tk()
    JTerminal(root, argv)
    root.mainloop()


if __name__ == "__main__":
    main()
