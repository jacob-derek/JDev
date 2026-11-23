#!/usr/bin/env python3
"""jcat - a gatinha passeia pela TELA: anda no topo das janelas, pula entre elas, dorme, ganha carinho no clique.

É UMA janela só (com o formato do gato, via extensão SHAPE do X11), então nunca existem dois gatos.
Precisa de python-xlib (o JWM já exige). Roda em segundo plano:
    python3 jcat.py            (o jwm-session chama; some da JBar o gatinho embutido)
    python3 jcat.py --agora    não espera o JDev terminar de carregar
    JCAT=0 desliga   JGATO_SKIN=cinza|gatinha   JGATO_ESCALA=3 muda o tamanho
Botão esquerdo = carinho (coração).  Botão DIREITO = pega no colo: ela fica pendurada, vai com o mouse
e, ao soltar, cai até o chão mais próximo.
Outros programas fazem coração na gata com:   import jcat; jcat.avisar("coracao")
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from dataclasses import dataclass

import jcatsprite as jcat

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "jdev")
PRONTO = os.path.join(CACHE, "pronto")
EVENTO = os.path.join(CACHE, "gato-evento")
MARGEM_CORACAO = 5          # linhas de pixel acima do gato, para o coração
DURACAO_PULO = 0.5
GRAVIDADE = 2400.0          # px/s² da queda depois de soltar
QUICAR = 0.28               # fração da velocidade que volta no 1º impacto
ALTURA_PULO = 46            # px de arco
LARGURA_MIN = 90            # janelas mais estreitas que isso não servem de chão
DURACAO_POUSO_MANUAL = 12.0 # tempo que ela fica onde foi solta antes de retomar o passeio


@dataclass(frozen=True)
class Chao:
    x0: int
    x1: int
    y: int                  # y do topo (onde as patas pisam)


def chaos(janelas, area) -> list[Chao]:
    """Topos de janelas (x, y, w, h) viram chãos; topos na mesma altura que se tocam viram um chão só.
    Sempre há ao menos um: a borda de cima da área útil `area` (x, y, w, h)."""
    ax, ay, aw, _ = area
    por_y: dict[int, list[list[int]]] = {}
    for x, y, w, h in janelas:
        if w >= LARGURA_MIN and h > 20 and y >= 0:
            por_y.setdefault(y, []).append([x, x + w])
    saida = []
    for y, faixas in por_y.items():
        faixas.sort()
        atual = faixas[0][:]
        for a, b in faixas[1:]:
            if a <= atual[1] + 2:
                atual[1] = max(atual[1], b)
            else:
                saida.append(Chao(atual[0], atual[1], y))
                atual = [a, b]
        saida.append(Chao(atual[0], atual[1], y))
    if not saida:
        saida.append(Chao(ax, ax + aw, ay))
    return sorted(saida, key=lambda c: (c.y, c.x0))


def retangulos(pixels, escala: int, linha0: int = MARGEM_CORACAO):
    """[(letra, x, y, w, h)] em pixels da janela: pixels vizinhos da mesma cor na linha viram um retângulo só."""
    por_linha: dict[int, list[tuple[int, str]]] = {}
    for cx, cy, ch in pixels:
        por_linha.setdefault(cy + linha0, []).append((cx, ch))
    saida = []
    for cy, itens in sorted(por_linha.items()):
        itens.sort()
        i = 0
        while i < len(itens):
            x, ch = itens[i]
            j = i
            while j + 1 < len(itens) and itens[j + 1][1] == ch and itens[j + 1][0] == itens[j][0] + 1:
                j += 1
            saida.append((ch, x * escala, cy * escala, (itens[j][0] - x + 1) * escala, escala))
            i = j + 1
    return saida


class Passeio:
    """Une o Gato (comportamento) às superfícies: escolhe o chão, pula de um para outro, devolve (x, y_do_chão)."""

    def __init__(self, gato: jcat.Gato, escala: int, rng: random.Random | None = None):
        self.gato, self.escala = gato, escala
        self.rng = rng or random.Random()
        self.chao: Chao | None = None
        self.pulo = None            # (t, de_y, para_chao)
        self.y = 0.0
        self.seguro = False         # no colo
        self.queda = None           # [vy, alvo, quicou]
        self.pouso_manual: Chao | None = None
        self.t_pouso_manual = 0.0

    @property
    def pulando(self) -> bool:
        return self.pulo is not None

    @property
    def ocupado(self) -> bool:
        return self.pulando or self.seguro or self.queda is not None

    def pegar(self) -> None:
        self.seguro, self.pulo, self.queda = True, None, None
        self.gato.pegar()
        self.gato.visivel = True

    def levar(self, x: float, y_pes: float) -> None:
        """Posição do canto esquerdo (x) e da linha dos pés (y_pes) enquanto está no colo."""
        self.gato.x, self.y = x, y_pes

    def soltar(self, lista: list[Chao], posicao: tuple[float, float] | None = None) -> None:
        """Pousa no ponto do mouse ou, sem ponto, no chão mais próximo abaixo dela."""
        g = self.gato
        self.seguro = False
        if posicao is not None:
            # Ao soltar com o mouse, respeita o ponto escolhido em vez de encaixar a gata
            # automaticamente no topo de uma janela. A pequena plataforma temporária
            # deixa que ela caminhe um pouco ali antes de voltar ao passeio habitual.
            x, y = posicao
            largura = jcat.LARG * self.escala
            x0 = max(0, int(x - 16))
            x1 = x0 + largura + 32
            g.x, self.y = max(0, float(x)), max(0.0, float(y))
            self.pouso_manual = Chao(x0, x1, int(self.y))
            self.t_pouso_manual = DURACAO_POUSO_MANUAL
            self.chao = self.pouso_manual
            self.pulo = self.queda = None
            g.soltar()
            return
        meio = g.x + jcat.LARG * self.escala / 2
        abaixo = [c for c in lista if c.y >= self.y - 6 and c.x0 <= meio <= c.x1]
        alvo = min(abaixo, key=lambda c: c.y) if abaixo else min(
            lista, key=lambda c: abs(c.y - self.y) + max(0, c.x0 - meio, meio - c.x1))
        g.x = max(alvo.x0, min(alvo.x1 - jcat.LARG * self.escala, g.x))
        if alvo.y < self.y - 6:                 # chão acima: pula até lá
            self.pulo = (0.0, self.y, alvo)
        else:
            self.queda = [0.0, alvo, False]

    def _pousar(self, c: Chao) -> None:
        self.chao, self.y = c, float(c.y)

    def atualizar(self, dt: float, lista: list[Chao], tocando: bool = False) -> tuple[float, float]:
        g = self.gato
        if self.seguro:
            g.animar(dt)
            return g.x, self.y
        if self.queda:
            g.animar(dt)
            vy, alvo, quicou = self.queda
            vy += GRAVIDADE * min(dt, 0.05)
            self.y += vy * min(dt, 0.05)
            if self.y >= alvo.y:
                self.y = float(alvo.y)
                if not quicou and vy > 220:
                    self.queda = [-vy * QUICAR, alvo, True]
                else:
                    self.queda = None
                    self.chao = alvo
                    g.soltar()
            else:
                self.queda = [vy, alvo, quicou]
            return g.x, self.y
        if self.pulo:
            t, de_y, para = self.pulo
            t += dt
            p = min(1.0, t / DURACAO_PULO)
            self.y = de_y + (para.y - de_y) * p - ALTURA_PULO * math.sin(math.pi * p)
            g.x = max(para.x0, min(para.x1 - jcat.LARG * self.escala, g.x))
            if p >= 1.0:
                self.pulo = None
                self._pousar(para)
            else:
                self.pulo = (t, de_y, para)
            return g.x, self.y
        if self.pouso_manual is not None:
            self.t_pouso_manual -= dt
            g.passo(dt, self.pouso_manual.x0, self.pouso_manual.x1, self.escala, tocando)
            if self.t_pouso_manual > 0:
                return g.x, self.y
            self.pouso_manual = None
        if self.chao is None or not any(self.chao.y == c.y and c.x0 <= g.x + 4 <= c.x1 for c in lista):
            # chão sumiu (janela fechou/mudou de lugar): cai no mais próximo
            alvo = min(lista, key=lambda c: abs(c.y - (self.chao.y if self.chao else c.y)))
            if self.chao is None:
                self._pousar(alvo)
            else:
                self.pulo = (0.0, self.y, alvo)
        else:
            vivo = next(c for c in lista if self.chao.y == c.y and c.x0 <= g.x + 4 <= c.x1)
            self.chao = vivo        # a janela pode ter crescido/encolhido
        if self.chao and not self.pulo:
            g.passo(dt, self.chao.x0, self.chao.x1, self.escala, tocando)
            if len(lista) > 1 and g.estado == "senta" and self.rng.random() < 0.12 * dt:
                outros = [c for c in lista if c != self.chao and c.x1 - c.x0 >= LARGURA_MIN]
                if outros:
                    self.pulo = (0.0, self.y, self.rng.choice(outros))
        return g.x, self.y


def avisar(evento: str = "coracao") -> None:
    """Para outros programas: faz a gata reagir (por enquanto só 'coracao')."""
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(EVENTO, "w", encoding="utf-8") as f:
            f.write(f"{evento} {time.time()}\n")
    except OSError:
        pass


def _ler_evento(ultimo: float):
    try:
        m = os.stat(EVENTO).st_mtime
    except OSError:
        return ultimo, None
    if m > ultimo:
        try:
            with open(EVENTO, encoding="utf-8") as f:
                return m, f.read().split()[0]
        except (OSError, IndexError):
            return m, None
    return ultimo, None


# ══════════════════════════════════════════════════════════════════════════════
#  X11 (precisa de python-xlib; não testável fora de uma sessão X)
# ══════════════════════════════════════════════════════════════════════════════
class Tela:
    def __init__(self):
        from Xlib import X, display
        from Xlib.ext import shape
        self.X, self.shape = X, shape
        self.d = display.Display()
        if not self.d.has_extension("SHAPE"):
            raise RuntimeError("o servidor X não tem a extensão SHAPE")
        self.scr = self.d.screen()
        self.root = self.scr.root
        self.atom = {n: self.d.intern_atom(n) for n in ("_NET_CLIENT_LIST", "_NET_CURRENT_DESKTOP",
                                                       "_NET_WM_DESKTOP", "_NET_WORKAREA")}
        self.win = None
        self.gc = None
        self.pixel_cor: dict[str, int] = {}

    def _prop(self, janela, nome):
        p = janela.get_full_property(self.atom[nome], self.X.AnyPropertyType)
        return list(p.value) if p is not None else []

    def area(self):
        v = self._prop(self.root, "_NET_WORKAREA")
        if len(v) >= 4:
            return tuple(int(i) for i in v[:4])
        g = self.root.get_geometry()
        return (0, 0, g.width, g.height)

    def janelas(self):
        X = self.X
        atual = (self._prop(self.root, "_NET_CURRENT_DESKTOP") or [0])[0]
        saida = []
        for wid in self._prop(self.root, "_NET_CLIENT_LIST"):
            try:
                w = self.d.create_resource_object("window", wid)
                if w.get_attributes().map_state != X.IsViewable:
                    continue
                desk = (self._prop(w, "_NET_WM_DESKTOP") or [atual])[0]
                if desk not in (atual, 0xFFFFFFFF):
                    continue
                g = w.get_geometry()
                o = w.translate_coords(self.root, 0, 0)
                saida.append((o.x, o.y, g.width, g.height))
            except Exception:       # janela sumiu no meio da leitura
                continue
        return saida

    def criar(self, largura: int, altura: int, cores: dict[str, str]):
        X = self.X
        self.win = self.root.create_window(
            0, 0, largura, altura, 0, self.scr.root_depth, X.InputOutput, X.CopyFromParent,
            override_redirect=1,
            event_mask=X.ButtonPressMask | X.ButtonReleaseMask | X.ButtonMotionMask | X.ExposureMask)
        self.win.set_wm_name("jcat")
        self.gc = self.win.create_gc()
        cmap = self.scr.default_colormap
        for letra, hexa in cores.items():
            r, g, b = (int(hexa[i:i + 2], 16) * 257 for i in (1, 3, 5))
            self.pixel_cor[letra] = cmap.alloc_color(r, g, b).pixel

    def desenhar(self, rects):
        shp, X = self.shape, self.X
        formas = [(x, y, w, h) for _, x, y, w, h in rects]
        for tipo in (shp.SK.Bounding, shp.SK.Input):
            self.win.shape_rectangles(shp.SO.Set, tipo, X.Unsorted, 0, 0, formas)
        por_cor: dict[str, list] = {}
        for letra, x, y, w, h in rects:
            por_cor.setdefault(letra, []).append((x, y, w, h))
        for letra, lista in por_cor.items():
            self.gc.change(foreground=self.pixel_cor.get(letra, 0))
            self.win.poly_fill_rectangle(self.gc, lista)

    def mostrar(self, x: int, y: int, visivel: bool = True):
        if visivel:
            self.win.configure(x=int(x), y=int(y), stack_mode=self.X.Above)
            self.win.map()
        else:
            self.win.unmap()

    def _cursor_mao(self):
        """Cursor de 'segurando' (setinha de mover do cursor font do X). None se não der."""
        try:
            fonte = self.d.open_font("cursor")
            return fonte.create_glyph_cursor(fonte, 52, 53, (0, 0, 0), (65535, 65535, 65535))
        except Exception:
            return None

    def agarrar(self):
        """Prende o ponteiro na janela da gata (os eventos continuam chegando ao arrastar) e troca o cursor."""
        X = self.X
        if getattr(self, "_cursor", None) is None:
            self._cursor = self._cursor_mao()
        self.win.grab_pointer(True, X.ButtonReleaseMask | X.ButtonMotionMask | X.PointerMotionMask,
                              X.GrabModeAsync, X.GrabModeAsync, X.NONE, self._cursor or X.NONE, X.CurrentTime)

    def largar(self):
        self.d.ungrab_pointer(self.X.CurrentTime)

    def eventos(self):
        """(clique_esquerdo, expose, acoes) — acoes: ('pegar', dx, dy, rx, ry), ('mover', rx, ry), ('soltar',)."""
        X = self.X
        clique = expor = False
        acoes = []
        while self.d.pending_events():
            e = self.d.next_event()
            if e.type == X.ButtonPress:
                if e.detail == 3:
                    acoes.append(("pegar", e.event_x, e.event_y, e.root_x, e.root_y))
                else:
                    clique = True
            elif e.type == X.ButtonRelease and e.detail == 3:
                acoes.append(("soltar", e.root_x, e.root_y))
            elif e.type == X.MotionNotify:
                if acoes and acoes[-1][0] == "mover":
                    acoes.pop()
                acoes.append(("mover", e.root_x, e.root_y))
            elif e.type == X.Expose:
                expor = True
        return clique, expor, acoes

    def enviar(self):
        self.d.flush()


def esperar_pronto(limite: float = 14.0) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim and not os.path.exists(PRONTO):
        time.sleep(0.2)
    time.sleep(3.5)


def rodar(agora: bool = False) -> int:
    escala = int(os.environ.get("JGATO_ESCALA", "3") or 3)
    skin = os.environ.get("JGATO_SKIN", jcat.SKIN_PADRAO)
    gato = jcat.Gato(skin=skin)
    passeio = Passeio(gato, escala)
    tela = Tela()
    larg, alt = jcat.LARG * escala, (jcat.ALT + MARGEM_CORACAO) * escala
    tela.criar(larg, alt, jcat.CORES_GATINHA)
    if not agora:
        esperar_pronto()
    lista, t_lista, t_alto = [], 0.0, 0.0
    ultimo_evento = time.time()
    anterior = time.monotonic()
    quadro_antigo, mostrando = None, False
    offset = (0, 0)
    while True:
        t = time.monotonic()
        dt, anterior = t - anterior, t
        if t - t_lista > 0.6:
            lista, t_lista = chaos(tela.janelas(), tela.area()), t
        ultimo_evento, ev = _ler_evento(ultimo_evento)
        if ev == "coracao":
            gato.carinho()
        clique, expor, acoes = tela.eventos()
        if clique and not passeio.ocupado:
            gato.carinho()
        for acao in acoes:
            try:
                if acao[0] == "pegar":
                    offset = (acao[1], acao[2])
                    passeio.pegar()
                    tela.agarrar()
                elif acao[0] == "mover" and passeio.seguro:
                    passeio.levar(acao[1] - offset[0], acao[2] - offset[1] + alt)
                elif acao[0] == "soltar" and passeio.seguro:
                    tela.largar()
                    pouso = (acao[1] - offset[0], acao[2] - offset[1] + alt)
                    passeio.soltar(chaos(tela.janelas(), tela.area()), pouso)
            except Exception as exc:        # o carinho nunca derruba a gata
                print(f"jcat: {exc}", file=sys.stderr)
        x, y = passeio.atualizar(dt, lista)
        chave = (gato.estado, gato.quadro_i, gato.dir, gato.t_coracao > 0, int(gato.t_coracao > 1.0), gato.visivel)
        if gato.visivel:
            if chave != quadro_antigo or expor:
                tela.desenhar(retangulos(gato.pixels(), escala))
                quadro_antigo = chave
            tela.mostrar(x, max(0, y - alt), True)   # sem espaço em cima (topo = 0): anda dentro da faixa do topo
            mostrando = True
            if t - t_alto > 1.5:        # mantém por cima de tudo
                t_alto = t
        elif mostrando:
            tela.mostrar(0, 0, False)
            mostrando = False
        tela.enviar()
        time.sleep(0.03 if (gato.estado in ("anda", "pega") or passeio.ocupado) else 0.15)


def main(argv=None) -> int:
    """O JCat visual agora vive preso à JBar; não abre mais uma janela flutuante."""
    return 0


if __name__ == "__main__":
    sys.exit(main())
