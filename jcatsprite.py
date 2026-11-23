"""Sprites e máquina de estados compartilhados pelo gato de passeio, sem Tk (testável).

Cada sprite tem 16x12 "pixels" lógicos. Letras: B corpo, D sombra, E olho, N nariz, Z sono, H coração.
`pixels()` retorna (coluna, linha, letra) para desenho em quadradinhos.
Comportamento: senta, anda de um lado a outro do espaço livre da barra, dorme (e solta zzz); com música
tocando não dorme e balança; clicar nele faz carinho (coração). JGATO=0 desliga.
"""
from __future__ import annotations

import random

LARG, ALT = 16, 12
VELOCIDADE = 26.0        # pixels de tela por segundo

ANDA_A = [
"................",
"...........B...B",
"..B........BBBBB",
".BB........BEBEB",
".B..BBBBBBBBBBBN",
".B.BBBBBBBBBBBB.",
"..BBBBBBBBBBBBB.",
"...BBBBBBBBBBB..",
"...BB.......BB..",
"...BB.......BB..",
"...DD.......DD..",
"................",
]
ANDA_B = [
"................",
"...........B...B",
"..B........BBBBB",
".BB........BEBEB",
".B..BBBBBBBBBBBN",
".B.BBBBBBBBBBBB.",
"..BBBBBBBBBBBBB.",
"...BBBBBBBBBBB..",
".....BB...BB....",
".....BB...BB....",
".....DD...DD....",
"................",
]
SENTA_A = [
"................",
"........B...B...",
"........BBBBB...",
"........BEBEB...",
"........BBNBB...",
".......BBBBBBB..",
".......BBBBBBB..",
"......BBBBBBBBB.",
"......BBBBBBBBB.",
".BBB..BBBBBBBBB.",
"B..BBBBBBBBBBBB.",
".BBDDDDDDDDDDD..",
]
SENTA_B = [
"................",
"........B...B...",
"........BBBBB...",
"........BEBEB...",
"........BBNBB...",
".......BBBBBBB..",
".......BBBBBBB..",
"......BBBBBBBBB.",
"......BBBBBBBBB.",
"BBB...BBBBBBBBB.",
"...BBBBBBBBBBBB.",
".BBDDDDDDDDDDD..",
]
DORME_A = [
"................",
"................",
"..............Z.",
".............ZZ.",
"................",
"................",
"....BBBBBB......",
"..BBBBBBBBBBB...",
".BBBBBBBBBBBBB..",
".BBBBBBBBBBBDBB.",
"BBBBBBBBBBBBBBB.",
".DDDDDDDDDDDDD..",
]
DORME_B = [
"................",
"..............Z.",
".............ZZ.",
"................",
"................",
"................",
"....BBBBBB......",
"..BBBBBBBBBBB...",
".BBBBBBBBBBBBB..",
".BBBBBBBBBBBDBB.",
"BBBBBBBBBBBBBBB.",
".DDDDDDDDDDDDD..",
]

# ── skin "gatinha": tortoiseshell (casco de tartaruga) filhote, a gatinha da dedicatória ──────────────
# G cinza-escuro  K caramelo  M marrom  C bege  W branco  F rosto/orelhas escuros  Y olho âmbar
# N nariz  P patinhas escuras  Z sono  H coração
GATINHA_ANDA_A = [
".........F....F.",
".........FF..FF.",
".........FWFFWF.",
".........FYFFYF.",
"..K..GGGGFFFFFFN",
".KK.GGKGGMGWW...",
"..KGGMGGKGGGWW..",
"...GGGMGGGKGGG..",
"...PP.......PP..",
"...PP.......PP..",
"...PP.......CC..",
"................",
]
GATINHA_ANDA_B = [
".........F....F.",
".........FF..FF.",
".........FWFFWF.",
".........FYFFYF.",
"..K..GGGGFFFFFFN",
".KK.GGKGGMGWW...",
"..KGGMGGKGGGWW..",
"...GGGMGGGKGGG..",
".....PP...PP....",
".....PP...PP....",
".....PP...CC....",
"................",
]
GATINHA_SENTA_A = [
"........F....F..",
"........FF..FF..",
"........FWFFWF..",
"........FYFFYF..",
"........FFFNFF..",
".......GWWWGG...",
"......GGWWWKGG..",
"......GKGGMGGK..",
".....GGMGGKGGGG.",
".KK.GGGGGGGGGPC.",
"K..KGGGGGGGGGPP.",
".KKKPPPPPPPPPP..",
]
GATINHA_SENTA_B = [
"........F....F..",
"........FF..FF..",
"........FWFFWF..",
"........FYFFYF..",
"........FFFNFF..",
".......GWWWGG...",
"......GGWWWKGG..",
"......GKGGMGGK..",
".....GGMGGKGGGG.",
"KK..GGGGGGGGGPC.",
".K.KGGGGGGGGGPP.",
"..KKPPPPPPPPPP..",
]
GATINHA_DORME_A = [
"................",
"..............Z.",
".............ZZ.",
"................",
".........F..F...",
".....GGGGFFFFFF.",
"....GKGGGFWFFWF.",
"...GGMGGKGGGFFFN",
"..GKGGGMGGKGGWW.",
".KGGGGGMGGGGGGC.",
"KKKGGGGGGGGGGPP.",
".KKKPPPPPPPPPP..",
]
GATINHA_DORME_B = [
"..............Z.",
".............ZZ.",
"................",
"................",
".........F..F...",
".....GGGGFFFFFF.",
"....GKGGGFWFFWF.",
"...GGMGGKGGGFFFN",
"..GKGGGMGGKGGWW.",
".KGGGGGMGGGGGGC.",
"KKKGGGGGGGGGGPP.",
".KKKPPPPPPPPPP..",
]
GATINHA_PEGA_A = [
".....F....F.....",
".....FF..FF.....",
".....FWFFWF.....",
".....FYFFYF.....",
".....FFFNFF.....",
"....GGGWWGGG....",
"....GKGGMGGK.K..",
"....GGMGGKGG..K.",
".....GGGGGGG..K.",
".....PP..PP.....",
"....PP....PP....",
"....C......C....",
]
GATINHA_PEGA_B = [
".....F....F.....",
".....FF..FF.....",
".....FWFFWF.....",
".....FYFFYF.....",
".....FFFNFF.....",
"....GGGWWGGG....",
"....GKGGMGGK....",
"....GGMGGKGG.K..",
".....GGGGGGG..K.",
"......PPPP...K..",
".....PP..PP.....",
"....C......C....",
]
CORES_GATINHA = {"G": "#55555c", "K": "#c8894a", "M": "#8a5a36", "C": "#dcc6a2", "W": "#f4f0e6",
                 "F": "#2e2e34", "Y": "#f0b020", "N": "#b06a6a", "P": "#2a2a2f", "Z": "#7dcfff",
                 "H": "#e0566a"}

CORACAO = ["H.H", "HHH", ".H."]         # desenhado ACIMA da cabeça (linhas negativas)

# O sprite de colo da gatinha também serve ao skin cinza, mas com a paleta
# antiga. Converte as cores da pelagem para corpo/sombra e conserva os olhos.
_PEGA_CINZA = tuple(
    tuple(linha.translate(str.maketrans({"G": "B", "K": "D", "M": "B", "C": "D",
                                         "W": "B", "F": "B", "Y": "E", "P": "B"}))
          for linha in quadro)
    for quadro in (GATINHA_PEGA_A, GATINHA_PEGA_B)
)

SKINS = {
    "gatinha": {"anda": (GATINHA_ANDA_A, GATINHA_ANDA_B), "senta": (GATINHA_SENTA_A, GATINHA_SENTA_B),
                "dorme": (GATINHA_DORME_A, GATINHA_DORME_B), "pega": (GATINHA_PEGA_A, GATINHA_PEGA_B)},
    "cinza": {"anda": (ANDA_A, ANDA_B), "senta": (SENTA_A, SENTA_B), "dorme": (DORME_A, DORME_B), "pega": _PEGA_CINZA},
}
SKIN_PADRAO = "gatinha"
INTERVALO = {"anda": 0.22, "senta": 0.7, "dorme": 0.9, "pega": 0.14}
DURACAO = {"anda": (2.0, 6.0), "senta": (3.0, 8.0), "dorme": (10.0, 25.0), "pega": (999.0, 999.0)}


class Gato:
    def __init__(self, rng: random.Random | None = None, skin: str = SKIN_PADRAO):
        self.rng = rng or random.Random()
        self.skin = skin if skin in SKINS else SKIN_PADRAO
        self.estado = "senta"
        self.dir = 1                       # 1 = olhando/andando para a direita
        self.x = 0.0                       # borda esquerda do sprite, em pixels de tela
        self.visivel = False
        self.t_estado = self.rng.uniform(*DURACAO["senta"])
        self.t_anim = 0.0
        self.quadro_i = 0
        self.t_coracao = 0.0
        self._inicializado = False

    # ── comportamento ──
    def _mudar(self, estado: str) -> None:
        self.estado = estado
        self.t_estado = self.rng.uniform(*DURACAO[estado])
        self.t_anim, self.quadro_i = 0.0, 0

    def _decidir(self, tocando: bool) -> None:
        if self.estado == "senta":
            pesos = [("anda", 50), ("dorme", 0 if tocando else 30), ("senta", 20)]
        elif self.estado == "anda":
            pesos = [("senta", 70), ("anda", 30)]
        else:
            pesos = [("senta", 100)]
        r = self.rng.uniform(0, sum(p for _, p in pesos))
        nome = pesos[-1][0]
        for opcao, p in pesos:
            r -= p
            if r <= 0 < p:
                nome = opcao
                break
        if nome == "anda" and (self.estado == "anda" or self.rng.random() < 0.4):
            self.dir = -self.dir
        self._mudar(nome)

    def carinho(self) -> None:
        """Clique no gato: para, senta e solta um coração por ~2 s."""
        self._mudar("senta")
        self.t_estado = 3.0
        self.t_coracao = 2.0

    def pegar(self) -> None:
        """Alguém pegou a gata no colo (botão direito): fica pendurada, patinhas balançando."""
        self._mudar("pega")
        self.t_coracao = 0.0

    def soltar(self) -> None:
        """Pousou de novo: senta um instante."""
        self._mudar("senta")
        self.t_estado = 1.5

    def animar(self, dt: float) -> None:
        """Só avança os quadros (gata no colo ou caindo: o resto da lógica fica parado)."""
        self.t_anim += max(0.0, min(dt, 0.5))
        if self.t_anim >= INTERVALO[self.estado]:
            self.t_anim -= INTERVALO[self.estado]
            self.quadro_i ^= 1

    def passo(self, dt: float, x_min: float, x_max: float, escala: int = 2, tocando: bool = False) -> None:
        """Avança `dt` segundos dentro do espaço livre [x_min, x_max] (pixels de tela)."""
        dt = max(0.0, min(dt, 0.5))
        lo, hi = x_min, x_max - LARG * escala
        if hi - lo < 8:                    # não cabe: some até haver espaço
            self.visivel = False
            return
        self.visivel = True
        if not self._inicializado:
            self.x, self._inicializado = lo + (hi - lo) * self.rng.random(), True
        self.x = max(lo, min(hi, self.x))
        self.t_coracao = max(0.0, self.t_coracao - dt)
        self.t_estado -= dt
        self.t_anim += dt
        if tocando and self.estado == "dorme":       # acordou com a música
            self._mudar("senta")
        intervalo = 0.25 if (tocando and self.estado == "senta") else INTERVALO[self.estado]
        if self.t_anim >= intervalo:
            self.t_anim -= intervalo
            self.quadro_i ^= 1
        if self.estado == "anda":
            self.x += self.dir * VELOCIDADE * dt
            if self.x <= lo or self.x >= hi:
                self.x = max(lo, min(hi, self.x))
                self.dir = -self.dir
                self._mudar("senta")
                return
        if self.t_estado <= 0:
            self._decidir(tocando)

    # ── desenho ──
    def pixels(self) -> list[tuple[int, int, str]]:
        """(coluna, linha, letra) do quadro atual, já espelhado se estiver indo para a esquerda."""
        rows = SKINS[self.skin][self.estado][self.quadro_i]
        out = []
        for y, linha in enumerate(rows):
            for x, ch in enumerate(linha):
                if ch != ".":
                    out.append((x if self.dir > 0 else LARG - 1 - x, y, ch))
        if self.t_coracao > 0 and self.estado != "dorme":
            col0 = 10 if self.dir > 0 else LARG - 13      # em cima da cabeça
            subir = 1 if self.t_coracao > 1.0 else 0       # sobe um pouquinho enquanto some
            for y, linha in enumerate(CORACAO):
                for x, ch in enumerate(linha):
                    if ch != ".":
                        out.append((col0 + x, y - 4 - subir, "H"))
        return out
