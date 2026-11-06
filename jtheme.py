#!/usr/bin/env python3
"""
jtheme - temas e medidas compartilhados pelo JDev (JWM, JBar, JTerm, JDesk, JCode, JRun).

Temas:  tokyonight (padrão) · catppuccin (Mocha) · gruvbox (dark) · dawn (claro, quente, sem brilho)

Escolha do tema, em ordem:
    1. variável de ambiente  JTHEME=gruvbox
    2. arquivo               ~/.config/jdev/theme   (uma palavra)
    3. padrão                tokyonight

Linha de comando:
    python3 jtheme.py              lista os temas (o ativo vem marcado)
    python3 jtheme.py set gruvbox  grava a escolha (vale na próxima sessão / próximo JDesk)
    python3 jtheme.py show [nome]  mostra as cores no terminal

Só constantes e funções leves: pode ser importado por qualquer programa sem custo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Os temas. Cada cor tem um PAPEL (não um nome de tema): trocar de tema é trocar o dicionário.
# ══════════════════════════════════════════════════════════════════════════════
THEMES: dict[str, dict] = {
    "tokyonight": dict(
        label="Tokyo Night", light=False,
        bg_deep="#13141c", bg="#1a1b26", bg_alt="#1f2335", bg_hover="#2a2f45",
        line="#292e42", line2="#3b4261", select="#33467c",
        fg="#a9b1d6", fg_bright="#c0caf5", fg_soft="#9aa5ce", dim="#565f89", comment="#636da6", ln="#444b6a",
        secondary="#737aa2",
        on_bright="#16161e", on_accent="#fbe9ef", focus="#b04a67", border="#56566e",
        red="#f7768e", green="#9ece6a", yellow="#e0af68", orange="#ff9e64",
        blue="#7aa2f7", cyan="#7dcfff", cyan2="#89ddff", purple="#bb9af7",
        border_idle="#292e42", header_idle="#6b7394", header_focus="#16161e",
        ansi_black="#15161e", ansi_brightblack="#7b83a8", ansi_white="#a9b1d6", ansi_brightwhite="#c0caf5",
    ),
    "catppuccin": dict(
        label="Catppuccin Mocha", light=False,
        bg_deep="#11111b", bg="#1e1e2e", bg_alt="#313244", bg_hover="#45475a",
        line="#313244", line2="#45475a", select="#45475a",
        fg="#bac2de", fg_bright="#cdd6f4", fg_soft="#a6adc8", dim="#6c7086", comment="#7f849c", ln="#585b70",
        secondary="#9399b2",
        on_bright="#11111b", on_accent="#11111b", focus="#cba6f7", border="#585b70",
        red="#f38ba8", green="#a6e3a1", yellow="#f9e2af", orange="#fab387",
        blue="#89b4fa", cyan="#89dceb", cyan2="#94e2d5", purple="#cba6f7",
        border_idle="#313244", header_idle="#7f849c", header_focus="#11111b",
        ansi_black="#181825", ansi_brightblack="#7f849c", ansi_white="#bac2de", ansi_brightwhite="#cdd6f4",
    ),
    "gruvbox": dict(
        label="Gruvbox Dark", light=False,
        bg_deep="#1d2021", bg="#282828", bg_alt="#3c3836", bg_hover="#504945",
        line="#3c3836", line2="#504945", select="#504945",
        fg="#d5c4a1", fg_bright="#ebdbb2", fg_soft="#bdae93", dim="#928374", comment="#928374", ln="#665c54",
        secondary="#a89984",
        on_bright="#1d2021", on_accent="#1d2021", focus="#d3869b", border="#665c54",
        red="#fb4934", green="#b8bb26", yellow="#fabd2f", orange="#fe8019",
        blue="#83a598", cyan="#8ec07c", cyan2="#8ec07c", purple="#d3869b",
        border_idle="#3c3836", header_idle="#a89984", header_focus="#1d2021",
        ansi_black="#1d2021", ansi_brightblack="#928374", ansi_white="#a89984", ansi_brightwhite="#ebdbb2",
    ),
    # Claro de papel quente (inspirado no Rosé Pine Dawn): fundo creme, texto roxo-acinzentado de
    # contraste médio e acentos dessaturados. Nada de branco puro, que é o que cansa a vista.
    "dawn": dict(
        label="Dawn (claro)", light=True,
        bg_deep="#ebe1d6", bg="#faf4ed", bg_alt="#fffaf3", bg_hover="#f2e9e1",
        line="#dfdad9", line2="#cecacd", select="#e4d9e8",
        fg="#575279", fg_bright="#464261", fg_soft="#6e6a86", dim="#8a85a0", comment="#8a85a0", ln="#b9b4c2",
        secondary="#6e6a86",
        on_bright="#26233a", on_accent="#faf4ed", focus="#a8506a", border="#cecacd",
        red="#b4637a", green="#5a9a78", yellow="#b8791f", orange="#d7827e",
        blue="#286983", cyan="#56949f", cyan2="#56949f", purple="#907aa9",
        border_idle="#dfdad9", header_idle="#797593", header_focus="#faf4ed",
        ansi_black="#575279", ansi_brightblack="#9893a5", ansi_white="#797593", ansi_brightwhite="#464261",
    ),
}

ALIASES = {
    "tokyo": "tokyonight", "tokyo-night": "tokyonight", "tn": "tokyonight",
    "catppuccin-mocha": "catppuccin", "mocha": "catppuccin", "cat": "catppuccin",
    "gruvbox-dark": "gruvbox", "gruv": "gruvbox",
    "light": "dawn", "claro": "dawn", "rosepine-dawn": "dawn",
}
PADRAO = "tokyonight"


def _arquivo() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jdev" / "theme"


def _resolver(nome: str | None) -> str | None:
    n = (nome or "").strip().lower()
    n = ALIASES.get(n, n)
    return n if n in THEMES else None


def escolhido() -> str:
    nome = _resolver(os.environ.get("JTHEME"))
    if nome:
        return nome
    try:
        nome = _resolver(_arquivo().read_text(encoding="utf-8"))
    except OSError:
        nome = None
    return nome or PADRAO


NOME = escolhido()
T = THEMES[NOME]
LIGHT = bool(T["light"])

# ══════════════════════════════════════════════════════════════════════════════
#  Constantes públicas (os nomes que o resto do JDev importa)
# ══════════════════════════════════════════════════════════════════════════════
# fundos
DESK_BG = T["bg_deep"]       # fundo do JDesk; também é o "vazio" entre as pílulas da barra
PANE_BG = T["bg"]            # fundo dos painéis/terminais
PILL_BG = T["bg_alt"]        # fundo de cada pílula da JBar
PILL_HOVER = T["bg_hover"]
LINE = T["line"]
SELECT_BG = T["select"]

# textos
FG = T["fg"]
DIM = T["dim"]
DARK = T["on_bright"]        # texto sobre pílulas de cor viva (modo, divisão)
ON_ACCENT = T["on_accent"]   # texto sobre a cor de foco

# destaque
FOCUS = T["focus"]           # borda da janela focada (JWM) e workspace ativo (JBar)
BORDER = T["border"]         # borda das janelas sem foco
FLOAT = T["yellow"]          # janela flutuante
MODE = T["green"]            # modo resize ligado
BLUE, GREEN, YELLOW, RED = T["blue"], T["green"], T["yellow"], T["red"]
CYAN, PURPLE = T["cyan"], T["purple"]

# painéis do JDesk
BORDER_IDLE = T["border_idle"]
HEADER_FG_IDLE = T["header_idle"]
HEADER_FG_FOCUS = T["header_focus"]
ACCENTS = {"jfiles": BLUE, "jshell": GREEN, "jcode": PURPLE, "jclass": YELLOW}

# paleta ANSI do JTerm (nomes do pyte)
ANSI_BLACK_BG = T["ansi_black"]
ANSI_BLACK_FG = T["ansi_brightblack"]
COLOR_NAMES = {
    "black": ANSI_BLACK_BG, "red": T["red"], "green": T["green"], "brown": T["yellow"],
    "blue": T["blue"], "magenta": T["purple"], "cyan": T["cyan"], "white": T["ansi_white"],
    "brightblack": T["ansi_brightblack"], "brightred": T["red"], "brightgreen": T["green"],
    "brightbrown": T["yellow"], "brightyellow": T["yellow"], "brightblue": T["blue"],
    "brightmagenta": T["purple"], "brightcyan": T["cyan2"], "brightwhite": T["ansi_brightwhite"],
}

# medidas (px)
GAP = 8                      # espaço entre janelas e entre pílulas
BAR_H = 36                   # altura da faixa da barra (o JWM reserva exatamente isso embaixo)
PILL_H = 28


# ══════════════════════════════════════════════════════════════════════════════
#  Estilos do JCode (prompt_toolkit) gerados a partir do tema
# ══════════════════════════════════════════════════════════════════════════════
def estilo_jcode() -> dict:
    t = T
    return {
        "": f"{t['fg_bright']} bg:{t['bg']}",
        "background": f"bg:{t['bg']}",
        "header": f"{t['fg_bright']} bold bg:{t['line']}",
        "status": f"{t['fg_bright']} bg:{t['line']}",
        "status.error": f"{t['red']} bold bg:{t['line']}",
        "line-number": t["ln"],
        "line-number.current": f"{t['blue']} bold",
        "line-number.separator": t["line2"],
        "indent-guide": t["line2"],
        "pygments.keyword": t["purple"],
        "pygments.string": t["green"],
        "pygments.comment": t["comment"],
        "pygments.number": t["orange"],
        "pygments.name": t["fg_soft"],
        "pygments.name.function": t["blue"],
        "pygments.name.namespace": t["cyan"],
        "pygments.operator": t["cyan2"],
        "pygments.decorator": t["yellow"],
        "pygments.name.decorator": t["yellow"],
        "outline": f"bg:{t['bg_deep']}",
        "outline.header": f"{t['blue']} bold",
        "outline.selected": f"{t['yellow']} bold bg:{t['line']}",
        "outline.item": t["fg_bright"],
        "outline.empty": t["comment"],
        "completion-menu": f"bg:{t['line']} {t['fg_bright']}",
        "completion-menu.completion": f"bg:{t['line']} {t['fg_bright']}",
        "completion-menu.completion.current": f"bg:{t['blue']} {t['bg']} bold",
        "completion-menu.meta.completion": f"bg:{t['line']} {t['comment']}",
    }


def estilo_jcode_idle() -> dict:
    t = T
    return {"": f"bg:{t['bg']} {t['fg_bright']}", "titulo": f"{t['blue']} bold",
            "texto": t["fg_bright"], "dim": t["comment"]}


def estilo_jfiles() -> dict:
    t = T
    return {
        "": f"{t['fg_bright']} bg:{t['bg']}",
        "header": f"bg:{t['blue']} fg:{t['on_bright']} bold",
        "path": f"bg:{t['line']} fg:{t['fg_bright']} bold",
        "border": f"fg:{t['line2']} bg:{t['bg']}",
        "selected": f"bg:{t['line']} fg:{t['yellow']} bold",
        "item": f"fg:{t['fg_bright']} bg:{t['bg']}",
        "preview": f"fg:{t['fg_bright']} bg:{t['bg']}",
        "empty": f"fg:{t['comment']} bg:{t['bg']} italic",
        "footer": f"bg:{t['bg_deep']} fg:{t['fg_soft']} bold",
        "status": f"bg:{t['line']} fg:{t['green']} bold",
        "prompt": f"bg:{t['red']} fg:{t['on_bright']} bold",
        "outline": f"bg:{t['bg_deep']}",
        "outline.header": f"fg:{t['blue']} bg:{t['bg_deep']} bold",
        "outline.help": f"fg:{t['comment']} bg:{t['bg_deep']}",
        "outline.selected": f"bg:{t['line']} fg:{t['yellow']} bold",
        "outline.item": f"fg:{t['fg_bright']} bg:{t['bg_deep']}",
        "line-number.separator": f"fg:{t['line2']} bg:{t['bg']}",
    }


def estilo_jshell() -> dict:
    t = T
    return {
        "prompt": f"{t['cyan']} bold",
        "error": f"{t['red']} bold",
        "success": f"{t['green']} bold",
        "info": t["blue"],
        "secondary": t["secondary"],
        "command": f"{t['purple']} bold",
        "arg": t["yellow"],
        "auto-suggestion": t["dim"],
        # prompt "HUD": pílulas (sem setas) + barra de vida no canto direito
        "pill.cwd": f"bg:{t['line']} {t['blue']} bold",
        "pill.git": f"bg:{t['bg_alt']} {t['purple']}",
        "pill.gitdirty": f"bg:{t['bg_alt']} {t['yellow']}",
        "pill.err": f"bg:{t['red']} {t['on_bright']} bold",
        "pill.root": f"bg:{t['red']} {t['on_bright']} bold",
        "combo.full": f"bg:{t['green']} {t['on_bright']} bold",
        "combo.mid": f"bg:{t['yellow']} {t['on_bright']} bold",
        "combo.low": f"bg:{t['red']} {t['on_bright']} bold",
        "hp.full": t["green"],
        "hp.mid": t["yellow"],
        "hp.low": t["red"],
        "hp.empty": t["line2"],
        "rprompt": t["dim"],
        "continuation": t["dim"],
        # realce enquanto digita
        "cmd.ok": f"{t['green']} bold",
        "cmd.bad": t["red"],
        "kw": f"{t['purple']} bold",
        "str": t["yellow"],
        "var": t["cyan"],
        "op": t["purple"],
        "flag": t["blue"],
        "path": "underline",
        "comment": f"{t['dim']} italic",
        "dir": f"{t['blue']} bold",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Linha de comando
# ══════════════════════════════════════════════════════════════════════════════
def _bloco(hexcor: str) -> str:
    r, g, b = int(hexcor[1:3], 16), int(hexcor[3:5], 16), int(hexcor[5:7], 16)
    return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m"


def _mostrar(nome: str) -> None:
    t = THEMES[nome]
    print(f"{t['label']}  ({nome}{', claro' if t['light'] else ''})")
    chaves = ("bg_deep", "bg", "bg_alt", "fg", "dim", "focus", "red", "green", "yellow", "blue", "cyan", "purple")
    print("  " + "".join(_bloco(t[k]) for k in chaves))
    print("  " + " ".join(chaves))


def _main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd in ("list", "ls"):
        for nome, t in THEMES.items():
            marca = "*" if nome == NOME else " "
            print(f" {marca} {nome:<11} {t['label']}")
        print(f"\nfonte: {'JTHEME' if _resolver(os.environ.get('JTHEME')) else _arquivo()}")
        return 0
    if cmd == "set" and len(argv) == 2:
        nome = _resolver(argv[1])
        if not nome:
            print(f"tema desconhecido: {argv[1]}. Opções: {', '.join(THEMES)}", file=sys.stderr)
            return 2
        arq = _arquivo()
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(nome + "\n", encoding="utf-8")
        print(f"tema '{nome}' gravado em {arq}.")
        print("Vale na próxima vez que o JWM/JDesk subir (saia e entre na sessão; Super+Shift+Q).")
        if os.environ.get("JTHEME"):
            print("Aviso: a variável JTHEME está definida e tem prioridade sobre o arquivo.")
        return 0
    if cmd == "show":
        for nome in ([_resolver(argv[1])] if len(argv) > 1 and _resolver(argv[1]) else THEMES):
            _mostrar(nome)
            print()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
