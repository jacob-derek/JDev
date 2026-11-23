#!/usr/bin/env python3
"""jrelogio - relógio selva: um tucano fofo espera enquanto a areia da ampulheta cai (1 volta por minuto).

    python3 jrelogio.py               janela normal (o JWM trata como qualquer janela)
    python3 jrelogio.py --rapido      a ampulheta vira a cada 10 s (para ver a animação sem esperar)
    python3 jrelogio.py --ciclo 5m    a ampulheta vira a cada 5 min (aceita 90, 45s, 5m, 1h30m, 1:30)
    python3 jrelogio.py --timer 25m   conta de agora até 25 min, mostra o tempo que falta e avisa (JToast) no fim
    python3 jrelogio.py --sem-borda --pos 40,40     janelinha sem moldura (override-redirect) numa posição
    JRELOGIO_ESCALA=6 muda o tamanho (padrão 5)

Tudo é desenhado com quadradinhos (pixel art) a partir de funções puras, então dá para testar sem tela.
A ampulheta vira de cabeça para baixo no segundo 0; o tucano pisca, respira, e dorme à noite (21h às 6h).
"""
from __future__ import annotations

import math
import os
import random
import sys
import time

W, H = 52, 64                      # tamanho da cena em "pixels lógicos"
CX = 19                            # eixo da ampulheta
TOPO0, TOPO1 = 12, 24              # bulbo de cima (linhas)
PESCOCO = 25
BASE0, BASE1 = 26, 38              # bulbo de baixo
NLIN = TOPO1 - TOPO0 + 1           # 13 linhas de areia em cada bulbo
FLIP_S = 0.8                       # duração da virada

CORES = {
    "bg": "#f4f9e9", "pill": "#e2efc9", "texto": "#3b5d3a",
    "f1": "#6fbf5a", "f2": "#3f9a4a", "f3": "#a5d96b", "vine": "#4f9f55",
    "madeira": "#a8723b", "madeira2": "#7d5128",
    "vidro": "#b9e3f2", "borda": "#7fc4de", "areia": "#f2c14e", "areia2": "#e0a232",
    "K": "#2b2b33", "W": "#fbf7ee", "Y": "#ffd23f", "O": "#ff8c2a", "R": "#e0443a",
    "B": "#4aa8d8", "P": "#15151a", "F": "#f08a24", "zz": "#7fa9c9",
}

# ── tucano 16x15, olhando para a esquerda (para a ampulheta) ──────────────────
TUCANO = [
    "......KKKK......",
    ".....KKKKKK.....",
    "..YYYYKKKKKK....",
    ".YYYYYYBPKKK....",
    "YYYYYYYYBKKKK...",
    "OOOOOOYWWKKKKK..",
    ".ROOOOWWWWKKKK..",
    "..RO..WWWWKKKKK.",
    "......WWWWKKKKK.",
    ".......WWKKKKK..",
    ".......KKKKKKK..",
    "........KKKKK..K",
    ".........KKKK.KK",
    "........F..F..K.",
    "........FF.FF...",
]
TUC_X, TUC_Y = 34, 26              # canto do sprite (pés ficam em y=39..40, em cima do galho)

# ── fonte 5x7 dos dígitos ─────────────────────────────────────────────────────
DIGITOS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["0", "0", "1", "0", "1", "0", "0"],
}


# ── lógica pura ───────────────────────────────────────────────────────────────
def eh_noite(hora: int) -> bool:
    return hora >= 21 or hora < 6


def parse_duracao(texto: str) -> float:
    """'90' → 90 s; '45s', '5m', '1h30m', '1:30' (= 1 min 30 s; '1:02:03' = 1 h 2 min 3 s) → segundos."""
    t = (texto or "").strip().lower().replace(" ", "")
    if not t:
        raise ValueError("duração vazia")
    if ":" in t:
        partes = [int(p) for p in t.split(":")]
        if len(partes) > 3 or any(p < 0 for p in partes):
            raise ValueError(texto)
        seg = 0
        for p in partes:
            seg = seg * 60 + p
        return float(seg)
    total, num = 0.0, ""
    for ch in t:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "hms" and num:
            total += float(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
        else:
            raise ValueError(texto)
    if num:
        total += float(num)
    if total <= 0:
        raise ValueError(texto)
    return total


def texto_restante(restante: float) -> str:
    """'MM:SS' do que falta (ou 'H:MM' com horas → 'HH:MM'): sempre 5 caracteres para caber na pílula."""
    r = max(0, int(math.ceil(restante)))
    if r >= 3600:
        return f"{min(99, r // 3600):02d}:{(r % 3600) // 60:02d}"
    return f"{r // 60:02d}:{r % 60:02d}"


def progresso(ts: float, ciclo: float = 60.0) -> tuple[float, float]:
    """(p, t_desde_virada): p de 0 a 1 ao longo do ciclo; t_desde_virada em segundos desde o começo do ciclo."""
    t = ts % ciclo
    return t / ciclo, t


def _meia_largura(y: int) -> int:
    """Meia-largura do vidro (contorno) na linha y; 0 no pescoço."""
    if TOPO0 <= y <= TOPO1:
        return 1 + round(6 * (TOPO1 - y) / (NLIN - 1))
    if BASE0 <= y <= BASE1:
        return 1 + round(6 * (y - BASE0) / (NLIN - 1))
    return 0


def ampulheta_pixels(p: float, t: float = 0.0, fluxo: bool = True):
    """[(x, y, cor)] da ampulheta com a areia em p (0 = tudo em cima, 1 = tudo embaixo)."""
    px = []
    for x in range(CX - 9, CX + 10):
        for y in (10, 11, 39, 40):
            px.append((x, y, "madeira2" if y in (10, 40) else "madeira"))
    for y in range(12, 39):
        px += [(CX - 9, y, "madeira"), (CX + 9, y, "madeira")]
    for y in list(range(TOPO0, TOPO1 + 1)) + list(range(BASE0, BASE1 + 1)):
        hw = _meia_largura(y)
        px += [(CX - hw, y, "borda"), (CX + hw, y, "borda")]
        for x in range(CX - hw + 1, CX + hw):
            px.append((x, y, "vidro"))
    px.append((CX, PESCOCO, "borda"))
    topo_n = round(NLIN * (1 - p))
    base_n = round(NLIN * p)
    for i in range(topo_n):                       # areia de cima: sobe a partir do fundo do bulbo
        y = TOPO1 - i
        hw = _meia_largura(y)
        for x in range(CX - hw + 1, CX + hw):
            px.append((x, y, "areia" if (x + y) % 5 else "areia2"))
    for i in range(base_n):                       # areia de baixo: monte (a camada de cima é mais estreita)
        y = BASE1 - i
        hw = _meia_largura(y)
        folga = 1 if i == base_n - 1 and base_n > 2 else 0
        for x in range(CX - hw + 1 + folga, CX + hw - folga):
            px.append((x, y, "areia" if (x + y) % 5 else "areia2"))
    if fluxo and 0 < topo_n and base_n < NLIN:
        y_fim = BASE1 - base_n
        fase = int(t * 8)
        for y in range(PESCOCO, y_fim + 1):
            if (y + fase) % 3:
                px.append((CX, y, "areia"))
    return px


def virar(pixels, s: float):
    """Espelha a cena verticalmente em torno do pescoço com fator s (1 → -1): efeito de virar a ampulheta."""
    out = []
    for x, y, c in pixels:
        out.append((x, round(PESCOCO + (y - PESCOCO) * s), c))
    return out


def tucano_pixels(t: float, noite: bool, rng_semente: int = 0):
    """Pixels do tucano: respira (cabeça sobe/desce 1px), pisca de tempos em tempos, dorme à noite."""
    ciclo = 4.6 + (rng_semente % 3) * 0.4
    fase = t % ciclo
    pisca = noite or fase > ciclo - 0.25
    olhando_fora = (int(t // 11) % 3 == 2) and not noite     # de vez em quando olha para frente
    bob = 1 if int(t / 0.9) % 2 else 0
    out = []
    for j, linha in enumerate(TUCANO):
        for i, ch in enumerate(linha):
            if ch == ".":
                continue
            if j == 3 and i in (7, 8) and (pisca or olhando_fora):
                ch = "K" if pisca and i == 8 else ("B" if i == 7 else "P")
            elif j == 3 and i == 7 and not pisca:
                ch = "B"
            dy = bob if j <= 9 else 0
            out.append((TUC_X + i, TUC_Y + j + dy, ch))
    if noite:                                                      # zZ subindo
        k = int(t / 0.8) % 3
        out += [(TUC_X + 5, TUC_Y - 2 - k, "zz"), (TUC_X + 6, TUC_Y - 2 - k, "zz"),
                (TUC_X + 6, TUC_Y - 3 - k, "zz"), (TUC_X + 7, TUC_Y - 3 - k, "zz")]
    return out


def texto_pixels(hhmm: str, dois_pontos: bool = True):
    """Pixels do 'HH:MM' (fonte 5x7) centrado em x, linhas 52..58."""
    largura = sum((len(DIGITOS[c][0]) if c != ":" else 1) + 1 for c in hhmm) - 1
    x = (W - largura) // 2
    out = []
    for c in hhmm:
        g = DIGITOS[c]
        if c == ":" and not dois_pontos:
            x += 2
            continue
        for j, linha in enumerate(g):
            for i, bit in enumerate(linha):
                if bit == "1":
                    out.append((x + i, 52 + j, "texto"))
        x += len(g[0]) + 1
    return out


def cenario_pixels(t: float):
    """Fundo selva: folhas no topo (balançam de leve), cipó à esquerda, galho do tucano, pílula do horário."""
    out = []
    bal = int(t / 1.3) % 2
    for x in range(0, 14):                        # folhagem esquerda
        for y in range(0, 5):
            if x + y * 2 < 20 and (x * 3 + y) % 7 != 0:
                out.append((x, y, "f2" if (x + y) % 3 else "f1"))
    for x in range(36, 52):                       # folhagem direita
        for y in range(0, 4):
            if (51 - x) + y * 2 < 20 and (x + y * 5) % 6 != 0:
                out.append((x, y, "f2" if (x + y) % 3 else "f3"))
    for y in range(5, 32):                        # cipó
        out.append((2 + (1 if (y // 7) % 2 else 0), y, "vine"))
        if y % 6 == 2:
            out += [(4 + bal, y, "f1"), (5 + bal, y, "f3"), (4 + bal, y + 1, "f2")]
    for x in range(30, 52):                       # galho
        out += [(x, 41, "madeira"), (x, 42, "madeira2")]
    out += [(47 + bal, 38, "f1"), (48 + bal, 38, "f3"), (49, 39, "f2"), (48, 40, "f1"), (49, 40, "f3")]
    for x in range(8, 44):                        # pílula do horário
        for y in range(49, 62):
            if not ((x in (8, 43)) and (y in (49, 61))):
                out.append((x, y, "pill"))
    return out


def cena_pixels(agora: float, ciclo: float = 60.0, noite: bool | None = None,
                timer: tuple[float, float] | None = None):
    """Lista final de (x, y, cor) em ordem de desenho, para o instante `agora` (timestamp).
    `timer` = (inicio, duracao): modo contagem (sem virar; o texto mostra o que falta)."""
    tm = time.localtime(agora)
    if noite is None:
        noite = eh_noite(tm.tm_hour)
    if timer:
        inicio, dur = timer
        p, t = min(1.0, max(0.0, (agora - inicio) / dur)), 99.0
        texto = texto_restante(dur - (agora - inicio))
        pontos = p >= 1.0 or int(agora) % 2 == 0
    else:
        p, t = progresso(agora, ciclo)
        texto, pontos = time.strftime("%H:%M", tm), int(agora) % 2 == 0
    px = cenario_pixels(agora)
    if t < FLIP_S:                                # virando: desenha o estado anterior (tudo embaixo) espelhando
        s = math.cos(math.pi * t / FLIP_S)
        px += virar(ampulheta_pixels(1.0, t, fluxo=False), s)
    else:
        px += ampulheta_pixels(p, agora)
    px += tucano_pixels(agora, noite)
    px += texto_pixels(texto, dois_pontos=pontos)
    return px


def agrupar(pixels):
    """Junta pixels vizinhos da mesma cor na mesma linha em retângulos (x, y, w, cor): bem menos itens no Canvas.
    Ordem de desenho preservada: quem vem depois cobre quem veio antes."""
    mapa: dict[tuple[int, int], str] = {}
    ordem: list[tuple[int, int]] = []
    for x, y, c in pixels:
        if 0 <= x < W and 0 <= y < H:
            if (x, y) not in mapa:
                ordem.append((x, y))
            mapa[(x, y)] = c
    por_linha: dict[int, list[tuple[int, str]]] = {}
    for x, y in ordem:
        por_linha.setdefault(y, []).append((x, mapa[(x, y)]))
    saida = []
    for y, itens in sorted(por_linha.items()):
        itens.sort()
        i = 0
        while i < len(itens):
            x, c = itens[i]
            j = i
            while j + 1 < len(itens) and itens[j + 1][1] == c and itens[j + 1][0] == itens[j][0] + 1:
                j += 1
            saida.append((x, y, itens[j][0] - x + 1, c))
            i = j + 1
    return saida


# ── janela (Tk) ───────────────────────────────────────────────────────────────
def rodar(rapido: bool = False, sem_borda: bool = False, pos: str | None = None,
          ciclo: float | None = None, timer: float | None = None) -> int:
    import tkinter as tk
    esc = int(os.environ.get("JRELOGIO_ESCALA", "5") or 5)
    ciclo = ciclo or (10.0 if rapido else 60.0)
    inicio = time.time()
    avisado = {"ok": False}
    root = tk.Tk()
    root.title("JRelogio")
    root.configure(bg=CORES["bg"])
    root.resizable(False, False)
    cv = tk.Canvas(root, width=W * esc, height=H * esc, bg=CORES["bg"], highlightthickness=0, bd=0)
    cv.pack()
    if sem_borda:
        root.overrideredirect(True)
        if pos:
            try:
                x, y = (int(v) for v in pos.split(","))
                root.geometry(f"+{x}+{y}")
            except ValueError:
                pass
    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("q", lambda _e: root.destroy())

    def quadro():
        try:
            agora = time.time()
            cv.delete("all")
            if timer and not avisado["ok"] and agora - inicio >= timer:
                avisado["ok"] = True
                try:
                    import jhello
                    jhello.notificar("Tempo! ⏳", "a areia acabou", 8000)
                except Exception:       # o aviso é só um extra
                    pass
            for x, y, w, c in agrupar(cena_pixels(agora, ciclo, timer=(inicio, timer) if timer else None)):
                cv.create_rectangle(x * esc, y * esc, (x + w) * esc, (y + 1) * esc, fill=CORES[c], outline="")
            virando = (not timer) and progresso(agora, ciclo)[1] < FLIP_S
            root.after(50 if virando else 150, quadro)
        except tk.TclError:
            return
    quadro()
    root.mainloop()
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pos = None
    if "--pos" in argv:
        i = argv.index("--pos")
        pos = argv[i + 1] if i + 1 < len(argv) else None
    def valor(flag):
        if flag in argv:
            i = argv.index(flag)
            return parse_duracao(argv[i + 1]) if i + 1 < len(argv) else None
        return None
    try:
        return rodar("--rapido" in argv, "--sem-borda" in argv, pos, valor("--ciclo"), valor("--timer"))
    except ValueError as exc:
        print(f"jrelogio: duração inválida ({exc}). Exemplos: 90, 45s, 5m, 1h30m, 1:30", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"jrelogio: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    random.seed()
    sys.exit(main())
