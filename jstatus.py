"""jstatus - barra de status do JCode: pílulas (como a JBar), ícone do tipo do arquivo, ramo do git.

Tudo aqui é função pura (sem prompt_toolkit): `montar_status` devolve fragmentos (classe, texto)
que o JCode desenha, e `estilos_status` gera as classes a partir do tema ativo.
Com Nerd Font (JICONES=nerd, o padrão dentro do JTerm) as pílulas têm pontas arredondadas e o
arquivo ganha ícone; sem ela, cai num visual simples que funciona em qualquer terminal.
"""
from __future__ import annotations

from pathlib import Path

CAP_E, CAP_D = "", ""
RAMO = ""

# extensão -> (nome da linguagem, ícone nerd, cor da paleta)
LINGUAGENS = {
    ".py": ("Python", "", "yellow"), ".pyw": ("Python", "", "yellow"),
    ".js": ("JavaScript", "", "yellow"), ".mjs": ("JavaScript", "", "yellow"),
    ".ts": ("TypeScript", "", "blue"), ".tsx": ("TypeScript", "", "blue"),
    ".json": ("JSON", "", "yellow"), ".md": ("Markdown", "", "cyan"),
    ".markdown": ("Markdown", "", "cyan"), ".html": ("HTML", "", "orange"),
    ".css": ("CSS", "", "blue"), ".sh": ("Shell", "", "green"),
    ".bash": ("Shell", "", "green"), ".zsh": ("Shell", "", "green"),
    ".c": ("C", "", "blue"), ".h": ("C", "", "blue"),
    ".cpp": ("C++", "", "blue"), ".hpp": ("C++", "", "blue"),
    ".rs": ("Rust", "", "orange"), ".go": ("Go", "", "cyan"),
    ".java": ("Java", "", "red"), ".rb": ("Ruby", "", "red"),
    ".php": ("PHP", "", "purple"), ".lua": ("Lua", "", "blue"),
    ".toml": ("TOML", "", "dim"), ".yml": ("YAML", "", "dim"),
    ".yaml": ("YAML", "", "dim"), ".txt": ("Texto", "", "fg"),
}
PADRAO_ARQ = ("Texto", "", "fg")

# nome da pílula -> (cor do texto, cor do fundo, negrito) em chaves da paleta
PILULAS = {
    "arq": ("fg_bright", "line", False), "git": ("purple", "bg_alt", False),
    "m.busca": ("on_bright", "yellow", True), "m.ir": ("on_bright", "cyan", True),
    "m.sel": ("on_bright", "purple", True), "m.exp": ("on_bright", "green", True),
    "err": ("on_bright", "red", True), "pos": ("fg_bright", "line", True),
    "pct": ("fg_soft", "bg_alt", False), "lang": ("blue", "bg_alt", False),
    "flag": ("yellow", "bg_alt", False),
}

PALETA_PADRAO = {
    "bg_deep": "#13141c", "bg_alt": "#1f2335", "line": "#292e42", "line2": "#3b4261",
    "fg_bright": "#c0caf5", "fg": "#a9b1d6", "fg_soft": "#9aa5ce", "dim": "#565f89",
    "on_bright": "#16161e", "red": "#f7768e", "green": "#9ece6a", "yellow": "#e0af68",
    "orange": "#ff9e64", "blue": "#7aa2f7", "cyan": "#7dcfff", "purple": "#bb9af7",
}


def paleta(jtheme=None) -> dict:
    """Cores do tema ativo (jtheme.T) completando o que faltar com o Tokyo Night."""
    p = dict(PALETA_PADRAO)
    t = getattr(jtheme, "T", None)
    if isinstance(t, dict):
        p.update({k: v for k, v in t.items() if k in p and isinstance(v, str)})
    return p


def estilos_status(jtheme=None) -> dict:
    p = paleta(jtheme)
    est = {"st.bar": f"{p['fg']} bg:{p['bg_deep']}", "st.msg": f"{p['yellow']} bg:{p['bg_deep']}",
           "st.erro": f"{p['red']} bold bg:{p['bg_deep']}"}
    for nome, (fg, bg, negrito) in PILULAS.items():
        est[f"st.{nome}"] = f"{p[fg]} bg:{p[bg]}" + (" bold" if negrito else "")
        est[f"st.{nome}.cap"] = f"{p[bg]} bg:{p['bg_deep']}"      # ponta arredondada: cor da pílula sobre a barra
    for cor in ("yellow", "blue", "green", "red", "orange", "cyan", "purple", "dim", "fg"):
        est[f"st.ico.{cor}"] = f"{p[cor]} bg:{p['line']}"
    est["st.arq.mod"] = f"{p['yellow']} bold bg:{p['line']}"
    est["st.arq.ok"] = f"{p['green']} bg:{p['line']}"
    est["st.arq.err"] = f"{p['red']} bold bg:{p['line']}"
    est["st.pct.cheio"] = f"{p['blue']} bg:{p['bg_alt']}"
    est["st.pct.vazio"] = f"{p['line2']} bg:{p['bg_alt']}"
    return est


def linguagem(nome_arquivo: str):
    return LINGUAGENS.get(Path(nome_arquivo).suffix.lower(), PADRAO_ARQ)


def ramo_git(caminho) -> str | None:
    """Ramo atual lendo .git/HEAD (sem rodar o git). None se não estiver num repositório."""
    try:
        pasta = Path(caminho).resolve().parent
        for _ in range(25):
            g = pasta / ".git"
            if g.is_file():                        # worktree/submódulo: "gitdir: caminho"
                txt = g.read_text(encoding="utf-8", errors="replace").strip()
                if txt.startswith("gitdir:"):
                    g = (pasta / txt[7:].strip()).resolve()
            if g.is_dir():
                head = (g / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
                if head.startswith("ref:"):
                    return head.rsplit("/", 1)[-1]
                return head[:7] or None
            if pasta.parent == pasta:
                return None
            pasta = pasta.parent
    except OSError:
        return None
    return None


def _tam(frags) -> int:
    return sum(len(t) for _, t in frags)


def _pilula(nome: str, partes, nerd: bool):
    """partes: texto (str) ou lista de (classe_extra | None, texto). Devolve fragmentos da pílula."""
    if isinstance(partes, str):
        partes = [(None, partes)]
    classe = f"class:st.{nome}"
    out = []
    if nerd:
        out.append((f"{classe}.cap", CAP_E))
    out.append((classe, " "))
    for extra, txt in partes:
        out.append((f"class:{extra}" if extra else classe, txt))
    out.append((classe, " "))
    if nerd:
        out.append((f"{classe}.cap", CAP_D))
    return out


def _elidir(txt: str, n: int) -> str:
    return txt if len(txt) <= n else (txt[:max(0, n - 1)] + "…" if n > 0 else "")


def _barra(pct: int, celulas: int = 8):
    cheio = round(celulas * pct / 100)
    return [("st.pct.cheio", "━" * cheio), ("st.pct.vazio", "─" * (celulas - cheio))]


def montar_status(e: dict, largura: int, nerd: bool = False):
    """Fragmentos (classe, texto) da barra de status, ocupando exatamente `largura` colunas.

    Campos de `e`: nome, modificado, salvo_ok, erro_salvar, modo ("busca"|"ir"|"sel"|"exp"|None),
    modo_texto, linha, coluna, total, ramo, flags (lista), erro_sintaxe ((linha, msg) | None),
    mensagens (lista de str).
    """
    largura = max(20, largura)
    lang, glifo, cor = linguagem(e["nome"])
    esq, dir_ = [], []

    # ── esquerda: arquivo (ícone, nome, estado) ──
    if e.get("modificado"):
        estado = ("st.arq.mod", "●")
    elif e.get("salvo_ok", True):
        estado = ("st.arq.ok", "✓")
    else:
        estado = ("st.arq.err", "!")
    nome = _elidir(e["nome"], max(8, largura // 3))
    partes = ([(f"st.ico.{cor}", glifo), (None, " ")] if nerd else []) + [(None, nome), (None, " "), estado]
    esq += _pilula("arq", partes, nerd)

    bloco_modo = bloco_git = []
    if e.get("modo"):
        rotulo = {"busca": "BUSCAR", "ir": "IR", "sel": "SELEÇÃO", "exp": "EXPLORAR"}.get(e["modo"], e["modo"].upper())
        txt = rotulo + (f" {e.get('modo_texto', '')}▏" if e["modo"] in ("busca", "ir") else "")
        bloco_modo = [("class:st.bar", " ")] + _pilula(f"m.{e['modo']}", _elidir(txt, max(10, largura // 3)), nerd)
    if e.get("ramo"):
        bloco_git = [("class:st.bar", " ")] + _pilula("git", f"{RAMO} {_elidir(e['ramo'], 24)}" if nerd else f"⎇ {_elidir(e['ramo'], 24)}", nerd)
    arq = esq
    esq = arq + bloco_modo + bloco_git
    if _tam(esq) > largura - 2:          # tela estreita: o ramo é o primeiro a sair, depois o modo
        esq = arq + bloco_modo
    if _tam(esq) > largura - 2:
        esq = arq

    # ── direita (do mais importante ao menos): posição, progresso, linguagem, flags ──
    total = max(1, e.get("total", 1))
    pct = min(100, max(0, round(100 * (e["linha"] + 1) / total)))
    blocos_dir = [
        _pilula("pos", f"{e['linha'] + 1}:{e['coluna'] + 1}", nerd),
        _pilula("pct", _barra(pct) + [(None, f" {pct:>3}%")], nerd),
        _pilula("lang", lang, nerd),
    ]
    if e.get("flags"):
        blocos_dir.append(_pilula("flag", " ".join(e["flags"]), nerd))

    # ── meio: erro de sintaxe, mensagens ──
    meio_txt, meio_cls = "", "st.msg"
    if e.get("erro_salvar"):
        meio_txt, meio_cls = f"✗ {e['erro_salvar']}", "st.erro"
    elif e.get("erro_sintaxe"):
        l, msg = e["erro_sintaxe"]
        meio_txt, meio_cls = f"✗ L{l if l is not None else '?'}: {msg}", "st.erro"
    msgs = [m for m in e.get("mensagens", []) if m]
    if msgs:
        meio_txt = (meio_txt + "  ·  " if meio_txt else "") + "  ·  ".join(msgs)

    # corta pela direita (menos importante primeiro) até caber, deixando espaço para o erro/mensagem
    reserva = min(len(meio_txt) + 2, 40) if meio_txt else 0
    while len(blocos_dir) > 1 and _tam(esq) + sum(_tam(b) + 1 for b in blocos_dir) + reserva + 1 > largura:
        blocos_dir.pop()                 # a posição (primeiro bloco) fica; a mensagem é que encolhe
    if blocos_dir and _tam(esq) + _tam(blocos_dir[0]) + 1 > largura:
        blocos_dir = []
    dir_ = []
    for b in blocos_dir:
        dir_ += [("class:st.bar", " ")] + b
    livre = largura - _tam(esq) - _tam(dir_)
    meio = []
    if meio_txt and livre > 4:
        meio = [(f"class:{meio_cls}", " " + _elidir(meio_txt, livre - 2) + " ")]
    folga = max(0, largura - _tam(esq) - _tam(meio) - _tam(dir_))
    return esq + meio + [("class:st.bar", " " * folga)] + dir_
