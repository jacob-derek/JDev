"""jfcore - núcleo do JFiles: tudo que não depende de tela (listar, filtrar, completar caminho,
git, recentes, modo seletor, arrastar). Só funções puras/pequenas, testadas em tests/test_jfcore.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    import jstatus
except ImportError:
    jstatus = None

# ══════════════════════════════════════════════════════════════════════════════
#  Entradas de pasta
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Entrada:
    nome: str
    caminho: Path
    pasta: bool
    link: bool = False
    tam: int = 0
    mtime: float = 0.0

    @property
    def oculto(self) -> bool:
        return self.nome.startswith(".")


ORDENS = ("nome", "tamanho", "data")


def listar(pasta, ocultos: bool = False, ordem: str = "nome") -> list[Entrada]:
    """Conteúdo de `pasta`: pastas primeiro. Levanta OSError (permissão etc.) para o chamador tratar."""
    saida = []
    with os.scandir(pasta) as it:
        for e in it:
            if not ocultos and e.name.startswith("."):
                continue
            try:
                eh_dir = e.is_dir()
                st = e.stat()
                tam, mt = st.st_size, st.st_mtime
            except OSError:          # link quebrado, arquivo sumiu no meio
                eh_dir, tam, mt = False, 0, 0.0
            try:
                link = e.is_symlink()
            except OSError:
                link = False
            saida.append(Entrada(e.name, Path(e.path), eh_dir, link, 0 if eh_dir else tam, mt))
    if ordem == "tamanho":
        chave = lambda x: (not x.pasta, -x.tam, x.nome.lower())  # noqa: E731
    elif ordem == "data":
        chave = lambda x: (not x.pasta, -x.mtime, x.nome.lower())  # noqa: E731
    else:
        chave = lambda x: (not x.pasta, x.nome.lower())  # noqa: E731
    saida.sort(key=chave)
    return saida


def filtrar(entradas, consulta: str):
    """Mantém quem contém as letras da consulta em ordem (a-b-c casa 'abacaxi'); sem consulta, tudo."""
    q = consulta.strip().lower()
    if not q:
        return list(entradas)
    achou = []
    for e in entradas:
        n = e.nome.lower()
        if q in n:
            achou.append((0, e))
            continue
        i = 0
        for c in n:
            if i < len(q) and c == q[i]:
                i += 1
        if i == len(q):
            achou.append((1, e))
    # quem contém o trecho inteiro vem antes do "mais ou menos", sem bagunçar a ordem original
    return [e for _, e in sorted(achou, key=lambda p: p[0])]


def fmt_tamanho(n: float) -> str:
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" or n >= 10 else f"{n:.1f}{u}"
        n /= 1024.0
    return f"{n:.1f}T"


def fmt_data(mtime: float, agora: float | None = None) -> str:
    if not mtime:
        return "—"
    agora = time.time() if agora is None else agora
    t = time.localtime(mtime)
    if abs(agora - mtime) < 180 * 86400:
        return time.strftime("%d %b %H:%M", t)
    return time.strftime("%d %b  %Y", t)


def largura(s: str) -> int:
    """Colunas que o texto ocupa (CJK/emoji largos contam 2)."""
    return sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in "WF" else 1) for c in s)


def cortar(s: str, n: int) -> str:
    """Corta em `n` colunas, com … se não couber; completa com espaços até exatamente n."""
    if n <= 0:
        return ""
    if largura(s) > n:
        out, w = "", 0
        for c in s:
            cw = largura(c)
            if w + cw > n - 1:
                break
            out, w = out + c, w + cw
        s = out + "…"
    return s + " " * (n - largura(s))


# ══════════════════════════════════════════════════════════════════════════════
#  Ícones por tipo
# ══════════════════════════════════════════════════════════════════════════════
_EXTRAS = {
    "imagem": ("", "purple", {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tif", ".tiff"}),
    "pdf": ("", "red", {".pdf"}),
    "zip": ("", "orange", {".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".zst", ".tgz"}),
    "video": ("", "purple", {".mp4", ".mkv", ".webm", ".avi", ".mov"}),
    "audio": ("", "cyan", {".mp3", ".flac", ".ogg", ".wav", ".m4a", ".opus"}),
    "texto": ("", "fg", {".log", ".csv", ".ini", ".cfg", ".conf", ".pgn"}),
}
GLIFO_PASTA, GLIFO_LINK, GLIFO_ARQ, GLIFO_EXEC = "", "", "", ""


def icone(e: Entrada, nerd: bool, fallback=("📁", "📄", "🔗")) -> tuple[str, str]:
    """(glifo, cor da paleta) do tipo da entrada. Sem Nerd Font usa os ícones de jicons."""
    if not nerd:
        return (fallback[0], "blue") if e.pasta else ((fallback[2], "cyan") if e.link else (fallback[1], "fg"))
    if e.pasta:
        return GLIFO_PASTA, "blue"
    suf = e.caminho.suffix.lower()
    if jstatus is not None and suf in jstatus.LINGUAGENS:
        _, glifo, cor = jstatus.LINGUAGENS[suf]
        return glifo, cor
    for _, (glifo, cor, exts) in _EXTRAS.items():
        if suf in exts:
            return glifo, cor
    if e.link:
        return GLIFO_LINK, "cyan"
    try:
        if os.access(e.caminho, os.X_OK):
            return GLIFO_EXEC, "green"
    except OSError:
        pass
    return GLIFO_ARQ, "fg"


EXT_IMAGEM = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# ══════════════════════════════════════════════════════════════════════════════
#  Caminhos: ir para qualquer lugar (Ctrl+L)
# ══════════════════════════════════════════════════════════════════════════════


def resolver(texto: str, base) -> Path:
    """'~/x', '$HOME/x', '../y' ou 'z' (relativo à pasta atual) -> caminho absoluto normalizado."""
    t = os.path.expandvars(os.path.expanduser(texto.strip()))
    p = Path(t) if os.path.isabs(t) else Path(base) / t
    return Path(os.path.normpath(p))


def completar(texto: str, base, so_pastas: bool = True):
    """Tab: devolve (novo_texto, opcoes). Uma opção só: completa (e põe '/' se for pasta);
    várias: avança até o prefixo comum e devolve a lista para mostrar."""
    bruto = texto
    pai_txt, _, prefixo = bruto.rpartition("/")
    pai_txt = pai_txt + "/" if "/" in bruto else ""
    pai = resolver(pai_txt, base) if pai_txt else Path(base)
    try:
        nomes = []
        with os.scandir(pai) as it:
            for e in it:
                try:
                    eh_dir = e.is_dir()
                except OSError:
                    eh_dir = False
                if so_pastas and not eh_dir:
                    continue
                if e.name.startswith(".") and not prefixo.startswith("."):
                    continue
                nomes.append((e.name, eh_dir))
    except OSError:
        return texto, []
    cand = [(n, d) for n, d in nomes if n.startswith(prefixo)]
    if not cand:
        cand = [(n, d) for n, d in nomes if n.lower().startswith(prefixo.lower())]
    cand.sort(key=lambda x: x[0].lower())
    opcoes = [n + ("/" if d else "") for n, d in cand]
    if not opcoes:
        return texto, []
    if len(opcoes) == 1:
        return pai_txt + opcoes[0], opcoes
    comum = os.path.commonprefix([n for n, _ in cand])
    if len(comum) > len(prefixo):
        return pai_txt + comum, opcoes
    return texto, opcoes


# ── pastas recentes (tipo zoxide: "ir pra qualquer lugar" digitando um pedaço do nome) ──
def arquivo_recentes() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "jdev" / "jfiles-recentes"


def recentes_ler(arq=None) -> dict[str, int]:
    arq = Path(arq) if arq else arquivo_recentes()
    dados = {}
    try:
        for linha in arq.read_text(encoding="utf-8").splitlines():
            n, _, p = linha.partition("\t")
            if p and n.isdigit():
                dados[p] = int(n)
    except OSError:
        pass
    return dados


def recentes_registrar(pasta, arq=None, limite: int = 300) -> None:
    arq = Path(arq) if arq else arquivo_recentes()
    p = str(pasta)
    if p == str(Path.home()) or p == "/":
        return
    dados = recentes_ler(arq)
    dados[p] = dados.get(p, 0) + 1
    if len(dados) > limite:     # joga fora os menos visitados
        for k, _ in sorted(dados.items(), key=lambda kv: kv[1])[: len(dados) - limite]:
            dados.pop(k)
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(".tmp")
        tmp.write_text("".join(f"{n}\t{p}\n" for p, n in dados.items()), encoding="utf-8")
        os.replace(tmp, arq)
    except OSError:
        pass


def recentes_buscar(consulta: str, dados: dict[str, int], max_: int = 6) -> list[str]:
    """Pastas recentes cujo caminho contém TODAS as palavras da consulta; mais visitadas primeiro
    (e quem termina com a palavra ganha preferência). Pastas que não existem mais são ignoradas."""
    palavras = consulta.lower().split()
    if not palavras:
        return []
    pontos = []
    for p, n in dados.items():
        baixo = p.lower()
        if all(w in baixo for w in palavras) and os.path.isdir(p):
            bonus = 5 if baixo.rstrip("/").endswith(palavras[-1]) else 0
            pontos.append((n + bonus, p))
    pontos.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, p in pontos[:max_]]


# ══════════════════════════════════════════════════════════════════════════════
#  Git (marcas na lista)
# ══════════════════════════════════════════════════════════════════════════════
_PRIO = {"!": 4, "●": 3, "+": 2, "-": 2, "?": 1}
_COR = {"!": "red", "●": "yellow", "+": "green", "-": "red", "?": "dim"}


def _marca_xy(xy: str) -> str:
    if "U" in xy or xy in ("AA", "DD"):
        return "!"
    if "D" in xy:
        return "-"
    if xy == "??":
        return "?"
    if "A" in xy and xy[1] == " ":
        return "+"
    return "●"


def interpretar_porcelain(saida: str, prefixo: str) -> dict[str, tuple[str, str]]:
    """Saída de `git status --porcelain=v1 -z` -> {nome na pasta atual: (marca, cor)}.
    `prefixo` é o caminho da pasta atual dentro do repositório (ex.: 'src/'), '' na raiz."""
    marcas: dict[str, str] = {}
    partes = saida.split("\0")
    i = 0
    while i < len(partes):
        item = partes[i]
        i += 1
        if len(item) < 4:
            continue
        xy, caminho = item[:2], item[3:]
        if "R" in xy or "C" in xy:      # renomeado: o próximo campo é o caminho antigo
            i += 1
        if prefixo and not caminho.startswith(prefixo):
            continue
        nome = caminho[len(prefixo):].split("/", 1)[0]
        if not nome:
            continue
        m = _marca_xy(xy)
        if m == "-" and "/" in caminho[len(prefixo):]:
            m = "●"                     # arquivo apagado dentro de uma pasta: a pasta "mudou"
        if _PRIO[m] > _PRIO.get(marcas.get(nome, ""), 0):
            marcas[nome] = m
    return {n: (m, _COR[m]) for n, m in marcas.items()}


def git_marcas(pasta, timeout: float = 1.5) -> dict[str, tuple[str, str]]:
    """Marcas do git para os itens de `pasta` ({} fora de repositório, sem git ou se demorar)."""
    if shutil.which("git") is None:
        return {}
    try:
        pre = subprocess.run(["git", "-C", str(pasta), "rev-parse", "--show-prefix"],
                             capture_output=True, text=True, timeout=timeout)
        if pre.returncode != 0:
            return {}
        st = subprocess.run(["git", "-C", str(pasta), "status", "--porcelain=v1", "-z",
                             "--untracked-files=normal"], capture_output=True, text=True,
                            timeout=timeout, errors="replace")
        if st.returncode != 0:
            return {}
        return interpretar_porcelain(st.stdout, pre.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return {}


def ramo(pasta) -> str | None:
    if jstatus is None:
        return None
    # ramo_git olha o pai do caminho dado; passamos um filho fictício para valer para a própria pasta
    return jstatus.ramo_git(Path(pasta) / "_")


# ══════════════════════════════════════════════════════════════════════════════
#  Modo seletor (--pick): é como o Firefox usa o JFiles pra escolher arquivo
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Opcoes:
    pick: bool = False
    multiplo: bool = False
    pasta: bool = False         # escolher pasta
    salvar: str | None = None   # nome sugerido (modo "salvar como")
    saida: str | None = None    # arquivo onde gravar a escolha (um caminho por linha)
    inicio: str | None = None
    titulo: str | None = None


def ler_argumentos(argv: list[str]) -> Opcoes:
    """--pick [--multiple] [--dir] [--save NOME] [--out ARQ] [--start CAMINHO] [--title T]"""
    o = Opcoes()
    it = iter(argv)
    for a in it:
        if a == "--pick":
            o.pick = True
        elif a == "--multiple":
            o.multiplo = True
        elif a == "--dir":
            o.pasta = True
        elif a in ("--save", "--out", "--start", "--title"):
            v = next(it, None)
            if v is not None:
                setattr(o, {"--save": "salvar", "--out": "saida", "--start": "inicio", "--title": "titulo"}[a], v)
        elif a == "--save-here":
            o.salvar = ""
        elif not a.startswith("-") and o.inicio is None:    # `jfiles ~/Downloads`
            o.inicio = a
    if o.salvar is not None or o.pasta or o.multiplo or o.saida:
        o.pick = True
    return o


def ponto_de_partida(inicio: str | None, padrao) -> tuple[Path, str | None]:
    """(pasta, item a destacar) a partir do caminho sugerido pelo portal (pode ser arquivo, pasta ou lixo)."""
    if inicio:
        p = Path(os.path.expanduser(inicio))
        try:
            if p.is_dir():
                return p.resolve(), None
            if p.parent.is_dir():
                return p.parent.resolve(), (p.name if p.exists() else None)
        except OSError:
            pass
    return Path(padrao), None


def gravar_escolha(saida: str | None, caminhos) -> None:
    """Grava um caminho por linha (formato esperado pelo xdg-desktop-portal-termfilechooser).
    Sem escolha, deixa o arquivo vazio: é assim que o portal entende 'cancelado'."""
    if not saida:
        return
    texto = "".join(f"{c}\n" for c in caminhos)
    Path(saida).write_text(texto, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Arrastar para fora / copiar caminho / lixeira
# ══════════════════════════════════════════════════════════════════════════════
ARRASTADORES = (            # (executável, argumentos antes dos arquivos)
    ("ripdrag", ["-x", "-a"]),
    ("dragon-drop", ["-x", "-a"]),
    ("xdragon", ["-x", "-a"]),
    ("dragon", ["-x", "-a"]),
)


def comando_arrastar(caminhos) -> list[str] | None:
    """Comando que abre a janelinha 'arraste daqui' com os arquivos, ou None se não houver ferramenta."""
    for exe, args in ARRASTADORES:
        achado = shutil.which(exe)
        if achado:
            return [achado, *args, *map(str, caminhos)]
    return None


def comando_clipboard() -> list[str] | None:
    for exe, args in (("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("xsel", ["-ib"])):
        achado = shutil.which(exe)
        if achado:
            return [achado, *args]
    return None


def comando_lixeira(caminhos) -> list[str] | None:
    if shutil.which("gio"):
        return ["gio", "trash", *map(str, caminhos)]
    if shutil.which("trash-put"):
        return ["trash-put", *map(str, caminhos)]
    return None


def nome_livre(destino: Path) -> Path:
    """Se `destino` existe, devolve 'nome (2).ext', 'nome (3).ext'... (colar sem sobrescrever)."""
    if not destino.exists() and not destino.is_symlink():
        return destino
    n = 2
    while True:
        cand = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not cand.exists() and not cand.is_symlink():
            return cand
        n += 1


def pasta_dentro_de_si(origem: Path, destino_pasta: Path) -> bool:
    try:
        o, d = origem.resolve(), destino_pasta.resolve()
    except OSError:
        return False
    return origem.is_dir() and (d == o or o in d.parents)


# ══════════════════════════════════════════════════════════════════════════════
#  Uma linha da lista + estilos
# ══════════════════════════════════════════════════════════════════════════════
def linha(e: Entrada, larg: int, sel: bool, marcado: bool, git, nerd: bool,
          fallback=("📁", "📄", "🔗"), agora: float | None = None):
    """Fragmentos (classe, texto) de uma linha da lista, ocupando exatamente `larg` colunas."""
    s = ".sel" if sel else ""
    glifo, cor = icone(e, nerd, fallback)
    frags = [(f"class:jf.mark{s}", "▍ " if marcado else "  "),
             (f"class:jf.ico.{cor}{s}", glifo + " ")]
    usado = 2 + largura(glifo) + 1
    direita = []
    if larg >= 30:
        gm, gc = git or (" ", "dim")
        direita.append((f"class:jf.ico.{gc}{s}", f" {gm} "))
    if larg >= 44:
        direita.append((f"class:jf.dim{s}", ("" if e.pasta else fmt_tamanho(e.tam)).rjust(6) + " "))
    if larg >= 64:
        direita.append((f"class:jf.dim{s}", cortar(fmt_data(e.mtime, agora), 12) + " "))
    r = sum(largura(t) for _, t in direita)
    nome = e.nome + ("/" if e.pasta else "")
    classe = "jf.dir" if e.pasta else ("jf.dim" if e.oculto else "jf.row")
    frags.append((f"class:{classe}{s}", cortar(nome, max(1, larg - usado - r))))
    return frags + direita


CORES_ICONE = ("yellow", "blue", "green", "red", "orange", "cyan", "purple", "dim", "fg")


def estilos(jtheme=None) -> dict:
    """Classes jf.* (e as pílulas st.* do jstatus) a partir do tema ativo."""
    base = jstatus.paleta(jtheme) if jstatus else {}
    t = getattr(jtheme, "T", None) or {}
    p = {"bg": "#1a1b26", "select": "#33467c", "fg": "#a9b1d6", "fg_bright": "#c0caf5", "dim": "#565f89",
         "blue": "#7aa2f7", "purple": "#bb9af7", "yellow": "#e0af68", "green": "#9ece6a", "red": "#f7768e",
         "orange": "#ff9e64", "cyan": "#7dcfff", "bg_deep": "#13141c", "line": "#292e42"}
    p.update(base)
    p.update({k: t[k] for k in ("bg", "select") if isinstance(t.get(k), str)})
    est = dict(jstatus.estilos_status(jtheme)) if jstatus else {}
    est.update({
        "": f"{p['fg']} bg:{p['bg']}",
        "jf.row": f"{p['fg']} bg:{p['bg']}", "jf.row.sel": f"{p['fg_bright']} bold bg:{p['select']}",
        "jf.dir": f"{p['blue']} bold bg:{p['bg']}", "jf.dir.sel": f"{p['blue']} bold bg:{p['select']}",
        "jf.dim": f"{p['dim']} bg:{p['bg']}", "jf.dim.sel": f"{p['dim']} bg:{p['select']}",
        "jf.mark": f"{p['purple']} bold bg:{p['bg']}", "jf.mark.sel": f"{p['purple']} bold bg:{p['select']}",
        "jf.in": f"{p['fg_bright']} bg:{p['bg_deep']}", "jf.cur": "reverse",
        "jf.titulo": f"{p['blue']} bold bg:{p['bg']}", "jf.sep": f"{p['line']} bg:{p['bg']}",
        "jf.dica": f"{p['dim']} bg:{p['bg_deep']}", "jf.tecla": f"{p['yellow']} bg:{p['bg_deep']}",
    })
    for cor in CORES_ICONE:
        est[f"jf.ico.{cor}"] = f"{p[cor]} bg:{p['bg']}"
        est[f"jf.ico.{cor}.sel"] = f"{p[cor]} bg:{p['select']}"
    return est
