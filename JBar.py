#!/usr/bin/env python3
"""
JBar - barra superior do JDesk (Fase 2).

  [ 1 2 3 4 ]            [ qui 15 out  14:32 ]     [ ♪ artista - faixa  VOL 65%  RAM 42%  CPU 12% ]

- As métricas são coletadas numa thread (nada de subprocess ou I/O na thread da UI).
- psutil é opcional: sem ele, CPU/RAM/rede aparecem como "--" (o volume e o relógio seguem).
- Tocando agora: playerctl (opcional). Clique pausa/retoma; roda do mouse troca de faixa.
- Volume: pactl/amixer (Linux), pycaw (Windows), osascript (macOS). Se nada estiver
  disponível, mostra "--" sem reclamar.

Roda sozinho para teste:  python JBar.py

Modo clean do JWM (jwm --no-ui):  python JBar.py --solo --wm-pid N
  A barra vira uma janela própria (sem moldura, que o JWM nem gerencia) na faixa reservada do
  rodapé do monitor primário. Posição, visibilidade (Super+Shift+B) e workspaces vêm do
  ~/.cache/jwm-state.json; clicar num número pede o workspace ao JWM (EWMH _NET_CURRENT_DESKTOP).
"""
import argparse
import json
import locale
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Paleta e medidas vêm do jtheme (uma única fonte para JWM, JBar, JTerm e JDesk)
try:  # opcional: sem o jtheme.py ao lado vale o Tokyo Night embutido
    from jtheme import (BAR_H, DARK, DESK_BG, DIM, FG, FOCUS, GAP, GREEN, BLUE, CYAN, RED, YELLOW, LINE,
                        MODE, ON_ACCENT, PILL_BG, PILL_H, PILL_HOVER)
except ImportError:
    BAR_H, PILL_H, GAP = 44, 34, 8
    DESK_BG, PILL_BG, PILL_HOVER, LINE = "#13141c", "#1f2335", "#2a2f45", "#292e42"
    FG, DIM, DARK, ON_ACCENT = "#a9b1d6", "#565f89", "#16161e", "#fbe9ef"
    FOCUS, MODE = "#b04a67", "#9ece6a"
    GREEN, BLUE, CYAN, RED, YELLOW = "#9ece6a", "#7aa2f7", "#7dcfff", "#f7768e", "#e0af68"
try:
    from jtheme import BAR_FONT
except ImportError:
    BAR_FONT = 12
try:  # o gatinho é opcional: sem jcat.py a barra segue igual
    import jcat
except ImportError:
    jcat = None
BAR_BG = DESK_BG   # o "vazio" entre as pílulas tem a cor do fundo do JDesk: parece transparente
HOVER = PILL_HOVER

INTERVAL = 1.5  # segundos entre coletas
VOLUME_STEP = 5  # percentual por movimento do scroll


# ── Volume ───────────────────────────────────────────────────────────────────
def _run(cmd, timeout=1.0):
    env = {**os.environ, "LC_ALL": "C"}  # saída do pactl/amixer sem tradução
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout


def _pactl():
    vol = re.search(r"(\d+)%", _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
    if not vol:
        return None
    mute = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).lower()
    return int(vol.group(1)), "yes" in mute


def _amixer():
    out = _run(["amixer", "get", "Master"])
    vol = re.search(r"\[(\d+)%\]", out)
    if not vol:
        return None
    return int(vol.group(1)), "[off]" in out


def adjust_volume(delta):
    """Ajusta o volume do sistema; delta deve ser +1 ou -1."""
    step = VOLUME_STEP if delta > 0 else -VOLUME_STEP
    try:
        if shutil.which("pactl"):
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{step:+d}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=1.0, check=False,
            )
            return
        if shutil.which("amixer"):
            # amixer aceita incrementos/decrementos como "5%+" e "5%-".
            amount = f"{abs(step)}%{'+' if step > 0 else '-'}"
            subprocess.run(
                ["amixer", "set", "Master", amount],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=1.0, check=False,
            )
            return
        if IS_MAC and shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e", f"set volume output volume (output volume of (get volume settings) {'+' if step > 0 else '-'} {abs(step)})"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=1.0, check=False,
            )
    except (OSError, subprocess.SubprocessError):
        pass


def toggle_mute():
    """Liga/desliga o mudo do sistema."""
    try:
        if shutil.which("pactl"):
            cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
        elif shutil.which("amixer"):
            cmd = ["amixer", "set", "Master", "toggle"]
        elif IS_MAC and shutil.which("osascript"):
            cmd = ["osascript", "-e", "set volume output muted (not (output muted of (get volume settings)))"]
        else:
            return
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def ler_tocando():
    """(texto, tocando) da faixa atual via playerctl; None se não há playerctl, player ou faixa."""
    if not shutil.which("playerctl"):
        return None
    try:
        out = _run(["playerctl", "metadata", "--format", "{{status}}\t{{artist}}\t{{title}}"])
    except (OSError, subprocess.SubprocessError):
        return None
    status, _, resto = out.strip().partition("\t")
    artista, _, titulo = resto.partition("\t")
    if status not in ("Playing", "Paused") or not (artista or titulo):
        return None
    return (f"{artista} - {titulo}" if artista and titulo else (titulo or artista)), status == "Playing"


def controlar_player(acao):
    """acao: play-pause | next | previous."""
    if shutil.which("playerctl"):
        try:
            subprocess.run(["playerctl", acao], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=1.0, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def brilho(delta):
    """Brilho da tela +5% / -5% (brightnessctl, como no sway antigo). Sem ele, não faz nada."""
    if shutil.which("brightnessctl"):
        try:
            subprocess.run(["brightnessctl", "set", "5%+" if delta > 0 else "5%-"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def layout_atual() -> str:
    """Le o layout xkb atual. Devolve "br", "us" ou "" se nao conseguir."""
    try:
        out = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True, timeout=1).stdout
        m = re.search(r"^layout:\s*(\S+)", out, re.M)
        return m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def mudar_layout(proximo: str | None = None) -> str:
    """Alterna br <-> us (ou usa `proximo` explicitamente). Devolve o layout aplicado."""
    atual = layout_atual()
    if proximo is None:
        proximo = "us" if atual == "br" else "br"
    try:
        subprocess.run(["setxkbmap", proximo], capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass
    return proximo



def em_thread(fn, *args):
    """Roda fn fora da thread da interface (pactl pode demorar e congelaria o Tk)."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def pedir_workspace(i):
    """Pede ao JWM (mensagem EWMH _NET_CURRENT_DESKTOP) para ir ao workspace i (0-based)."""
    def _enviar():
        try:
            from Xlib import X, display, protocol
            d = display.Display()
            try:
                raiz = d.screen().root
                ev = protocol.event.ClientMessage(
                    window=raiz, client_type=d.intern_atom("_NET_CURRENT_DESKTOP"),
                    data=(32, [int(i), X.CurrentTime, 0, 0, 0]))
                raiz.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                d.flush()
            finally:
                d.close()
        except Exception:   # sem python-xlib ou sem X: o clique simplesmente não faz nada
            pass
    em_thread(_enviar)


def _osascript():
    out = _run(["osascript", "-e", "get volume settings"])
    vol = re.search(r"output volume:(\d+)", out)
    if not vol:
        return None
    return int(vol.group(1)), "output muted:true" in out


def _windows_reader():
    try:
        import comtypes
        comtypes.CoInitialize()  # COM precisa ser iniciado em cada thread que o usa
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except Exception:
        return None

    def read():
        dev = AudioUtilities.GetSpeakers()
        ev = getattr(dev, "EndpointVolume", None)  # pycaw novo
        if ev is None:  # pycaw antigo
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            ev = cast(iface, POINTER(IAudioEndpointVolume))
        return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())

    return read


def make_volume_readers():
    """Lista de leitores candidatos; o primeiro que funcionar passa a ser o usado."""
    if IS_WINDOWS:
        r = _windows_reader()
        return [r] if r else []
    if IS_MAC:
        return [_osascript] if shutil.which("osascript") else []
    readers = []
    if shutil.which("pactl"):
        readers.append(_pactl)
    if shutil.which("amixer"):
        readers.append(_amixer)
    return readers


# ── Coleta ───────────────────────────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.data = {"cpu": None, "ram": None, "down": None, "up": None,
                     "vol": None, "muted": False, "kbd": "", "play": None}

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()
        threading.Thread(target=self._loop_kbd, daemon=True).start()

    def stop(self):
        self.stop_ev.set()

    def set_kbd(self, valor):
        """Atualiza o layout na hora (usado logo depois de trocar pelo clique)."""
        with self.lock:
            self.data["kbd"] = valor

    def _loop_kbd(self):
        """Layout do teclado em tempo real: consulta leve a cada 0,3 s, fora da thread da interface."""
        if not shutil.which("setxkbmap"):
            return
        while not self.stop_ev.wait(0.3):
            atual = layout_atual()
            if atual:
                self.set_kbd(atual)

    def snapshot(self):
        with self.lock:
            return dict(self.data)

    def _run_loop(self):
        try:
            import psutil
        except ImportError:
            psutil = None
        readers = make_volume_readers()  # na própria thread (COM no Windows)
        tem_player = bool(shutil.which("playerctl"))
        net_prev = None
        if psutil:
            psutil.cpu_percent(None)  # a primeira chamada só marca o ponto de partida
            try:
                c = psutil.net_io_counters()
                net_prev = (time.monotonic(), c.bytes_recv, c.bytes_sent) if c else None
            except Exception:
                net_prev = None

        if self.stop_ev.wait(0.8):  # 1ª amostra logo depois do ponto de partida
            return
        while True:
            d = {}
            if psutil:
                try:
                    d["cpu"] = psutil.cpu_percent(None)
                    d["ram"] = psutil.virtual_memory().percent
                    c = psutil.net_io_counters()
                    if c:
                        now = time.monotonic()
                        if net_prev:
                            dt = max(0.001, now - net_prev[0])
                            d["down"] = max(0, (c.bytes_recv - net_prev[1]) / dt)
                            d["up"] = max(0, (c.bytes_sent - net_prev[2]) / dt)
                        net_prev = (now, c.bytes_recv, c.bytes_sent)
                except Exception:
                    pass
            for i, read in enumerate(readers):
                try:
                    r = read()
                except Exception:
                    r = None
                if r:
                    d["vol"], d["muted"] = r
                    if i:  # promove o leitor que funcionou
                        readers.insert(0, readers.pop(i))
                    break
            d["play"] = ler_tocando() if tem_player else None
            with self.lock:
                self.data.update(d)
            if self.stop_ev.wait(INTERVAL):
                return


# ── Formatação ───────────────────────────────────────────────────────────────
def fmt_rate(bps):
    if bps is None:
        return "--"
    for unit in ("B", "K", "M", "G"):
        if bps < 1024 or unit == "G":
            return f"{bps:.0f}{unit}" if unit == "B" or bps >= 100 else f"{bps:.1f}{unit}"
        bps /= 1024
    return "--"


def level_color(pct, warn=65, crit=85):
    if pct is None:
        return DIM
    if pct >= crit:
        return RED
    if pct >= warn:
        return YELLOW
    return GREEN


BLOCOS = "▁▂▃▄▅▆▇█"


def barra(pct):
    """Mini gráfico de uma célula (8 níveis)."""
    if pct is None:
        return "·"
    return BLOCOS[max(0, min(7, int(pct / 12.5)))]


def equalizador(t, barras=3):
    """Mini equalizador animado (só enfeite: não lê o áudio). `t` em segundos; cada barra balança em ritmo próprio."""
    out = []
    for i in range(barras):
        v = 0.5 + 0.28 * math.sin(t * (5.1 + i * 1.7) + i * 2.1) + 0.22 * math.sin(t * (9.3 - i * 1.1) + i)
        out.append(BLOCOS[max(0, min(7, int(v * 8)))])
    return "".join(out) + " "


def curto(texto, n):
    """Texto numa linha só, com no máximo n caracteres (termina em … se cortou)."""
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= n else texto[: max(1, n - 1)].rstrip() + "…"


def pct_txt(v):
    return "--" if v is None else f"{v:.0f}%"


# ── Barra ────────────────────────────────────────────────────────────────────
def _estado_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "jwm-state.json")


def _pid_vivo(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class StatusBar(tk.Canvas):
    """Barra em pílulas: onde há conteúdo, uma cápsula arredondada; entre elas, o fundo do JDesk.

    Fica numa faixa RESERVADA no rodapé (o JWM tira essa altura da área das janelas), então nunca
    cobre o que você está escrevendo. O JWM escreve ~/.cache/jwm-state.json (modo, divisão pendente,
    título da janela ativa, barra visível ou não) e a barra só LÊ esse arquivo.
    """
    HEIGHT = BAR_H
    COMPACT_W = 1100  # abaixo disso (ex.: monitor em pé) somem NET, data e título
    TAB_W = round(BAR_FONT * 2.6)
    PAD = round(BAR_FONT * 0.9)

    def __init__(self, parent, n_ws, on_select, on_visibilidade=None, on_estado=None, solo=False,
                 pid_esperado=None):
        super().__init__(parent, bg=BAR_BG, height=self.HEIGHT, bd=0, highlightthickness=0)
        try:
            locale.setlocale(locale.LC_TIME, "")  # dia/mês no idioma do sistema
        except locale.Error:
            pass
        self.font = font.Font(family=self._family(), size=BAR_FONT)
        self.font_bold = self.font.copy()
        self.font_bold.configure(weight="bold")
        self.n_ws = n_ws
        self.on_select = on_select
        self.on_visibilidade = on_visibilidade
        self.on_estado = on_estado          # chamado com o estado do JWM a cada mudança (modo solo)
        self.solo = solo                    # janela própria: workspaces e posição vêm do jwm-state.json
        self.pid_esperado = pid_esperado    # só aceita o estado escrito por ESTE JWM (ignora arquivo velho)
        self.metrics = None
        self.job = None
        self.job_estado = None
        self.current = 0
        self.created = set()
        self.modo = ""            # modo do próprio JDesk (resize de painéis)
        self.dados = {}           # último snapshot das métricas
        self.estado = {}          # conteúdo do jwm-state.json
        self._estado_mtime = None
        self._visivel = True
        self._hover = None
        self._hits = []           # (x1, x2, nome, dado) da última renderização
        self._sig = None
        self.gato = jcat.Gato() if (jcat and os.environ.get("JGATO", "1").strip() != "0") else None
        self.escala_gato = max(2, round(BAR_FONT / 6))
        self._livre = None        # (x1, x2): o maior espaço vazio da barra, onde o gato passeia
        self._gato_box = None
        self._gato_t = time.monotonic()
        self.job_gato = None

        self.bind("<Configure>", lambda e: self._render(force=True))
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._on_click)
        self.bind("<Button-4>", lambda e: self._on_scroll(e, +1))
        self.bind("<Button-5>", lambda e: self._on_scroll(e, -1))
        self.bind("<MouseWheel>", lambda e: self._on_scroll(e, 1 if e.delta > 0 else -1))

    @staticmethod
    def _family():
        # mesma preferência de fonte do terminal
        candidatos = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono",
                      "Menlo", "Liberation Mono", "Courier New"]
        familias = set(font.families())
        return next((f for f in candidatos if f in familias), "TkFixedFont")

    # ── API ──
    def set_workspaces(self, current, created):
        self.current, self.created = current, set(created)
        self._render()

    def set_modo(self, texto):
        self.modo = texto or ""
        self._render()

    def start(self, metrics):
        self.metrics = metrics
        self.refresh()
        self.poll_estado()
        if self.gato:
            self._tick_gato()

    def stop(self):
        for attr in ("job", "job_estado", "job_gato"):
            job = getattr(self, attr)
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attr, None)

    # ── estado escrito pelo JWM ──
    def poll_estado(self):
        try:
            path = _estado_path()
            try:
                mtime = os.stat(path).st_mtime_ns
            except OSError:
                mtime = None
            if mtime != self._estado_mtime:
                self._estado_mtime = mtime
                novo = {}
                if mtime is not None:
                    try:
                        with open(path, encoding="utf-8") as f:
                            lido = json.load(f)
                        if _pid_vivo(lido.get("pid")) and self.pid_esperado in (None, lido.get("pid")):
                            novo = lido   # arquivo velho de outra sessão é ignorado
                    except (OSError, ValueError):
                        novo = {}
                self.estado = novo
                if self.solo and novo:
                    try:
                        self.n_ws = int(novo.get("n_ws", self.n_ws))
                        self.current = int(novo.get("ws", self.current + 1)) - 1   # "ws" é 1-based
                        self.created = {int(i) for i in novo.get("ws_used", ())}   # 0-based
                    except (TypeError, ValueError):
                        pass
                visivel = bool(novo.get("bar", True))
                if visivel != self._visivel:
                    self._visivel = visivel
                    if self.on_visibilidade:
                        self.on_visibilidade(visivel)
                if self.on_estado:
                    self.on_estado(novo)
                self._render()
        except tk.TclError:
            return
        self.job_estado = self.after(250, self.poll_estado)

    # ── desenho ──
    def _medir(self, segs):
        return sum(self.font_bold.measure(t) if b else self.font.measure(t) for t, _c, b in segs)

    def _capsula(self, x1, x2, y1, y2, cor):
        r = (y2 - y1) / 2
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        self.create_polygon(pts, smooth=True, fill=cor, outline="")

    def _texto(self, x, cy, segs):
        for t, cor, bold in segs:
            self.create_text(x, cy, text=t, fill=cor, font=self.font_bold if bold else self.font, anchor="w")
            x += self.font_bold.measure(t) if bold else self.font.measure(t)
        return x

    def _pilula(self, x, y1, y2, segs, bg=PILL_BG, nome=None, dado=None, hover_bg=None):
        w = self._medir(segs) + 2 * self.PAD
        if nome:
            self._hits.append((x, x + w, nome, dado))
        self._capsula(x, x + w, y1, y2, hover_bg if (hover_bg and self._hover == (nome, dado)) else bg)
        self._texto(x + self.PAD, (y1 + y2) / 2, segs)
        return w

    def _elidir(self, texto, largura):
        if largura <= 0:
            return ""
        if self.font.measure(texto) <= largura:
            return texto
        while texto and self.font.measure(texto + "…") > largura:
            texto = texto[:-1]
        return texto.rstrip() + "…" if texto else ""

    def _render(self, force=False):
        try:
            W = self.winfo_width()
        except tk.TclError:
            return
        if W <= 1:
            return
        d, est = self.dados, self.estado
        compact = W < self.COMPACT_W
        data, hora = time.strftime("%a %d %b|%H:%M").lower().split("|")
        vol, muted = d.get("vol"), d.get("muted")
        if vol is None:
            vseg = [("VOL ", DIM, False), ("--", DIM, False)]
        elif muted:
            vseg = [("VOL ", DIM, False), ("mudo", RED, False)]
        else:
            vseg = [("VOL ", DIM, False), (f"{vol}%", CYAN, False)]
        right = [("vol", vseg)]
        kbd = d.get("kbd")
        if not compact and kbd:
            kbd_seg = [("KB ", DIM, False), (kbd.upper(), YELLOW if kbd != "br" else CYAN, True)]
            right.append(("kbd", kbd_seg))
        for key, nome in (("ram", "RAM"), ("cpu", "CPU")):
            v = d.get(key)
            right.append((key, [(f"{nome} ", DIM, False),
                                (f"{barra(v)} {pct_txt(v):>4}", level_color(v), False)]))
        play = d.get("play")
        if play and W >= 1400:   # só com espaço de sobra: o relógio nunca é espremido
            texto_faixa, tocando = play
            right.insert(0, ("play", [(equalizador(time.monotonic()) if tocando else "‖ ", GREEN if tocando else DIM, False),
                                      (curto(texto_faixa, 26), FG, False)]))
        clock = ([] if compact else [(data + "  ", DIM, False)]) + [(hora, FG, True)]
        modo_wm = est.get("mode")
        split = est.get("split")
        titulo = "" if compact else (est.get("title") or "")
        sig = (W, self.n_ws, self.current, tuple(sorted(self.created)), self.modo, modo_wm, split, titulo, self._hover, d.get("kbd"),
               tuple(tuple(s) for _k, s in right), tuple(clock))
        if not force and sig == self._sig:
            return
        self._sig = sig

        self.delete("all")
        self._hits = []
        y1 = (self.HEIGHT - PILL_H) // 2
        y2 = y1 + PILL_H
        cy = (y1 + y2) / 2

        # ── esquerda: workspaces (+ modos) ──
        x = GAP
        wsw = self.n_ws * self.TAB_W + 8
        self._capsula(x, x + wsw, y1, y2, PILL_BG)
        for i in range(self.n_ws):
            tx1 = x + 4 + i * self.TAB_W
            tx2 = tx1 + self.TAB_W
            if i == self.current:
                self._capsula(tx1 + 1, tx2 - 1, y1 + 3, y2 - 3, FOCUS)
                cor = ON_ACCENT
            elif self._hover == ("tab", i):
                self._capsula(tx1 + 1, tx2 - 1, y1 + 3, y2 - 3, PILL_HOVER)
                cor = FG
            else:
                cor = FG if i in self.created else DIM
            self.create_text((tx1 + tx2) / 2, cy, text=str(i + 1), fill=cor, font=self.font_bold)
            self._hits.append((tx1, tx2, "tab", i))
        x += wsw + GAP

        if modo_wm:
            x += self._pilula(x, y1, y2, [(f" {modo_wm.upper()} ", DARK, True)], bg=MODE) + GAP
        if self.modo:
            x += self._pilula(x, y1, y2, [(f" {self.modo} ", DARK, True)], bg=YELLOW) + GAP
        if split:
            x += self._pilula(x, y1, y2, [("split ", DIM, False), (split, YELLOW, True)]) + GAP
        esquerda_fim = x

        # ── direita: métricas, da ponta para dentro ──
        x = W - GAP
        for key, segs in reversed(right):
            w = self._medir(segs) + 2 * self.PAD
            x -= w
            self._hits.append((x, x + w, key, None))
            self._capsula(x, x + w, y1, y2, PILL_HOVER if (key in ("vol", "play") and self._hover == (key, None)) else PILL_BG)
            self._texto(x + self.PAD, cy, segs)
            x -= GAP
        direita_ini = x + GAP

        # ── centro: relógio ──
        cw = self._medir(clock) + 2 * self.PAD
        cx = (W - cw) // 2
        if cx < esquerda_fim:               # sem espaço: encosta no que vem depois da esquerda
            cx = esquerda_fim
        if cx + cw <= direita_ini - GAP:
            self._capsula(cx, cx + cw, y1, y2, PILL_BG)
            self._texto(cx + self.PAD, cy, clock)
            relogio_ini = cx
        else:
            relogio_ini = direita_ini

        # ── título da janela ativa: entre os modos e o relógio ──
        if titulo:
            disp = relogio_ini - GAP - esquerda_fim - 2 * self.PAD
            txt = self._elidir(titulo, disp)
            if txt and disp > 40:
                esquerda_fim += self._pilula(esquerda_fim, y1, y2, [(txt, FG, False)]) + GAP

        # ── espaço vazio (para o gato): antes e depois do relógio; fica com o maior ──
        vazios = [(esquerda_fim + GAP, relogio_ini - GAP)]
        if relogio_ini != direita_ini:
            vazios.append((relogio_ini + cw + GAP, direita_ini - GAP))
        melhor = max(vazios, key=lambda v: v[1] - v[0])
        self._livre = melhor if melhor[1] - melhor[0] > 0 else None
        self._desenhar_gato()

    # ── gato ──
    COR_GATO = {"B": FG, "D": DIM, "E": DARK, "N": RED, "Z": CYAN, "H": RED}

    def _desenhar_gato(self):
        self.delete("gato")
        self._gato_box = None
        g = self.gato
        if not g or not g.visivel or not self._livre:
            return
        e = self.escala_gato
        base = (self.HEIGHT + PILL_H) // 2 - 3          # "chão": perto do fundo das pílulas
        topo = base - jcat.ALT * e
        x0 = int(g.x)
        for col, lin, ch in g.pixels():
            cor = self.COR_GATO.get(ch)
            if cor:
                px, py = x0 + col * e, topo + lin * e
                self.create_rectangle(px, py, px + e, py + e, fill=cor, outline="", tags="gato")
        self._gato_box = (x0, topo, x0 + jcat.LARG * e, base)

    def _tick_gato(self):
        try:
            agora = time.monotonic()
            dt, self._gato_t = agora - self._gato_t, agora
            if self._livre and self._visivel:
                tocando = bool((self.dados.get("play") or (None, False))[1])
                self.gato.passo(dt, self._livre[0], self._livre[1], self.escala_gato, tocando)
                self._desenhar_gato()
            else:
                self.delete("gato")
        except tk.TclError:
            return
        except Exception:          # enfeite: nunca derruba a barra
            pass
        self.job_gato = self.after(120, self._tick_gato)

    # ── mouse ──
    def _hit_em(self, x):
        for x1, x2, nome, dado in self._hits:
            if x1 <= x <= x2:
                return nome, dado
        return None

    def _set_hover(self, h):
        if h != self._hover:
            self._hover = h
            self.configure(cursor="hand2" if h else "")
            self._render()

    def _on_motion(self, e):
        h = self._hit_em(e.x)
        self._set_hover(h if h and h[0] in ("tab", "vol", "kbd", "play") else None)

    def _on_click(self, e):
        box = self._gato_box
        if self.gato and box and box[0] <= e.x <= box[2] and box[1] - 8 <= e.y <= box[3]:
            self.gato.carinho()                          # clicou no gato: coração
            self._desenhar_gato()
            return
        h = self._hit_em(e.x)
        if not h:
            return
        if h[0] == "tab":
            self.on_select(h[1])
        elif h[0] == "vol":
            em_thread(toggle_mute)
        elif h[0] == "kbd":
            def _trocar():
                novo = mudar_layout()
                if self.metrics:
                    self.metrics.set_kbd(novo)
            em_thread(_trocar)
        elif h[0] == "play":
            em_thread(controlar_player, "play-pause")

    def _on_scroll(self, e, direcao):
        h = self._hit_em(e.x)
        if h and h[0] == "vol":
            em_thread(adjust_volume, direcao)
        elif h and h[0] == "play":
            em_thread(controlar_player, "next" if direcao > 0 else "previous")

    # ── atualização (só lê o snapshot; nada bloqueante aqui) ──
    def refresh(self):
        try:
            self.dados = self.metrics.snapshot() if self.metrics else {}
            self._render()
        except tk.TclError:
            return
        self.job = self.after(250, self.refresh)


SOLO_CHECK_MS = 2000   # de quanto em quanto tempo confere se o JWM ainda existe


def main_solo(wm_pid=None):
    """JBar como janela própria (modo clean do JWM): sem moldura, na faixa do rodapé do monitor primário.

    override_redirect: o JWM não gerencia a janela (sem foco, sem mosaico, sem borda). Quem decide
    onde ela fica e se aparece é o JWM, pelo jwm-state.json (bar_rect e bar, este último com Super+Shift+B).
    """
    root = tk.Tk()
    root.title("JBar")
    root.configure(bg=BAR_BG)
    root.overrideredirect(True)
    try:
        root.wm_attributes("-type", "dock")   # o picom não arredonda os cantos nem põe sombra em "dock"
    except tk.TclError:
        pass
    root.withdraw()
    metrics = Metrics()
    metrics.start()
    ctl = {"rect": None, "visivel": False}

    def aplicar(est):
        rect = est.get("bar_rect")
        try:
            x, y, w, h = (int(v) for v in rect)
        except (TypeError, ValueError):
            rect = None
        if not est.get("bar", True) or rect is None:
            if ctl["visivel"]:
                root.withdraw()
                ctl["visivel"] = False
            return
        if [x, y, w, h] != ctl["rect"]:
            root.geometry(f"{w}x{h}+{x}+{y}")
            ctl["rect"] = [x, y, w, h]
        if not ctl["visivel"]:
            root.deiconify()
            root.lift()
            ctl["visivel"] = True

    barra = StatusBar(root, 4, pedir_workspace, on_estado=aplicar, solo=True, pid_esperado=wm_pid)
    barra.pack(fill=tk.BOTH, expand=True)
    barra.start(metrics)

    def sair():
        barra.stop()
        metrics.stop()
        root.destroy()

    def vigiar():
        if wm_pid is not None and not _pid_vivo(wm_pid):   # o JWM acabou: a barra não fica órfã
            sair()
            return
        root.after(SOLO_CHECK_MS, vigiar)

    root.after(SOLO_CHECK_MS, vigiar)
    root.mainloop()


if __name__ == "__main__" and "--solo" in sys.argv:
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--solo", action="store_true")
    _ap.add_argument("--wm-pid", type=int, default=None)
    main_solo(_ap.parse_args().wm_pid)
elif __name__ == "__main__":  # teste isolado da barra
    root = tk.Tk()
    root.title("JBar")
    root.geometry("900x60")
    root.configure(bg=DARK)
    m = Metrics()
    m.start()
    bar = StatusBar(root, 4, lambda i: bar.set_workspaces(i, {0, i}))
    bar.pack(fill=tk.X)
    bar.set_workspaces(0, {0})
    bar.start(m)
    root.mainloop()
