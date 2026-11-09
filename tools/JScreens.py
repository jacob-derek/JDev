#!/usr/bin/env python3
"""
JScreens - organiza os monitores com o mouse e salva a disposicao.

    python3 JScreens.py            abre a janela (arrastar monitores, rotacao, resolucao)
    python3 JScreens.py --apply    aplica a disposicao salva (o jwm-layout chama isto ao iniciar)
    python3 JScreens.py --show     mostra a disposicao atual em JSON
    python3 JScreens.py --save     salva a disposicao atual como padrao

Config: ~/.config/jdev/screens.json (JSCREENS_CONFIG muda o caminho)
Teclas na janela: setas movem o monitor (10 px; Shift 100 px), Tab troca de monitor, Esc fecha.

Vive em tools/ (ferramenta). A parte de cima do arquivo (parse, montar_args, encaixar...) nao usa Tk: tem testes em tests/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Fica em tools/: a raiz do JDev (jtheme.py, jwm-wallpaper) tambem entra no caminho de busca.
_AQUI = Path(__file__).resolve().parent
for _p in (_AQUI, _AQUI.parent):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

ROTACOES = ("normal", "left", "right", "inverted")
ROTULOS = {"normal": "Normal", "left": "Esquerda", "right": "Direita", "inverted": "Invertido"}
MODOS_EXTRA = ("1920x1080", "1600x900", "1366x768", "1280x720", "1024x768")
VERSAO = 1
Ret = tuple[int, int, int, int]  # x, y, largura, altura


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════
def caminho_config() -> Path:
    env = os.environ.get("JSCREENS_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jdev" / "screens.json"


def carregar_config(caminho: Path | None = None) -> dict | None:
    """Le o JSON salvo. Devolve None se nao existe ou se esta invalido."""
    p = caminho or caminho_config()
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dados, dict) or not isinstance(dados.get("saidas"), dict):
        return None
    return dados


def salvar_config(cfg: dict, caminho: Path | None = None) -> Path:
    p = caminho or caminho_config()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  xrandr: ler o estado
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Saida:
    nome: str
    conectada: bool = False
    ativa: bool = False
    primaria: bool = False
    x: int = 0
    y: int = 0
    w: int = 0            # tamanho atual, ja com a rotacao
    h: int = 0
    rotacao: str = "normal"
    modo: str | None = None       # "1600x900"
    taxa: float | None = None
    modos: dict[str, list[float]] = field(default_factory=dict)   # "1600x900" -> [60.0, 59.9]
    alias: dict[str, str] = field(default_factory=dict)           # "1600x900" -> "1600x900_60.00" (modo criado)


_GEOM = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")
_MODO = re.compile(r"^\s+(\d+x\d+)(\S*)\s+(.*)$")
_TAXA = re.compile(r"^(\d+(?:\.\d+)?)([*+]*)$")


def parse_query(texto: str) -> list[Saida]:
    """Interpreta a saida de `xrandr --query`."""
    saidas: list[Saida] = []
    atual: Saida | None = None
    for linha in texto.splitlines():
        if not linha.strip() or linha.startswith("Screen"):
            continue
        if not linha[0].isspace():
            tok = linha.split()
            if len(tok) < 2 or tok[1] not in ("connected", "disconnected"):
                atual = None
                continue
            atual = Saida(nome=tok[0], conectada=tok[1] == "connected")
            saidas.append(atual)
            i = 2
            if i < len(tok) and tok[i] == "primary":
                atual.primaria = True
                i += 1
            if i < len(tok):
                m = _GEOM.match(tok[i])
                if m:
                    atual.ativa = True
                    atual.w, atual.h, atual.x, atual.y = (int(g) for g in m.groups())
                    i += 1
                    if i < len(tok) and tok[i] in ROTACOES:
                        atual.rotacao = tok[i]
            continue
        if atual is None:
            continue
        m = _MODO.match(linha)
        if not m:
            continue
        base, sufixo, resto = m.groups()
        if sufixo.startswith("_"):
            atual.alias[base] = base + sufixo
        taxas = atual.modos.setdefault(base, [])
        for t in resto.split():
            mt = _TAXA.match(t)
            if not mt:
                continue
            taxa = float(mt.group(1))
            if taxa not in taxas:
                taxas.append(taxa)
            if "*" in mt.group(2):
                atual.modo, atual.taxa = base, taxa
    for s in saidas:
        if s.ativa and s.modo is None and s.w and s.h:      # modo atual sem asterisco: deduz pela geometria
            w, h = (s.h, s.w) if s.rotacao in ("left", "right") else (s.w, s.h)
            s.modo = f"{w}x{h}"
    return saidas


def tamanho_efetivo(modo: str | None, rotacao: str) -> tuple[int, int]:
    """Largura e altura que o monitor ocupa na area de trabalho (troca se girado)."""
    try:
        w, h = (int(v) for v in (modo or "").split("x"))
    except ValueError:
        return (0, 0)
    return (h, w) if rotacao in ("left", "right") else (w, h)


def config_de_saidas(saidas: list[Saida]) -> dict:
    """Foto do estado atual no formato do JSON (serve para salvar e para reverter)."""
    out: dict[str, dict] = {}
    for s in saidas:
        if not s.conectada:
            continue
        modo = s.modo or (next(iter(s.modos), None))
        out[s.nome] = {"ativa": s.ativa, "modo": modo, "taxa": s.taxa, "rotacao": s.rotacao,
                       "x": s.x, "y": s.y, "primaria": s.primaria}
    return {"versao": VERSAO, "saidas": out}


# ══════════════════════════════════════════════════════════════════════════════
#  xrandr: montar o comando
# ══════════════════════════════════════════════════════════════════════════════
def _rot(e: dict) -> str:
    r = e.get("rotacao", "normal")
    return r if r in ROTACOES else "normal"


def montar_args(cfg: dict, saidas: list[Saida]) -> list[str]:
    """Argumentos do xrandr (um unico comando, com todas as saidas).

    - monitor da config que nao esta conectado: ignorado
    - monitor conectado que nao esta na config: vai para a direita, no modo automatico
    - posicoes sao deslocadas para o canto 0x0 (sem espaco vazio para o mouse escapar)
    """
    conectadas = {s.nome: s for s in saidas if s.conectada}
    cfg_s = cfg.get("saidas", {})
    ativos: list[tuple[str, dict]] = []
    desligar: list[str] = []
    for nome, e in cfg_s.items():
        if nome not in conectadas:
            continue
        if e.get("ativa", True):
            ativos.append((nome, e))
        else:
            desligar.append(nome)
    extras = [n for n in conectadas if n not in cfg_s]
    for s in saidas:
        if not s.conectada and s.ativa:
            desligar.append(s.nome)
    if not ativos and not extras:
        return []

    minx = min((int(e.get("x", 0)) for _, e in ativos), default=0)
    miny = min((int(e.get("y", 0)) for _, e in ativos), default=0)
    primaria = next((n for n, e in ativos if e.get("primaria")), None)
    if primaria is None:
        primaria = ativos[0][0] if ativos else extras[0]

    args: list[str] = []
    direita, borda = None, None
    for nome, e in ativos:
        s = conectadas[nome]
        modo, taxa, rot = e.get("modo"), e.get("taxa"), _rot(e)
        x, y = int(e.get("x", 0)) - minx, int(e.get("y", 0)) - miny
        args += ["--output", nome]
        if modo and modo in s.modos:
            nome_modo = s.alias.get(modo, modo)
            args += ["--mode", nome_modo]
            if taxa and nome_modo == modo and any(abs(taxa - r) < 0.05 for r in s.modos[modo]):
                args += ["--rate", f"{float(taxa):g}"]
        else:
            args.append("--auto")
        args += ["--rotate", rot, "--pos", f"{x}x{y}"]
        if nome == primaria:
            args.append("--primary")
        w, _h = tamanho_efetivo(modo, rot)
        if borda is None or x + w > borda:
            direita, borda = nome, x + w
    for n in extras:
        args += ["--output", n, "--auto", "--rotate", "normal"]
        if direita:
            args += ["--right-of", direita]
        else:
            args += ["--pos", "0x0"]
        if n == primaria:
            args.append("--primary")
        direita = n
    for n in desligar:
        args += ["--output", n, "--off"]
    return args


def rodar(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    """Roda um comando; devolve (codigo, stdout + stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return (127, str(exc))
    return (r.returncode, (r.stdout or "") + (r.stderr or ""))


def garantir_modos(cfg: dict, saidas: list[Saida], runner=rodar, log=print) -> None:
    """Cria com cvt os modos que o monitor nao anuncia (ex.: VGA em 1600x900)."""
    por_nome = {s.nome: s for s in saidas if s.conectada}
    for nome, e in cfg.get("saidas", {}).items():
        s = por_nome.get(nome)
        modo = e.get("modo")
        if s is None or not e.get("ativa", True) or not modo or modo in s.modos or "x" not in modo:
            continue
        w, h = modo.split("x", 1)
        taxa = str(int(float(e.get("taxa") or 60)))
        rc, out = runner(["cvt", w, h, taxa])
        m = re.search(r'^Modeline "([^"]+)"\s+(.*)$', out, re.M) if rc == 0 else None
        if not m:
            log(f"{nome}: modo {modo} indisponivel e sem cvt; usando automatico")
            continue
        nome_modo, params = m.group(1), m.group(2).split()
        runner(["xrandr", "--newmode", nome_modo, *params])
        rc2, _ = runner(["xrandr", "--addmode", nome, nome_modo])
        if rc2 == 0:
            s.modos.setdefault(modo, []).append(float(taxa))
            s.alias[modo] = nome_modo
            log(f"{nome}: modo {modo} criado ({nome_modo})")


def aplicar_config(cfg: dict, runner=rodar, log=print) -> int:
    """Aplica a config. 0 = ok, 2 = nada a aplicar, 3 = falhou."""
    rc, out = runner(["xrandr", "--query"])
    if rc != 0:
        log(f"xrandr --query falhou: {out.strip()}")
        return 3
    saidas = parse_query(out)
    garantir_modos(cfg, saidas, runner, log)
    args = montar_args(cfg, saidas)
    if not args:
        log("nenhum monitor a configurar")
        return 2
    rc, out = runner(["xrandr", *args])
    log(("ok: xrandr " if rc == 0 else f"FALHOU ({rc}): xrandr ") + " ".join(args) + ("" if rc == 0 else f"\n{out.strip()}"))
    return 0 if rc == 0 else 3


# ══════════════════════════════════════════════════════════════════════════════
#  Geometria (arrastar com o mouse)
# ══════════════════════════════════════════════════════════════════════════════
def _cruza(a: Ret, b: Ret) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def encaixar(r: Ret, outros: list[Ret], limite: int) -> tuple[int, int]:
    """Gruda `r` nas bordas dos outros monitores (e alinha topo, base ou centro) se estiver perto."""
    x, y, w, h = r
    dx = dy = None
    for ox, oy, ow, oh in outros:
        for cand in (ox - w, ox + ow, ox, ox + ow - w, ox + (ow - w) // 2):
            d = cand - x
            if abs(d) <= limite and (dx is None or abs(d) < abs(dx)):
                dx = d
        for cand in (oy - h, oy + oh, oy, oy + oh - h, oy + (oh - h) // 2):
            d = cand - y
            if abs(d) <= limite and (dy is None or abs(d) < abs(dy)):
                dy = d
    return (x + (dx or 0), y + (dy or 0))


def sem_sobreposicao(r: Ret, outros: list[Ret]) -> tuple[int, int]:
    """Se `r` cobre outro monitor, empurra para o lado livre mais proximo."""
    x, y, w, h = r
    for _ in range(8):
        batida = next((o for o in outros if _cruza((x, y, w, h), o)), None)
        if batida is None:
            break
        ox, oy, ow, oh = batida
        opcoes = [(ox - w, y), (ox + ow, y), (x, oy - h), (x, oy + oh)]
        x, y = min(opcoes, key=lambda p: abs(p[0] - x) + abs(p[1] - y))
    return (x, y)


def encostam(a: Ret, b: Ret) -> bool:
    """True se os dois dividem um trecho de borda (o mouse consegue passar de um para o outro)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    lado = (ax + aw == bx or bx + bw == ax) and min(ay + ah, by + bh) > max(ay, by)
    topo = (ay + ah == by or by + bh == ay) and min(ax + aw, bx + bw) > max(ax, bx)
    return lado or topo


def juntar(rects: dict[str, Ret]) -> dict[str, Ret]:
    """Garante que todos os monitores encostem em algum grupo (sem vao por onde o mouse some)."""
    if len(rects) < 2:
        return dict(rects)
    out = dict(rects)
    nomes = list(out)
    alcancados = {nomes[0]}
    while len(alcancados) < len(nomes):
        mudou = False
        for n in nomes:
            if n in alcancados:
                continue
            if any(encostam(out[n], out[m]) for m in alcancados):
                alcancados.add(n)
                mudou = True
        if mudou:
            continue
        # nenhum encosta: gruda o mais proximo no grupo
        melhor = None
        for n in (n for n in nomes if n not in alcancados):
            x, y, w, h = out[n]
            for m in alcancados:
                ox, oy, ow, oh = out[m]
                for cx, cy in ((ox + ow, y), (ox - w, y), (x, oy + oh), (x, oy - h)):
                    cand = (cx, cy, w, h)
                    if any(_cruza(cand, out[k]) for k in alcancados):
                        continue
                    if not encostam(cand, out[m]):
                        # ajusta o eixo livre para sobrepor um trecho de borda
                        if cx in (ox + ow, ox - w):
                            cy = min(max(cy, oy - h + 1), oy + oh - 1)
                        else:
                            cx = min(max(cx, ox - w + 1), ox + ow - 1)
                        cand = (cx, cy, w, h)
                        if any(_cruza(cand, out[k]) for k in alcancados) or not encostam(cand, out[m]):
                            continue
                    dist = abs(cx - x) + abs(cy - y)
                    if melhor is None or dist < melhor[0]:
                        melhor = (dist, n, cand)
        if melhor is None:
            break
        out[melhor[1]] = melhor[2]
        alcancados.add(melhor[1])
    return out


def alinhar(nome: str, rects: dict[str, Ret], como: str) -> tuple[int, int]:
    """Alinha `nome` ao vizinho mais proximo: como = inicio | centro | fim."""
    x, y, w, h = rects[nome]
    outros = [(m, r) for m, r in rects.items() if m != nome]
    if not outros:
        return (x, y)
    m, (ox, oy, ow, oh) = min(outros, key=lambda mr: abs(mr[1][0] - x) + abs(mr[1][1] - y))
    lado_a_lado = (x + w <= ox or ox + ow <= x)
    if lado_a_lado:
        y = {"inicio": oy, "centro": oy + (oh - h) // 2, "fim": oy + oh - h}[como]
    else:
        x = {"inicio": ox, "centro": ox + (ow - w) // 2, "fim": ox + ow - w}[como]
    return (x, y)


# ══════════════════════════════════════════════════════════════════════════════
#  Cores (jtheme e opcional)
# ══════════════════════════════════════════════════════════════════════════════
def _cores() -> dict:
    padrao = dict(bg="#1a1b26", fundo="#13141c", painel="#1f2335", hover="#2a2f45", fg="#c0caf5", dim="#565f89",
                  foco="#b04a67", sobre="#fbe9ef", linha="#292e42", verde="#9ece6a", amarelo="#e0af68",
                  vermelho="#f7768e")
    try:
        import jtheme
        t = jtheme.T
        return dict(bg=t["bg"], fundo=t["bg_deep"], painel=t["bg_alt"], hover=t["bg_hover"], fg=t["fg_bright"],
                    dim=t["dim"], foco=t["focus"], sobre=t["on_accent"], linha=t["line"], verde=t["green"],
                    amarelo=t["yellow"], vermelho=t["red"])
    except (ImportError, AttributeError, KeyError):
        return padrao


# ══════════════════════════════════════════════════════════════════════════════
#  Janela
# ══════════════════════════════════════════════════════════════════════════════
class App:
    LIMITE_ENCAIXE = 16        # px na tela: o encaixe puxa quando as bordas ficam a ate 16 px
    SEGUNDOS = 10

    def __init__(self, tk, tkfont):
        self.tk = tk
        self.c = _cores()
        self.root = tk.Tk()
        self.root.title("JScreens")
        self.root.configure(bg=self.c["bg"])
        self.root.geometry("900x560")
        self.root.minsize(760, 480)
        tam = int(os.environ.get("JSCREENS_FONT", "12"))
        fams = set(tkfont.families())
        fam = next((f for f in ("Cascadia Mono", "JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono") if f in fams),
                   "TkFixedFont")
        self.f = tkfont.Font(family=fam, size=tam)
        self.fb = tkfont.Font(family=fam, size=tam, weight="bold")
        self.fg = tkfont.Font(family=fam, size=tam + 4, weight="bold")
        self.saidas: list[Saida] = []
        self.est: dict[str, dict] = {}
        self.sel: str | None = None
        self.escala = 0.1
        self.desloc = (0.0, 0.0)
        self.arrasto: tuple[str, float, float] | None = None
        self.aqui = _AQUI
        self._montar()
        self.recarregar()

    # ── montagem ──
    def _montar(self):
        tk, c = self.tk, self.c
        topo = tk.Frame(self.root, bg=c["bg"])
        topo.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        self.canvas = tk.Canvas(topo, bg=c["fundo"], highlightthickness=1, highlightbackground=c["linha"])
        self.canvas.pack(side="left", fill="both", expand=True)
        lado = tk.Frame(topo, bg=c["bg"], width=300)
        lado.pack(side="right", fill="y", padx=(12, 0))
        lado.pack_propagate(False)

        self.titulo = tk.Label(lado, text="", bg=c["bg"], fg=c["foco"], font=self.fg, anchor="w")
        self.titulo.pack(fill="x", pady=(0, 8))
        self.v_ativa = tk.BooleanVar(value=True)
        self.v_prim = tk.BooleanVar(value=False)
        tk.Checkbutton(lado, text="Ligado", variable=self.v_ativa, command=self._mudou_ativa, **self._cb()).pack(anchor="w")
        tk.Checkbutton(lado, text="Principal", variable=self.v_prim, command=self._mudou_prim, **self._cb()).pack(anchor="w")

        tk.Label(lado, text="Resolucao", bg=c["bg"], fg=c["dim"], font=self.f, anchor="w").pack(fill="x", pady=(10, 0))
        self.v_modo = tk.StringVar()
        self.m_modo = tk.OptionMenu(lado, self.v_modo, "")
        self._estilo_menu(self.m_modo)
        self.m_modo.pack(fill="x")
        tk.Label(lado, text="Taxa (Hz)", bg=c["bg"], fg=c["dim"], font=self.f, anchor="w").pack(fill="x", pady=(8, 0))
        self.v_taxa = tk.StringVar()
        self.m_taxa = tk.OptionMenu(lado, self.v_taxa, "")
        self._estilo_menu(self.m_taxa)
        self.m_taxa.pack(fill="x")

        tk.Label(lado, text="Rotacao", bg=c["bg"], fg=c["dim"], font=self.f, anchor="w").pack(fill="x", pady=(10, 0))
        self.v_rot = tk.StringVar(value="normal")
        for r in ROTACOES:
            tk.Radiobutton(lado, text=ROTULOS[r], variable=self.v_rot, value=r, command=self._mudou_rot,
                           **self._cb()).pack(anchor="w")

        tk.Label(lado, text="Posicao (px)", bg=c["bg"], fg=c["dim"], font=self.f, anchor="w").pack(fill="x", pady=(10, 0))
        pos = tk.Frame(lado, bg=c["bg"])
        pos.pack(fill="x")
        self.v_x, self.v_y = tk.StringVar(), tk.StringVar()
        for rot, var in (("X", self.v_x), ("Y", self.v_y)):
            tk.Label(pos, text=rot, bg=c["bg"], fg=c["fg"], font=self.f).pack(side="left")
            e = tk.Entry(pos, textvariable=var, width=6, bg=c["painel"], fg=c["fg"], insertbackground=c["fg"],
                         relief="flat", font=self.f)
            e.pack(side="left", padx=(4, 10))
            e.bind("<Return>", self._mudou_pos)
            e.bind("<FocusOut>", self._mudou_pos)

        al = tk.Frame(lado, bg=c["bg"])
        al.pack(fill="x", pady=(10, 0))
        for txt, como in (("Inicio", "inicio"), ("Centro", "centro"), ("Fim", "fim")):
            tk.Button(al, text=txt, command=lambda k=como: self._alinhar(k), **self._bt()).pack(side="left", padx=(0, 6))

        base = tk.Frame(self.root, bg=c["bg"])
        base.pack(fill="x", padx=14, pady=(4, 14))
        self.status = tk.Label(base, text="", bg=c["bg"], fg=c["dim"], font=self.f, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        for txt, cmd in (("Fechar", self.root.destroy), ("Salvar", self.salvar), ("Aplicar", self.aplicar),
                         ("Aplicar e salvar", lambda: self.aplicar(salvar=True))):
            tk.Button(base, text=txt, command=cmd, **self._bt()).pack(side="right", padx=(8, 0))
        tk.Button(base, text="Recarregar", command=self.recarregar, **self._bt()).pack(side="right", padx=(8, 0))
        tk.Button(base, text="Carregar salvo", command=self.carregar_salvo, **self._bt()).pack(side="right", padx=(8, 0))

        cv = self.canvas
        cv.bind("<ButtonPress-1>", self._clicou)
        cv.bind("<B1-Motion>", self._arrastou)
        cv.bind("<ButtonRelease-1>", self._soltou)
        cv.bind("<Configure>", lambda e: self.desenhar())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Tab>", self._proximo)
        for tecla, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.items():
            self.root.bind(f"<{tecla}>", lambda e, a=dx, b=dy: self._mover_teclado(a, b, 10))
            self.root.bind(f"<Shift-{tecla}>", lambda e, a=dx, b=dy: self._mover_teclado(a, b, 100))

    def _cb(self):
        c = self.c
        return dict(bg=c["bg"], fg=c["fg"], selectcolor=c["painel"], activebackground=c["bg"], activeforeground=c["fg"],
                    font=self.f, anchor="w", highlightthickness=0, bd=0)

    def _bt(self):
        c = self.c
        return dict(bg=c["painel"], fg=c["fg"], activebackground=c["hover"], activeforeground=c["fg"], relief="flat",
                    font=self.f, padx=12, pady=6, bd=0, highlightthickness=0)

    def _estilo_menu(self, om):
        c = self.c
        om.configure(bg=c["painel"], fg=c["fg"], activebackground=c["hover"], activeforeground=c["fg"], relief="flat",
                     font=self.f, highlightthickness=0, bd=0, anchor="w")
        om["menu"].configure(bg=c["painel"], fg=c["fg"], font=self.f)

    # ── dados ──
    def _query(self) -> list[Saida]:
        rc, out = rodar(["xrandr", "--query"])
        return parse_query(out) if rc == 0 else []

    def recarregar(self):
        self.saidas = [s for s in self._query() if s.conectada]
        self.est = {}
        for s in self.saidas:
            modo = s.modo or next(iter(s.modos), None)
            self.est[s.nome] = {"ativa": s.ativa, "modo": modo, "taxa": s.taxa, "rotacao": s.rotacao,
                                "x": s.x, "y": s.y, "primaria": s.primaria}
        self._posicionar_inativos()
        self.sel = next((n for n in self.est if self.est[n]["ativa"]), next(iter(self.est), None))
        self.dizer(f"{len(self.saidas)} monitor(es) conectado(s)" if self.saidas else "xrandr nao retornou monitores")
        self._painel()
        self.desenhar()

    def carregar_salvo(self):
        cfg = carregar_config()
        if not cfg:
            self.dizer("nenhuma config salva ainda")
            return
        for nome, e in cfg["saidas"].items():
            if nome in self.est:
                self.est[nome].update({k: e[k] for k in ("ativa", "modo", "taxa", "rotacao", "x", "y", "primaria")
                                       if k in e})
        self.dizer("config salva carregada (falta aplicar)")
        self._painel()
        self.desenhar()

    def _posicionar_inativos(self):
        borda = max(
            (self._ret(n)[0] + self._ret(n)[2]
             for n in self.est if self.est[n]["ativa"]),
            default=0,
        )
        for n in self.est:
            e = self.est[n]
            if not e["ativa"]:
                e["x"], e["y"] = borda, 0

    def _ret(self, nome: str) -> Ret:
        e = self.est[nome]
        w, h = tamanho_efetivo(e.get("modo"), e.get("rotacao", "normal"))
        return (int(e["x"]), int(e["y"]), w or 1280, h or 720)

    def _rets_ativos(self, exceto: str | None = None) -> dict[str, Ret]:
        return {n: self._ret(n) for n, e in self.est.items() if e["ativa"] and n != exceto}

    def config_atual(self) -> dict:
        saidas = {n: dict(e) for n, e in self.est.items()}
        rets = juntar({n: self._ret(n) for n, e in self.est.items() if e["ativa"]})
        for n, (x, y, _w, _h) in rets.items():
            saidas[n]["x"], saidas[n]["y"] = x, y
        if saidas and not any(e["ativa"] and e["primaria"] for e in saidas.values()):
            primeiro = next((n for n, e in saidas.items() if e["ativa"]), None)
            if primeiro:
                saidas[primeiro]["primaria"] = True
        return {"versao": VERSAO, "saidas": saidas}

    # ── desenho ──
    def _calc_escala(self):
        rets = [self._ret(n) for n in self.est]
        if not rets:
            return
        x0 = min(r[0] for r in rets)
        y0 = min(r[1] for r in rets)
        x1 = max(r[0] + r[2] for r in rets)
        y1 = max(r[1] + r[3] for r in rets)
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        larg, alt = max(x1 - x0, 1), max(y1 - y0, 1)
        self.escala = min(cw * 0.7 / larg, ch * 0.7 / alt, 0.25)
        self.desloc = ((cw - larg * self.escala) / 2 - x0 * self.escala, (ch - alt * self.escala) / 2 - y0 * self.escala)

    def _para_tela(self, r: Ret):
        s, (dx, dy) = self.escala, self.desloc
        return (r[0] * s + dx, r[1] * s + dy, (r[0] + r[2]) * s + dx, (r[1] + r[3]) * s + dy)

    def desenhar(self):
        cv, c = self.canvas, self.c
        cv.delete("all")
        if self.arrasto is None:
            self._calc_escala()
        for n in self.est:
            ativo = self.est[n]["ativa"]
            x1, y1, x2, y2 = self._para_tela(self._ret(n))
            sel = n == self.sel
            cv.create_rectangle(x1, y1, x2, y2, fill=c["foco"] if sel else c["painel"],
                                outline=c["foco"] if sel else c["dim"], width=3 if sel else 1,
                                dash=() if ativo else (4, 4))
            cor = c["sobre"] if sel else c["fg"]
            e = self.est[n]
            estrela = "  *" if e["primaria"] and ativo else ""
            cv.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 10, text=f"{n}{estrela}", fill=cor, font=self.fb)
            res = f'{e["modo"] or "?"}  {ROTULOS.get(e["rotacao"], "")}' if ativo else "desligado"
            cv.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 14, text=res, fill=cor, font=self.f)
        rets = {n: self._ret(n) for n in self.est if self.est[n]["ativa"]}
        if len(rets) > 1 and any(juntar(rets)[n] != rets[n] for n in rets):
            self.dizer("aviso: monitores soltos (sem encostar). Aplicar vai encostar")

    # ── painel lateral ──
    def _painel(self):
        n = self.sel
        if n is None:
            self.titulo.configure(text="(sem monitor)")
            return
        e = self.est[n]
        self.titulo.configure(text=n)
        self.v_ativa.set(e["ativa"])
        self.v_prim.set(e["primaria"])
        self.v_rot.set(e["rotacao"])
        self.v_x.set(str(e["x"]))
        self.v_y.set(str(e["y"]))
        s = next((s for s in self.saidas if s.nome == n), None)
        modos = list(s.modos) if s else []
        if e["modo"] and e["modo"] not in modos:
            modos.insert(0, e["modo"])
        for extra in MODOS_EXTRA:        # modos comuns que o monitor pode nao anunciar (criados com cvt ao aplicar)
            if extra not in modos:
                modos.append(extra)
        modos.sort(key=lambda m: -(tamanho_efetivo(m, "normal")[0] * tamanho_efetivo(m, "normal")[1]))
        self._preencher(self.m_modo, self.v_modo, modos, self._escolher_modo)
        self.v_modo.set(e["modo"] or "")
        taxas = sorted((s.modos.get(e["modo"], []) if s else []), reverse=True)
        self._preencher(self.m_taxa, self.v_taxa, [f"{t:g}" for t in taxas], self._escolher_taxa)
        self.v_taxa.set(f'{e["taxa"]:g}' if e["taxa"] else "")

    def _preencher(self, om, var, valores, cmd):
        menu = om["menu"]
        menu.delete(0, "end")
        for v in valores:
            menu.add_command(label=v, command=lambda v=v: cmd(v))

    def _escolher_modo(self, modo):
        e = self.est[self.sel]
        e["modo"] = modo
        s = next((s for s in self.saidas if s.nome == self.sel), None)
        taxas = s.modos.get(modo, []) if s else []
        e["taxa"] = taxas[0] if taxas else 60.0
        self._painel()
        self.desenhar()

    def _escolher_taxa(self, txt):
        try:
            self.est[self.sel]["taxa"] = float(txt)
        except ValueError:
            return
        self._painel()

    def _mudou_ativa(self):
        e = self.est[self.sel]
        e["ativa"] = bool(self.v_ativa.get())
        if e["ativa"]:
            borda = max((r[0] + r[2] for n, r in self._rets_ativos(self.sel).items()), default=0)
            e["x"], e["y"] = borda, 0
        elif e["primaria"]:
            e["primaria"] = False
        self._painel()
        self.desenhar()

    def _mudou_prim(self):
        marcar = bool(self.v_prim.get())
        for n, e in self.est.items():
            e["primaria"] = marcar and n == self.sel
        self.desenhar()

    def _mudou_rot(self):
        self.est[self.sel]["rotacao"] = self.v_rot.get()
        self._painel()
        self.desenhar()

    def _mudou_pos(self, _e=None):
        if self.sel is None:
            return
        try:
            self.est[self.sel]["x"] = int(self.v_x.get())
            self.est[self.sel]["y"] = int(self.v_y.get())
        except ValueError:
            self.dizer("posicao invalida: usar numeros inteiros")
            return
        self.desenhar()

    def _alinhar(self, como):
        if self.sel is None:
            return
        rets = {n: self._ret(n) for n, e in self.est.items() if e["ativa"]}
        if self.sel not in rets:
            return
        x, y = alinhar(self.sel, rets, como)
        self.est[self.sel]["x"], self.est[self.sel]["y"] = x, y
        self._painel()
        self.desenhar()

    # ── mouse e teclado ──
    def _clicou(self, ev):
        for n in reversed(list(self.est)):
            x1, y1, x2, y2 = self._para_tela(self._ret(n))
            if x1 <= ev.x <= x2 and y1 <= ev.y <= y2:
                self.sel = n
                self.arrasto = (n, ev.x - x1, ev.y - y1)
                self._painel()
                self.desenhar()
                return
        self.arrasto = None

    def _arrastou(self, ev):
        if not self.arrasto:
            return
        n, ox, oy = self.arrasto
        if not self.est[n]["ativa"]:
            return
        dx, dy = self.desloc
        self.est[n]["x"] = int((ev.x - ox - dx) / self.escala)
        self.est[n]["y"] = int((ev.y - oy - dy) / self.escala)
        self.desenhar()

    def _soltou(self, _ev):
        if not self.arrasto:
            return
        n = self.arrasto[0]
        self.arrasto = None
        if self.est[n]["ativa"]:
            x, y, w, h = self._ret(n)
            outros = list(self._rets_ativos(n).values())
            x, y = encaixar((x, y, w, h), outros, int(self.LIMITE_ENCAIXE / max(self.escala, 0.01)))
            x, y = sem_sobreposicao((x, y, w, h), outros)
            self.est[n]["x"], self.est[n]["y"] = x, y
        self._painel()
        self.desenhar()

    def _mover_teclado(self, dx, dy, passo):
        if self.sel is None or not self.est[self.sel]["ativa"]:
            return
        if self.root.focus_get() is not None and self.root.focus_get().winfo_class() == "Entry":
            return
        e = self.est[self.sel]
        e["x"] += dx * passo
        e["y"] += dy * passo
        self._painel()
        self.desenhar()

    def _proximo(self, _e=None):
        nomes = list(self.est)
        if nomes:
            self.sel = nomes[(nomes.index(self.sel) + 1) % len(nomes)] if self.sel in nomes else nomes[0]
            self._painel()
            self.desenhar()
        return "break"

    # ── acoes ──
    def dizer(self, texto):
        self.status.configure(text=texto)

    def salvar(self):
        p = salvar_config(self.config_atual())
        self.dizer(f"salvo em {p}")

    def _wallpaper(self):
        alvo = next((p for p in (self.aqui / "jwm-wallpaper", self.aqui.parent / "jwm-wallpaper") if p.is_file()), None)
        if alvo and shutil.which("sh"):
            subprocess.Popen(["sh", str(alvo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def aplicar(self, salvar=False):
        antes = config_de_saidas(self._query())
        cfg = self.config_atual()
        logs: list[str] = []
        rc = aplicar_config(cfg, log=logs.append)
        if rc != 0:
            self.dizer("falhou: " + (logs[-1].splitlines()[-1] if logs else "xrandr"))
            return
        self._wallpaper()
        self.root.after(400, self.recarregar)
        self._confirmar(antes, cfg if salvar else None)

    def _confirmar(self, antes, cfg_salvar):
        tk, c = self.tk, self.c
        win = tk.Toplevel(self.root)
        win.title("Manter?")
        win.configure(bg=c["bg"])
        win.transient(self.root)
        info = tk.Label(win, text="", bg=c["bg"], fg=c["fg"], font=self.f, padx=24, pady=16)
        info.pack()
        restante = [self.SEGUNDOS]
        feito = [False]

        def reverter(_e=None):
            if feito[0]:
                return
            feito[0] = True
            aplicar_config(antes)
            self._wallpaper()
            win.destroy()
            self.root.after(400, self.recarregar)
            self.dizer("revertido")

        def manter(_e=None):
            if feito[0]:
                return
            feito[0] = True
            if cfg_salvar is not None:
                self.salvar()
            win.destroy()
            self.dizer("mantido" + (" e salvo" if cfg_salvar is not None else ""))

        def tique():
            if feito[0]:
                return
            if restante[0] <= 0:
                reverter()
                return
            info.configure(text=f"Manter esta disposicao?\nReverte sozinho em {restante[0]} s")
            restante[0] -= 1
            win.after(1000, tique)

        botoes = tk.Frame(win, bg=c["bg"])
        botoes.pack(pady=(0, 16))
        tk.Button(botoes, text="Manter", command=manter, **self._bt()).pack(side="left", padx=8)
        tk.Button(botoes, text="Reverter", command=reverter, **self._bt()).pack(side="left", padx=8)
        win.protocol("WM_DELETE_WINDOW", reverter)
        win.bind("<Return>", manter)
        win.bind("<Escape>", reverter)
        win.focus_force()
        tique()

    def rodar(self):
        self.root.mainloop()


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--apply" in args:
        cfg = carregar_config()
        if cfg is None:
            _log(f"JScreens: sem config valida em {caminho_config()}")
            return 2
        return aplicar_config(cfg, log=_log)
    if "--show" in args or "--save" in args:
        rc, out = rodar(["xrandr", "--query"])
        if rc != 0:
            _log("JScreens: xrandr --query falhou")
            return 3
        cfg = config_de_saidas(parse_query(out))
        if "--save" in args:
            print(f"salvo em {salvar_config(cfg)}")
        else:
            print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0
    import tkinter as tk
    from tkinter import font as tkfont
    App(tk, tkfont).rodar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
