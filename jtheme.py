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
    python3 jtheme.py check [nome] confere chaves, cores e contraste (aponta o valor errado)

Só constantes e funções leves: pode ser importado por qualquer programa sem custo.
"""
from __future__ import annotations

import os
import re
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
    "ashes": dict(
        label="Ashes of the Wake", light=False,
        bg_deep="#101713", bg="#18231e", bg_alt="#22332b", bg_hover="#304338",
        line="#2c4035", line2="#49604c", select="#6a4932",
        fg="#d8c6a0", fg_bright="#f0dfb5", fg_soft="#b8b497", dim="#82907b", comment="#71806c", ln="#536252",
        secondary="#a79a73",
        on_bright="#151914", on_accent="#151914", focus="#d15b32", border="#59624c",
        red="#d94b2f", green="#a8a94e", yellow="#d7ad55", orange="#e77a36",
        blue="#638c79", cyan="#72a99a", cyan2="#9fc4b0", purple="#a17c79",
        border_idle="#2c4035", header_idle="#9a9a70", header_focus="#151914",
        ansi_black="#151914", ansi_brightblack="#71806c", ansi_white="#d8c6a0", ansi_brightwhite="#f0dfb5",
    ),

    # Deftones — Around the Fur: azul frio, carvão e tons quentes de pele.
    "around_the_fur": dict(
        label="Around the Fur", light=False,
        bg_deep="#090d13", bg="#111923", bg_alt="#1b2835", bg_hover="#293746",
        line="#263746", line2="#40566a", select="#3d5368",
        fg="#c5cbd0", fg_bright="#e8e3dc", fg_soft="#aab6c1", dim="#718292", comment="#687887", ln="#4b5d6d",
        secondary="#9aa8b3",
        on_bright="#10151b", on_accent="#10151b", focus="#d58b79", border="#596a78",
        red="#d97870", green="#9eaa91", yellow="#d6b58b", orange="#d99573",
        blue="#789bb8", cyan="#8db5c8", cyan2="#b0cbd5", purple="#a99ab8",
        border_idle="#263746", header_idle="#9aa8b3", header_focus="#10151b",
        ansi_black="#10151b", ansi_brightblack="#718292", ansi_white="#c5cbd0", ansi_brightwhite="#e8e3dc",
    ),

    # Capa escura de pintura e papel envelhecido: preto, vinho e vermelho queimado.
    "hipopoto": dict(
        label="Hipopoto", light=False,
        bg_deep="#090808", bg="#141111", bg_alt="#211918", bg_hover="#302321",
        line="#382725", line2="#59403a", select="#63312d",
        fg="#c9b8a7", fg_bright="#ead9c6", fg_soft="#b9a698", dim="#806e67", comment="#78645e", ln="#594943",
        secondary="#a68b7c",
        on_bright="#100b0b", on_accent="#f2ded0", focus="#b63e35", border="#72514a",
        red="#d34b3f", green="#8e9a72", yellow="#c6a16a", orange="#d16a45",
        blue="#778a91", cyan="#8ba6a3", cyan2="#b0c2b8", purple="#a77b82",
        border_idle="#382725", header_idle="#a68b7c", header_focus="#100b0b",
        ansi_black="#100b0b", ansi_brightblack="#78645e", ansi_white="#c9b8a7", ansi_brightwhite="#ead9c6",
    ),

    # Cinza neutro: grafite, aço e branco suave.
    "carbon": dict(
        label="Carbon", light=False,
        bg_deep="#101112", bg="#191b1e", bg_alt="#24272b", bg_hover="#30343a",
        line="#2c3035", line2="#454b53", select="#414a55",
        fg="#c1c5ca", fg_bright="#eceff2", fg_soft="#a9afb7", dim="#777f89", comment="#737b84", ln="#555d66",
        secondary="#969da6",
        on_bright="#111315", on_accent="#111315", focus="#b5bec8", border="#626b75",
        red="#d97878", green="#9caf91", yellow="#d4bd83", orange="#d69a72",
        blue="#8da9c4", cyan="#91b9bf", cyan2="#b1cbd0", purple="#b1a0c7",
        border_idle="#2c3035", header_idle="#969da6", header_focus="#111315",
        ansi_black="#111315", ansi_brightblack="#737b84", ansi_white="#c1c5ca", ansi_brightwhite="#eceff2",
    ),

    # Monokai clássico: fundo quase preto e acentos vivos.
    "monokai": dict(
        label="Monokai", light=False,
        bg_deep="#171814", bg="#272822", bg_alt="#34352d", bg_hover="#414238",
        line="#3e3d32", line2="#5b5a4f", select="#49483e",
        fg="#cfcfc2", fg_bright="#f8f8f2", fg_soft="#b8b8a9", dim="#858577", comment="#75715e", ln="#666658",
        secondary="#a6a696",
        on_bright="#1b1c17", on_accent="#1b1c17", focus="#f92672", border="#68685c",
        red="#f92672", green="#a6e22e", yellow="#e6db74", orange="#fd971f",
        blue="#66d9ef", cyan="#66d9ef", cyan2="#a1efe4", purple="#ae81ff",
        border_idle="#3e3d32", header_idle="#a6a696", header_focus="#1b1c17",
        ansi_black="#1b1c17", ansi_brightblack="#75715e", ansi_white="#cfcfc2", ansi_brightwhite="#f8f8f2",
    ),

    # Nord: azul glacial e cinzas frios.
    "nord": dict(
        label="Nord", light=False,
        bg_deep="#242933", bg="#2e3440", bg_alt="#3b4252", bg_hover="#434c5e",
        line="#3b4252", line2="#4c566a", select="#4c607d",
        fg="#d8dee9", fg_bright="#eceff4", fg_soft="#c5cedb", dim="#7b88a1", comment="#737f96", ln="#596579",
        secondary="#aeb9ca",
        on_bright="#242933", on_accent="#242933", focus="#88c0d0", border="#68758a",
        red="#bf616a", green="#a3be8c", yellow="#ebcb8b", orange="#d08770",
        blue="#81a1c1", cyan="#88c0d0", cyan2="#8fbcbb", purple="#b48ead",
        border_idle="#3b4252", header_idle="#aeb9ca", header_focus="#242933",
        ansi_black="#242933", ansi_brightblack="#737f96", ansi_white="#d8dee9", ansi_brightwhite="#eceff4",
    ),

    # Everforest: verde musgo, madeira e tons suaves.
    "everforest": dict(
        label="Everforest", light=False,
        bg_deep="#1e2320", bg="#2d353b", bg_alt="#343f3e", bg_hover="#414b50",
        line="#3d484d", line2="#56635f", select="#4b5c55",
        fg="#d3c6aa", fg_bright="#e9e2d0", fg_soft="#c2b89f", dim="#859289", comment="#829181", ln="#65736b",
        secondary="#a7b0a0",
        on_bright="#202725", on_accent="#202725", focus="#a7c080", border="#66766b",
        red="#e67e80", green="#a7c080", yellow="#dbbc7f", orange="#e69875",
        blue="#7fbbb3", cyan="#83c092", cyan2="#9ecf9f", purple="#d699b6",
        border_idle="#3d484d", header_idle="#a7b0a0", header_focus="#202725",
        ansi_black="#202725", ansi_brightblack="#829181", ansi_white="#d3c6aa", ansi_brightwhite="#e9e2d0",
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
    "around-the-fur": "around_the_fur", "atf": "around_the_fur",
    "hipopot(o)": "hipopoto", "hipo": "hipopoto",
    "gray": "carbon", "grey": "carbon", "grafite": "carbon",
    "monokai-classic": "monokai",
    "nordic": "nord",
    "ever-forest": "everforest",
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


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _luz(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luz(a), _luz(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (cor do texto, cor do fundo, minimo, o que mede)
_CONTRASTES_ERRO = (
    ("fg", "bg", 6.0, "texto sobre o fundo"),
    ("on_accent", "focus", 3.5, "texto sobre a cor de foco"),
    ("on_bright", "green", 3.5, "texto sobre o verde do modo"),
)
_CONTRASTES_AVISO = (
    ("dim", "bg_alt", 2.5, "texto apagado sobre a pilula"),
    ("comment", "bg", 3.0, "comentarios sobre o fundo"),
)


def validar(nome: str | None = None) -> list[tuple[str, str, str]]:
    """Confere os temas. Devolve (nivel, tema, mensagem); nivel = ERRO ou AVISO."""
    ref = THEMES["tokyonight"]
    saida: list[tuple[str, str, str]] = []
    for n, t in THEMES.items():
        if nome and n != nome:
            continue
        for k in sorted(set(ref) - set(t)):
            saida.append(("ERRO", n, f"falta a chave '{k}'"))
        for k in sorted(set(t) - set(ref)):
            saida.append(("ERRO", n, f"chave desconhecida '{k}' (erro de digitacao?)"))
        invalido = False
        for k, v in t.items():
            if k in ("label", "light") or k not in ref:
                continue
            if not isinstance(v, str) or not _HEX.match(v):
                invalido = True
                dica = ""
                if isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{6}", v):
                    dica = " (falta o # no comeco)"
                elif isinstance(v, str) and re.fullmatch(r"#?[0-9a-fA-F]{3}", v):
                    dica = " (3 digitos nao valem: usar 6, ex.: #aabbcc)"
                saida.append(("ERRO", n, f"{k} = {v!r} nao e uma cor valida{dica}"))
        if invalido:
            continue
        for a, b, minimo, rotulo in _CONTRASTES_ERRO:
            if a in t and b in t:
                c = _contraste(t[a], t[b])
                if c < minimo:
                    saida.append(("ERRO", n, f"{rotulo}: contraste {c:.1f} (minimo {minimo}); ajustar {a} ou {b}"))
        for a, b, minimo, rotulo in _CONTRASTES_AVISO:
            if a in t and b in t:
                c = _contraste(t[a], t[b])
                if c < minimo:
                    saida.append(("AVISO", n, f"{rotulo}: contraste {c:.1f} (ideal {minimo}+)"))
    return saida


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
    if cmd == "check":
        alvo = _resolver(argv[1]) if len(argv) > 1 else None
        if len(argv) > 1 and not alvo:
            print(f"tema desconhecido: {argv[1]}", file=sys.stderr)
            return 2
        problemas = validar(alvo)
        for nivel, n, msg in problemas:
            print(f"{nivel:<5} {n}: {msg}")
        erros = sum(1 for p in problemas if p[0] == "ERRO")
        print(f"{erros} erro(s), {len(problemas) - erros} aviso(s) em {1 if alvo else len(THEMES)} tema(s)")
        return 1 if erros else 0
    if cmd == "show":
        for nome in ([_resolver(argv[1])] if len(argv) > 1 and _resolver(argv[1]) else THEMES):
            _mostrar(nome)
            print()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
