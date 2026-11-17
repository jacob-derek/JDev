#!/usr/bin/env python3
"""
JCava - cava com as cores do tema ativo do JDev.

    python3 tools/JCava.py             gera ~/.config/jdev/cava.conf e abre o cava
    python3 tools/JCava.py --print     só mostra a configuração
    python3 tools/JCava.py --install   grava em ~/.config/cava/config (o antigo vira config.bak)

    --estilo chama|acento|frio   chama (padrão): vinho -> cor de foco -> amarelo -> marfim
                                 acento: um tom só, a cor de foco do tema
                                 frio: azul -> ciano -> verde
    --fps N                      quadros por segundo (padrão 30: leve para o Tk)
    --fonte NOME                 fonte de áudio do Pulse (padrão: o monitor da saída padrão)

As cores vêm do jtheme.py (o tema de `python3 jtheme.py set <nome>`); sem ele vale o Tokyo Night.
Trocou de tema? Rode de novo (ou use --install de novo).

Por que "noncurses": o modo ncurses do cava redefine a paleta do terminal (sequência OSC 4), que o
JTerm (pyte) ignora, e as cores saem erradas. O noncurses manda cores 24 bits direto no texto.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
for _p in (AQUI.parent, AQUI):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    import jtheme as _t
except ImportError:
    _t = None

HEX = re.compile(r"#[0-9a-fA-F]{6}")
CONF_JDEV = Path.home() / ".config" / "jdev" / "cava.conf"
CONF_CAVA = Path.home() / ".config" / "cava" / "config"

# Equalizador de graves/agudos que já estava na sua configuração (um valor por faixa).
EQ = (1.6, 1.5, 1.3, 1.1, 1.0, 1.0, 1.1, 1.2)


def _cor(nome, padrao):
    valor = getattr(_t, nome, padrao)
    return valor if isinstance(valor, str) and HEX.fullmatch(valor) else padrao


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mistura(a, b, t):
    """Cor entre a (t=0) e b (t=1)."""
    return _hex(tuple(x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))))


def gradiente(ancoras, n=8):
    """n cores espaçadas entre as âncoras (de baixo para cima, como o cava espera)."""
    if len(ancoras) == 1:
        return list(ancoras) * n
    saida = []
    for i in range(n):
        pos = i * (len(ancoras) - 1) / (n - 1)
        k = min(int(pos), len(ancoras) - 2)
        saida.append(mistura(ancoras[k], ancoras[k + 1], pos - k))
    return saida


def paleta(estilo):
    fundo = _cor("PANE_BG", "#1a1b26")
    fg = _cor("FG", "#a9b1d6")
    foco = _cor("FOCUS", "#b04a67")
    amarelo = _cor("YELLOW", "#e0af68")
    if estilo == "acento":
        ancoras = [mistura(fundo, foco, 0.45), foco, mistura(foco, fg, 0.55)]
    elif estilo == "frio":
        ancoras = [_cor("BLUE", "#7aa2f7"), _cor("CYAN", "#7dcfff"), _cor("GREEN", "#9ece6a")]
    else:  # chama
        ancoras = [mistura(fundo, foco, 0.55), foco, amarelo, mistura(amarelo, fg, 0.6)]
    return gradiente(ancoras), fg


def nome_do_tema():
    nome = os.environ.get("JTHEME", "")
    if not nome:
        try:
            nome = (Path.home() / ".config" / "jdev" / "theme").read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return nome or "padrão (Tokyo Night)"


def fonte_de_audio(forcada=None):
    """Monitor da saída padrão do Pulse/PipeWire; se não achar, deixa o cava escolher."""
    if forcada:
        return forcada
    try:
        saida = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                               timeout=2).stdout.strip()
        if saida:
            return saida + ".monitor"
    except (OSError, subprocess.SubprocessError):
        pass
    return "auto"


def gerar(estilo="chama", fps=30, fonte=None):
    cores, fg = paleta(estilo)
    linhas = [
        f"# Gerado por tools/JCava.py a partir do tema do JDev: {nome_do_tema()} (estilo {estilo}).",
        "# Mude o tema com `python3 jtheme.py set <nome>` e rode o JCava de novo.",
        "",
        "[general]",
        f"framerate = {fps}",
        "bars = 0",            # 0 = preenche a largura do terminal
        "bar_width = 2",
        "bar_spacing = 1",
        "alignment = center",
        "autosens = 1",        # ajusta sozinho ao volume (o fixo estourava ou sumia ao mexer no volume)
        "sensitivity = 100",
        "lower_cutoff_freq = 35",
        "higher_cutoff_freq = 16000",
        "",
        "[input]",
        "method = pulse",
        f"source = {fonte_de_audio(fonte)}",
        "",
        "[output]",
        "method = noncurses",
        "channels = stereo",
        "",
        "[color]",
        "background = 'default'",   # o fundo é o do painel do JTerm
        f"foreground = '{fg}'",
        "gradient = 1",
        f"gradient_count = {len(cores)}",
    ]
    linhas += [f"gradient_color_{i} = '{c}'" for i, c in enumerate(cores, 1)]
    linhas += [
        "",
        "[smoothing]",
        "monstercat = 1",
        "waves = 0",
        "noise_reduction = 60",
        "",
        "[eq]",
    ]
    linhas += [f"{i} = {v}" for i, v in enumerate(EQ, 1)]
    return "\n".join(linhas) + "\n"


def gravar(caminho, texto, guardar_antigo=False):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if guardar_antigo and caminho.exists() and caminho.read_text(encoding="utf-8") != texto:
        backup = caminho.with_name(caminho.name + ".bak")
        if backup.exists():
            backup = caminho.with_name(f"{caminho.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(caminho, backup)
        print(f"Configuração antiga guardada em {backup}")
    caminho.write_text(texto, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="cava com as cores do tema ativo do JDev")
    ap.add_argument("--print", action="store_true", help="só mostra a configuração")
    ap.add_argument("--install", action="store_true", help="grava em ~/.config/cava/config")
    ap.add_argument("--estilo", choices=("chama", "acento", "frio"), default="chama")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--fonte", default=None)
    args = ap.parse_args()

    texto = gerar(args.estilo, max(10, min(args.fps, 120)), args.fonte)
    if args.print:
        print(texto, end="")
        return 0
    if args.install:
        gravar(CONF_CAVA, texto, guardar_antigo=True)
        print(f"Gravado em {CONF_CAVA}")
        return 0
    cava = shutil.which("cava")
    if not cava:
        print("cava não encontrado. No Void: sudo xbps-install -S cava", file=sys.stderr)
        return 1
    gravar(CONF_JDEV, texto)
    os.execv(cava, [cava, "-p", str(CONF_JDEV)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
