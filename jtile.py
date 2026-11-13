"""
jtile - mosaico em árvore (estilo Sway/i3/bspwm) para o JWM. Sem dependência de X: só geometria.

  * Cada monitor de cada workspace tem uma Arvore.
  * Folha = uma janela. Divisão = duas metades (a, b) lado a lado ('h') ou empilhadas ('v').
  * Retângulos são EXTERNOS (borda incluída); o gap fica só entre as janelas.
"""
from __future__ import annotations

from typing import Optional

Rect = tuple[int, int, int, int]


class No:
    __slots__ = ("pai", "rect")

    def __init__(self):
        self.pai: Optional["Divisao"] = None
        self.rect: Rect = (0, 0, 1, 1)


class Folha(No):
    __slots__ = ("wid",)

    def __init__(self, wid: int):
        super().__init__()
        self.wid = wid


class Divisao(No):
    __slots__ = ("orient", "ratio", "a", "b")

    def __init__(self, orient: str, a: No, b: No, ratio: float = 0.5):
        super().__init__()
        self.orient, self.ratio, self.a, self.b = orient, ratio, a, b
        a.pai = b.pai = self


class Arvore:
    def __init__(self):
        self.raiz: Optional[No] = None
        self.folhas: dict[int, Folha] = {}

    # ── conteúdo ──
    def __len__(self) -> int:
        return len(self.folhas)

    def __contains__(self, wid: int) -> bool:
        return wid in self.folhas

    def _trocar_filho(self, velho: No, novo: No) -> None:
        pai = velho.pai
        novo.pai = pai
        if pai is None:
            self.raiz = novo
        elif pai.a is velho:
            pai.a = novo
        else:
            pai.b = novo

    def inserir(self, wid: int, alvo: Optional[int] = None, orient: str = "h") -> None:
        """Divide a folha `alvo` (ou a última, se None/inexistente) e põe `wid` na metade nova."""
        if wid in self.folhas:
            return
        if self.raiz is None:
            self.folhas[wid] = self.raiz = Folha(wid)
            return
        if alvo not in self.folhas:
            alvo = next(reversed(self.folhas))
        velha = self.folhas[alvo]
        nova = Folha(wid)
        self.folhas[wid] = nova
        pai = velha.pai              # guardar antes: o construtor de Divisao reaponta velha.pai
        div = Divisao(orient, velha, nova)
        div.rect = velha.rect
        div.pai = pai
        if pai is None:
            self.raiz = div
        elif pai.a is velha:
            pai.a = div
        else:
            pai.b = div

    def remover(self, wid: int) -> None:
        f = self.folhas.pop(wid, None)
        if f is None:
            return
        pai = f.pai
        if pai is None:
            self.raiz = None
            return
        irmao = pai.b if pai.a is f else pai.a
        self._trocar_filho(pai, irmao)

    def ids(self) -> list[int]:
        return list(self.folhas)

    # ── geometria ──
    def layout(self, x: int, y: int, w: int, h: int, gap: int, min_w: int = 1, min_h: int = 1) -> dict[int, Rect]:
        out: dict[int, Rect] = {}
        if self.raiz is not None:
            self._layout(self.raiz, (x, y, max(1, w), max(1, h)), gap, min_w, min_h, out)
        return out

    def _layout(self, n: No, r: Rect, gap: int, min_w: int, min_h: int, out: dict) -> None:
        n.rect = r
        x, y, w, h = r
        if isinstance(n, Folha):
            out[n.wid] = r
            return
        if n.orient == "h":
            util = max(2, w - gap)
            wa = int(util * n.ratio)
            wa = max(min(min_w, util // 2), min(util - min(min_w, util // 2), wa))
            self._layout(n.a, (x, y, wa, h), gap, min_w, min_h, out)
            self._layout(n.b, (x + wa + gap, y, util - wa, h), gap, min_w, min_h, out)
        else:
            util = max(2, h - gap)
            ha = int(util * n.ratio)
            ha = max(min(min_h, util // 2), min(util - min(min_h, util // 2), ha))
            self._layout(n.a, (x, y, w, ha), gap, min_w, min_h, out)
            self._layout(n.b, (x, y + ha + gap, w, util - ha), gap, min_w, min_h, out)

    # ── operações estilo sway ──
    def alternar_divisao(self, wid: int) -> bool:
        """layout toggle split: troca h <-> v na divisão que contém a janela."""
        f = self.folhas.get(wid)
        if f is None or f.pai is None:
            return False
        f.pai.orient = "v" if f.pai.orient == "h" else "h"
        return True

    def trocar(self, a: int, b: int) -> None:
        fa, fb = self.folhas.get(a), self.folhas.get(b)
        if fa is None or fb is None or fa is fb:
            return
        fa.wid, fb.wid = b, a
        self.folhas[a], self.folhas[b] = fb, fa

    def redimensionar(self, wid: int, direcao: str, px: int, gap: int) -> bool:
        """Move a divisória mais próxima na direção dada (left/right/up/down) em `px` pixels.
        'right'/'down' CRESCEM a janela (largura/altura); 'left'/'up' ENCOLHEM (como o modo resize do sway)."""
        horizontal = direcao in ("left", "right")
        orient = "h" if horizontal else "v"
        sinal = 1 if direcao in ("right", "down") else -1
        no: No = self.folhas.get(wid)
        if no is None:
            return False
        while no.pai is not None:
            pai = no.pai
            if pai.orient == orient:
                _x, _y, w, h = pai.rect
                util = max(2, (w if horizontal else h) - gap)
                # crescer = afastar a divisória da janela: no lado 'a' ela anda p/ frente (+), no 'b' p/ trás (-)
                lado = 1 if pai.a is no else -1
                pai.ratio = min(0.9, max(0.1, pai.ratio + sinal * lado * px / util))
                return True
            no = pai
        return False


def vizinho(rects: dict[int, Rect], wid: int, direcao: str) -> Optional[int]:
    """Janela adjacente na direção dada, olhando só a geometria (serve p/ foco e movimento)."""
    if wid not in rects:
        return None
    cx, cy, cw, ch = rects[wid]
    melhor, chave = None, None
    for outro, (x, y, w, h) in rects.items():
        if outro == wid:
            continue
        if direcao == "left":
            ok, dist, sobre = x + w <= cx + 1, cx - (x + w), min(cy + ch, y + h) - max(cy, y)
        elif direcao == "right":
            ok, dist, sobre = x >= cx + cw - 1, x - (cx + cw), min(cy + ch, y + h) - max(cy, y)
        elif direcao == "up":
            ok, dist, sobre = y + h <= cy + 1, cy - (y + h), min(cx + cw, x + w) - max(cx, x)
        else:
            ok, dist, sobre = y >= cy + ch - 1, y - (cy + ch), min(cx + cw, x + w) - max(cx, x)
        if not ok or sobre <= 0:
            continue
        k = (max(0, dist), -sobre)
        if chave is None or k < chave:
            melhor, chave = outro, k
    return melhor
