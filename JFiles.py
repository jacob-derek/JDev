#!/usr/bin/env python3
"""JFiles - gerenciador de arquivos do JDev: terminal por baixo, regalias de interface gráfica por cima.

  jfiles [pasta]                      navega (Ctrl+L: ir para QUALQUER caminho, Tab completa)
  jfiles --pick [--multiple] [--dir] [--save NOME] [--out ARQ] [--start CAMINHO]
                                      modo seletor (é como o Firefox escolhe arquivo; ver jfiles-picker)

A lógica que não depende de tela mora em jfcore.py (testada em tests/test_jfcore.py).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import stat as _stat
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

try:  # canal de mensagens do JDesk (opcional)
    import jipc
except ImportError:
    jipc = None

try:  # ícones conforme o terminal (JICONES=nerd|emoji|ascii)
    import jicons
except ImportError:
    jicons = None

try:
    import jtheme  # paleta compartilhada do JDev (opcional)
except ImportError:
    jtheme = None

try:
    import jstatus
except ImportError:
    jstatus = None

import jfcore

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.styles import Style

NERD = jicons is not None and jicons.MODO == "nerd"
FALLBACK = (jicons.PASTA, jicons.ARQUIVO, jicons.LINK) if jicons else ("📁", "📄", "🔗")
CAP_E = getattr(jstatus, "CAP_E", "")
CAP_D = getattr(jstatus, "CAP_D", "")
RAMO = getattr(jstatus, "RAMO", "")
JCODE = Path(__file__).resolve().parent / "JCode.py"
MIDIA = jfcore.EXT_IMAGEM | {".svg", ".mp4", ".mkv", ".webm", ".avi", ".mov",
                             ".mp3", ".flac", ".ogg", ".wav", ".m4a", ".opus"}


# ══════════════════════════════════════════════════════════════════════════════
#  Estado
# ══════════════════════════════════════════════════════════════════════════════
class Estado:
    def __init__(self):
        self.pasta = Path.cwd().resolve()
        self.todos, self.itens = [], []
        self.indice = self.inicio = 0
        self.ocultos = False
        self.ordem = "nome"
        self.filtro = ""
        self.marcados: set[str] = set()
        self.area = None                 # ("copiar"|"recortar", [Path])
        self.modo = "normal"             # normal | filtro | prompt | confirma
        self.tipo = None                 # qual pergunta está aberta
        self.rotulo = ""
        self.texto, self.cursor, self.opcoes = "", 0, []
        self.pendente = None             # dados da confirmação aberta
        self.msg, self.msg_erro, self.msg_t = "", False, 0.0
        self.info = self.ajuda = False
        self.git, self.ramo, self.git_pedido = {}, None, True
        self.opts = jfcore.Opcoes()
        self.resultado = None            # modo seletor: lista de caminhos (vazia = cancelado)
        self.abrir = None                # arquivo a abrir no terminal
        self.externo = None              # comando de shell (!)
        self.recentes = {}


S = Estado()
refresh_pedido = threading.Event()  # acionado pelo JDesk (mensagem "refresh")


def aviso(txt: str, erro: bool = False):
    S.msg, S.msg_erro, S.msg_t = txt, erro, time.time()


def atual():
    return S.itens[S.indice] if S.itens and 0 <= S.indice < len(S.itens) else None


def alvos() -> list[Path]:
    """Itens marcados (que ainda existem) ou, sem marcas, o item sob o cursor."""
    marcados = [Path(p) for p in sorted(S.marcados) if os.path.lexists(p)]
    if marcados:
        return marcados
    e = atual()
    return [e.caminho] if e else []


# ══════════════════════════════════════════════════════════════════════════════
#  Lista e navegação
# ══════════════════════════════════════════════════════════════════════════════
def aplicar_filtro(nome=None, manter=True):
    anterior = S.indice
    S.itens = jfcore.filtrar(S.todos, S.filtro)
    S.indice = 0 if not manter else min(anterior, max(0, len(S.itens) - 1))
    if nome:
        for i, e in enumerate(S.itens):
            if e.nome == nome:
                S.indice = i
                break


def atualizar_lista(destacar=None):
    nome = destacar or (atual().nome if atual() else None)
    try:
        S.todos = jfcore.listar(S.pasta, S.ocultos, S.ordem)
    except OSError as erro:
        S.todos = []
        aviso(f"✗ {erro.strerror or erro}", True)
    aplicar_filtro(nome)


def ir_para(pasta, destacar=None) -> bool:
    pasta = Path(pasta)
    try:
        with os.scandir(pasta):
            pass
        novo = pasta.resolve()
    except OSError as erro:
        aviso(f"✗ {pasta}: {erro.strerror or erro}", True)
        return False
    S.pasta, S.filtro, S.inicio = novo, "", 0
    S.itens, S.indice = [], 0
    S.git, S.ramo, S.git_pedido = {}, None, True
    jfcore.recentes_registrar(novo)
    atualizar_lista(destacar)
    if not destacar:
        S.indice = 0
    return True


def subir():
    if S.pasta.parent == S.pasta:
        aviso("Você já está na raiz.")
        return
    ir_para(S.pasta.parent, destacar=S.pasta.name)


def mover(delta: int):
    if S.itens:
        S.indice = max(0, min(len(S.itens) - 1, S.indice + delta))


# ══════════════════════════════════════════════════════════════════════════════
#  Ações (todas devolvem uma mensagem em `aviso`, nunca derrubam o app)
# ══════════════════════════════════════════════════════════════════════════════
def criar(nome: str, pasta: bool):
    nome = nome.strip()
    if not nome or "/" in nome:
        return aviso("✗ Nome inválido.", True)
    destino = S.pasta / nome
    try:
        destino.mkdir() if pasta else destino.touch(exist_ok=False)
        aviso("✓ Pasta criada" if pasta else "✓ Arquivo criado")
        atualizar_lista(nome)
    except FileExistsError:
        aviso("✗ Já existe um item com este nome.", True)
    except OSError as erro:
        aviso(f"✗ {erro.strerror or erro}", True)


def renomear(novo: str):
    e = atual()
    novo = novo.strip()
    if e is None or not novo or "/" in novo:
        return aviso("✗ Nome inválido.", True)
    destino = e.caminho.with_name(novo)
    if destino.exists():
        return aviso("✗ Já existe um item com este nome.", True)
    try:
        e.caminho.rename(destino)
        S.marcados.discard(str(e.caminho))
        aviso("✓ Renomeado")
        atualizar_lista(novo)
    except OSError as erro:
        aviso(f"✗ {erro.strerror or erro}", True)


def guardar(modo: str):
    lista = alvos()
    if not lista:
        return aviso("✗ Nada selecionado.", True)
    S.area = (modo, lista)
    aviso(f"{'Copiado' if modo == 'copiar' else 'Recortado'}: {len(lista)} item(ns) — vá à pasta de destino e use P")


def colar():
    if not S.area:
        return aviso("✗ Nada copiado/recortado.", True)
    modo, lista = S.area
    feitos, ultimo = 0, None
    for origem in lista:
        try:
            if jfcore.pasta_dentro_de_si(origem, S.pasta):
                aviso(f"✗ '{origem.name}' não cabe dentro dela mesma.", True)
                continue
            if modo == "recortar" and origem.parent == S.pasta:
                continue
            destino = jfcore.nome_livre(S.pasta / origem.name)
            if modo == "copiar":
                if origem.is_dir() and not origem.is_symlink():
                    shutil.copytree(origem, destino, symlinks=True)
                else:
                    shutil.copy2(origem, destino, follow_symlinks=False)
            else:
                shutil.move(str(origem), str(destino))
            feitos, ultimo = feitos + 1, destino.name
        except (OSError, shutil.Error) as erro:
            aviso(f"✗ {origem.name}: {getattr(erro, 'strerror', None) or erro}", True)
    if modo == "recortar":
        S.area = None
        S.marcados.clear()
    if feitos:
        aviso(f"✓ {feitos} item(ns) {'copiado(s)' if modo == 'copiar' else 'movido(s)'}")
    atualizar_lista(ultimo)


def apagar(lista: list[Path], lixeira: bool):
    if lixeira:
        cmd = jfcore.comando_lixeira(lista)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        aviso(f"✓ {len(lista)} item(ns) na lixeira" if ok else "✗ A lixeira falhou (nada foi apagado).", not ok)
    else:
        falhas = 0
        for p in lista:
            try:
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            except OSError:
                falhas += 1
        aviso("✓ Apagado definitivamente" if not falhas else f"✗ {falhas} item(ns) não puderam ser apagados.",
              bool(falhas))
    S.marcados.clear()
    atualizar_lista()


def arrastar():
    lista = alvos()
    if not lista:
        return aviso("✗ Nada para arrastar.", True)
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return aviso("✗ Arrastar precisa de ambiente gráfico (DISPLAY).", True)
    cmd = jfcore.comando_arrastar(lista)
    if cmd is None:
        return aviso("✗ Falta a ferramenta de arrastar: instale ripdrag ou dragon (veja o CHANGELOG).", True)
    try:
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        aviso(f"⇪ Arraste da janelinha: {len(lista)} item(ns)")
    except OSError as erro:
        aviso(f"✗ {erro.strerror or erro}", True)


def copiar_caminhos():
    lista = alvos()
    cmd = jfcore.comando_clipboard()
    if not lista:
        return
    if cmd is None:
        return aviso("✗ Sem xclip/xsel/wl-copy para a área de transferência.", True)
    try:
        subprocess.run(cmd, input="\n".join(map(str, lista)).encode(), timeout=3, check=False)
        aviso(f"✓ Caminho copiado ({len(lista)})")
    except (OSError, subprocess.SubprocessError):
        aviso("✗ Não consegui copiar.", True)


def alternar_marca(e):
    k = str(e.caminho)
    S.marcados.symmetric_difference_update({k})


def ciclar_ordem():
    S.ordem = jfcore.ORDENS[(jfcore.ORDENS.index(S.ordem) + 1) % len(jfcore.ORDENS)]
    atualizar_lista()
    aviso(f"Ordem: {S.ordem}")


def info_linha(e) -> str:
    try:
        st = e.caminho.lstat()
        tipo = "pasta" if e.pasta else ("link" if e.link else "arquivo")
        return (f"{e.nome} · {tipo} · {jfcore.fmt_tamanho(st.st_size)} · {_stat.filemode(st.st_mode)} · "
                f"{jfcore.fmt_data(st.st_mtime)}")
    except OSError:
        return f"{e.nome} · [erro ao ler atributos]"


# ══════════════════════════════════════════════════════════════════════════════
#  Abrir / escolher
# ══════════════════════════════════════════════════════════════════════════════
def finalizar(caminhos, app):
    S.resultado = [str(c) for c in caminhos]
    app.exit()


def comando_para(arquivo: Path):
    """Escolhe o programa certo pela extensão. Devolve (comando, destacado?)."""
    gui = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    suf = arquivo.suffix.lower()
    if suf == ".pdf":
        if gui and shutil.which("zathura"):
            return ["zathura", str(arquivo)], True
        if shutil.which("pdftotext"):
            return ["sh", "-c", 'pdftotext -layout "$1" - | less -R', "_", str(arquivo)], False
    if suf in MIDIA and gui and shutil.which("xdg-open"):
        return ["xdg-open", str(arquivo)], True
    return [sys.executable, str(JCODE), str(arquivo)], False


def ativar(app):
    """Enter no item sob o cursor."""
    e = atual()
    if e is None:
        return
    S.info = False
    if e.pasta:
        ir_para(e.caminho)
        return
    o = S.opts
    if o.pick:
        if o.pasta:
            return aviso("✗ Escolha uma pasta (Tab escolhe a pasta sob o cursor).", True)
        if o.salvar is not None:
            return abrir_prompt("salvar", "Salvar como", e.nome)
        return finalizar(alvos() if (o.multiplo and S.marcados) else [e.caminho], app)
    alvo = e.caminho.resolve()
    # Dentro do JDesk: manda o arquivo para o painel certo; sem JDesk (ou sem resposta) abre aqui.
    if jipc is not None and jipc.enviar({"cmd": "open", "path": str(alvo)}):
        return aviso(f"✓ Aberto no JDesk: {alvo.name}")
    S.abrir = alvo
    app.exit()


# ══════════════════════════════════════════════════════════════════════════════
#  Campo de texto de uma linha (ir, filtro, renomear...)
# ══════════════════════════════════════════════════════════════════════════════
def abrir_prompt(tipo: str, rotulo: str, texto: str = ""):
    S.modo, S.tipo, S.rotulo = "prompt", tipo, rotulo
    S.texto, S.cursor, S.opcoes = texto, len(texto), []


def fechar_prompt():
    S.modo, S.tipo, S.texto, S.cursor, S.opcoes = "normal", None, "", 0, []


def pedir_confirmacao(tipo: str, rotulo: str, dados):
    S.modo, S.tipo, S.rotulo, S.pendente = "confirma", tipo, rotulo, dados


def depois_de_editar():
    S.opcoes = []
    if S.modo == "filtro":
        S.filtro = S.texto
        aplicar_filtro(manter=False)


def inserir(txt: str):
    S.texto = S.texto[:S.cursor] + txt + S.texto[S.cursor:]
    S.cursor += len(txt)
    depois_de_editar()


def sugestoes_ir() -> list[str]:
    t = S.texto.strip()
    if S.opcoes or not t or "/" in t or t.startswith(("~", ".", "$")):
        return S.opcoes
    return [Path(p).name + "  (" + p.replace(str(Path.home()), "~") + ")" for p in
            jfcore.recentes_buscar(t, S.recentes)]


def ir_digitado(app):
    t = S.texto.strip()
    if not t:
        return
    p = jfcore.resolver(t, S.pasta)
    if p.is_dir():
        ir_para(p)
    elif p.exists():
        ir_para(p.parent, destacar=p.name)
    elif "/" not in t and not t.startswith(("~", ".", "$")):
        achados = jfcore.recentes_buscar(t, S.recentes)
        if achados:
            ir_para(achados[0])
        else:
            aviso(f"✗ Nenhuma pasta recente combina com '{t}'.", True)
    else:
        aviso(f"✗ Não existe: {p}", True)


def confirmar_prompt(app):
    tipo, texto = S.tipo, S.texto
    if tipo == "ir":
        fechar_prompt()
        ir_digitado(app)
    elif tipo == "arq":
        fechar_prompt()
        criar(texto, False)
    elif tipo == "pasta":
        fechar_prompt()
        criar(texto, True)
    elif tipo == "renomear":
        fechar_prompt()
        renomear(texto)
    elif tipo == "shell":
        fechar_prompt()
        if texto.strip():
            S.externo = (texto, [str(p) for p in alvos()])
            app.exit()
    elif tipo == "salvar":
        nome = texto.strip()
        if not nome or "/" in nome:
            return aviso("✗ Nome inválido.", True)
        destino = S.pasta / nome
        fechar_prompt()
        if destino.exists():
            pedir_confirmacao("sobrescrever", f"'{nome}' já existe. Substituir? [s/N]", destino)
        else:
            finalizar([destino], app)


def responder_confirmacao(sim: bool, app):
    tipo, dados = S.tipo, S.pendente
    S.modo, S.tipo, S.pendente = "normal", None, None
    if not sim:
        return aviso("Cancelado.")
    if tipo == "apagar":
        apagar(*dados)
    elif tipo == "sobrescrever":
        finalizar([dados], app)


def pedir_apagar():
    lista = alvos()
    if not lista:
        return
    lixeira = jfcore.comando_lixeira(lista) is not None
    nome = lista[0].name if len(lista) == 1 else f"{len(lista)} itens"
    destino = "→ lixeira" if lixeira else "DEFINITIVAMENTE (sem lixeira!)"
    pedir_confirmacao("apagar", f"Apagar {nome} {destino}? [s/N]", (lista, lixeira))


# ══════════════════════════════════════════════════════════════════════════════
#  Desenho
# ══════════════════════════════════════════════════════════════════════════════
def tamanho_terminal():
    """Dimensões seguras mesmo durante a inicialização/redimensionamento."""
    try:
        t = app.renderer.output.get_size()
        return max(1, t.columns), max(1, t.rows)
    except Exception:
        t = shutil.get_terminal_size((80, 24))
        return max(1, t.columns), max(1, t.lines)


def largura_lista() -> int:
    cols, _ = tamanho_terminal()
    return max(50, cols * 55 // 100) if cols >= 100 else cols


def altura_lista() -> int:
    return max(1, tamanho_terminal()[1] - 3)


def pilula(nome: str, texto: str):
    classe = f"class:st.{nome}"
    out = [(f"{classe}.cap", CAP_E)] if NERD else []
    out.append((classe, f" {texto} "))
    if NERD:
        out.append((f"{classe}.cap", CAP_D))
    return out


def _tam(frags) -> int:
    return sum(jfcore.largura(t) for _, t in frags)


def titulo_modo() -> str | None:
    o = S.opts
    if o.titulo:
        return o.titulo
    if not o.pick:
        return None
    if o.salvar is not None:
        return "Salvar como"
    if o.pasta:
        return "Escolher pastas" if o.multiplo else "Escolher pasta"
    return "Escolher arquivos" if o.multiplo else "Escolher arquivo"


def gerar_cabecalho():
    cols, _ = tamanho_terminal()
    pre, pos = [], []
    tm = titulo_modo()
    if tm:
        pre += pilula("m.exp", tm.upper())
        pre.append(("class:st.bar", " "))
    if S.ramo:
        pos += [("class:st.bar", " ")] + pilula("git", f"{RAMO} {S.ramo}" if NERD else S.ramo)
    if S.filtro:
        pos += [("class:st.bar", " ")] + pilula("m.busca", f"/ {S.filtro}")
    caminho = str(S.pasta).replace(str(Path.home()), "~", 1) if str(S.pasta).startswith(str(Path.home())) else str(S.pasta)
    espaco = max(10, cols - _tam(pre) - _tam(pos) - 4)
    if jfcore.largura(caminho) > espaco:
        caminho = "…" + caminho[-(espaco - 1):]
    meio = pilula("arq", caminho)
    resto = max(0, cols - _tam(pre) - _tam(meio) - _tam(pos))
    return pre + meio + pos + [("class:st.bar", " " * resto)]


def _clicar(i: int):
    def tratar(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            mover(-3)
        elif ev.event_type == MouseEventType.SCROLL_DOWN:
            mover(3)
        elif ev.event_type == MouseEventType.MOUSE_UP and ev.button == MouseButton.LEFT:
            if i == S.indice:
                ativar(app)
            else:
                S.indice = i
        else:
            return NotImplemented
        app.invalidate()
    return tratar


AJUDA = [
    ("Navegar", ""),
    ("↑ ↓ PgUp PgDn", "mover        Enter/→ abrir        Backspace/← subir"),
    ("Ctrl+L", "ir para QUALQUER caminho (Tab completa; texto solto = pasta recente)"),
    ("/", "filtrar digitando (Enter entra, Esc limpa)        ~ pasta pessoal"),
    ("Selecionar", ""),
    ("Espaço", "marcar/desmarcar        a marcar tudo        Esc limpa marcas"),
    ("Arquivos", ""),
    ("n / N", "novo arquivo / nova pasta        r ou F2 renomear"),
    ("c  x  p", "copiar / recortar / colar (marcados ou o item sob o cursor)"),
    ("Del ou D", "apagar (lixeira se existir)"),
    ("Poderes", ""),
    ("!", 'rodar comando aqui; "$@" são os marcados, ex.:  !mv "$@" ~/Imagens'),
    ("d", "arrastar para fora (precisa de ripdrag ou dragon)        y copiar caminho"),
    ("Ver", ""),
    ("i", "info/preview        s ordem (nome/tamanho/data)        . ou F3 ocultos"),
    ("Sair", "Ctrl+Q"),
]


def gerar_ajuda():
    out = [("class:jf.titulo", "  Atalhos do JFiles   (qualquer tecla fecha)\n\n")]
    for a, b in AJUDA:
        if not b:
            out.append(("class:jf.titulo", f"\n  {a}\n"))
        else:
            out += [("class:jf.tecla", f"   {a:<16}"), ("class:jf.row", b + "\n")]
    return out


def gerar_corpo():
    if S.ajuda:
        return gerar_ajuda()
    if not S.itens:
        txt = f"  nada casa com '{S.filtro}'\n" if S.filtro else "  (pasta vazia ou sem permissão)\n"
        return [("class:jf.dim", txt)]
    alt, larg = altura_lista(), largura_lista()
    if S.indice < S.inicio:
        S.inicio = S.indice
    elif S.indice >= S.inicio + alt:
        S.inicio = S.indice - alt + 1
    S.inicio = max(0, min(S.inicio, max(0, len(S.itens) - alt)))
    agora = time.time()
    saida = []
    for i in range(S.inicio, min(len(S.itens), S.inicio + alt)):
        e = S.itens[i]
        frags = jfcore.linha(e, larg - 1, i == S.indice, str(e.caminho) in S.marcados,
                             S.git.get(e.nome), NERD, FALLBACK, agora)
        h = _clicar(i)
        saida += [(c, t, h) for c, t in frags] + [("class:jf.row", "\n", h)]
    return saida[:-1]  # sem a última quebra de linha


def preview_imagem(e, pw, alt):
    linhas = [("class:jf.dim", f" {e.nome}  ·  {jfcore.fmt_tamanho(e.tam)}\n")]
    if Image is None:
        return linhas + [("class:jf.dim", "\n Miniaturas precisam do Pillow (pip install pillow)\n")]
    try:
        with Image.open(e.caminho) as img:
            linhas.append(("class:jf.dim", f" {img.format or ''} {img.size[0]}×{img.size[1]}\n\n"))
            mini = img.convert("RGB")
            mini.thumbnail((max(8, pw - 4), max(4, (alt - 4) * 2)), Image.Resampling.LANCZOS)
            w, h = mini.size
            px = mini.load()
            for y in range(0, h, 2):
                for x in range(w):
                    cima = px[x, y]
                    baixo = px[x, y + 1] if y + 1 < h else cima
                    linhas.append((f"fg:#{cima[0]:02x}{cima[1]:02x}{cima[2]:02x} "
                                   f"bg:#{baixo[0]:02x}{baixo[1]:02x}{baixo[2]:02x}", "▀"))
                linhas.append(("class:jf.row", "\n"))
    except Exception as erro:  # arquivo corrompido, formato estranho, falta de memória...
        linhas.append(("class:jf.dim", f" [não deu para abrir a imagem: {erro}]\n"))
    return linhas


def gerar_preview():
    e = atual()
    cols, _ = tamanho_terminal()
    pw, alt = max(10, cols - largura_lista() - 1), altura_lista()
    if e is None:
        return [("class:jf.dim", " nada selecionado\n")]
    if S.info:
        return [("class:jf.row", " " + info_linha(e).replace(" · ", "\n ") + "\n")]
    if e.pasta:
        try:
            filhos = jfcore.listar(e.caminho, S.ocultos)
        except OSError:
            return [("class:jf.dim", " [sem permissão de leitura]\n")]
        if not filhos:
            return [("class:jf.dim", " pasta vazia\n")]
        out = []
        for f in filhos[:alt]:
            glifo, cor = jfcore.icone(f, NERD, FALLBACK)
            out += [(f"class:jf.ico.{cor}", f" {glifo} "),
                    ("class:jf.dir" if f.pasta else "class:jf.row", jfcore.cortar(f.nome, pw - 4).rstrip() + "\n")]
        if len(filhos) > alt:
            out.append(("class:jf.dim", f" … +{len(filhos) - alt}\n"))
        return out
    if e.caminho.suffix.lower() in jfcore.EXT_IMAGEM:
        return preview_imagem(e, pw, alt)
    try:
        with open(e.caminho, "rb") as f:
            bloco = f.read(8192)
    except OSError:
        return [("class:jf.dim", " [sem permissão de leitura]\n")]
    if b"\0" in bloco:
        return [("class:jf.dim", f" [binário · {jfcore.fmt_tamanho(e.tam)}]\n")]
    linhas = bloco.decode("utf-8", errors="replace").replace("\t", "    ").splitlines()
    out = []
    for ln in linhas[:alt]:
        limpo = "".join(c for c in ln if c.isprintable())
        out.append(("class:jf.row", " " + jfcore.cortar(limpo, pw - 2).rstrip() + "\n"))
    return out or [("class:jf.dim", " [arquivo vazio]\n")]


def gerar_status():
    cols, _ = tamanho_terminal()
    if S.modo in ("prompt", "filtro") and S.tipo != "salvar" or S.modo == "prompt":
        opcoes = sugestoes_ir() if S.tipo == "ir" else []
        if opcoes:
            txt = "  ".join(("→ " if i == 0 and not S.opcoes else "") + o for i, o in enumerate(opcoes))
            return [("class:st.bar", " " + jfcore.cortar(txt, cols - 1))]
    esq = []
    if S.marcados:
        esq += pilula("m.sel", f"{len(S.marcados)} marcado(s)") + [("class:st.bar", " ")]
    if S.area:
        esq += pilula("flag", f"{'copiar' if S.area[0] == 'copiar' else 'recortar'} {len(S.area[1])}") + [("class:st.bar", " ")]
    if S.msg and time.time() - S.msg_t < 8:
        esq.append(("class:st.erro" if S.msg_erro else "class:st.msg", " " + S.msg))
    elif atual() is not None:
        esq.append(("class:st.bar", " " + info_linha(atual())))
    dir_ = pilula("flag", f"{S.ordem}{'  ocultos' if S.ocultos else ''}") + [("class:st.bar", " ")]
    dir_ += pilula("pos", f"{S.indice + 1 if S.itens else 0}/{len(S.itens)}")
    espaco = cols - _tam(dir_)
    if _tam(esq) > espaco:    # corta a mensagem em vez de empurrar as pílulas da direita
        txt = "".join(t for _, t in esq)
        esq = [(esq[-1][0] if esq else "class:st.bar", jfcore.cortar(txt, max(0, espaco)).rstrip())]
    folga = max(0, espaco - _tam(esq))
    return esq + [("class:st.bar", " " * folga)] + dir_


DICAS = {
    "normal": [("↵", "abrir"), ("Esp", "marcar"), ("/", "filtro"), ("^L", "ir"), ("!", "shell"), ("d", "arrastar"),
               ("n", "novo"), ("c x p", "copiar/mover"), ("Del", "apagar"), ("?", "ajuda")],
    "pick": [("↵", "escolher"), ("Esp", "marcar"), ("/", "filtro"), ("^L", "ir"), ("⌫", "subir"),
             ("Esc", "cancelar"), ("?", "ajuda")],
}


def gerar_rodape():
    cols, _ = tamanho_terminal()
    if S.modo == "confirma":
        return [("class:st.err", f" {S.rotulo} ")]
    if S.modo in ("prompt", "filtro"):
        rot = "/" if S.modo == "filtro" else S.rotulo
        a, c, b = S.texto[:S.cursor], S.texto[S.cursor:S.cursor + 1] or " ", S.texto[S.cursor + 1:]
        return [("class:st.m.ir", f" {rot} "), ("class:jf.in", " " + a), ("class:jf.cur", c), ("class:jf.in", b + " " * 200)]
    dicas = list(DICAS["pick" if S.opts.pick else "normal"])
    if S.opts.pick and S.opts.pasta:
        dicas.insert(0, ("Tab", "escolher pasta"))
    if S.opts.pick and S.opts.salvar is not None:
        dicas.insert(0, ("Tab", "nome do arquivo"))
    out, usado = [], 0
    for tecla, txt in dicas:
        n = len(tecla) + len(txt) + 3
        if usado + n > cols:
            break
        out += [("class:jf.tecla", f" {tecla}"), ("class:jf.dica", f" {txt} ")]
        usado += n
    return out + [("class:jf.dica", " " * max(0, cols - usado))]


# ══════════════════════════════════════════════════════════════════════════════
#  Teclas
# ══════════════════════════════════════════════════════════════════════════════
teclas = KeyBindings()
normal = Condition(lambda: S.modo == "normal" and not S.ajuda)
editando = Condition(lambda: S.modo in ("prompt", "filtro"))
filtrando = Condition(lambda: S.modo == "filtro")
confirmando = Condition(lambda: S.modo == "confirma")
ajuda_aberta = Condition(lambda: S.ajuda)
em_selecao_pasta = Condition(lambda: S.modo == "normal" and not S.ajuda and S.opts.pick
                             and (S.opts.pasta or S.opts.salvar is not None))


def tecla(*chaves, filtro=normal, eager=False):
    def deco(fn):
        def tratar(event):
            fn(event)
            event.app.invalidate()
        for chave in chaves:   # cada tecla é uma alternativa (add("a","b") seria a SEQUÊNCIA a-b)
            teclas.add(chave, filter=filtro, eager=eager)(tratar)
        return fn
    return deco


@tecla("up")
def _(ev): mover(-1)  # noqa: E704


@tecla("down")
def _(ev): mover(1)  # noqa: E704


@tecla("pageup")
def _(ev): mover(-altura_lista())  # noqa: E704


@tecla("pagedown")
def _(ev): mover(altura_lista())  # noqa: E704


@tecla("home")
def _(ev): S.indice = 0  # noqa: E704


@tecla("end")
def _(ev): S.indice = max(0, len(S.itens) - 1)  # noqa: E704


@tecla("enter")
def _(ev): ativar(ev.app)  # noqa: E704


@tecla("right")
def _(ev):
    e = atual()
    if e is not None and e.pasta:
        ir_para(e.caminho)


@tecla("backspace", "left")
def _(ev): subir()  # noqa: E704


@tecla("~")
def _(ev): ir_para(Path.home())  # noqa: E704


@tecla(" ")
def _(ev):
    e = atual()
    if e is not None:
        alternar_marca(e)
        mover(1)


@tecla("a")
def _(ev):
    chaves = {str(e.caminho) for e in S.itens}
    if chaves and chaves <= S.marcados:
        S.marcados -= chaves
    else:
        S.marcados |= chaves


@tecla("escape", eager=True)
def _(ev):
    if S.filtro:
        S.filtro = ""
        aplicar_filtro(manter=False)
    elif S.marcados:
        S.marcados.clear()
    elif S.area:
        S.area = None
    elif S.opts.pick:
        finalizar([], ev.app)


@tecla("/")
def _(ev):
    S.modo, S.tipo, S.texto, S.cursor = "filtro", "filtro", S.filtro, len(S.filtro)


@tecla("c-l", "g")
def _(ev): abrir_prompt("ir", "ir para")  # noqa: E704


@tecla("!")
def _(ev): abrir_prompt("shell", "$")  # noqa: E704


@tecla("n")
def _(ev): abrir_prompt("arq", "novo arquivo")  # noqa: E704


@tecla("N")
def _(ev): abrir_prompt("pasta", "nova pasta")  # noqa: E704


@tecla("r", "f2")
def _(ev):
    e = atual()
    if e is not None:
        abrir_prompt("renomear", "renomear", e.nome)


@tecla("c")
def _(ev): guardar("copiar")  # noqa: E704


@tecla("x")
def _(ev): guardar("recortar")  # noqa: E704


@tecla("p", "c-v")
def _(ev): colar()  # noqa: E704


@tecla("delete", "D")
def _(ev): pedir_apagar()  # noqa: E704


@tecla("d")
def _(ev): arrastar()  # noqa: E704


@tecla("y")
def _(ev): copiar_caminhos()  # noqa: E704


@tecla("i")
def _(ev):
    e = atual()
    if tamanho_terminal()[0] < 100 and e is not None:   # sem coluna de preview: mostra em uma linha
        aviso(info_linha(e))
    else:
        S.info = not S.info


@tecla("s")
def _(ev): ciclar_ordem()  # noqa: E704


@tecla(".", "f3")
def _(ev):
    S.ocultos = not S.ocultos
    S.inicio = 0
    atualizar_lista()
    aviso("Ocultos visíveis." if S.ocultos else "Ocultos escondidos.")


@tecla("c-r")
def _(ev):
    atualizar_lista()
    S.git_pedido = True


@tecla("?", "f1")
def _(ev): S.ajuda = True  # noqa: E704


@tecla("c-q", filtro=Condition(lambda: S.modo == "normal"))
def _(ev):
    if S.opts.pick:
        finalizar([], ev.app)
    else:
        ev.app.exit()


@tecla("tab", filtro=em_selecao_pasta)
def _(ev):
    o = S.opts
    if o.salvar is not None:
        return abrir_prompt("salvar", "Salvar como", o.salvar or "")
    e = atual()
    if S.marcados:
        finalizar(alvos(), ev.app)
    elif e is not None and e.pasta:
        finalizar([e.caminho], ev.app)
    else:
        finalizar([S.pasta], ev.app)


@teclas.add("<any>", filter=ajuda_aberta)
def _(event):
    S.ajuda = False
    event.app.invalidate()


# ── campo de texto ──
@tecla("escape", filtro=editando, eager=True)
def _(ev):
    if S.modo == "filtro":
        S.filtro = ""
        aplicar_filtro(manter=False)
        S.modo, S.tipo = "normal", None
        S.texto = ""
    else:
        fechar_prompt()


@tecla("enter", filtro=editando)
def _(ev):
    if S.modo == "filtro":
        S.modo, S.tipo, S.texto = "normal", None, ""
        ativar(ev.app)
    else:
        confirmar_prompt(ev.app)


@tecla("up", filtro=filtrando)
def _(ev): mover(-1)  # noqa: E704


@tecla("down", filtro=filtrando)
def _(ev): mover(1)  # noqa: E704


@tecla("left", filtro=editando)
def _(ev): S.cursor = max(0, S.cursor - 1)  # noqa: E704


@tecla("right", filtro=editando)
def _(ev): S.cursor = min(len(S.texto), S.cursor + 1)  # noqa: E704


@tecla("home", "c-a", filtro=editando)
def _(ev): S.cursor = 0  # noqa: E704


@tecla("end", "c-e", filtro=editando)
def _(ev): S.cursor = len(S.texto)  # noqa: E704


@tecla("backspace", filtro=editando)
def _(ev):
    if S.cursor:
        S.texto = S.texto[:S.cursor - 1] + S.texto[S.cursor:]
        S.cursor -= 1
        depois_de_editar()


@tecla("delete", filtro=editando)
def _(ev):
    S.texto = S.texto[:S.cursor] + S.texto[S.cursor + 1:]
    depois_de_editar()


@tecla("c-u", filtro=editando)
def _(ev):
    S.texto, S.cursor = S.texto[S.cursor:], 0
    depois_de_editar()


@tecla("c-w", filtro=editando)
def _(ev):
    antes = S.texto[:S.cursor].rstrip()
    corte = max(antes.rfind("/"), antes.rfind(" ")) + 1
    S.texto, S.cursor = S.texto[:corte] + S.texto[S.cursor:], corte
    depois_de_editar()


@tecla("tab", filtro=Condition(lambda: S.modo == "prompt" and S.tipo == "ir"))
def _(ev):
    novo, opcoes = jfcore.completar(S.texto, S.pasta)
    S.texto, S.cursor, S.opcoes = novo, len(novo), opcoes
    if not opcoes:
        aviso("Sem sugestões.")


@teclas.add("<any>", filter=editando)
def _(event):
    txt = "".join(k.data for k in event.key_sequence if k.data and k.data.isprintable())
    if txt:
        inserir(txt)
        event.app.invalidate()


@teclas.add("<bracketed-paste>", filter=editando)
def _(event):
    inserir("".join(c for c in event.data if c.isprintable()))
    event.app.invalidate()


# ── confirmação (s/N) ──
@teclas.add("<any>", filter=confirmando)
def _(event):
    dados = "".join(k.data for k in event.key_sequence)
    responder_confirmacao(dados.lower() in ("s", "y"), event.app)
    event.app.invalidate()


# ══════════════════════════════════════════════════════════════════════════════
#  Layout e aplicação
# ══════════════════════════════════════════════════════════════════════════════
colunas_preview = Condition(lambda: tamanho_terminal()[0] >= 100 and not S.ajuda)

layout = Layout(HSplit([
    Window(content=FormattedTextControl(gerar_cabecalho), height=1),
    VSplit([
        Window(content=FormattedTextControl(gerar_corpo), style="class:jf.row",
               width=lambda: Dimension.exact(largura_lista()) if tamanho_terminal()[0] >= 100 and not S.ajuda
               else Dimension()),
        ConditionalContainer(Window(width=1, char="│", style="class:jf.sep"), filter=colunas_preview),
        ConditionalContainer(Window(content=FormattedTextControl(gerar_preview), style="class:jf.row",
                                    wrap_lines=False), filter=colunas_preview),
    ]),
    Window(content=FormattedTextControl(gerar_status), height=1, style="class:st.bar"),
    Window(content=FormattedTextControl(gerar_rodape), height=1, style="class:jf.dica"),
]))

estilo = Style.from_dict(jfcore.estilos(jtheme))
app = Application(layout=layout, key_bindings=teclas, style=estilo, full_screen=True, mouse_support=True)


# ── atualização automática ───────────────────────────────────────────────────
# O mtime da pasta muda quando entra, sai ou é renomeado um arquivo (ex.: download do JClass).
# Checar isso é quase de graça, então a lista acompanha o disco sem F5. O git roda fora do laço
# de desenho (em thread) a cada ~3 s, para um repositório grande nunca travar a tela.
def _assinatura_pasta():
    try:
        return S.pasta.stat().st_mtime_ns
    except OSError:
        return None


async def vigiar_pasta():
    pasta, assinatura, ciclo = S.pasta, _assinatura_pasta(), 0
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(0.7)
        ciclo += 1
        forcar = refresh_pedido.is_set()
        refresh_pedido.clear()
        if S.pasta != pasta:  # o usuário navegou: a lista já foi atualizada
            pasta, assinatura = S.pasta, _assinatura_pasta()
        else:
            atual_ = _assinatura_pasta()
            if forcar or atual_ != assinatura:
                assinatura = atual_
                atualizar_lista()
                app.invalidate()
        if S.git_pedido or ciclo % 4 == 0:
            S.git_pedido = False
            alvo = S.pasta
            try:
                marcas, ramo = await loop.run_in_executor(None, lambda a=alvo: (jfcore.git_marcas(a), jfcore.ramo(a)))
            except Exception:  # decorativo: nunca derruba o app
                continue
            if alvo == S.pasta and (marcas != S.git or ramo != S.ramo):
                S.git, S.ramo = marcas, ramo
                app.invalidate()


def iniciar_vigia():
    criar = getattr(app, "create_background_task", None)
    if criar is not None:
        criar(vigiar_pasta())


def _ao_receber(msg):  # thread do jipc: só sinaliza; quem mexe na lista é o laço do app
    if msg.get("cmd") == "refresh":
        refresh_pedido.set()


def rodar_shell(cmd: str, arquivos: list[str]):
    print(f"\n$ {cmd}\n")
    try:
        subprocess.run(["sh", "-c", cmd, "jfiles", *arquivos], cwd=S.pasta, check=False)
    except OSError as erro:
        print(erro)
    try:
        input("\n[Enter para voltar ao JFiles]")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    S.opts = jfcore.ler_argumentos(argv)
    S.recentes = jfcore.recentes_ler()
    pasta, destacar = jfcore.ponto_de_partida(S.opts.inicio, Path.cwd())
    S.pasta = Path(pasta)
    # Só o painel "jfiles" do JDesk se registra (um JFiles aberto pelo JShell não rouba as mensagens).
    if (not S.opts.pick and jipc is not None and jipc.disponivel()
            and os.environ.get("JDESK_PANE") == "jfiles"):
        jipc.Receptor("jfiles", _ao_receber).iniciar()

    try:
        while True:
            S.recentes = jfcore.recentes_ler()
            atualizar_lista(destacar)
            destacar = None
            if S.opts.pick and S.opts.salvar is not None and S.modo == "normal" and S.resultado is None:
                abrir_prompt("salvar", "Salvar como", S.opts.salvar or "")
            app.run(pre_run=iniciar_vigia)

            if S.externo:
                cmd, arquivos = S.externo
                S.externo = None
                rodar_shell(cmd, arquivos)
                continue
            if S.abrir is not None:
                arquivo, S.abrir = S.abrir, None
                try:
                    cmd, destacado = comando_para(arquivo)
                    if destacado:  # janela gráfica: não prende o terminal
                        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        subprocess.run(cmd, check=False)
                except OSError as erro:
                    aviso(f"✗ Erro ao abrir: {erro}", True)
                continue
            break
    finally:
        if S.opts.pick:   # sempre grava (vazio = cancelado), senão o portal ficaria esperando
            try:
                jfcore.gravar_escolha(S.opts.saida, S.resultado or [])
            except OSError as erro:
                print(f"JFiles: não consegui gravar {S.opts.saida}: {erro}", file=sys.stderr)
            if S.resultado and not S.opts.saida:
                print("\n".join(S.resultado))
    return 0 if (not S.opts.pick or S.resultado) else 1


if __name__ == "__main__":
    sys.exit(main())
