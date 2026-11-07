#!/usr/bin/env python3
"""
JBar - barra superior do JDesk (Fase 2).

  [ 1 2 3 4 ]            [ qui 15 out  14:32 ]            [ VOL 65%  RAM 42%  NET ↓ 1.2M ↑ 30K  CPU 12% ]

- As métricas são coletadas numa thread (nada de subprocess ou I/O na thread da UI).
- psutil é opcional: sem ele, CPU/RAM/rede aparecem como "--" (o volume e o relógio seguem).
- Volume: pactl/amixer (Linux), pycaw (Windows), osascript (macOS). Se nada estiver
  disponível, mostra "--" sem reclamar.

Roda sozinho para teste:  python JBar.py
"""
import json
import locale
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
    BAR_H, PILL_H, GAP = 36, 28, 8
    DESK_BG, PILL_BG, PILL_HOVER, LINE = "#13141c", "#1f2335", "#2a2f45", "#292e42"
    FG, DIM, DARK, ON_ACCENT = "#a9b1d6", "#565f89", "#16161e", "#fbe9ef"
    FOCUS, MODE = "#b04a67", "#9ece6a"
    GREEN, BLUE, CYAN, RED, YELLOW = "#9ece6a", "#7aa2f7", "#7dcfff", "#f7768e", "#e0af68"
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


def brilho(delta):
    """Brilho da tela +5% / -5% (brightnessctl, como no sway antigo). Sem ele, não faz nada."""
    if shutil.which("brightnessctl"):
        try:
            subprocess.run(["brightnessctl", "set", "5%+" if delta > 0 else "5%-"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def em_thread(fn, *args):
    """Roda fn fora da thread da interface (pactl pode demorar e congelaria o Tk)."""
    threading.Thread(target=fn, args=args, daemon=True).start()


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
                     "vol": None, "muted": False}

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def stop(self):
        self.stop_ev.set()

    def snapshot(self):
        with self.lock:
            return dict(self.data)

    def _run_loop(self):
        try:
            import psutil
        except ImportError:
            psutil = None
        readers = make_volume_readers()  # na própria thread (COM no Windows)
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
    TAB_W = 26
    PAD = 10

    def __init__(self, parent, n_ws, on_select, on_visibilidade=None):
        super().__init__(parent, bg=BAR_BG, height=self.HEIGHT, bd=0, highlightthickness=0)
        try:
            locale.setlocale(locale.LC_TIME, "")  # dia/mês no idioma do sistema
        except locale.Error:
            pass
        self.font = font.Font(family=self._family(), size=10)
        self.font_bold = self.font.copy()
        self.font_bold.configure(weight="bold")
        self.n_ws = n_ws
        self.on_select = on_select
        self.on_visibilidade = on_visibilidade
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

    def stop(self):
        for attr in ("job", "job_estado"):
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
                        if _pid_vivo(lido.get("pid")):   # arquivo velho de outra sessão é ignorado
                            novo = lido
                    except (OSError, ValueError):
                        novo = {}
                self.estado = novo
                visivel = bool(novo.get("bar", True))
                if visivel != self._visivel:
                    self._visivel = visivel
                    if self.on_visibilidade:
                        self.on_visibilidade(visivel)
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
        for key, nome in (("ram", "RAM"), ("net", "NET"), ("cpu", "CPU")):
            if key == "net":
                if compact:
                    continue
                dn, up = d.get("down"), d.get("up")
                right.append((key, [("NET ", DIM, False),
                                    (f"↓{fmt_rate(dn):>5}", GREEN if dn is not None else DIM, False),
                                    (" ", DIM, False),
                                    (f"↑{fmt_rate(up):>5}", BLUE if up is not None else DIM, False)]))
            else:
                v = d.get(key)
                right.append((key, [(f"{nome} ", DIM, False),
                                    (f"{barra(v)} {pct_txt(v):>4}", level_color(v), False)]))
        clock = ([] if compact else [(data + "  ", DIM, False)]) + [(hora, FG, True)]
        modo_wm = est.get("mode")
        split = est.get("split")
        titulo = "" if compact else (est.get("title") or "")
        sig = (W, self.current, tuple(sorted(self.created)), self.modo, modo_wm, split, titulo, self._hover,
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
            self._capsula(x, x + w, y1, y2, PILL_HOVER if (key == "vol" and self._hover == ("vol", None)) else PILL_BG)
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
                self._pilula(esquerda_fim, y1, y2, [(txt, FG, False)])

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
        self._set_hover(h if h and h[0] in ("tab", "vol") else None)

    def _on_click(self, e):
        h = self._hit_em(e.x)
        if not h:
            return
        if h[0] == "tab":
            self.on_select(h[1])
        elif h[0] == "vol":
            em_thread(toggle_mute)

    def _on_scroll(self, e, direcao):
        h = self._hit_em(e.x)
        if h and h[0] == "vol":
            em_thread(adjust_volume, direcao)

    # ── atualização (só lê o snapshot; nada bloqueante aqui) ──
    def refresh(self):
        try:
            self.dados = self.metrics.snapshot() if self.metrics else {}
            self._render()
        except tk.TclError:
            return
        self.job = self.after(1000, self.refresh)


if __name__ == "__main__":  # teste isolado da barra
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
