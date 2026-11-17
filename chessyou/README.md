# ChessYou!

Analisador de partidas de xadrez para o terminal (Textual + python-chess + Stockfish).
Tabuleiro cercado, com coordenadas nas bordas e peças em letras: azul = brancas, vermelho = pretas.
Barra de vantagem na direita; embaixo, a análise do Stockfish e a lista de lances. As cores vêm do `jtheme` do JDev quando ele é achado
(`~/JDev` ou `JDEV_DIR`).

## Usar
```bash
pip install --user -r requirements.txt     # no Void: sudo xbps-install -S stockfish
python -m chessyou --demo                  # partida de exemplo
python -m chessyou minha_partida.pgn       # PGN do lichess/chess.com (--partida N escolhe a N-ésima)
```
Teclas: `←` `→` lances · `Home`/`End` · `a` analisar (Stockfish) · `n`/`p` próximo/anterior erro · `f` virar · `q` sair.
Stockfish fora do PATH? `--stockfish /caminho` ou `STOCKFISH=...`.

## Como os erros são medidos
Pela queda na chance de vitória (fórmula do lichess), não em peões: 10% = imprecisão (?!), 20% = erro (?), 30% = gafe (??).

## Testes
`python3 -m unittest discover -s tests -t .` (cobre a lógica pura; a tela ainda não tem teste).
