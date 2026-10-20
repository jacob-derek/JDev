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

# Tokyo Night
BAR_BG = "#16161e"
FG = "#a9b1d6"
DIM = "#565f89"
BLUE = "#7aa2f7"
GREEN = "#9ece6a"
YELLOW = "#e0af68"
RED = "#f7768e"
CYAN = "#7dcfff"
DARK = "#1a1b26"

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


# ── Barra ────────────────────────────────────────────────────────────────────
class StatusBar(tk.Frame):
    HEIGHT = 26

    def __init__(self, parent, n_ws, on_select):
        super().__init__(parent, bg=BAR_BG, height=self.HEIGHT, bd=0, highlightthickness=0)
        self.pack_propagate(False)
        try:
            locale.setlocale(locale.LC_TIME, "")  # dia/mês no idioma do sistema
        except locale.Error:
            pass
        self.font = font.Font(family=self._family(), size=10)
        self.font_bold = self.font.copy()
        self.font_bold.configure(weight="bold")
        self.metrics = None
        self.job = None

        # workspaces (esquerda)
        left = tk.Frame(self, bg=BAR_BG)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        self.tabs = []
        for i in range(n_ws):
            lb = tk.Label(left, text=f" {i + 1} ", bg=BAR_BG, fg=DIM, font=self.font, bd=0, cursor="hand2")
            lb.pack(side=tk.LEFT, fill=tk.Y, padx=1)
            lb.bind("<Button-1>", lambda e, i=i: on_select(i))
            self.tabs.append(lb)

        # indicador de modo (estilo "mode resize" do sway): aparece só quando há um modo ativo
        self.modo_lb = tk.Label(left, text="", bg=YELLOW, fg=DARK, font=self.font_bold, bd=0)

        # métricas (direita)
        right = tk.Frame(self, bg=BAR_BG)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8))
        self.lb = {}
        for key in ("vol", "ram", "net", "cpu"):
            lb = tk.Label(right, text="", bg=BAR_BG, fg=DIM, font=self.font, bd=0)
            lb.pack(side=tk.LEFT, padx=7)
            self.lb[key] = lb

        # O scroll só altera o volume quando o ponteiro está sobre VOL.
        self.lb["vol"].configure(cursor="hand2")
        self.lb["vol"].bind("<Button-4>", lambda e: self._volume_scroll(+1))
        self.lb["vol"].bind("<Button-5>", lambda e: self._volume_scroll(-1))
        self.lb["vol"].bind("<MouseWheel>", self._volume_mousewheel)
        self.lb["vol"].bind("<Button-1>", lambda e: (em_thread(toggle_mute), "break")[1])  # clique = mudo

        # relógio (centro de verdade, independente da largura dos lados)
        self.clock = tk.Label(self, text="", bg=BAR_BG, fg=FG, font=self.font_bold, bd=0)
        self.clock.place(relx=0.5, rely=0.5, anchor="center")

    @staticmethod
    def _family():
        # mesma preferência de fonte do terminal
        candidatos = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono",
                      "Menlo", "Liberation Mono", "Courier New"]
        familias = set(font.families())
        return next((f for f in candidatos if f in familias), "TkFixedFont")

    # ── API ──
    def set_workspaces(self, current, created):
        for i, lb in enumerate(self.tabs):
            if i == current:
                lb.configure(bg=BLUE, fg=DARK, font=self.font_bold)
            elif i in created:
                lb.configure(bg=BAR_BG, fg=FG, font=self.font)
            else:
                lb.configure(bg=BAR_BG, fg=DIM, font=self.font)

    def set_modo(self, texto):
        if texto:
            self.modo_lb.configure(text=f" {texto} ")
            self.modo_lb.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))
        else:
            self.modo_lb.pack_forget()

    def start(self, metrics):
        self.metrics = metrics
        self.refresh()

    def stop(self):
        if self.job:
            try:
                self.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def _volume_scroll(self, direction):
        em_thread(adjust_volume, direction)
        return "break"

    def _volume_mousewheel(self, event):
        if event.delta == 0:
            return "break"
        return self._volume_scroll(+1 if event.delta > 0 else -1)

    # ── atualização (só lê o snapshot; nada bloqueante aqui) ──
    def refresh(self):
        try:
            self.clock.configure(text=time.strftime("%a %d %b  %H:%M").lower())
            d = self.metrics.snapshot() if self.metrics else {}

            vol, muted = d.get("vol"), d.get("muted")
            if vol is None:
                self.lb["vol"].configure(text="VOL --", fg=DIM)
            elif muted:
                self.lb["vol"].configure(text="VOL mudo", fg=RED)
            else:
                self.lb["vol"].configure(text=f"VOL {vol}%", fg=CYAN)

            ram, cpu = d.get("ram"), d.get("cpu")
            self.lb["ram"].configure(text="RAM --" if ram is None else f"RAM {ram:.0f}%",
                                     fg=level_color(ram))
            self.lb["cpu"].configure(text="CPU --" if cpu is None else f"CPU {cpu:.0f}%",
                                     fg=level_color(cpu))
            down, up = d.get("down"), d.get("up")
            self.lb["net"].configure(text=f"NET ↓{fmt_rate(down):>5} ↑{fmt_rate(up):>5}",
                                     fg=FG if down is not None else DIM)
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
