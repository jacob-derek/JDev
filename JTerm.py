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
    python JDesk.py                  -> ambiente com vários painéis (usa PtyPane daqui)

Atalhos:
    Ctrl+Shift+C / Ctrl+Insert   copiar (Ctrl+C copia se houver seleção)
    Ctrl+Shift+V / Shift+Insert  colar (botão direito: copia se houver seleção, senão cola)
    Ctrl+Shift+A                 seleciona tudo (histórico + tela)
    Shift+PageUp / Shift+PageDown, roda do mouse   histórico (scrollback)
    Ctrl + roda do mouse         zoom da fonte

Seleção com o mouse (guardada em linhas absolutas do histórico, então sobrevive à rolagem):
    arrastar                     seleciona; arrastar para fora da janela rola sozinho
    roda do mouse enquanto arrasta   continua a seleção
    Shift + clique               estende a seleção existente (clique, role, Shift+clique no fim)
    duplo clique / triplo clique palavra / linha
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
import unicodedata
from tkinter import font, messagebox

import pyte

try:
    from jcursor import decscusr
except ImportError:   # sem o jcursor.py o terminal segue com o cursor de bloco fixo
    def decscusr(_n):
        return "block", False

IS_WINDOWS = os.name == "nt"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Ajustes ──────────────────────────────────────────────────────────────────
SCROLLBACK = 5000          # linhas de histórico
FEED_BUDGET = 0.012        # segundos máx. processando saída por ciclo (mantém a UI viva)
BUSY_MS, IDLE_MS = 3, 10   # intervalo do ciclo com/sem saída
MAX_TAGS = 1500            # limite de estilos distintos antes de limpar o cache
FONT_MIN, FONT_MAX = 7, 32
KEEP_OPEN_ON_ERROR = True  # se o processo sair com erro, mantém a janela para ler a mensagem
AUTOSCROLL_MS = 45         # intervalo da rolagem automática ao arrastar a seleção para fora da janela
WORD_STOP = set("()[]{}<>\"'`,;|&")   # separadores no duplo clique (além de espaços)

# ── Tema Tokyo Night ─────────────────────────────────────────────────────────
try:  # paleta única do JDev; opcional: sem o jtheme.py ao lado vale o Tokyo Night embutido
    from jtheme import (ACCENTS, BLUE as _BLUE, BORDER_IDLE, DESK_BG, FG as DEFAULT_FG, HEADER_FG_FOCUS,
                        HEADER_FG_IDLE, PANE_BG as DEFAULT_BG, SELECT_BG)
except ImportError:
    DEFAULT_FG, DEFAULT_BG, SELECT_BG = "#a9b1d6", "#1a1b26", "#33467c"
    DESK_BG = "#13141c"        # fundo do JDesk: aparece como o "espaço" entre os painéis
    BORDER_IDLE, _BLUE = "#292e42", "#7aa2f7"
    HEADER_FG_IDLE, HEADER_FG_FOCUS = "#6b7394", "#16161e"
    # cor de cada painel: ponto no cabeçalho (inativo) e borda/cabeçalho (com foco)
    ACCENTS = {"jfiles": "#7aa2f7", "jshell": "#9ece6a", "jcode": "#bb9af7", "jclass": "#e0af68"}
PAD = 8
DEFAULT_KEY = (DEFAULT_FG, DEFAULT_BG, False, False, False, False)

# A paleta ANSI precisa distinguir preto como TEXTO de preto como FUNDO:
# usar #15161e para os dois tornava texto ANSI preto quase invisível no fundo #1a1b26.
try:
    from jtheme import ANSI_BLACK_BG, ANSI_BLACK_FG, COLOR_NAMES, LIGHT  # paleta ANSI vem do tema
except ImportError:
    LIGHT = False
    ANSI_BLACK_FG = "#7b83a8"       # preto ANSI elevado para uma cor legível em texto
    ANSI_BLACK_BG = "#15161e"       # preto real continua escuro quando usado como fundo
    COLOR_NAMES = {
        "black": ANSI_BLACK_BG, "red": "#f7768e", "green": "#9ece6a", "brown": "#e0af68",
        "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#a9b1d6",
        "brightblack": "#7b83a8", "brightred": "#f7768e", "brightgreen": "#9ece6a",
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

ALT_SCREEN_RE = re.compile(r"\x1b\[\?(?:1049|1047|47)([hl])|\x1b\[([0-6]?) q")
# sequência cortada no fim de um bloco de dados (ex.: "\x1b[?10" + "49h" no próximo)
PARTIAL_RE = re.compile(r"\x1b(?:\[(?:\?\d{0,4}|\d? ?)?)?$")
# DECSCUSR (ESC [ Ps SP q): formato e piscar do cursor. O pyte não entende; tratamos aqui (jcursor).
BLINK_MS = 530


# ── Backends de PTY ──────────────────────────────────────────────────────────
class UnixPty:
    def __init__(self, argv, rows, cols, env, cwd):
        import fcntl
        import pty
        import struct
        import subprocess
        import termios
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


# ── Painel: um pty + emulador + widget (reutilizável em janela única ou no JDesk) ──
BORDER_FOCUS = _BLUE

_family_cache = None


def pick_family():
    global _family_cache
    if _family_cache is None:
        families = set(font.families())
        _family_cache = next((f for f in FONT_CANDIDATES if f in families), "TkFixedFont")
    return _family_cache


def enable_dpi_awareness():
    if IS_WINDOWS:  # texto nítido e tamanhos corretos em telas com escala > 100%
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _eh_emoji(c):
    """Caracteres cuja fonte de fallback costuma ser mais alta que a fonte do terminal."""
    o = ord(c)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o == 0xFE0F


def _celulas(texto):
    """Divide o texto de uma linha em células de terminal.
    Caractere largo ocupa 2 células (a segunda é ""); combinantes ficam na célula anterior."""
    cel = []
    for c in texto:
        if cel and (unicodedata.combining(c) or c in "\u200d\ufe0f"):
            cel[-1] += c
        elif unicodedata.east_asian_width(c) in ("W", "F"):
            cel.append(c)
            cel.append("")
        else:
            cel.append(c)
    return cel


class PtyPane(tk.Frame):
    """Um terminal completo (pty + pyte + Text) dentro de um Frame.

    exit_mode:
      "close"   -> comportamento clássico do JTerm: processo sai => chama on_close
      "restart" -> processo sai => mostra o código e espera Enter (ou o host) reiniciar
    key_filter(pane, evento) -> True se o host consumiu a tecla (atalhos do JDesk)
    O processo só é iniciado quando o widget já tem tamanho real (evita pty 24x80 errado).
    """

    def __init__(self, parent, argv, name="JShell", cwd=None, env_extra=None, header=False,
                 exit_mode="close", on_title=None, on_close=None, key_filter=None,
                 on_focus=None, font_size=12):
        super().__init__(parent, bg=BORDER_IDLE, bd=0, highlightthickness=0)
        self.argv = list(argv)
        self.name = name
        self.cwd = cwd or os.getcwd()
        self.env_extra = env_extra or {}
        self.exit_mode = exit_mode
        self.on_title = on_title
        self.on_close = on_close
        self.key_filter = key_filter
        self.on_focus = on_focus

        self.accent = ACCENTS.get(str(name).lower(), BORDER_FOCUS)
        self.font = font.Font(family=pick_family(), size=font_size)
        self.font_bold = self.font.copy()
        self.font_bold.configure(weight="bold")
        self.font_italic = self.font.copy()
        self.font_italic.configure(slant="italic")
        self.font_bold_italic = self.font_bold.copy()
        self.font_bold_italic.configure(slant="italic")
        self.lh_real = 0               # altura real (px) da maior linha com emoji já medida
        self._medidas_estaveis = 0
        self._remedir_job = None
        self.update_metrics()

        self.header = None
        if header:
            self.header_bar = tk.Frame(self, bg=BORDER_IDLE, bd=0, highlightthickness=0)
            self.header_bar.pack(fill=tk.X)
            self.dot = tk.Label(self.header_bar, text=" \u25cf", bg=BORDER_IDLE, fg=self.accent,
                                font=("TkDefaultFont", 9, "bold"), bd=0, pady=2)
            self.dot.pack(side=tk.LEFT)
            self.header = tk.Label(self.header_bar, text=f" {name.upper()} ", bg=BORDER_IDLE,
                                   fg=HEADER_FG_IDLE, anchor="w", font=("TkDefaultFont", 9, "bold"),
                                   bd=0, pady=2)
            self.header.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.text = tk.Text(
            self, bg=DEFAULT_BG, fg=DEFAULT_FG, font=self.font, wrap="none",
            bd=0, highlightthickness=0, padx=PAD, pady=PAD, insertwidth=0,
            selectbackground=SELECT_BG, selectforeground=DEFAULT_FG,
            spacing1=0, spacing2=0, spacing3=0, cursor="xterm", undo=False,
        )
        if header:
            self.text.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))
        else:
            self.text.pack(fill=tk.BOTH, expand=True)

        # Seleção própria (o "sel" nativo do Tk some quando o Text é redesenhado/rolado):
        # guardada em (linha_absoluta, coluna). linha_absoluta = índice no histórico; as linhas da
        # tela vêm depois (len(history) + y), e esse número não muda quando a linha vai para o histórico.
        self.text.tag_configure("jsel", background=SELECT_BG, foreground=DEFAULT_FG)
        self.sel_a = None         # início (ou âncora) da seleção
        self.sel_b = None         # fim
        self.sel_drag = False     # botão 1 pressionado
        self.sel_mode = "char"    # "char" | "word" | "line"
        self._anchor = None       # onde o arrasto começou
        self._origin = None       # faixa inicial do duplo/triplo clique
        self._ptr = (0, 0)        # último ponto do ponteiro durante o arrasto
        self._scan_job = None     # rolagem automática
        self._sel_dirty = False   # precisa repintar a seleção
        self._sel_painted = False
        self._primary_handler = False
        self._primary_owned = False
        self._primary_cache = (None, b"")
        self.tags = {}            # estilo -> nome da tag do Tk
        self.style_cache = {}     # (campos do Char, é_cursor) -> estilo
        self.color_cache = {}
        self.line_cache = {}      # linha da tela -> runs atualmente desenhados
        self.tag_counter = 0
        self.resize_job = None
        self.started = False      # processo já foi iniciado alguma vez
        self.destroyed = False    # painel encerrado de vez
        self.dead = False         # processo terminou (painel segue na tela)
        self.visible = True
        self.waiting_close = False
        self.waiting_restart = False
        self.pty = None
        self.stop_io = None
        self.queue = queue.Queue(maxsize=128)
        self.write_queue = queue.Queue()
        self.rows, self.cols = 24, 80
        self._new_emulator()

        self.text.bind("<Key>", self.on_key)
        self.text.bind("<Button-1>", self.on_press)
        self.text.bind("<Double-Button-1>", self.on_double)
        self.text.bind("<Triple-Button-1>", self.on_triple)
        self.text.bind("<B1-Motion>", self.on_drag)
        self.text.bind("<ButtonRelease-1>", self.on_release)
        self.text.bind("<B1-Leave>", lambda e: "break")   # sem a rolagem automática nativa do Tk
        self.text.bind("<B1-Enter>", lambda e: "break")
        self.text.bind("<Button-2>", lambda e: self.paste(primary=True))
        self.text.bind("<Button-3>", self.on_right_click)
        self.text.bind("<MouseWheel>", self.on_wheel)
        self.text.bind("<Button-4>", self.on_wheel)
        self.text.bind("<Button-5>", self.on_wheel)
        self.text.bind("<Configure>", self.on_configure)
        self.text.bind("<FocusIn>", self._focus_in)

    # ── ciclo de vida do processo ──
    def _new_emulator(self):
        self.screen = TermScreen(self.cols, self.rows, self.send, self.on_scroll_out,
                                 self.clear_history, self.set_title)
        self.stream = pyte.Stream(self.screen)
        self.history = []         # linhas que saíram pelo topo (já em runs)
        self.offset = 0           # quantas linhas o usuário rolou para cima
        self.alt_saved = None
        self.pending = ""         # sequência de escape cortada entre dois blocos
        self.last_cursor_y = 0
        self.cur_forma, self.cur_pisca, self.cur_on = "block", False, True
        self._cur_pos = None
        self._blink_job = getattr(self, "_blink_job", None)    # não perde o timer ao reiniciar o emulador
        self._cur_widget = getattr(self, "_cur_widget", None)
        self.sel_a = self.sel_b = self._anchor = self._origin = None
        self.sel_drag = False
        self.reset_text_lines()

    def start_process(self):
        if self.destroyed:
            return
        self.rows, self.cols = self.calc_size()
        self.dead = self.waiting_close = self.waiting_restart = False
        self._new_emulator()

        env = os.environ.copy()
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor",
                    "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        env.setdefault("JICONES", "nerd")  # aqui emojis (acima de U+FFFF) não são confiáveis no Tk
        env.update(self.env_extra)

        q = self.queue = queue.Queue(maxsize=128)   # limite = contrapressão no processo
        wq = self.write_queue = queue.Queue()
        try:
            Backend = WinPty if IS_WINDOWS else UnixPty
            pty = self.pty = Backend(self.argv, self.rows, self.cols, env, self.cwd)
        except Exception as exc:
            self.pty = None
            if self.exit_mode == "close":
                messagebox.showerror("JTerminal", f"Não foi possível iniciar:\n{' '.join(self.argv)}\n\n{exc!r}")
                if self.on_close:
                    self.on_close(self)
                return
            self.dead = self.waiting_restart = True
            self.feed(f"\x1b[31mNão foi possível iniciar: {' '.join(self.argv)}\r\n{exc!r}\r\n"
                      f"[Enter reinicia]\x1b[0m\r\n")
            self.safe_render()
            return

        self.stop_io = threading.Event()
        threading.Thread(target=self.reader, args=(pty, q, self.stop_io), daemon=True).start()
        threading.Thread(target=self.writer, args=(pty, wq, self.stop_io), daemon=True).start()

    def kill_process(self):
        if self.stop_io:
            self.stop_io.set()
        try:
            self.write_queue.put(None)
        except Exception:
            pass
        if self.pty:
            try:
                self.pty.close()
            except Exception:
                pass
        self.pty = None

    def restart(self):
        if self.destroyed:
            return
        self.kill_process()
        self.start_process()

    def encerrar(self):
        """Mata o processo e deixa o painel parado, esperando Enter para reiniciar."""
        if self.destroyed or self.dead or not self.started:
            return
        self.kill_process()
        self.on_process_exit("encerrado")

    def shutdown(self):
        if self.destroyed:
            return
        self.destroyed = True
        if self._blink_job is not None:
            try:
                self.after_cancel(self._blink_job)
            except (tk.TclError, ValueError):
                pass
            self._blink_job = None
        self.kill_process()
        try:
            self.destroy()
        except tk.TclError:
            pass

    # ── foco / visibilidade / aparência ──
    def focus_text(self):
        self.text.focus_set()

    def _focus_in(self, _e):
        if self.on_focus:
            self.on_focus(self)

    def set_active(self, active):
        bg = self.accent if active else BORDER_IDLE
        self.configure(bg=bg)
        if self.header:
            self.header_bar.configure(bg=bg)
            self.dot.configure(bg=bg, fg=HEADER_FG_FOCUS if active else self.accent)
            self.header.configure(bg=bg, fg=HEADER_FG_FOCUS if active else HEADER_FG_IDLE)

    def set_header(self, text):
        if self.header:
            self.header.configure(text=f" {text} ")

    def set_visible(self, visible):
        if visible == self.visible:
            return
        self.visible = visible
        if visible:  # o que chegou enquanto estava escondido é desenhado agora
            self.line_cache.clear()
            self.screen.dirty.update(range(self.screen.lines))
            self.safe_render()

    # ── tamanho / fonte ──
    def update_metrics(self):
        self.cw = max(1, self.font.measure("0"))
        self.lh = max(1, self.font.metrics("linespace"))

    def calc_size(self):
        w = self.text.winfo_width() - 2 * PAD
        h = self.text.winfo_height() - 2 * PAD
        return max(5, h // max(self.lh, self.lh_real)), max(20, w // self.cw)

    def reset_text_lines(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n" * (self.rows - 1))
        self.line_cache.clear()
        self.screen.dirty.update(range(self.rows))

    def on_configure(self, _event):
        if self.destroyed:
            return
        if not self.started:
            if self.text.winfo_width() > 60 and self.text.winfo_height() > 40:
                self.started = True
                self.after_idle(self.start_process)
            return
        if self.resize_job:
            self.after_cancel(self.resize_job)
        self.resize_job = self.after(60, self.apply_resize)

    def apply_resize(self, force=False):
        self.resize_job = None
        if self.destroyed or not self.started:
            return
        rows, cols = self.calc_size()
        if not force and (rows, cols) == (self.rows, self.cols):
            return
        self.rows, self.cols = rows, cols
        self._resize_screen(rows, cols)
        if self.pty:
            self.pty.set_size(rows, cols)
        self.offset = min(self.offset, len(self.history))
        self._sel_dirty = True
        self.reset_text_lines()
        self.safe_render()

    # Redimensionamento da tela do pyte. O Screen.resize() do pyte tem dois problemas que
    # bagunçam o prompt (o prompt_toolkit calcula tudo relativo ao cursor): ao diminuir, ele
    # joga fora as linhas do topo SEM levar o cursor junto (o cursor fica "abaixo" do texto,
    # às vezes fora da tela) e sem guardá-las no histórico; ao aumentar, não traz o histórico
    # de volta. Aqui o cursor acompanha o conteúdo, como no xterm/VTE.
    def _linha_vazia(self, row):
        return not row or all(c.data in (" ", "") and c.bg == "default" and not c.reverse
                              for c in row.values())

    def _preencher_linha(self, y, runs, cols):
        """Reconstrói a linha y do pyte a partir de runs do histórico."""
        s = self.screen
        row = s.buffer[y]
        row.clear()
        base = s.default_char
        x = 0
        for (fg, bg, bold, italic, under, strike), texto in runs:
            fg = "default" if fg == DEFAULT_FG else (fg[1:] if fg.startswith("#") else fg)
            bg = "default" if bg == DEFAULT_BG else (bg[1:] if bg.startswith("#") else bg)
            for cel in _celulas(texto):
                if x >= cols:
                    return
                row[x] = base._replace(data=cel, fg=fg, bg=bg, bold=bold, italics=italic,
                                       underscore=under, strikethrough=strike)
                x += 1

    def _resize_screen(self, rows, cols):
        s = self.screen
        buf, cur = s.buffer, s.cursor
        old_rows, old_cols = s.lines, s.columns
        normal = self.alt_saved is None   # tela cheia (vim etc.) se redesenha sozinha

        if rows < old_rows:
            excess = old_rows - rows
            # primeiro descarta linhas vazias abaixo do cursor; o resto sai pelo topo (vai ao histórico)
            vazias, y = 0, old_rows - 1
            while y > cur.y and vazias < excess and self._linha_vazia(buf.get(y)):
                vazias += 1
                y -= 1
            top = min(cur.y, excess - vazias) if normal else 0
            for y in range(top):
                self.on_scroll_out(buf[y])
            if top:
                for y in range(top, old_rows):
                    row = buf.pop(y, None)
                    if row is None:
                        buf.pop(y - top, None)
                    else:
                        buf[y - top] = row
                cur.y -= top
            for y in [k for k in buf if k >= rows]:
                del buf[y]
        elif rows > old_rows and normal and self.history:
            pull = min(rows - old_rows, len(self.history))
            puxadas = self.history[-pull:]
            del self.history[-pull:]
            for y in range(old_rows - 1, -1, -1):
                row = buf.pop(y, None)
                if row is not None:
                    buf[y + pull] = row
            for i, runs in enumerate(puxadas):
                self._preencher_linha(i, runs, cols)
            cur.y += pull

        s.lines = rows
        s.resize(rows, cols)      # as linhas já estão certas: o pyte só ajusta as colunas
        s.set_margins()           # região de rolagem volta ao normal (como os terminais reais)
        if cols > old_cols:
            s.tabstops.update(range(8, cols, 8))
        cur.y = max(0, min(cur.y, rows - 1))
        if cols != old_cols:
            cur.x = min(cur.x, cols - 1)
        self.last_cursor_y = cur.y
        s.dirty.update(range(rows))

    def zoom(self, delta):
        size = max(FONT_MIN, min(FONT_MAX, int(self.font.cget("size")) + delta))
        for f in (self.font, self.font_bold, self.font_italic, self.font_bold_italic):
            f.configure(size=size)
        self.update_metrics()
        self.lh_real = 0  # a fonte mudou: a altura real precisa ser medida de novo
        self._medidas_estaveis = 0
        self.apply_resize(force=True)

    def set_title(self, title):
        if self.on_title:
            try:
                self.on_title(self, title)
            except tk.TclError:
                pass

    # ── threads de E/S (uma dupla por processo; 'stop' invalida threads antigas) ──
    def reader(self, pty, q, stop):
        while not stop.is_set():
            data = pty.read()
            if data is None:
                break
            while data and not stop.is_set():
                try:
                    q.put(data, timeout=0.2)
                    break
                except queue.Full:
                    continue
        if not stop.is_set():
            q.put(("exit", pty.wait_exit()))

    def writer(self, pty, wq, stop):
        # escrever no PTY pode bloquear (buffer cheio); por isso nunca é feito na thread da UI
        while True:
            data = wq.get()
            if data is None or stop.is_set():
                return
            pty.write(data)

    def send(self, text):
        self.write_queue.put(text)

    # ── consumo da saída (chamado pelo Pump com um orçamento de tempo) ──
    def has_output(self):
        return not self.queue.empty()

    def drain(self, budget):
        if self.destroyed:
            return False
        busy = False
        got_exit, exit_code = False, None
        try:
            deadline = time.perf_counter() + budget
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
            if busy and self.visible:
                self.safe_render()
            if got_exit:
                self.on_process_exit(exit_code)
        except Exception:
            pass
        return busy

    def on_process_exit(self, code):
        self.dead = True
        if self.exit_mode == "close":
            if code in (0, None) or not KEEP_OPEN_ON_ERROR:
                if self.on_close:
                    self.on_close(self)
                return
            self.waiting_close = True
            msg = f"[processo finalizado com código {code} — pressione Enter para fechar]"
        else:
            self.waiting_restart = True
            if isinstance(code, str):
                msg = f"[processo {code} — Enter reinicia]"
            else:
                msg = (f"[processo finalizado com código {code if code is not None else '?'} — "
                       f"Enter reinicia]")
        if self.alt_saved is not None:
            self.set_alt_screen(False)
        self.snap_bottom()
        self.feed(f"\r\n\x1b[31m{msg}\x1b[0m\r\n")
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
            if m.group(1):
                self.set_alt_screen(m.group(1) == "h")
            else:
                self.cur_forma, self.cur_pisca = decscusr(int(m.group(2) or 0))
                self.cur_on = True
                self.screen.dirty.add(self.screen.cursor.y)
            pos = m.end()
        self.stream.feed(data[pos:])

    def set_alt_screen(self, enable):
        """Simula o buffer alternativo (usado por apps de tela cheia)."""
        s = self.screen
        self._sel_clear()   # o conteúdo da tela troca por completo
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
            self._sel_shift(-500)
        if self.offset:  # mantém a posição de leitura estável enquanto chega saída
            self.offset = min(self.offset + 1, len(self.history))

    def clear_history(self):
        self.history.clear()
        self.offset = 0
        self._sel_clear()
        # Uma limpeza de scrollback não deve deixar linhas antigas em cache na viewport.
        self.line_cache.clear()
        if hasattr(self, "screen"):
            self.screen.dirty.update(range(self.screen.lines))

    def scroll_view(self, delta):
        new = max(0, min(len(self.history), self.offset + delta))
        if new == self.offset:
            return
        self.offset = new
        self._sel_dirty = True
        if new == 0:
            self.screen.dirty.update(range(self.screen.lines))
        self.safe_render()

    def snap_bottom(self):
        if self.offset:
            self.scroll_view(-self.offset)

    # ── renderização ──
    def color(self, c, default, foreground=False):
        cache_key = (c, default, foreground)
        r = self.color_cache.get(cache_key)
        if r is None:
            hex_value = c[1:] if isinstance(c, str) and c.startswith("#") else c
            near_black = False
            if isinstance(hex_value, str) and HEX_RE.fullmatch(hex_value):
                rgb = int(hex_value, 16)
                near_black = max((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255) <= 0x25
            if c == "default":
                r = default
            elif foreground and not LIGHT and (c == "black" or near_black):
                # ANSI black e truecolor quase preto ficam legíveis como texto (só em tema escuro).
                r = ANSI_BLACK_FG
            elif c in COLOR_NAMES:
                r = COLOR_NAMES[c]
            elif isinstance(hex_value, str) and HEX_RE.fullmatch(hex_value):
                r = "#" + hex_value
            else:
                r = default
            self.color_cache[cache_key] = r
        return r

    def compute_key(self, ch, is_cursor):
        fg = self.color(ch.fg, DEFAULT_FG, foreground=True)
        bg = self.color(ch.bg, DEFAULT_BG, foreground=False)
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
        bloco = self.cur_forma == "block" and self.cur_on     # barra/sublinhado são desenhados à parte
        cx = cur.x if (not cur.hidden and cur.y == y and bloco) else -1
        return self.line_runs(s.buffer[y], s.columns, cx)

    def draw_runs(self, y, runs):
        if self.line_cache.get(y) == runs:  # nada mudou: não mexe no widget
            return
        self.line_cache[y] = runs
        self._sel_dirty = True
        self.text.delete(f"{y + 1}.0", f"{y + 1}.end")
        if runs:
            args = []
            for key, chunk in runs:
                args.append(chunk)
                args.append(self.tag_for(key))
            self.text.insert(f"{y + 1}.0", *args)  # uma única chamada Tcl por linha
            self._medir_linha(y, runs)

    def _medir_linha(self, y, runs):
        """O Tk deixa a linha mais alta quando ela tem um glifo de fonte de fallback (emoji).
        Se o terminal assumisse a altura da fonte base, as últimas linhas ficariam cortadas
        (e isso varia com o zoom). Medimos a altura real e recalculamos as linhas que cabem."""
        if not self.visible or self._medidas_estaveis >= 8:
            return
        if not any(_eh_emoji(c) for _, t in runs for c in t):
            return
        try:
            info = self.text.dlineinfo(f"{y + 1}.0")
        except tk.TclError:
            return
        if not info:
            return
        h, base = info[3], max(self.lh, self.lh_real)
        if base < h <= base * 2:
            self.lh_real, self._medidas_estaveis = h, 0
            if self._remedir_job is None:
                self._remedir_job = self.after(30, self._reaplicar)
        else:
            self._medidas_estaveis += 1

    def _reaplicar(self):
        self._remedir_job = None
        if not self.destroyed:
            self.apply_resize(force=True)

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
        if self.destroyed:
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

        if self._sel_dirty:   # o Text apaga tags de linhas redesenhadas: pinta a seleção de novo
            self._apply_selection()
        if self.text.yview()[0] != 0.0:  # o Text nunca deve rolar sozinho
            self.text.yview_moveto(0)
        self._atualizar_cursor()

    # ── cursor: barra/sublinhado e piscar (DECSCUSR) ──
    def _esconder_cursor(self):
        w = self._cur_widget
        if w is not None:
            try:
                w.place_forget()
            except tk.TclError:
                pass

    def _atualizar_cursor(self):
        """Barra e sublinhado são uma faixa fina por cima do Text; o bloco é a célula invertida.
        Qualquer falha aqui só apaga o cursor decorativo: nunca derruba o terminal."""
        try:
            cur = self.screen.cursor
            pos = (cur.x, cur.y)
            if pos != self._cur_pos:      # andou: o cursor volta a aparecer (como em qualquer terminal)
                self._cur_pos = pos
                self.cur_on = True
            ativo = not self.destroyed and self.visible and not self.offset and not cur.hidden
            if not ativo:
                self._esconder_cursor()
                return
            if self.cur_forma == "block":
                self._esconder_cursor()
            elif not self.cur_on:
                self._esconder_cursor()
            else:
                caixa = self.text.bbox(f"{cur.y + 1}.0")
                if not caixa:
                    self._esconder_cursor()
                else:
                    if self._cur_widget is None:
                        self._cur_widget = tk.Frame(self.text, bd=0, highlightthickness=0, bg=DEFAULT_FG)
                    x, y, _w, h = caixa
                    x = PAD + cur.x * self.cw
                    if self.cur_forma == "bar":
                        self._cur_widget.place(x=x, y=y, width=2, height=h)
                    else:
                        self._cur_widget.place(x=x, y=y + h - 2, width=self.cw, height=2)
            if self.cur_pisca and self._blink_job is None:
                self._blink_job = self.after(BLINK_MS, self._piscar)
        except (tk.TclError, AttributeError):
            pass

    def _piscar(self):
        self._blink_job = None
        if self.destroyed or not self.cur_pisca:
            self.cur_on = True
            return
        self.cur_on = not self.cur_on
        try:
            y = self.screen.cursor.y
            self.line_cache.pop(y, None)
            self.screen.dirty.add(y)
            self.safe_render()             # redesenha a linha do cursor e atualiza a faixa
        except (tk.TclError, AttributeError):
            pass
        if not self.destroyed and self.cur_pisca and self._blink_job is None:
            self._blink_job = self.after(BLINK_MS, self._piscar)

    # ── teclado ──
    def on_key(self, e):
        ks = e.keysym
        if ks in MODIFIER_KEYS:
            return "break"

        # atalhos do host (JDesk) têm prioridade sobre tudo, inclusive painel finalizado
        if self.key_filter and self.key_filter(self, e):
            return "break"

        if self.waiting_close:
            if ks in ("Return", "KP_Enter", "Escape") and self.on_close:
                self.on_close(self)
            return "break"
        if self.waiting_restart:
            if ks in ("Return", "KP_Enter"):
                self.restart()
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
        if ctrl and shift and ks in ("A", "a"):
            self.select_all()
            return "break"
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

        if e.state & 0x4:  # Ctrl + roda = zoom (por painel)
            self.zoom(d)
        elif self.alt_saved is not None:  # app de tela cheia: roda vira setas
            app = MODE_APP_CURSOR in self.screen.mode
            arrow = ("\x1bO" if app else "\x1b[") + ("A" if d > 0 else "B")
            self.send(arrow * 3)
        else:
            self.scroll_view(d * 3)
            if self.sel_drag:   # rolou com o botão pressionado: o fim da seleção acompanha o ponteiro
                self._extend_to_pointer()
        return "break"

    def on_right_click(self, _e):
        if self.has_selection():
            self.copy()
            return "break"
        return self.paste()

    # ── seleção (em linhas absolutas) ──
    def _abs_base(self):
        return len(self.history) - self.offset

    def _row_runs(self, i):
        n = len(self.history)
        if 0 <= i < n:
            return self.history[i]
        j = i - n
        s = self.screen
        if 0 <= j < s.lines:
            return self.line_runs(s.buffer[j], s.columns)
        return []

    def _row_text(self, i):
        return "".join(t for _, t in self._row_runs(i))

    def _pos_from_event(self, x, y):
        """(linha_absoluta, coluna) sob o ponteiro, limitado à área visível."""
        try:
            row = int(self.text.index(f"@{x},{y}").split(".")[0]) - 1
        except (tk.TclError, ValueError):
            row = 0
        row = max(0, min(self.rows - 1, row))
        if y < 0:
            row = 0
        elif y >= self.text.winfo_height():
            row = self.rows - 1
        col = max(0, min(self.cols - 1, int((x - PAD) // self.cw)))
        return (self._abs_base() + row, col)

    def _snap(self, pos, mode):
        """Faixa (início, fim) da palavra ou da linha na posição."""
        row, col = pos
        if mode == "line":
            return (row, 0), (row, 10 ** 6)
        cel = _celulas(self._row_text(row))
        if not cel:
            return pos, pos
        col = min(col, len(cel) - 1)

        def palavra(c):
            return c == "" or (not c.isspace() and c[0] not in WORD_STOP)

        if not palavra(cel[col]):
            return (row, col), (row, col)
        i = j = col
        while i > 0 and palavra(cel[i - 1]):
            i -= 1
        while j < len(cel) - 1 and palavra(cel[j + 1]):
            j += 1
        return (row, i), (row, j)

    def _sel_range(self):
        if self.sel_a is None or self.sel_b is None:
            return None
        a, b = self.sel_a, self.sel_b
        return (a, b) if a <= b else (b, a)

    def has_selection(self):
        return self._sel_range() is not None

    def _sel_clear(self):
        if self.sel_a is None and self.sel_b is None and not self._sel_painted:
            return
        self.sel_a = self.sel_b = self._anchor = self._origin = None
        self.sel_drag = False
        self._sel_refresh()
        self._release_primary()

    def _release_primary(self):
        if self._primary_owned:
            self._primary_owned = False
            try:
                self.text.selection_clear(selection="PRIMARY")
            except tk.TclError:
                pass

    def _sel_shift(self, d):
        """O histórico perdeu (ou ganhou) linhas no começo: ajusta as linhas absolutas."""
        def mv(p):
            return None if p is None else (max(0, p[0] + d), p[1])
        self.sel_a, self.sel_b, self._anchor = mv(self.sel_a), mv(self.sel_b), mv(self._anchor)
        if self._origin:
            self._origin = (mv(self._origin[0]), mv(self._origin[1]))

    def _sel_refresh(self):
        self._sel_dirty = True
        self._apply_selection()

    def _apply_selection(self):
        self._sel_dirty = False
        r = self._sel_range()
        if r is None and not self._sel_painted:
            return
        t = self.text
        try:
            t.tag_remove("jsel", "1.0", "end")
            self._sel_painted = False
            if r is None:
                return
            (r0, c0), (r1, c1) = r
            base = self._abs_base()
            for y in range(self.rows):
                i = base + y
                if i < r0:
                    continue
                if i > r1:
                    break
                runs = self.line_cache.get(y)
                cel = _celulas("".join(tx for _, tx in runs)) if runs else []
                a = c0 if i == r0 else 0
                ini = f"{y + 1}.{sum(len(c) for c in cel[:a])}"
                if i == r1:
                    fim = f"{y + 1}.{sum(len(c) for c in cel[:c1 + 1])}"
                else:
                    fim = f"{y + 1}.end"
                t.tag_add("jsel", ini, fim)
            t.tag_raise("jsel")   # acima das cores de fundo do programa
            self._sel_painted = True
        except tk.TclError:
            pass

    def selection_text(self):
        r = self._sel_range()
        if r is None:
            return ""
        (r0, c0), (r1, c1) = r
        r0 = max(0, r0)
        r1 = min(r1, len(self.history) + self.screen.lines - 1)
        out = []
        for i in range(r0, r1 + 1):
            cel = _celulas(self._row_text(i))
            a = c0 if i == r0 else 0
            b = c1 + 1 if i == r1 else len(cel)
            out.append("".join(cel[a:b]).rstrip())
        return "\n".join(out).rstrip("\n")

    def select_all(self):
        n = len(self.history) + self.screen.lines
        self.sel_a, self.sel_b = (0, 0), (n - 1, 10 ** 6)
        self._sel_refresh()
        self._publish_primary()

    # mouse: botão 1
    def on_press(self, e):
        self.text.focus_set()
        self._ptr = (e.x, e.y)
        pos = self._pos_from_event(e.x, e.y)
        self.sel_drag = True
        self.sel_mode = "char"
        r = self._sel_range()
        if (e.state & 0x1) and r is not None:   # Shift+clique: estende a seleção existente
            self._anchor = r[1] if pos <= r[0] else r[0]
            self.sel_a, self.sel_b = self._anchor, pos
        else:
            self._anchor = pos
            self.sel_a = self.sel_b = None
        self._sel_refresh()
        return "break"

    def on_double(self, e):
        return self._press_snap(e, "word")

    def on_triple(self, e):
        return self._press_snap(e, "line")

    def _press_snap(self, e, mode):
        self.text.focus_set()
        self._ptr = (e.x, e.y)
        pos = self._pos_from_event(e.x, e.y)
        self.sel_drag = True
        self.sel_mode = mode
        self._origin = self._snap(pos, mode)
        self.sel_a, self.sel_b = self._origin
        self._anchor = pos
        self._sel_refresh()
        return "break"

    def on_drag(self, e):
        if self.sel_drag:
            self._ptr = (e.x, e.y)
            self._extend_to_pointer()
            self._maybe_autoscroll()
        return "break"

    def _extend_to_pointer(self):
        pos = self._pos_from_event(*self._ptr)
        if self.sel_mode == "char":
            if self._anchor is None:
                return
            self.sel_a, self.sel_b = self._anchor, pos
            if self.sel_a == self.sel_b:   # clique sem arrastar: nada selecionado
                self.sel_a = self.sel_b = None
        elif self._origin:
            ini, fim = self._snap(pos, self.sel_mode)
            a0, b0 = self._origin
            if pos < a0:
                self.sel_a, self.sel_b = ini, b0
            else:
                self.sel_a, self.sel_b = a0, fim
        self._sel_refresh()

    def _scroll_speed(self):
        y, h = self._ptr[1], self.text.winfo_height()
        step = max(1, self.lh)
        if y < 0:
            return min(6, 1 + int(-y) // step)       # acima da janela: rola para o histórico
        if y > h:
            return -min(6, 1 + int(y - h) // step)   # abaixo: rola para o fim
        return 0

    def _maybe_autoscroll(self):
        if self._scan_job is None and self.alt_saved is None and self._scroll_speed():
            self._scan_job = self.after(AUTOSCROLL_MS, self._autoscroll_tick)

    def _autoscroll_tick(self):
        self._scan_job = None
        if self.destroyed or not self.sel_drag or self.alt_saved is not None:
            return
        d = self._scroll_speed()
        if d:
            self.scroll_view(d)
            self._extend_to_pointer()
            self._scan_job = self.after(AUTOSCROLL_MS, self._autoscroll_tick)

    def on_release(self, _e):
        if self.sel_drag:
            self.sel_drag = False
            if self._scan_job is not None:
                self.after_cancel(self._scan_job)
                self._scan_job = None
            self._publish_primary()
        return "break"

    # seleção PRIMARY do X11 (colar com o botão do meio, inclusive em outros programas)
    def _publish_primary(self):
        if not self.has_selection():
            return
        try:
            if not self._primary_handler:
                self.text.selection_handle(self._primary_chunk, selection="PRIMARY")
                self._primary_handler = True
            self.text.selection_own(selection="PRIMARY", command=self._primary_lost)
            self._primary_owned = True
        except tk.TclError:
            pass

    def _primary_chunk(self, offset, length):
        off, n = int(offset), int(length)
        if off == 0 or self._primary_cache[0] is None:
            self._primary_cache = (True, self.selection_text().encode("utf-8"))
        data = self._primary_cache[1]
        end = min(len(data), off + n)
        while off < end < len(data) and (data[end] & 0xC0) == 0x80:   # não corta um caractere ao meio
            end -= 1
        return data[off:end].decode("utf-8", "ignore")

    def _primary_lost(self):
        self._primary_owned = False
        self._primary_cache = (None, b"")
        if not self.sel_drag:
            self._sel_clear()

    # ── área de transferência ──
    def copy(self):
        texto = self.selection_text()
        if not texto:
            return
        self.clipboard_clear()
        self.clipboard_append(texto)
        self._sel_clear()

    def paste(self, _event=None, primary=False):
        data = None
        if primary:
            try:
                data = self.text.selection_get(selection="PRIMARY")
            except tk.TclError:
                data = None
        if not data:
            try:
                data = self.clipboard_get()
            except tk.TclError:
                return "break"
        data = data.replace("\r\n", "\n").replace("\r", "\n").replace("\x1b", "")
        data = data.replace("\n", "\r")
        if MODE_BRACKETED_PASTE in self.screen.mode:
            data = "\x1b[200~" + data + "\x1b[201~"
        self.snap_bottom()
        self.send(data)
        return "break"


# ── Pump: um único ciclo que divide o orçamento de tempo entre os painéis ────
class Pump:
    def __init__(self, root, get_panes):
        self.root = root
        self.get_panes = get_panes
        self.running = True
        root.after(BUSY_MS, self.tick)

    def stop(self):
        self.running = False

    def tick(self):
        if not self.running:
            return
        busy = False
        try:
            ativos = [p for p in list(self.get_panes()) if not p.destroyed and p.has_output()]
            if ativos:  # painéis sem saída não custam nada
                share = FEED_BUDGET / len(ativos)
                for p in ativos:
                    busy = p.drain(share) or busy
        except Exception:
            pass
        if self.running:
            try:
                self.root.after(BUSY_MS if busy else IDLE_MS, self.tick)
            except tk.TclError:
                pass


# ── Janela única (comportamento original do JTerm) ───────────────────────────
class JTerminal:
    def __init__(self, root, argv):
        self.root = root
        root.title("JShell")
        root.geometry("900x580")
        root.minsize(300, 150)
        root.configure(bg=DEFAULT_BG)

        self.pane = PtyPane(root, argv, name="JShell", exit_mode="close",
                            on_title=lambda p, t: root.title(t or "JShell"),
                            on_close=lambda p: self.close())
        self.pane.pack(fill=tk.BOTH, expand=True)
        self.pane.focus_text()
        self.pump = Pump(root, lambda: [self.pane])
        root.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self.pump.stop()
        self.pane.shutdown()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    if len(sys.argv) > 1:
        argv = sys.argv[1:]
    else:
        argv = [sys.executable, os.path.join(BASE_DIR, "JShell.py")]

    enable_dpi_awareness()
    root = tk.Tk()
    JTerminal(root, argv)
    root.mainloop()


if __name__ == "__main__":
    main()
