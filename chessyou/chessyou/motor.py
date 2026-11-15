"""Ponte com o Stockfish (via python-chess). Precisa de: pip install chess  +  stockfish instalado."""
import os
import shutil

import chess
import chess.engine

from .analise import MATE_CP


def achar_stockfish(caminho=None):
    return caminho or os.environ.get("STOCKFISH") or shutil.which("stockfish")


def analisar_posicoes(posicoes, caminho, profundidade=14, progresso=None):
    """posicoes: lista de chess.Board. Devolve [(centipeoes_das_brancas, melhor_lance_em_SAN | None)]."""
    saida = []
    with chess.engine.SimpleEngine.popen_uci(caminho) as motor:
        for k, tab in enumerate(posicoes):
            if tab.is_checkmate():
                saida.append((-MATE_CP if tab.turn == chess.WHITE else MATE_CP, None))
            elif tab.is_game_over():
                saida.append((0, None))
            else:
                info = motor.analyse(tab, chess.engine.Limit(depth=profundidade))
                cp = info["score"].white().score(mate_score=MATE_CP)
                pv = info.get("pv")
                saida.append((cp, tab.san(pv[0]) if pv else None))
            if progresso:
                progresso(k + 1, len(posicoes))
    return saida
