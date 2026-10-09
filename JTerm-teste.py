#!/usr/bin/env python3
"""
JTerminal - janela de terminal (TTY) para o JShell.

Roda o JShell dentro de um pseudo-terminal real, então o JShell, o JCode e o
JFiles (que o JShell abre via subprocess) funcionam normalmente, inclusive
programas de tela cheia, cores, setas, cursor, redimensionamento etc.

Dependências:
    pip install pyte
    pip install pywinpty        # somente no Windows
    (prompt_toolkit é dependência do JShell, não deste arquivo)

Uso:
    python JTerm.py                  -> abre o JShell.py (mesma pasta)
    python JTerm.py outro_comando    -> abre outro comando no terminal

Atalhos:
    Ctrl+Shift+C / Ctrl+Insert   copiar (Ctrl+C copia se houver seleção)
    Ctrl+Shift+V / Shift+Insert  colar (botão direito: copia se houver seleção, senão cola)
    Shift+PageUp / Shift+PageDown, roda do mouse   histórico (scrollback)
    Ctrl + roda do mouse         zoom da fonte
"""
import codecs
import os
import queue
import re
import signal
import sys
import threading
import time
import tkinter as tk
from tkinter import font, messagebox

import pyte

IS_WINDOWS = os.name == "nt"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Ajustes ──────────────────────────────────────────────────────────────────
SCROLLBACK = 5000          # linhas de histórico
FEED_BUDGET = 0.012        # segundos máx. processando saída por ciclo (mantém a UI viva)
BUSY_MS, IDLE_MS = 3, 10   # intervalo do ciclo com/sem saída
MAX_TAGS = 1500            # limite de estilos distintos antes de limpar o cache
FONT_MIN, FONT_MAX = 7, 32
KEEP_OPEN_ON_ERROR = True  # se o processo sair com erro, mantém a janela para ler a mensagem

# ── Tema Tokyo Night ─────────────────────────────────────────────────────────
DEFAULT_FG = "#a9b1d6"
DEFAULT_BG = "#1a1b26"
SELECT_BG = "#33467c"
PAD = 8
DEFAULT_KEY = (DEFAULT_FG, DEFAULT_BG, False, False, False, False)

COLOR_NAMES = {
    "black": "#15161e", "red": "#f7768e", "green": "#9ece6a", "brown": "#e0af68",
    "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#a9b1d6",
    "brightblack": "#565f89", "brightred": "#f7768e", "brightgreen": "#9ece6a",
    "brightbrown": "#e0af68", "brightyellow": "#e0af68", "brightblue": "#7aa2f7",
    "brightmagenta": "#bb9af7", "brightcyan": "#7dcfff", "brightwhite": "#c0caf5",
}
HEX_RE = re.compile(r"[0-9a-fA-F]{6}")

FONT_CANDIDATES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono",
                   "Menlo", "Liberation Mono", "Courier New"]

# ── Teclas especiais -> sequências de terminal ───────────────────────────────
ARROWS = {"Up": "A", "Down": "B", "Right": "C", "Left": "D"}
HOME_END = {"Home": "H", "End": "F"}
KEYMAP = {
    "Return": "\r", "KP_Enter": "\r", "BackSpace": "\x7f", "Tab": "\t",
    "Escape": "\x1b", "ISO_Left_Tab": "\x1b[Z",
    "Insert": "\x1b[2~", "Delete": "\x1b[3~", "Prior": "\x1b[5~", "Next": "\x1b[6~",
    "F1": "\x1bOP", "F2": "\x1bOQ", "F3": "\x1bOR", "F4": "\x1bOS",
    "F5": "\x1b[15~", "F6": "\x1b[17~", "F7": "\x1b[18~", "F8": "\x1b[19~",
    "F9": "\x1b[20~", "F10": "\x1b[21~", "F11": "\x1b[23~", "F12": "\x1b[24~",
}
MODIFIER_KEYS = {
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
    "Super_L", "Super_R", "Win_L", "Win_R", "Hyper_L", "Hyper_R", "Caps_Lock", "Num_Lock",
    "Scroll_Lock", "ISO_Level3_Shift", "Mode_switch",
}
ALT_MASK = 0x20000 if IS_WINDOWS else 0x8

# Modos privados do pyte são guardados deslocados 5 bits à esquerda
MODE_APP_CURSOR = 1 << 5        # DECCKM  (?1)
MODE_BRACKETED_PASTE = 2004 << 5  # (?2004)

ALT_SCREEN_RE = re.compile(r"\x1b\[\?(?:1049|1047|47)([hl])")
# sequência cortada no fim de um bloco de dados (ex.: "\x1b[?10" + "49h" no próximo)
PARTIAL_RE = re.compile(r"\x1b(?:\[(?:\?\d{0,4})?)?$")


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
        except InterruptedError:
            return ""
        except OSError:
            return None
        if not data:
            return None
        return self.decoder.decode(data)

    def write(self, text):
        data = text.encode("utf-8")
        while data:
            try:
                n = os.write(self.master, data)
            except InterruptedError:
                continue
            except OSError:
                return
            data = data[n:]

    def set_size(self, rows, cols):
        try:
            winsz = self._struct.pack("HHHH", rows, cols, 0, 0)
            self._fcntl.ioctl(self.master, self._termios.TIOCSWINSZ, winsz)
        except OSError:
            pass

    def wait_exit(self):
        try:
            return self.proc.wait(timeout=2)
        except Exception:
            return None

    def close(self):
        try:  # derruba o grupo inteiro (JShell + JCode/JFiles abertos por ele)
            os.killpg(self.proc.pid, signal.SIGHUP)
        except Exception:
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
            except Exception:  # EOFError e afins = processo terminou
                return None
            if data:
                return data
            if not self.proc.isalive():
                return None
            time.sleep(0.003)  # evita loop apertado que disputa o GIL com a interface

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

    def wait_exit(self):
        for _ in range(40):
            if not self.proc.isalive():
                break
            time.sleep(0.05)
        return getattr(self.proc, "exitstatus", None)

    def close(self):
        try:
            self.proc.terminate(force=True)
        except Exception:
            pass


# ── Tela do terminal ─────────────────────────────────────────────────────────
class TermScreen(pyte.Screen):
    """Screen do pyte com: respostas a consultas, histórico e título da janela."""

    def __init__(self, cols, rows, on_reply, on_scroll_out, on_clear_history, on_title):
        self.on_reply = on_reply
        self.on_scroll_out = on_scroll_out
        self.on_clear_history = on_clear_history
        self.on_title = on_title
        super().__init__(cols, rows)

    def write_process_input(self, data):  # ex.: resposta de "posição do cursor"
        self.on_reply(data)

    def index(self):
        m = self.margins
        top, bottom = (m.top, m.bottom) if m else (0, self.lines - 1)
        if self.cursor.y == bottom and top == 0 and bottom == self.lines - 1:
            self.on_scroll_out(self.buffer[0])  # linha que está prestes a sair pelo topo
        super().index()

    def erase_in_display(self, how=0, *args, **kwargs):
        if how == 3:
            self.on_clear_history()
        super().erase_in_display(how, *args, **kwargs)

    def set_title(self, param):
        super().set_title(param)
        self.on_title(param)


# ── Janela ───────────────────────────────────────────────────────────────────
class JTerminal:
    def __init__(self, root, argv):
        self.root = root
        root.title("JShell")
        root.geometry("900x580")
        root.minsize(300, 150)
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
        self.update_metrics()

        self.text = tk.Text(
            root, bg=DEFAULT_BG, fg=DEFAULT_FG, font=self.font, wrap="none",
            bd=0, highlightthickness=0, padx=PAD, pady=PAD, insertwidth=0,
            selectbackground=SELECT_BG, selectforeground=DEFAULT_FG,
            spacing1=0, spacing2=0, spacing3=0, cursor="xterm", undo=False,
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.focus_set()

        self.tags = {}            # estilo -> nome da tag do Tk
        self.style_cache = {}     # (campos do Char, é_cursor) -> estilo
        self.color_cache = {}
        self.line_cache = {}      # linha da tela -> runs atualmente desenhados
        self.history = []         # linhas que saíram pelo topo (já em runs)
        self.offset = 0           # quantas linhas o usuário rolou para cima
        self.alt_saved = None
        self.pending = ""         # sequência de escape cortada entre dois blocos
        self.last_cursor_y = 0
        self.exited = False
        self.waiting_close = False
        self.resize_job = None
        self.tag_counter = 0
        self.queue = queue.Queue(maxsize=128)   # limite = contrapressão no processo
        self.write_queue = queue.Queue()

        root.update()
        rows, cols = self.calc_size()
        self.rows, self.cols = rows, cols

        self.screen = TermScreen(cols, rows, self.send, self.on_scroll_out,
                                 self.clear_history, self.set_title)
        self.stream = pyte.Stream(self.screen)
        self.reset_text_lines()

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            Backend = WinPty if IS_WINDOWS else UnixPty
            self.pty = Backend(argv, rows, cols, env, os.getcwd())
        except Exception as exc:
            messagebox.showerror("JTerminal", f"Não foi possível iniciar:\n{' '.join(argv)}\n\n{exc!r}")
            root.destroy()
            raise SystemExit(1)

        threading.Thread(target=self.reader, daemon=True).start()
        threading.Thread(target=self.writer, daemon=True).start()

        self.text.bind("<Key>", self.on_key)
        self.text.bind("<Button-1>", lambda e: self.text.focus_set())
        self.text.bind("<Button-2>", lambda e: self.paste(primary=True))
        self.text.bind("<Button-3>", self.on_right_click)
        self.text.bind("<MouseWheel>", self.on_wheel)
        self.text.bind("<Button-4>", self.on_wheel)
        self.text.bind("<Button-5>", self.on_wheel)
        self.text.bind("<Configure>", self.on_configure)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.root.after(BUSY_MS, self.pump)

    # ── tamanho / fonte ──
    def update_metrics(self):
        self.cw = max(1, self.font.measure("0"))
        self.lh = max(1, self.font.metrics("linespace"))

    def calc_size(self):
        w = self.text.winfo_width() - 2 * PAD
        h = self.text.winfo_height() - 2 * PAD
        return max(5, h // self.lh), max(20, w // self.cw)

    def reset_text_lines(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n" * (self.rows - 1))
        self.line_cache.clear()
        self.screen.dirty.update(range(self.rows))

    def on_configure(self, _event):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(60, self.apply_resize)

    def apply_resize(self, force=False):
        self.resize_job = None
        if self.exited:
            return
        rows, cols = self.calc_size()
        if not force and (rows, cols) == (self.rows, self.cols):
            return
        self.rows, self.cols = rows, cols
        self.screen.resize(rows, cols)
        self.pty.set_size(rows, cols)
        self.offset = min(self.offset, len(self.history))
        self.reset_text_lines()
        self.render()

    def zoom(self, delta):
        size = max(FONT_MIN, min(FONT_MAX, int(self.font.cget("size")) + delta))
        for f in (self.font, self.font_bold, self.font_italic, self.font_bold_italic):
            f.configure(size=size)
        self.update_metrics()
        self.apply_resize(force=True)

    def set_title(self, title):
        try:
            self.root.title(title or "JShell")
        except tk.TclError:
            pass

    # ── threads de E/S ──
    def reader(self):
        while True:
            data = self.pty.read()
            if data is None:
                break
            if data:
                self.queue.put(data)
        self.queue.put(("exit", self.pty.wait_exit()))

    def writer(self):
        # escrever no PTY pode bloquear (buffer cheio); por isso nunca é feito na thread da UI
        while True:
            data = self.write_queue.get()
            if data is None:
                return
            self.pty.write(data)

    def send(self, text):
        self.write_queue.put(text)

    # ── ciclo principal: consome saída, atualiza emulador e desenha ──
    def pump(self):
        if self.exited:
            return
        busy = False
        exit_code = None
        got_exit = False
        try:
            deadline = time.perf_counter() + FEED_BUDGET
            while time.perf_counter() < deadline:
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
                busy = True
                if isinstance(item, tuple):
                    got_exit, exit_code = True, item[1]
                    break
                try:
                    self.feed(item)
                except Exception:
                    # o emulador nunca pode derrubar o ciclo (isso congelaria a janela)
                    self.pending = ""
            if busy:
                self.safe_render()
            if got_exit:
                self.on_process_exit(exit_code)
        except Exception:
            pass
        finally:
            if not self.exited:
                self.root.after(BUSY_MS if busy else IDLE_MS, self.pump)

    def on_process_exit(self, code):
        if code in (0, None) or not KEEP_OPEN_ON_ERROR:
            self.close()
            return
        self.waiting_close = True
        self.snap_bottom()
        self.feed(f"\r\n\x1b[31m[processo finalizado com código {code} — "
                  f"pressione Enter para fechar]\x1b[0m\r\n")
        self.safe_render()

    # ── emulação ──
    def feed(self, data):
        if self.pending:
            data, self.pending = self.pending + data, ""
        m = PARTIAL_RE.search(data)
        if m:
            self.pending = data[m.start():]
            data = data[:m.start()]
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

    # ── histórico ──
    def on_scroll_out(self, line):
        if self.alt_saved is not None:  # apps de tela cheia não alimentam o histórico
            return
        self.history.append(self.line_runs(line, self.screen.columns))
        if len(self.history) > SCROLLBACK + 500:
            del self.history[:500]
        if self.offset:  # mantém a posição de leitura estável enquanto chega saída
            self.offset = min(self.offset + 1, len(self.history))

    def clear_history(self):
        self.history.clear()
        self.offset = 0

    def scroll_view(self, delta):
        new = max(0, min(len(self.history), self.offset + delta))
        if new == self.offset:
            return
        self.offset = new
        if new == 0:
            self.screen.dirty.update(range(self.screen.lines))
        self.safe_render()

    def snap_bottom(self):
        if self.offset:
            self.scroll_view(-self.offset)

    # ── renderização ──
    def color(self, c, default):
        r = self.color_cache.get((c, default))
        if r is None:
            if c == "default":
                r = default
            elif c in COLOR_NAMES:
                r = COLOR_NAMES[c]
            elif HEX_RE.fullmatch(c):
                r = "#" + c
            else:
                r = default
            self.color_cache[(c, default)] = r
        return r

    def compute_key(self, ch, is_cursor):
        fg = self.color(ch.fg, DEFAULT_FG)
        bg = self.color(ch.bg, DEFAULT_BG)
        if ch.reverse != is_cursor:  # XOR: reverse do app e/ou cursor
            fg, bg = bg, fg
        return (fg, bg, bool(ch.bold), bool(ch.italics),
                bool(ch.underscore), bool(ch.strikethrough))

    def tag_for(self, key):
        if key == DEFAULT_KEY:
            return ""
        name = self.tags.get(key)
        if name:
            return name
        fg, bg, bold, italic, under, strike = key
        self.tag_counter += 1
        name = f"s{self.tag_counter}"
        f = {(False, False): self.font, (True, False): self.font_bold,
             (False, True): self.font_italic, (True, True): self.font_bold_italic}[(bold, italic)]
        self.text.tag_configure(name, foreground=fg, background=bg, font=f,
                                underline=under, overstrike=strike)
        self.tags[key] = name
        return name

    def flush_tags(self):
        """Muitos estilos distintos (ex.: degradês truecolor) deixam o Text lento: recomeça."""
        for name in self.tags.values():
            self.text.tag_delete(name)
        self.tags.clear()
        self.line_cache.clear()
        self.screen.dirty.update(range(self.screen.lines))

    def line_runs(self, line, columns, cx=-1):
        """Converte uma linha do pyte em [(estilo, texto), ...]."""
        runs = []
        cache = self.style_cache
        for x in range(columns):
            ch = line[x]
            data = ch.data
            if not data:  # segunda metade de caractere largo
                continue
            ck = (ch[1:], x == cx)
            key = cache.get(ck)
            if key is None:
                key = cache[ck] = self.compute_key(ch, x == cx)
            if runs and runs[-1][0] == key:
                runs[-1][1] += data
            else:
                runs.append([key, data])
        if runs and runs[-1][0] == DEFAULT_KEY:
            runs[-1][1] = runs[-1][1].rstrip(" ")
            if not runs[-1][1]:
                runs.pop()
        return [(k, t) for k, t in runs]

    def live_runs(self, y):
        s = self.screen
        cur = s.cursor
        cx = cur.x if (not cur.hidden and cur.y == y) else -1
        return self.line_runs(s.buffer[y], s.columns, cx)

    def draw_runs(self, y, runs):
        if self.line_cache.get(y) == runs:  # nada mudou: não mexe no widget
            return
        self.line_cache[y] = runs
        self.text.delete(f"{y + 1}.0", f"{y + 1}.end")
        if runs:
            args = []
            for key, chunk in runs:
                args.append(chunk)
                args.append(self.tag_for(key))
            self.text.insert(f"{y + 1}.0", *args)  # uma única chamada Tcl por linha

    def safe_render(self):
        try:
            self.render()
        except Exception:
            # estado de tags/linhas inconsistente: redesenha tudo do zero
            try:
                self.line_cache.clear()
                self.screen.dirty.update(range(self.screen.lines))
                self.render()
            except Exception:
                pass

    def render(self):
        if self.exited:
            return
        s = self.screen
        if len(self.tags) > MAX_TAGS:
            self.flush_tags()

        if self.offset:  # visualizando o histórico
            s.dirty.clear()
            n = len(self.history)
            base = n - self.offset
            for y in range(min(self.rows, s.lines)):
                i = base + y
                if i < n:
                    runs = self.history[i]
                else:
                    runs = self.line_runs(s.buffer[i - n], s.columns)
                self.draw_runs(y, runs)
        else:
            dirty = set(s.dirty)
            s.dirty.clear()
            dirty.add(self.last_cursor_y)
            dirty.add(s.cursor.y)
            self.last_cursor_y = s.cursor.y
            for y in sorted(dirty):
                if 0 <= y < s.lines:
                    self.draw_runs(y, self.live_runs(y))

        if self.text.yview()[0] != 0.0:  # o Text nunca deve rolar sozinho
            self.text.yview_moveto(0)

    # ── teclado ──
    def on_key(self, e):
        ks = e.keysym
        if ks in MODIFIER_KEYS:
            return "break"

        if self.waiting_close:
            if ks in ("Return", "KP_Enter", "Escape"):
                self.close()
            return "break"

        ctrl = bool(e.state & 0x4)
        shift = bool(e.state & 0x1)
        alt = bool(e.state & ALT_MASK)
        char = e.char

        # atalhos da janela
        if ctrl and shift and ks in ("C", "c"):
            self.copy()
            return "break"
        if ctrl and shift and ks in ("V", "v"):
            return self.paste()
        if shift and ks == "Insert":
            return self.paste()
        if ctrl and ks == "Insert":
            self.copy()
            return "break"
        if ctrl and not shift and ks in ("c", "C") and self.has_selection():
            self.copy()
            return "break"
        if shift and ks in ("Prior", "Next") and self.alt_saved is None:
            page = max(1, self.rows - 1)
            self.scroll_view(page if ks == "Prior" else -page)
            return "break"

        # AltGr no Windows chega como Ctrl+Alt: é só o caractere (ex.: "/" e "?" no ABNT2)
        if IS_WINDOWS and ctrl and alt and char and char >= " ":
            self.snap_bottom()
            self.send(char)
            return "break"

        mod = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)
        app_cursor = MODE_APP_CURSOR in self.screen.mode
        seq = None

        if ks in ARROWS or ks in HOME_END:
            letter = ARROWS.get(ks) or HOME_END[ks]
            if mod > 1:
                seq = f"\x1b[1;{mod}{letter}"
            else:
                seq = ("\x1bO" if app_cursor else "\x1b[") + letter
        elif ks == "Tab" and shift:
            seq = "\x1b[Z"
        elif ks == "BackSpace" and ctrl:
            seq = "\x17"
        elif ks == "space" and ctrl:
            seq = "\x00"
        elif ks in KEYMAP:
            seq = KEYMAP[ks]
            if mod > 1 and seq.endswith("~"):
                seq = seq[:-1] + f";{mod}~"
            elif mod > 1 and seq.startswith("\x1bO"):
                seq = f"\x1b[1;{mod}{seq[-1]}"
            elif alt and len(seq) == 1:
                seq = "\x1b" + seq
        elif char:
            seq = char
            if alt and not ctrl:
                seq = "\x1b" + seq

        if seq:
            self.snap_bottom()
            self.send(seq)
        return "break"

    # ── mouse ──
    def on_wheel(self, e):
        if getattr(e, "num", 0) == 4:
            d = 1
        elif getattr(e, "num", 0) == 5:
            d = -1
        else:
            d = 1 if e.delta > 0 else -1

        if e.state & 0x4:  # Ctrl + roda = zoom
            self.zoom(d)
        elif self.alt_saved is not None:  # app de tela cheia: roda vira setas
            app = MODE_APP_CURSOR in self.screen.mode
            arrow = ("\x1bO" if app else "\x1b[") + ("A" if d > 0 else "B")
            self.send(arrow * 3)
        else:
            self.scroll_view(d * 3)
        return "break"

    def on_right_click(self, _e):
        if self.has_selection():
            self.copy()
            return "break"
        return self.paste()

    # ── área de transferência ──
    def has_selection(self):
        return bool(self.text.tag_ranges("sel"))

    def copy(self):
        try:
            sel = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return
        sel = "\n".join(line.rstrip() for line in sel.split("\n"))
        self.root.clipboard_clear()
        self.root.clipboard_append(sel)
        self.text.tag_remove("sel", "1.0", "end")

    def paste(self, _event=None, primary=False):
        data = None
        if primary:
            try:
                data = self.text.selection_get(selection="PRIMARY")
            except tk.TclError:
                data = None
        if data is None:
            try:
                data = self.root.clipboard_get()
            except tk.TclError:
                return "break"
        data = data.replace("\r\n", "\n").replace("\r", "\n").replace("\x1b", "")
        data = data.replace("\n", "\r")
        if MODE_BRACKETED_PASTE in self.screen.mode:
            data = "\x1b[200~" + data + "\x1b[201~"
        self.snap_bottom()
        self.send(data)
        return "break"

    # ── encerramento ──
    def close(self):
        if self.exited:
            return
        self.exited = True
        self.write_queue.put(None)
        try:
            self.pty.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    if len(sys.argv) > 1:
        argv = sys.argv[1:]
    else:
        argv = [sys.executable, os.path.join(BASE_DIR, "JShell.py")]

    if IS_WINDOWS:  # texto nítido e tamanhos corretos em telas com escala > 100%
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    root = tk.Tk()
    JTerminal(root, argv)
    root.mainloop()


if __name__ == "__main__":
    main()
