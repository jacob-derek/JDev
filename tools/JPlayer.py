#!/usr/bin/env python3
"""JPlayer - player de musica 100% terminal, com capa do album.

Uso:  JPlayer.py [pasta]     (padrao: /mnt/sd se existir, senao a pasta atual)
      JPlayer.py --256 ...   (se as cores da capa ficarem estranhas)

Teclas:
  espaco  pausa / continua        n / p   proxima / anterior
  <- / -> volta / avanca 5s       cima / baixo   navegar na fila
  enter   toca a selecionada      + / -   volume
  s       aleatorio               q       sair

Dependencias (Void):  sudo xbps-install -S python3-pygame python3-Pillow
"""
import io
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

AUDIO_EXT = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
COVER_NAMES = ("cover", "folder", "front", "album", "artwork")
MAX_IMAGE = 30 * 1024 * 1024

ESC = "\x1b"
RESET = ESC + "[0m"
BOLD = ESC + "[1m"
REV = ESC + "[7m"


def c256(n):
    return f"{ESC}[38;5;{n}m"


GREEN = c256(71)    # #5faf5f, o verde do seu tema
DIM = c256(242)
LINE = c256(238)
TEXT = c256(252)
RED = c256(167)

UP = ("\x1b[A", "\x1bOA", "k")
DOWN = ("\x1b[B", "\x1bOB", "j")
RIGHT = ("\x1b[C", "\x1bOC")
LEFT = ("\x1b[D", "\x1bOD")
PGUP = ("\x1b[5~",)
PGDN = ("\x1b[6~",)
HOME = ("\x1b[H", "\x1b[1~", "\x1bOH")
END = ("\x1b[F", "\x1b[4~", "\x1bOF")
KEY_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z~]|\x1bO[A-Za-z]|\x1b|.", re.S)


# ---------------------------------------------------------------- utilidades
def natural(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(text))]


def fmt(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def clip(text, width):
    if width <= 0:
        return ""
    return text if len(text) <= width else text[:max(0, width - 1)] + "…"


def scan(folder):
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in files:
            if name.startswith("."):
                continue
            path = Path(root) / name
            if path.suffix.lower() in AUDIO_EXT:
                found.append(path)
    found.sort(key=lambda p: natural(p.relative_to(folder)))
    return found


def make_label(path, root):
    return path.stem if path.parent == root else f"{path.parent.name} · {path.stem}"


# ------------------------------------------------- capa: leitura dos arquivos
def syncsafe(b):
    return ((b[0] & 0x7F) << 21) | ((b[1] & 0x7F) << 14) | ((b[2] & 0x7F) << 7) | (b[3] & 0x7F)


def parse_apic(body, v22):
    if not body:
        return None
    enc = body[0]
    if v22:
        pos = 4
    else:
        end = body.find(b"\x00", 1)
        if end < 0:
            return None
        pos = end + 1
    pos += 1  # tipo da imagem
    if enc in (1, 2):  # descricao em UTF-16
        while pos + 1 < len(body) and body[pos:pos + 2] != b"\x00\x00":
            pos += 2
        pos += 2
    else:
        end = body.find(b"\x00", pos)
        pos = end + 1 if end >= 0 else len(body)
    return body[pos:] or None


def id3_cover(f):
    head = f.read(10)
    if len(head) < 10 or head[:3] != b"ID3":
        return None
    ver, flags = head[3], head[5]
    data = f.read(syncsafe(head[6:10]))
    if ver < 4 and flags & 0x80:
        data = data.replace(b"\xff\x00", b"\xff")
    pos = 0
    if flags & 0x40 and len(data) >= 4:  # cabecalho estendido
        pos = syncsafe(data[:4]) if ver == 4 else int.from_bytes(data[:4], "big") + 4
    hdr = 6 if ver == 2 else 10
    while pos + hdr <= len(data):
        if ver == 2:
            fid = data[pos:pos + 3]
            size = int.from_bytes(data[pos + 3:pos + 6], "big")
            fflags = b"\x00\x00"
        else:
            fid = data[pos:pos + 4]
            raw = data[pos + 4:pos + 8]
            size = syncsafe(raw) if ver == 4 else int.from_bytes(raw, "big")
            fflags = data[pos + 8:pos + 10]
        if not fid.strip(b"\x00"):
            break
        body = data[pos + hdr:pos + hdr + size]
        if fid in (b"APIC", b"PIC"):
            if ver == 4:
                if fflags[1] & 0x01:
                    body = body[4:]
                if fflags[1] & 0x02:
                    body = body.replace(b"\xff\x00", b"\xff")
            img = parse_apic(body, ver == 2)
            if img:
                return img
        pos += hdr + size
    return None


def flac_cover(f):
    if f.read(4) != b"fLaC":
        return None
    while True:
        h = f.read(4)
        if len(h) < 4:
            return None
        last, typ = h[0] & 0x80, h[0] & 0x7F
        length = int.from_bytes(h[1:4], "big")
        if typ == 6:
            b = f.read(length)
            i = 4
            i += 4 + int.from_bytes(b[i:i + 4], "big")      # mime
            i += 4 + int.from_bytes(b[i:i + 4], "big")      # descricao
            i += 16                                          # largura/altura/prof./cores
            n = int.from_bytes(b[i:i + 4], "big")
            return b[i + 4:i + 4 + n] or None
        f.seek(length, 1)
        if last:
            return None


def mp4_cover(f):
    f.seek(0, 2)
    end = f.tell()

    def find(start, stop, name):
        pos = start
        while pos + 8 <= stop:
            f.seek(pos)
            h = f.read(8)
            size = int.from_bytes(h[:4], "big")
            hdr = 8
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
                hdr = 16
            elif size == 0:
                size = stop - pos
            if size < hdr:
                return None
            if h[4:8] == name:
                return pos + hdr, pos + size
            pos += size
        return None

    loc = (0, end)
    for name in (b"moov", b"udta", b"meta"):
        loc = find(loc[0], loc[1], name)
        if not loc:
            return None
    loc = (loc[0] + 4, loc[1])  # 'meta' tem 4 bytes de versao/flags
    for name in (b"ilst", b"covr", b"data"):
        loc = find(loc[0], loc[1], name)
        if not loc:
            return None
    f.seek(loc[0] + 8)
    return f.read(loc[1] - loc[0] - 8) or None


def embedded_cover(path):
    try:
        with open(path, "rb") as f:
            magic = f.read(12)
            f.seek(0)
            if magic[:3] == b"ID3":
                data = id3_cover(f)
            elif magic[:4] == b"fLaC":
                data = flac_cover(f)
            elif magic[4:8] == b"ftyp":
                data = mp4_cover(f)
            else:
                data = None
        if data and len(data) <= MAX_IMAGE:
            return data
    except Exception:
        pass
    return None


def folder_cover(path):
    try:
        files = [f for f in path.parent.iterdir()
                 if f.is_file() and f.suffix.lower() in IMAGE_EXT and not f.name.startswith(".")]
    except OSError:
        return None
    if not files:
        return None
    named = {f.stem.lower(): f for f in files}
    pick = next((named[n] for n in COVER_NAMES if n in named), None)
    if pick is None:  # ex.: AlbumArt_{GUID}_Large.jpg do Windows Media Player
        pick = max(files, key=lambda f: f.stat().st_size)
    try:
        if pick.stat().st_size <= MAX_IMAGE:
            return pick.read_bytes()
    except OSError:
        pass
    return None


def find_cover(path):
    return embedded_cover(path) or folder_cover(path)


# ------------------------------------------------ capa: desenho no terminal
def to256(p):
    r, g, b = p
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def build_cover(data, cols, truecolor):
    """Cada celula usa o meio-bloco '▀': cor de frente = pixel de cima, fundo = pixel de baixo."""
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    img = img.crop((left, top, left + s, top + s)).resize((cols, cols), resample)
    px = img.load()
    lines = []
    for r in range(cols // 2):
        parts, last = [], None
        for c in range(cols):
            a, b = px[c, 2 * r], px[c, 2 * r + 1]
            if truecolor:
                code = f"{ESC}[38;2;{a[0]};{a[1]};{a[2]};48;2;{b[0]};{b[1]};{b[2]}m"
            else:
                code = f"{ESC}[38;5;{to256(a)};48;5;{to256(b)}m"
            if code != last:
                parts.append(code)
                last = code
            parts.append("▀")
        parts.append(RESET)
        lines.append("".join(parts))
    return lines


def placeholder(cols, text):
    rows = cols // 2
    lines = []
    for r in range(rows):
        body = text.center(cols) if r == rows // 2 else " " * cols
        lines.append(f"{ESC}[48;5;235m{c256(242)}{body}{RESET}")
    return lines


# --------------------------------------------------------------- pygame audio
class PygameAudio:
    """Backend de áudio SDL/Pygame; não depende do mpv nem de socket IPC."""
    def __init__(self, volume=80):
        try:
            import pygame
        except ImportError:
            raise SystemExit("pygame nao encontrado. Instale: sudo xbps-install -S python3-pygame")
        self.pygame = pygame
        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(max(0, min(1, volume / 100)))
        except Exception as exc:
            raise SystemExit(f"pygame nao conseguiu abrir a saida de audio: {exc}")
        self.volume = volume
        self.paused = False
        self.started_at = 0.0
        self.offset = 0.0
        self.duration = 0.0
        self.current = None
        self.was_busy = False

    def load_and_play(self, path):
        try:
            self.pygame.mixer.music.load(str(path))
            self.pygame.mixer.music.play()
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        self.current = str(path)
        self.offset = 0.0
        self.started_at = time.monotonic()
        self.paused = False
        self.was_busy = True
        self.duration = 0.0
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(str(path))
            if audio and audio.info:
                self.duration = float(audio.info.length)
        except Exception:
            pass

    def position(self):
        if self.paused:
            return self.offset
        if self.current and self.pygame.mixer.music.get_busy():
            return self.offset + max(0, time.monotonic() - self.started_at)
        return self.offset

    def pause_toggle(self):
        if not self.current:
            return
        if self.paused:
            self.pygame.mixer.music.unpause()
            self.started_at = time.monotonic()
            self.paused = False
        else:
            self.offset = self.position()
            self.pygame.mixer.music.pause()
            self.paused = True

    def seek(self, seconds):
        if not self.current:
            return
        target = max(0.0, self.position() + seconds)
        if self.duration:
            target = min(target, self.duration)
        try:
            self.pygame.mixer.music.set_pos(target)
            self.offset = target
            self.started_at = time.monotonic()
        except Exception:
            # Alguns formatos/compilações do SDL não permitem seek; mantém a reprodução.
            pass

    def set_volume(self, volume):
        self.volume = max(0, min(130, int(volume)))
        self.pygame.mixer.music.set_volume(min(1.0, self.volume / 100))

    def close(self):
        try:
            self.pygame.mixer.music.stop()
            self.pygame.mixer.quit()
        except Exception:
            pass


# ------------------------------------------------------------------- app
class App:
    def __init__(self, folder, truecolor):
        self.root = Path(folder)
        self.queue = scan(self.root)
        self.labels = [make_label(p, self.root) for p in self.queue]
        self.truecolor = truecolor
        self.index = -1
        self.sel = 0
        self.scroll = 0
        self.pos = 0.0
        self.dur = 0.0
        self.paused = False
        self.volume = 80
        self.shuffle = False
        self.title = self.artist = self.album = ""
        self.cover_data = None
        self.cover_hash = None
        self.cache = {}
        self.notice = ""
        self.notice_until = 0.0
        self.errors = 0
        self.last_sec = -1
        self.resized = False
        self.fatal = ""
        self.need = set()
        self.audio = PygameAudio(self.volume)
        if Image is None:
            self.say("sem capa: instale python3-Pillow", 3600)
        elif not self.queue:
            self.say(f"nenhuma musica encontrada em {self.root}", 3600)

    # ---- estado
    def say(self, text, seconds=6):
        self.notice = text
        self.notice_until = time.time() + seconds
        self.need.add("info")

    def play(self, i):
        if not 0 <= i < len(self.queue):
            return
        path = self.queue[i]
        self.index = self.sel = i
        self.pos = self.dur = 0.0
        self.last_sec = -1
        self.paused = False
        self.title, self.artist, self.album = path.stem, "", ""
        self.cover_data = find_cover(path)
        self.cover_hash = hash(self.cover_data) if self.cover_data else None
        try:
            self.audio.load_and_play(path)
            self.dur = self.audio.duration
        except Exception as exc:
            self.say(f"pygame nao conseguiu tocar {path.name}: {exc}", 12)
            return
        self.ensure_visible()
        self.need.add("all")

    def advance(self, step=1):
        n = len(self.queue)
        if not n:
            return
        if self.shuffle and step > 0 and n > 1:
            i = random.choice([k for k in range(n) if k != self.index])
        else:
            i = (self.index + step) % n if self.index >= 0 else 0
        self.play(i)

    def previous(self):
        if self.index >= 0 and self.pos > 3:
            self.audio.seek(-self.pos)
        else:
            self.advance(-1)

    def seek(self, delta):
        if self.index >= 0:
            self.audio.seek(delta)

    def set_volume(self, delta):
        self.volume = int(max(0, min(130, round(self.volume + delta))))
        self.audio.set_volume(self.volume)
        self.need.add("info")

    def move(self, delta):
        if self.queue:
            self.sel = max(0, min(len(self.queue) - 1, self.sel + delta))
            self.ensure_visible()
            self.need.add("queue")

    def ensure_visible(self):
        qrows = max(1, shutil.get_terminal_size((80, 24)).lines - 11)
        if self.sel < self.scroll:
            self.scroll = self.sel
        elif self.sel >= self.scroll + qrows:
            self.scroll = self.sel - qrows + 1
        self.scroll = max(0, self.scroll)

    # ---- eventos
    def on_event(self, ev):
        kind = ev.get("event")
        if kind == "property-change":
            name, data = ev.get("name"), ev.get("data")
            if name == "time-pos":
                if isinstance(data, (int, float)):
                    self.pos = float(data)
                    if int(self.pos) != self.last_sec:
                        self.last_sec = int(self.pos)
                        self.need.add("progress")
            elif name == "duration":
                self.dur = float(data) if isinstance(data, (int, float)) else 0.0
                self.need.add("progress")
            elif name == "pause":
                self.paused = bool(data)
                self.need.add("info")
            elif name == "volume":
                if isinstance(data, (int, float)):
                    self.volume = int(round(data))
                    self.need.add("info")
            elif name == "metadata" and isinstance(data, dict) and self.index >= 0:
                tags = {str(k).lower(): str(v) for k, v in data.items()}
                self.title = tags.get("title") or self.queue[self.index].stem
                self.artist = tags.get("artist") or tags.get("album_artist") or ""
                self.album = tags.get("album") or ""
                self.need.add("info")
        elif kind == "end-file":
            reason = ev.get("reason")
            if reason == "eof":
                self.errors = 0
                self.advance(1)
            elif reason == "error":
                self.errors += 1
                bad = self.queue[self.index].name if self.index >= 0 else "?"
                self.say(f"erro ao tocar: {bad}")
                if self.errors < len(self.queue):
                    self.advance(1)

    def on_key(self, k):
        if k in ("q", "Q"):
            return False
        if k == " ":
            if self.index < 0:
                self.play(self.sel)
            else:
                self.audio.pause_toggle()
                self.paused = self.audio.paused
                self.need.add("info")
        elif k in ("\r", "\n"):
            self.play(self.sel)
        elif k in ("n", "N"):
            self.advance(1)
        elif k in ("p", "P"):
            self.previous()
        elif k in RIGHT:
            self.seek(5)
        elif k in LEFT:
            self.seek(-5)
        elif k in UP:
            self.move(-1)
        elif k in DOWN:
            self.move(1)
        elif k in PGUP:
            self.move(-10)
        elif k in PGDN:
            self.move(10)
        elif k in HOME:
            self.move(-10 ** 6)
        elif k in END:
            self.move(10 ** 6)
        elif k in ("+", "="):
            self.set_volume(5)
        elif k in ("-", "_"):
            self.set_volume(-5)
        elif k in ("s", "S"):
            self.shuffle = not self.shuffle
            self.need.add("info")
        return True

    # ---- desenho
    def layout(self, W, H):
        cover = min((W - 6) // 2, 2 * (H - 5), 44)
        cover -= cover % 2
        if cover < 16:
            cover = 0
        x0 = 2 + (cover + 3 if cover else 0)
        return {"W": W, "H": H, "cover": cover, "x0": x0,
                "rw": max(10, W - x0 - 1), "qrows": max(0, H - 11)}

    def cover_lines(self, cols):
        key = (self.cover_hash, cols, self.truecolor, Image is not None)
        if key not in self.cache:
            lines = None
            if self.cover_data and Image is not None:
                try:
                    lines = build_cover(self.cover_data, cols, self.truecolor)
                except Exception:
                    lines = None
            if lines is None:
                msg = "sem Pillow" if (self.cover_data and Image is None) else "sem capa"
                lines = placeholder(cols, msg)
            if len(self.cache) > 12:
                self.cache.clear()
            self.cache[key] = lines
        return self.cache[key]

    def part_header(self, L):
        W = L["W"]
        path = str(self.root)
        path = clip(path, W - 14) if len(path) <= W - 14 else "…" + path[-(W - 15):]
        return (f"{ESC}[1;1H{ESC}[2K{ESC}[1;2H{GREEN}{BOLD}JPLAYER{RESET}"
                f"{ESC}[1;{max(10, W - len(path))}H{DIM}{path}{RESET}"
                f"{ESC}[2;1H{ESC}[2K{ESC}[2;2H{LINE}{'─' * (W - 2)}{RESET}")

    def part_cover(self, L):
        if not L["cover"]:
            return ""
        return "".join(f"{ESC}[{3 + i};2H{line}" for i, line in enumerate(self.cover_lines(L["cover"])))

    def part_info(self, L):
        x0, rw = L["x0"], L["rw"]
        if self.index >= 0:
            title, artist, album = self.title, self.artist, self.album
        else:
            title, artist, album = "Nada tocando", "enter ou espaço para tocar", ""
        if self.index < 0:
            state = "■ parado"
        else:
            state = "⏸ pausado" if self.paused else "▶ tocando"
        status = f"{state}   vol {self.volume}%   aleatório {'on' if self.shuffle else 'off'}"
        notice = self.notice if time.time() < self.notice_until else ""
        return (f"{ESC}[3;{x0}H{BOLD}{TEXT}{clip(title, rw)}{RESET}{ESC}[K"
                f"{ESC}[4;{x0}H{DIM}{clip(artist, rw)}{RESET}{ESC}[K"
                f"{ESC}[5;{x0}H{DIM}{clip(album, rw)}{RESET}{ESC}[K"
                f"{ESC}[6;{x0}H{ESC}[K"
                f"{ESC}[8;{x0}H{GREEN}{clip(status, rw)}{RESET}{ESC}[K"
                f"{ESC}[9;{x0}H{RED}{clip(notice, rw)}{RESET}{ESC}[K")

    def part_progress(self, L):
        x0, rw = L["x0"], L["rw"]
        cur, tot = fmt(self.pos), fmt(self.dur)
        bar_w = max(8, rw - len(cur) - len(tot) - 2)
        filled = int(bar_w * min(1.0, self.pos / self.dur)) if self.dur > 0 else 0
        return (f"{ESC}[7;{x0}H{DIM}{cur}{RESET} {GREEN}{'━' * filled}{LINE}{'━' * (bar_w - filled)}"
                f"{RESET} {DIM}{tot}{RESET}{ESC}[K")

    def part_queue(self, L):
        x0, rw = L["x0"], L["rw"]
        out = [f"{ESC}[10;{x0}H{DIM}FILA · {len(self.queue)} faixa(s){RESET}{ESC}[K"]
        for i in range(L["qrows"]):
            row, idx = 11 + i, self.scroll + i
            if idx < len(self.queue):
                text = clip(("▶ " if idx == self.index else "  ") + self.labels[idx], rw).ljust(rw)
                style = (GREEN if idx == self.index else TEXT) + (REV if idx == self.sel else "")
                out.append(f"{ESC}[{row};{x0}H{style}{text}{RESET}")
            else:
                out.append(f"{ESC}[{row};{x0}H{ESC}[K")
        return "".join(out)

    def part_footer(self, L):
        W, H = L["W"], L["H"]
        help_text = ("espaço pausa · n/p faixa · ←/→ ±5s · ↑/↓ fila · enter toca · "
                     "+/- volume · s aleatório · q sai")
        return f"{ESC}[{H};1H{ESC}[2K{ESC}[{H};2H{DIM}{clip(help_text, W - 2)}{RESET}"

    def render(self):
        if not self.need:
            return
        W, H = shutil.get_terminal_size((80, 24))
        need, self.need = self.need, set()
        if W < 44 or H < 12:
            os.write(1, f"{ESC}[2J{ESC}[1;1Hterminal pequeno demais ({W}x{H})".encode())
            return
        L = self.layout(W, H)
        out = []
        if "all" in need:
            out.append(f"{RESET}{ESC}[2J")
            need = {"header", "cover", "info", "progress", "queue", "footer"}
        for name in ("header", "cover", "info", "progress", "queue", "footer"):
            if name in need:
                out.append(getattr(self, "part_" + name)(L))
        os.write(1, "".join(out).encode())

    # ---- laco principal
    def run(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        signal.signal(signal.SIGWINCH, lambda *a: setattr(self, "resized", True))
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
        tty.setcbreak(fd)
        os.write(1, f"{ESC}[?1049h{ESC}[?25l{ESC}[?7l".encode())
        try:
            self.need.add("all")
            if self.queue:
                self.play(0)
            while True:
                if self.resized:
                    self.resized = False
                    self.ensure_visible()
                    self.need.add("all")
                if self.notice and time.time() >= self.notice_until:
                    self.notice = ""
                    self.need.add("info")
                self.render()
                # Atualiza posição e detecta fim da faixa sem IPC/socket.
                self.pos = self.audio.position()
                self.dur = self.audio.duration
                if int(self.pos) != self.last_sec:
                    self.last_sec = int(self.pos)
                    self.need.add("progress")
                busy = self.audio.pygame.mixer.music.get_busy()
                if self.index >= 0 and self.audio.was_busy and not busy and not self.audio.paused:
                    self.audio.was_busy = False
                    self.errors = 0
                    self.advance(1)
                ready, _, _ = select.select([fd], [], [], 0.20)
                if fd in ready:
                    raw = os.read(fd, 64)
                    if not raw:
                        break
                    for key in KEY_RE.findall(raw.decode("utf-8", "ignore")):
                        if self.on_key(key) is False:
                            return
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            os.write(1, f"{RESET}{ESC}[?7h{ESC}[?25h{ESC}[?1049l".encode())
            self.audio.close()
            if self.fatal:
                print(self.fatal)


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("JPlayer precisa rodar num terminal de verdade (stdin/stdout precisam ser um tty).")
    folders = [a for a in args if not a.startswith("--")]
    if folders:
        folder = Path(folders[0]).expanduser()
    elif Path("/mnt/sd").is_dir() and any(Path("/mnt/sd").iterdir()):
        folder = Path("/mnt/sd")
    else:
        folder = Path.cwd()
    if not folder.is_dir():
        sys.exit(f"pasta nao encontrada: {folder}")
    folder = folder.resolve()
    force = os.environ.get("JPLAYER_COLOR", "").lower()
    truecolor = not ("--256" in args or force == "256" or os.environ.get("TERM") in ("linux", "dumb"))
    app = App(folder, truecolor)
    try:
        app.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
