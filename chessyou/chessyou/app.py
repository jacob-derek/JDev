"""Interface do ChessYou! (Textual). Uso:  python -m chessyou partida.pgn   |   python -m chessyou --demo"""
from __future__ import annotations

import argparse

import chess
import chess.pgn
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Static

from . import analise, formato, motor, tabuleiro
from .cores import paleta

PAL = paleta()
ROTULO = {"imprecisao": "imprecisão", "erro": "erro", "gafe": "gafe", "ok": "ok"}
MARCA = {"imprecisao": "?!", "erro": "?", "gafe": "??"}


def _texto(linhas):
    """Segmentos (texto, cor, fundo, negrito) -> rich.Text."""
    t = Text(no_wrap=True)
    for i, seg in enumerate(linhas):
        for txt, fg, bg, neg in seg:
            t.append(txt, style=Style(color=fg, bgcolor=bg, bold=neg))
        if i < len(linhas) - 1:
            t.append("\n")
    return t


def _nome_lance(sans, ply):
    """12...Nf6 / 13.Bb3 para o lance `ply` (1 = primeiro lance das brancas)."""
    n = (ply + 1) // 2
    return "%d%s%s" % (n, "." if ply % 2 else "...", sans[ply - 1])


class ChessYou(App):
    CSS = f"""
    Screen {{ background: {PAL['fundo']}; }}
    #info {{ height: 1; padding: 0 2; }}
    #topo {{ height: auto; padding: 0 1; }}
    #tab {{ width: auto; height: auto; }}
    #barra {{ width: auto; height: auto; margin-left: 2; }}
    #base {{ height: 1fr; }}
    #analise, #lances {{ border: round {PAL['borda']}; height: 1fr; padding: 0 1; }}
    #analise {{ width: 1fr; }}
    #lances {{ width: 32; }}
    """
    BINDINGS = [
        Binding("left", "anterior", "Anterior"),
        Binding("right", "proximo", "Próximo"),
        Binding("home", "inicio", "Início"),
        Binding("end", "fim", "Fim"),
        Binding("p", "critico_ant", "Erro ant."),
        Binding("n", "critico_prox", "Próx. erro"),
        Binding("f", "virar", "Virar"),
        Binding("a", "analisar", "Analisar"),
        Binding("q", "quit", "Sair"),
    ]

    def __init__(self, jogo, stockfish=None, profundidade=14):
        super().__init__()
        self.stockfish, self.profundidade = stockfish, profundidade
        self.cabecalho = jogo.headers
        tab = jogo.board()
        self.posicoes, self.sans, self.lances = [tab.copy()], [], []
        for mv in jogo.mainline_moves():
            self.sans.append(tab.san(mv))
            self.lances.append(mv)
            tab.push(mv)
            self.posicoes.append(tab.copy())
        self.ply, self.virado = 0, False
        self.aval = self.melhores = None   # preenchidos pela analise
        self.criticos = []
        self.analisando = False
        self.status = ""

    def compose(self) -> ComposeResult:
        yield Static(id="info")
        with Horizontal(id="topo"):
            yield Static(id="tab")
            yield Static(id="barra")
        with Horizontal(id="base"):
            yield Static(id="analise")
            yield Static(id="lances")
        yield Footer()

    def on_mount(self):
        self.title = "ChessYou!"
        self.query_one("#analise").border_title = "Stockfish"
        self.query_one("#lances").border_title = "Lances"
        self._desenhar()

    # ── desenho ──
    def _desenhar(self):
        tab = self.posicoes[self.ply]
        pecas = {sq: (p.color, p.symbol().upper()) for sq, p in tab.piece_map().items()}
        ultimo = ()
        if self.ply:
            mv = self.lances[self.ply - 1]
            ultimo = (mv.from_square, mv.to_square)
        self._set("tab", _texto(tabuleiro.grade(pecas, PAL, ultimo, self.virado)))
        self._set("barra", self._texto_barra())

        h = self.cabecalho
        info = Text(no_wrap=True)
        info.append(h.get("White", "?"), style=Style(color=PAL["brancas"], bold=True))
        info.append("  x  ", style=Style(color=PAL["dim"]))
        info.append(h.get("Black", "?"), style=Style(color=PAL["pretas"], bold=True))
        info.append("   %s" % h.get("Result", "*"), style=Style(color=PAL["dim"]))
        evento = " · ".join(x for x in (h.get("Event", ""), h.get("Date", "")) if x and "?" not in x)
        if evento:
            info.append("   " + evento, style=Style(color=PAL["dim"]))
        self._set("info", info)

        lances = Text(no_wrap=True)
        for linha in formato.lista_lances(self.sans, self.ply):
            for txt, destaque in linha:
                lances.append(txt, style=Style(color=PAL["fundo"], bgcolor=PAL["destaque"], bold=True)
                              if destaque else Style(color=PAL["dim"] if txt.endswith(". ") else None))
            lances.append("\n")
        self._set("lances", lances)
        self._set("analise", self._painel_analise())

    def _texto_barra(self):
        """Barra de vantagem alinhada com as 8 fileiras do tabuleiro (que começam na 3ª linha)."""
        t = Text(no_wrap=True)
        if not self.aval:
            t.append(" --- \n\n", style=Style(color=PAL["dim"]))
            for _ in range(8):
                t.append("  ░░\n", style=Style(color=PAL["dim"]))
            return t
        t.append(formato.texto_cp(self.aval[self.ply]).center(5) + "\n\n", style=Style(bold=True))
        cor = {"brancas": PAL["brancas"], "pretas": PAL["pretas"], None: None}
        for ch, fg, bg in formato.barra_vertical(self.aval[self.ply], 8):
            t.append(" " + ch * 2 + "\n", style=Style(color=cor[fg], bgcolor=cor[bg]))
        return t

    def _painel_analise(self):
        t = Text()
        if not self.aval:
            if self.status:
                t.append(self.status, style=Style(color=PAL["dim"]))
            elif not self.stockfish:
                t.append("Stockfish não encontrado.\nInstale (sudo xbps-install -S stockfish) ou use --stockfish.",
                         style=Style(color=PAL["pretas"]))
            else:
                t.append("Pressione A para analisar a partida.", style=Style(color=PAL["dim"]))
            return t
        t.append("Avaliação ", style=Style(color=PAL["dim"]))
        t.append(formato.texto_cp(self.aval[self.ply]), style=Style(bold=True))
        t.append("   profundidade %d\n\n" % self.profundidade, style=Style(color=PAL["dim"]))
        if self.ply:
            p = analise.perda(self.aval[self.ply - 1], self.aval[self.ply], self.ply % 2 == 1)
            classe = analise.classificar(p)
            t.append("%s: %s" % (_nome_lance(self.sans, self.ply), ROTULO[classe]),
                     style=Style(bold=True, color=PAL["pretas"] if classe != "ok" else None))
            melhor = self.melhores[self.ply - 1] if self.melhores else None
            if classe != "ok" and melhor:
                t.append("  (perdeu %.0f%%)\nMelhor era %s" % (p, melhor))
            t.append("\n\n")
        t.append("Momentos críticos (n / p)\n", style=Style(color=PAL["dim"]))
        if not self.criticos:
            t.append("nenhum: partida limpa!")
        for c in self.criticos:
            atual = c["ply"] == self.ply
            t.append(_nome_lance(self.sans, c["ply"]) + MARCA[c["classe"]] + "  ",
                     style=Style(bold=atual, reverse=atual,
                                 color=PAL["brancas"] if c["brancas"] else PAL["pretas"]))
        return t

    def _set(self, id_, conteudo):
        self.query_one("#" + id_, Static).update(conteudo)

    # ── navegação ──
    def _ir(self, ply):
        self.ply = max(0, min(len(self.lances), ply))
        self._desenhar()

    def action_anterior(self): self._ir(self.ply - 1)
    def action_proximo(self): self._ir(self.ply + 1)
    def action_inicio(self): self._ir(0)
    def action_fim(self): self._ir(len(self.lances))

    def action_virar(self):
        self.virado = not self.virado
        self._desenhar()

    def action_critico_prox(self):
        alvo = [c["ply"] for c in self.criticos if c["ply"] > self.ply] or [c["ply"] for c in self.criticos]
        if alvo:
            self._ir(alvo[0])

    def action_critico_ant(self):
        alvo = [c["ply"] for c in self.criticos if c["ply"] < self.ply] or [c["ply"] for c in self.criticos]
        if alvo:
            self._ir(alvo[-1])

    # ── análise (thread, para a tela não travar) ──
    def action_analisar(self):
        if self.analisando or not self.lances:
            return
        if not self.stockfish:
            self.notify("Stockfish não encontrado. Instale-o ou use --stockfish /caminho.", severity="error")
            return
        self.analisando = True
        self._rodar_analise()

    @work(thread=True, exclusive=True)
    def _rodar_analise(self):
        try:
            res = motor.analisar_posicoes(
                self.posicoes, self.stockfish, self.profundidade,
                progresso=lambda k, n: self.call_from_thread(self._progresso, k, n))
        except Exception as exc:  # motor ausente, travado, caminho errado...
            self.call_from_thread(self._falhou, str(exc))
            return
        self.call_from_thread(self._pronto, res)

    def _progresso(self, k, n):
        self.status = "Analisando... %d/%d" % (k, n)
        self._desenhar()

    def _falhou(self, msg):
        self.analisando, self.status = False, ""
        self.notify("Falha na análise: " + msg, severity="error")
        self._desenhar()

    def _pronto(self, res):
        self.analisando, self.status = False, ""
        self.aval = [cp for cp, _ in res]
        self.melhores = [m for _, m in res]
        self.criticos = analise.momentos_criticos(self.aval)
        self._desenhar()


def carregar_pgn(caminho, indice=0):
    with open(caminho, encoding="utf-8", errors="replace") as f:
        jogo = None
        for _ in range(indice + 1):
            jogo = chess.pgn.read_game(f)
            if jogo is None:
                break
    return jogo


def demo():
    """Abertura de memória (e4 Nc6 Bc4 d5 Bb3 e5 Nc3 Nf6 ...). Para no primeiro lance ilegal."""
    jogo = chess.pgn.Game()
    jogo.headers.update({"White": "Você", "Black": "Amigo", "Event": "Demo (de memória)", "Result": "*"})
    tab, no = jogo.board(), jogo
    for san in "e4 Nc6 Bc4 d5 Bb3 e5 Nc3 Nf6 Nf3 dxe4 Nxe4 Nxe4".split():
        try:
            mv = tab.parse_san(san)
        except ValueError:
            break
        no = no.add_variation(mv)
        tab.push(mv)
    return jogo


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chessyou", description="ChessYou!: analisador de partidas no terminal")
    ap.add_argument("pgn", nargs="?", help="arquivo .pgn (lichess / chess.com)")
    ap.add_argument("--partida", type=int, default=1, help="qual partida do arquivo (padrão: 1)")
    ap.add_argument("--demo", action="store_true", help="abre uma partida de exemplo")
    ap.add_argument("--stockfish", help="caminho do Stockfish (ou use a variável STOCKFISH)")
    ap.add_argument("--profundidade", type=int, default=14)
    a = ap.parse_args(argv)
    if not (a.pgn or a.demo):
        ap.error("informe um arquivo .pgn ou use --demo")
    jogo = demo() if a.demo else carregar_pgn(a.pgn, max(0, a.partida - 1))
    if jogo is None:
        ap.error("nenhuma partida encontrada nesse arquivo")
    ChessYou(jogo, motor.achar_stockfish(a.stockfish), a.profundidade).run()
    return 0
