import difflib
import fnmatch
import getpass
import glob
import os
import re
import shlex
import shutil
import stat
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from html import escape as esc
from itertools import islice
from pathlib import Path

try:  # canal de mensagens do JDesk (opcional)
    import jipc
except ImportError:
    jipc = None

try:  # motor bash (opcional): sem ele o JShell continua funcionando como antes
    import jbash
except ImportError:
    jbash = None

try:  # ícones conforme o terminal (JICONES=nerd|emoji|ascii); sem jicons.py, emojis como sempre
    from jicons import ARQUIVO, LINK, PASTA, PASTA_ABERTA
except ImportError:
    PASTA, PASTA_ABERTA, ARQUIVO, LINK = "📁", "📂", "📄", "🔗"

from prompt_toolkit import PromptSession, print_formatted_text, HTML
from prompt_toolkit.application import get_app_or_none
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

try:
    import jtheme  # paleta compartilhada do JDev (opcional: sem ele vale o Tokyo Night embutido)
except ImportError:
    jtheme = None

BASE_DIR = Path(__file__).resolve().parent
JCODE = BASE_DIR / "JCode.py"
JFILES = BASE_DIR / "JFiles.py"
JCLASS = next((c for c in (BASE_DIR / "tools" / "JClass" / "JClass.py", BASE_DIR / "JClass" / "JClass.py")
               if c.is_file()), BASE_DIR / "tools" / "JClass" / "JClass.py")
HISTORICO = Path.home() / ".jshell_history"
RC = Path.home() / ".jshellrc"
IS_WIN = os.name == "nt"

# Tema elegante, minimalista e de alta legibilidade. Com o jtheme.py ao lado, segue o tema escolhido
# (python3 jtheme.py set <nome>); sem ele, vale o Tokyo Night abaixo (contraste consistente em tudo).
_tema = getattr(jtheme, "estilo_jshell", None)   # paleta do jtheme.py, se existir ao lado
estilo_jshell = Style.from_dict(_tema() if _tema else {
        'prompt': '#7dcfff bold',
        'error': '#f7768e bold',
        'success': '#9ece6a bold',
        'info': '#7aa2f7',
        'secondary': '#737aa2',
        'command': '#bb9af7 bold',
        'arg': '#e0af68',
        'auto-suggestion': '#565f89',
        # prompt "HUD": pílulas (sem setas) + barra de vida no canto direito
        'pill.cwd': 'bg:#292e42 #7aa2f7 bold',
        'pill.git': 'bg:#1f2335 #bb9af7',
        'pill.gitdirty': 'bg:#1f2335 #e0af68',
        'pill.err': 'bg:#f7768e #16161e bold',
        'pill.root': 'bg:#f7768e #16161e bold',
        'combo.full': 'bg:#9ece6a #16161e bold',
        'combo.mid': 'bg:#e0af68 #16161e bold',
        'combo.low': 'bg:#f7768e #16161e bold',
        'hp.full': '#9ece6a',
        'hp.mid': '#e0af68',
        'hp.low': '#f7768e',
        'hp.empty': '#3b4261',
        'rprompt': '#565f89',
        'continuation': '#565f89',
        # realce enquanto digita
        'cmd.ok': '#9ece6a bold',
        'cmd.bad': '#f7768e',
        'kw': '#bb9af7 bold',
        'str': '#e0af68',
        'var': '#7dcfff',
        'op': '#bb9af7',
        'flag': '#7aa2f7',
        'path': 'underline',
        'comment': '#565f89 italic',
        'dir': '#7aa2f7 bold',
})

# ══════════════════════════════════════════════════════════════════════════════
#  Infraestrutura
# ══════════════════════════════════════════════════════════════════════════════

STATUS = 0          # código de saída do último comando
SESSAO = None       # PromptSession (usada pelo comando history)
ALIASES = {"ll": "ls -l", "..": "cd ..", "...": "cd ../.."}

COMANDOS = {}       # nome/alias -> (função, expandir_glob)
AJUDA = []          # (grupo, nome, uso, descrição) na ordem de declaração


class SairShell(Exception):
    pass


class ErroArgs(Exception):
    """Erro de uso/argumentos (mensagem em texto simples, sem markup)."""


def imprimir(texto):
    """Imprime texto formatado (HTML do prompt_toolkit)."""
    print_formatted_text(HTML(texto), style=estilo_jshell)


def imprimir_ft(fragmentos):
    """Imprime fragmentos (estilo, texto) sem precisar escapar nada."""
    print_formatted_text(FormattedText(fragmentos), style=estilo_jshell)


def escrever(texto):
    """Saída crua (conteúdo de arquivos etc.)."""
    sys.stdout.write(texto)


def ok(msg):
    imprimir(f"<success>✓</success> {msg}")
    return 0


def erro(msg):
    imprimir(f"<error>Erro:</error> {msg}")
    return 1


def fmt(caminho):
    return f"<info>{esc(str(caminho))}</info>"


def uso(nome, args=""):
    imprimir(f"<info>Uso:</info> <command>{nome}</command> <arg>{esc(args)}</arg>")
    return 1


def comando(nome, uso_txt, desc, grupo, glob_=True, aliases=()):
    """Registra um comando interno (aparece automaticamente no help)."""
    def deco(fn):
        AJUDA.append((grupo, nome, uso_txt, desc))
        for n in (nome, *aliases):
            COMANDOS[n] = (fn, glob_)
        return fn
    return deco


def parse(args, bool_flags="", val_flags=""):
    """Separa flags curtas (-abc, -n 5, -n5) dos argumentos posicionais."""
    flags, pos = {}, []
    it = iter(args)
    fim = False
    for a in it:
        if fim or a == "-" or not a.startswith("-"):
            pos.append(a)
            continue
        if a == "--":
            fim = True
            continue
        if "n" in val_flags and re.fullmatch(r"-\d+", a):
            flags["n"] = a[1:]
            continue
        letras = a[1:]
        for j, c in enumerate(letras):
            if c in bool_flags:
                flags[c] = True
            elif c in val_flags:
                resto = letras[j + 1:]
                if resto:
                    flags[c] = resto
                else:
                    try:
                        flags[c] = next(it)
                    except StopIteration:
                        raise ErroArgs(f"a opção -{c} precisa de um valor") from None
                break
            else:
                raise ErroArgs(f"opção desconhecida: -{c}")
    return flags, pos


TEM_GLOB = re.compile(r"[*?\[]")


def expandir(args, glob_=True):
    """Expande ~, $VAR e curingas (*, ?) como um shell comum."""
    saida = []
    for a in args:
        a = os.path.expandvars(os.path.expanduser(a))
        if glob_ and TEM_GLOB.search(a):
            achados = sorted(glob.glob(a))
            if achados:
                saida.extend(achados)
                continue
        saida.append(a)
    return saida


def limpar_tela():
    """Limpa a tela e o scrollback no JTerm (CSI 3 J), sem depender de terminfo."""
    sys.stdout.write("\x1b[3J\x1b[H\x1b[2J")
    sys.stdout.flush()


def formatar_tamanho(tamanho_bytes):
    for unidade in ["B", "KB", "MB", "GB"]:
        if tamanho_bytes < 1024.0:
            return f"{tamanho_bytes:.1f} {unidade}"
        tamanho_bytes /= 1024.0

    return f"{tamanho_bytes:.1f} TB"


def tamanho_dir(caminho):
    """Tamanho total de uma pasta (sem seguir links simbólicos)."""
    total, pilha = 0, [caminho]
    while pilha:
        atual = pilha.pop()
        try:
            with os.scandir(atual) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            pilha.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def percorrer_arquivos(raiz):
    for base, dirs, nomes in os.walk(raiz, onerror=lambda e: None):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for n in sorted(nomes):
            yield Path(base) / n


def abrir_texto(caminho):
    """Abre um arquivo de texto, recusando pastas, binários e erros de acesso."""
    p = Path(caminho).expanduser()
    if not p.exists():
        raise ErroArgs(f"Não encontrado: {p}")
    if p.is_dir():
        raise ErroArgs(f"É um diretório: {p}")
    try:
        with open(p, "rb") as f:
            if b"\0" in f.read(4096):
                raise ErroArgs(f"Arquivo binário: {p}")
        return open(p, "r", encoding="utf-8", errors="replace")
    except PermissionError:
        raise ErroArgs(f"Sem permissão para ler: {p}") from None


def por_arquivo(arquivos, fn):
    status = 0
    for i, a in enumerate(arquivos):
        try:
            with abrir_texto(a) as f:
                if len(arquivos) > 1:
                    escrever(("\n" if i else "") + f"==> {a} <==\n")
                fn(f)
        except ErroArgs as e:
            status |= erro(esc(str(e)))
        except OSError as e:
            status |= erro(esc(str(e)))
    return status


def eh_protegido(p):
    """Impede apagar a raiz, a home ou qualquer pasta que contenha o diretório atual."""
    try:
        r = p.resolve()
        cwd = Path.cwd().resolve()
        return r == Path(r.anchor) or r == Path.home().resolve() or r == cwd or r in cwd.parents
    except OSError:
        return False


def confirmar(pergunta):
    try:
        resp = input(f"{pergunta} [s/N] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return resp.strip().lower() in ("s", "sim", "y", "yes")


# ══════════════════════════════════════════════════════════════════════════════
#  Comandos já existentes (mesmo comportamento, agora com código de status)
# ══════════════════════════════════════════════════════════════════════════════

def mudar_diretorio(caminho):
    try:
        os.chdir(Path(caminho).expanduser())
        return 0
    except FileNotFoundError:
        return erro("Diretório não encontrado.")
    except NotADirectoryError:
        return erro("Isso não é um diretório.")
    except PermissionError:
        return erro("Sem permissão para acessar esse diretório.")
    except OSError as e:
        return erro(esc(str(e)))


def remover_diretorio(caminho):
    pasta = Path(caminho).expanduser()

    if not pasta.exists():
        return erro(f"Diretório não encontrado: {fmt(pasta)}")

    if not pasta.is_dir():
        return erro(f"Isso não é um diretório: {fmt(pasta)}")

    try:
        pasta.rmdir()
        return ok(f"Diretório removido: {fmt(pasta)}")
    except PermissionError:
        return erro("Sem permissão para remover o diretório.")
    except OSError:
        return erro("O diretório não está vazio.")


def criar_diretorio(caminho, pais=False):
    pasta = Path(caminho).expanduser()

    if pasta.exists():
        if pais and pasta.is_dir():
            return 0
        return erro(f"Já existe: {fmt(pasta)}")

    try:
        pasta.mkdir(parents=pais)
        return ok(f"Diretório criado: {fmt(pasta)}")
    except FileNotFoundError:
        return erro("O caminho pai não existe. <secondary>(use -p para criá-lo)</secondary>")
    except PermissionError:
        return erro("Sem permissão para criar o diretório.")
    except OSError as e:
        return erro(esc(str(e)))


def criar_arquivo(caminho):
    arquivo = Path(caminho).expanduser()

    if arquivo.exists():
        return erro(f"Já existe: {fmt(arquivo)}")

    try:
        arquivo.touch()
        return ok(f"Arquivo criado: {fmt(arquivo)}")
    except FileNotFoundError:
        return erro("O diretório pai não existe.")
    except PermissionError:
        return erro("Sem permissão para criar o arquivo.")
    except OSError as e:
        return erro(esc(str(e)))


def renomear(origem, destino):
    origem = Path(origem).expanduser()
    destino = Path(destino).expanduser()

    if not origem.exists():
        return erro(f"Não encontrado: {fmt(origem)}")

    if destino.exists():
        return erro(f"Destino já existe: {fmt(destino)}")

    try:
        origem.rename(destino)
        return ok(f"<info>{esc(origem.name)}</info> → {fmt(destino)}")
    except PermissionError:
        return erro("Sem permissão para renomear.")
    except OSError as e:
        return erro(esc(str(e)))


def _tipo(e):
    try:
        if e.is_dir():
            return "d"
        if e.is_file():
            return "f"
    except OSError:
        pass
    return "o"


def listar(alvo=None, detalhes=False, ordem="nome",
        inverter=False, mostrar_ocultos=False):
    pasta = Path(alvo).expanduser() if alvo else Path.cwd()

    try:
        with os.scandir(pasta) as it:
            entradas = [
                e for e in it
                if mostrar_ocultos or not e.name.startswith(".")
            ]

    except FileNotFoundError:
        return erro(f"Não encontrado: {fmt(pasta)}")
    except NotADirectoryError:
        return erro(f"Isso não é um diretório: {fmt(pasta)}")
    except PermissionError:
        imprimir("<secondary>" + "─" * 55 + "</secondary>")
        return erro("Sem permissão para acessar este diretório.")

    itens = []
    for e in entradas:
        try:
            st = e.stat()
        except OSError:
            st = None
        itens.append((e, _tipo(e), st))


    def chave(it):
        e, t, st = it
        grupo = 0 if t == "d" else 1
        if ordem == "tempo":
            return (grupo, -(st.st_mtime if st else 0))
        if ordem == "tamanho":
            return (grupo, -(st.st_size if st else 0))
        return (grupo, e.name.lower())

    itens.sort(key=chave, reverse=inverter)

    linhas = [
        "<secondary>" + "─" * 55 + "</secondary>",
    ]

    if not itens:
        linhas.append("<secondary>  (diretório vazio)</secondary>")
        imprimir("\n".join(linhas))
        return 0

    n_pastas = n_arquivos = n_outros = 0
    for e, t, st in itens:
        nome = esc(e.name)
        extra = ""
        if detalhes:
            modo = stat.filemode(st.st_mode) if st else "?" * 10
            data = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%y %H:%M") if st else "?" * 14
            tam = formatar_tamanho(st.st_size) if (st and t != "d") else "-"
            extra = f"<secondary>{modo} {data} {tam:>9}</secondary>  "
            if e.is_symlink():
                try:
                    nome += f" <secondary>→ {esc(os.readlink(e.path))}</secondary>"
                except OSError:
                    pass

        if t == "d":
            n_pastas += 1
            linhas.append(f"  <command>{PASTA}</command> {extra}<info>{nome}/</info>")
        elif t == "f":
            n_arquivos += 1
            if detalhes:
                linhas.append(f"  <arg>{ARQUIVO}</arg> {extra}<secondary>{nome}</secondary>")
            else:
                tamanho = formatar_tamanho(st.st_size) if st else "?"
                linhas.append(
                    f"  <arg>{ARQUIVO}</arg> <secondary>{nome}</secondary> <secondary>[{tamanho}]</secondary>"
                )
        else:
            n_outros += 1
            linhas.append(f"  <arg>{LINK}</arg> {extra}<secondary>{nome}</secondary>")

    linhas.append("<secondary>" + "─" * 55 + "</secondary>")
    resumo = f"{n_pastas} pasta(s) · {n_arquivos} arquivo(s)"
    if n_outros:
        resumo += f" · {n_outros} outro(s)"
    linhas.append(f"<secondary>{resumo}</secondary>")
    imprimir("\n".join(linhas))
    return 0


def abrir_jcode(caminho, criar=False, aqui=False):
    arquivo = Path(caminho).expanduser()

    if not arquivo.is_absolute():
        arquivo = Path.cwd() / arquivo

    arquivo = arquivo.resolve()

    if arquivo.exists() and not arquivo.is_file():
        return erro(f"Isso não é um arquivo: {fmt(arquivo)}")

    if not arquivo.exists() and not criar:
        return erro(f"Arquivo não encontrado: {fmt(arquivo)}")

    if not JCODE.exists():
        return erro(f"JCode não encontrado: {fmt(JCODE)}")

    # Dentro do JDesk, abre no painel do JCode (use --aqui para abrir neste terminal).
    if not aqui and jipc is not None and jipc.enviar({"cmd": "open", "path": str(arquivo)}):
        imprimir(f"<secondary>Aberto no JCode do JDesk:</secondary> {fmt(arquivo)}")
        return 0

    try:
        return subprocess.run([sys.executable, str(JCODE), str(arquivo)]).returncode
    except KeyboardInterrupt:
        imprimir("\n<secondary>JCode interrompido.</secondary>")
        return 130


def abrir_jfiles():
    if not JFILES.exists():
        return erro(f"JFiles não encontrado: {fmt(JFILES)}")

    try:
        return subprocess.run([sys.executable, str(JFILES)]).returncode
    except KeyboardInterrupt:
        imprimir("\n<secondary>JFiles interrompido.</secondary>")
        return 130


# ══════════════════════════════════════════════════════════════════════════════
#  Registro dos comandos
# ══════════════════════════════════════════════════════════════════════════════

# ── Navegação ────────────────────────────────────────────────────────────────

@comando("ls", "[-l] [-t] [-S] [-r] [pasta]", "Lista os arquivos (-l detalhes, -t data, -S tamanho, -r inverte)",
         "Navegação", aliases=("dir", "jls"))
def cmd_ls(args):
    flags, alvos = parse(args, "ltSr")
    ordem = "tamanho" if "S" in flags else "tempo" if "t" in flags else "nome"
    status = 0
    for i, alvo in enumerate(alvos or [None]):
        if i:
            imprimir("")
        status |= listar(alvo, "l" in flags, ordem, "r" in flags)
    return status


@comando("cd", "[pasta]", "Muda o diretório atual (sem argumento: home · cd - : anterior)", "Navegação")
def cmd_cd(args):
    if len(args) > 1:
        return erro("Muitos argumentos.")
    destino = args[0] if args else "~"
    voltando = destino == "-"
    if voltando:
        destino = os.environ.get("OLDPWD")
        if not destino:
            return erro("OLDPWD não definido.")
    try:
        anterior = os.getcwd()
    except OSError:
        anterior = None
    status = mudar_diretorio(destino)
    if status == 0:
        if anterior:
            os.environ["OLDPWD"] = anterior
        if voltando:
            imprimir(fmt(Path.cwd()))
    return status


@comando("pwd", "", "Mostra o diretório atual", "Navegação")
def cmd_pwd(args):
    imprimir(fmt(Path.cwd()))
    return 0


@comando("tree", "[-a] [-L n] [pasta]", "Mostra a árvore de pastas (profundidade padrão: 3)", "Navegação")
def cmd_tree(args):
    flags, pos = parse(args, "a", "L")
    try:
        prof = int(flags.get("L", 3))
    except ValueError:
        return erro("Profundidade inválida.")
    raiz = Path(pos[0]).expanduser() if pos else Path.cwd()
    if not raiz.is_dir():
        return erro(f"Isso não é um diretório: {fmt(raiz)}")

    linhas = [f"<info>{esc(str(raiz))}</info>"]
    contagem = [0, 0]
    limite = 2000

    def eh_dir(e):
        try:
            return e.is_dir(follow_symlinks=False)
        except OSError:
            return False

    def descer(caminho, prefixo, nivel):
        if nivel > prof or len(linhas) >= limite:
            return
        try:
            with os.scandir(caminho) as it:
                entradas = [e for e in it if "a" in flags or not e.name.startswith(".")]
        except OSError:
            linhas.append(f"<secondary>{prefixo}└── </secondary><error>(sem permissão)</error>")
            return
        entradas.sort(key=lambda e: (not eh_dir(e), e.name.lower()))
        for i, e in enumerate(entradas):
            if len(linhas) >= limite:
                break
            ultimo = i == len(entradas) - 1
            ramo = "└── " if ultimo else "├── "
            if eh_dir(e):
                contagem[0] += 1
                linhas.append(f"<secondary>{prefixo}{ramo}</secondary><info>{esc(e.name)}/</info>")
                descer(e.path, prefixo + ("    " if ultimo else "│   "), nivel + 1)
            else:
                contagem[1] += 1
                linhas.append(f"<secondary>{prefixo}{ramo}</secondary>{esc(e.name)}")

    descer(raiz, "", 1)
    if len(linhas) >= limite:
        linhas.append("<secondary>… (saída truncada)</secondary>")
    linhas.append(f"<secondary>{contagem[0]} pasta(s) · {contagem[1]} arquivo(s)</secondary>")
    imprimir("\n".join(linhas))
    return 0


# ── Arquivos e pastas ────────────────────────────────────────────────────────

@comando("mkdir", "[-p] pasta...", "Cria uma pasta (-p cria os pais)", "Arquivos")
def cmd_mkdir(args):
    flags, pos = parse(args, "p")
    if not pos:
        return uso("mkdir", "pasta")
    status = 0
    for p in pos:
        status |= criar_diretorio(p, "p" in flags)
    return status


@comando("rd", "pasta...", "Remove uma pasta vazia", "Arquivos", aliases=("rmdir",))
def cmd_rd(args):
    _, pos = parse(args)
    if not pos:
        return uso("rd", "pasta")
    status = 0
    for p in pos:
        status |= remover_diretorio(p)
    return status


@comando("touch", "arquivo...", "Cria um arquivo vazio", "Arquivos")
def cmd_touch(args):
    _, pos = parse(args)
    if not pos:
        return uso("touch", "arquivo")
    status = 0
    for p in pos:
        status |= criar_arquivo(p)
    return status


@comando("ren", "antigo novo", "Renomeia um item", "Arquivos", aliases=("rename",))
def cmd_ren(args):
    if len(args) < 2:
        imprimir("<info>Uso:</info> <command>ren</command> <arg>antigo</arg> <arg>novo</arg>")
        return 1
    return renomear(args[0], args[1])


def _copiar(origem, alvo, recursivo, forcar):
    try:
        if origem.is_dir() and not origem.is_symlink():
            if not recursivo:
                return erro(f"É um diretório (use -r): {fmt(origem)}")
            ro, ra = origem.resolve(), alvo.resolve()
            if ra == ro or ro in ra.parents:
                return erro("Não é possível copiar uma pasta para dentro dela mesma.")
            if alvo.exists():
                return erro(f"Destino já existe: {fmt(alvo)}")
            shutil.copytree(origem, alvo, symlinks=True)
        else:
            if alvo.is_dir():
                return erro(f"Destino é uma pasta: {fmt(alvo)}")
            if alvo.exists():
                if os.path.samefile(origem, alvo):
                    return erro("Origem e destino são o mesmo arquivo.")
                if not forcar:
                    return erro(f"Destino já existe: {fmt(alvo)} <secondary>(use -f para sobrescrever)</secondary>")
            shutil.copy2(origem, alvo)
        return ok(f"<info>{esc(origem.name)}</info> → {fmt(alvo)}")
    except PermissionError:
        return erro("Sem permissão.")
    except (OSError, shutil.Error) as e:
        return erro(esc(str(e)))


@comando("cp", "[-r] [-f] origem... destino", "Copia arquivos/pastas (-r pastas, -f sobrescreve)",
         "Arquivos", aliases=("copy",))
def cmd_cp(args):
    flags, pos = parse(args, "rRf")
    if len(pos) < 2:
        return uso("cp", "[-r] [-f] origem... destino")
    *origens, destino = pos
    destino = Path(destino).expanduser()
    if len(origens) > 1 and not destino.is_dir():
        return erro("Com várias origens, o destino precisa ser uma pasta.")
    status = 0
    for o in origens:
        origem = Path(o).expanduser()
        if not origem.exists():
            status |= erro(f"Não encontrado: {fmt(origem)}")
            continue
        alvo = destino / origem.name if destino.is_dir() else destino
        status |= _copiar(origem, alvo, "r" in flags or "R" in flags, "f" in flags)
    return status

@comando("mv", "[-f] origem... destino", "Move/renomeia arquivos e pastas (-f sobrescreve)",
         "Arquivos", aliases=("move",))
def cmd_mv(args):
    flags, pos = parse(args, "f")
    if len(pos) < 2:
        return uso("mv", "[-f] origem... destino")
    *origens, destino = pos
    destino = Path(destino).expanduser()
    if len(origens) > 1 and not destino.is_dir():
        return erro("Com várias origens, o destino precisa ser uma pasta.")
    status = 0
    for o in origens:
        origem = Path(o).expanduser()
        if not origem.exists() and not origem.is_symlink():
            status |= erro(f"Não encontrado: {fmt(origem)}")
            continue
        alvo = destino / origem.name if destino.is_dir() else destino
        try:
            if origem.is_dir() and not origem.is_symlink():
                ro, ra = origem.resolve(), alvo.resolve()
                if ra == ro or ro in ra.parents:
                    status |= erro("Não é possível mover uma pasta para dentro dela mesma.")
                    continue
            if alvo.exists() or alvo.is_symlink():
                if not alvo.is_dir() and "f" in flags and not alvo.samefile(origem):
                    alvo.unlink()
                else:
                    status |= erro(f"Destino já existe: {fmt(alvo)}"
                                   + ("" if alvo.is_dir() else " <secondary>(use -f para sobrescrever)</secondary>"))
                    continue
            shutil.move(str(origem), str(alvo))
            status |= ok(f"<info>{esc(origem.name)}</info> → {fmt(alvo)}")
        except PermissionError:
            status |= erro("Sem permissão.")
        except (OSError, shutil.Error) as e:
            status |= erro(esc(str(e)))
    return status


@comando("rm", "[-r] [-f] alvo...", "Remove arquivos (-r pastas, com confirmação · -f sem perguntar)",
         "Arquivos", aliases=("del",))
def cmd_rm(args):
    flags, pos = parse(args, "rRf")
    if not pos:
        return uso("rm", "[-r] [-f] alvo...")
    recursivo = "r" in flags or "R" in flags
    forcar = "f" in flags
    status = 0
    for a in pos:
        p = Path(a).expanduser()
        try:
            if p.is_symlink():
                p.unlink()
                status |= ok(f"Removido: {fmt(p)}")
            elif not p.exists():
                if not forcar:
                    status |= erro(f"Não encontrado: {fmt(p)}")
            elif p.is_dir():
                if not recursivo:
                    status |= erro(f"É um diretório (use -r): {fmt(p)}")
                elif eh_protegido(p):
                    status |= erro(f"Recusado por segurança: {fmt(p)}")
                elif forcar or confirmar(f"Remover {p} e todo o seu conteúdo?"):
                    shutil.rmtree(p)
                    status |= ok(f"Removido: {fmt(p)}")
                else:
                    imprimir("<secondary>Cancelado.</secondary>")
            else:
                p.unlink()
                status |= ok(f"Removido: {fmt(p)}")
        except PermissionError:
            status |= erro(f"Sem permissão: {fmt(p)}")
        except OSError as e:
            status |= erro(esc(str(e)))
    return status


@comando("du", "[pasta]", "Mostra o tamanho de cada item (ordenado)", "Arquivos")
def cmd_du(args):
    _, pos = parse(args)
    alvo = Path(pos[0]).expanduser() if pos else Path.cwd()
    if not alvo.exists():
        return erro(f"Não encontrado: {fmt(alvo)}")
    if alvo.is_file():
        imprimir(f"<secondary>{formatar_tamanho(alvo.stat().st_size):>10}</secondary>  {fmt(alvo)}")
        return 0
    try:
        entradas = list(os.scandir(alvo))
    except PermissionError:
        return erro("Sem permissão para acessar este diretório.")
    medidas = []
    for e in entradas:
        try:
            if e.is_dir(follow_symlinks=False):
                medidas.append((tamanho_dir(e.path), e.name + "/", True))
            else:
                medidas.append((e.stat(follow_symlinks=False).st_size, e.name, False))
        except OSError:
            pass
    medidas.sort(key=lambda m: -m[0])
    linhas = []
    for tam, nome, eh_d in medidas:
        cor = "info" if eh_d else "secondary"
        linhas.append(f"<secondary>{formatar_tamanho(tam):>10}</secondary>  <{cor}>{esc(nome)}</{cor}>")
    total = sum(m[0] for m in medidas)
    linhas.append("<secondary>" + "─" * 30 + "</secondary>")
    linhas.append(f"<arg>{formatar_tamanho(total):>10}</arg>  <secondary>total</secondary>")
    imprimir("\n".join(linhas))
    return 0


@comando("df", "", "Mostra o uso de disco do diretório atual", "Arquivos")
def cmd_df(args):
    u = shutil.disk_usage(os.getcwd())
    pct = u.used / u.total * 100
    cheio = int(pct / 5)
    barra = "█" * cheio + "░" * (20 - cheio)
    cor = "success" if pct < 75 else "arg" if pct < 90 else "error"
    imprimir(
        f"<{cor}>{barra}</{cor}> <secondary>{pct:.0f}%</secondary>\n"
        f"<secondary>total </secondary>{formatar_tamanho(u.total)}  "
        f"<secondary>usado </secondary>{formatar_tamanho(u.used)}  "
        f"<secondary>livre </secondary>{formatar_tamanho(u.free)}"
    )
    return 0


# ── Texto ────────────────────────────────────────────────────────────────────

@comando("cat", "[-n] arquivo...", "Mostra o conteúdo de arquivos (-n numera as linhas)", "Texto")
def cmd_cat(args):
    flags, pos = parse(args, "n")
    if not pos:
        return uso("cat", "[-n] arquivo...")

    def mostrar(f):
        ultimo = "\n"
        for n, linha in enumerate(f, 1):
            escrever((f"{n:>6}  " if "n" in flags else "") + linha)
            ultimo = linha
        if not ultimo.endswith("\n"):
            escrever("\n")

    return por_arquivo(pos, mostrar)


def _num_linhas(flags):
    try:
        return int(flags.get("n", 10))
    except ValueError:
        raise ErroArgs("número de linhas inválido") from None


@comando("head", "[-n N] arquivo...", "Mostra as primeiras linhas (padrão: 10)", "Texto")
def cmd_head(args):
    flags, pos = parse(args, "", "n")
    if not pos:
        return uso("head", "[-n N] arquivo...")
    n = _num_linhas(flags)

    def mostrar(f):
        ultimo = "\n"
        for linha in islice(f, n):
            escrever(linha)
            ultimo = linha
        if not ultimo.endswith("\n"):
            escrever("\n")

    return por_arquivo(pos, mostrar)


@comando("tail", "[-n N] [-f] arquivo...", "Mostra as últimas linhas (-f acompanha · Ctrl+C sai)", "Texto")
def cmd_tail(args):
    import time
    flags, pos = parse(args, "f", "n")
    if not pos:
        return uso("tail", "[-n N] [-f] arquivo...")
    n = _num_linhas(flags)

    def mostrar(f):
        ultimo = "\n"
        for linha in deque(f, maxlen=n) if n > 0 else ():
            escrever(linha)
            ultimo = linha
        if not ultimo.endswith("\n"):
            escrever("\n")
        if "f" in flags and len(pos) == 1:

            sys.stdout.flush()
            while True:
                linha = f.readline()
                if linha:
                    escrever(linha)
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)

    return por_arquivo(pos, mostrar)


@comando("wc", "[-l] [-w] [-c] arquivo...", "Conta linhas, palavras e bytes", "Texto")
def cmd_wc(args):
    flags, pos = parse(args, "lwc")
    if not pos:
        return uso("wc", "[-l] [-w] [-c] arquivo...")
    mostrar = [k for k in "lwc" if k in flags] or list("lwc")
    totais = [0, 0, 0]
    status = 0
    linhas = []
    for a in pos:
        p = Path(a).expanduser()
        if not p.is_file():
            status |= erro(f"Não encontrado: {fmt(p)}")
            continue
        try:
            l = w = b = 0
            with open(p, "rb") as f:
                for linha in f:
                    l += linha.endswith(b"\n")
                    w += len(linha.split())
                    b += len(linha)
        except OSError as e:
            status |= erro(esc(str(e)))
            continue
        for i, v in enumerate((l, w, b)):
            totais[i] += v
        linhas.append(((l, w, b), str(p)))
    if len(linhas) > 1:
        linhas.append((tuple(totais), "total"))
    idx = {"l": 0, "w": 1, "c": 2}
    for valores, nome in linhas:
        escrever("".join(f"{valores[idx[k]]:>8}" for k in mostrar) + f" {nome}\n")
    return status


@comando("grep", "[-i] [-n] [-r] [-v] [-c] [-l] padrão [arquivos]", "Busca texto (regex) em arquivos",
         "Texto", glob_=False)
def cmd_grep(args):
    flags, pos = parse(args, "inrvcl")
    if not pos:
        return uso("grep", "[-i] [-n] [-r] [-v] [-c] [-l] padrão [arquivos]")
    try:
        rx = re.compile(pos[0], re.IGNORECASE if "i" in flags else 0)
    except re.error as e:
        return erro(f"Expressão regular inválida: <secondary>{esc(str(e))}</secondary>")

    alvos = expandir(pos[1:])
    if not alvos:
        if "r" not in flags:
            return erro("Informe ao menos um arquivo (ou use -r).")
        alvos = ["."]

    arquivos, status = [], 1   # 1 = nenhuma ocorrência (como o grep real)
    for a in alvos:
        p = Path(a)
        if p.is_dir():
            if "r" in flags:
                arquivos.extend(percorrer_arquivos(p))
            else:
                imprimir(f"<secondary>{esc(a)}: é um diretório (use -r)</secondary>")
        elif p.exists():
            arquivos.append(p)
        else:
            erro(f"Não encontrado: {fmt(p)}")
            status = 2

    mostrar_nome = len(arquivos) > 1 or "r" in flags
    inverter = "v" in flags
    for p in arquivos:
        frags, achou = [], 0
        try:
            with open(p, "rb") as fb:
                if b"\0" in fb.read(4096):
                    continue
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for n, linha in enumerate(f, 1):
                    linha = linha.rstrip("\n")
                    if bool(rx.search(linha)) == inverter:
                        continue
                    achou += 1
                    if "l" in flags:
                        break
                    if "c" in flags:
                        continue
                    if mostrar_nome:
                        frags += [("class:info", str(p)), ("class:secondary", ":")]
                    if "n" in flags:
                        frags += [("class:arg", str(n)), ("class:secondary", ":")]
                    if inverter:
                        frags.append(("", linha))
                    else:
                        pos_ = 0
                        for m in rx.finditer(linha):
                            if m.end() == m.start():
                                continue
                            frags += [("", linha[pos_:m.start()]), ("class:error bold", m.group())]
                            pos_ = m.end()
                        frags.append(("", linha[pos_:]))
                    frags.append(("", "\n"))
                    if len(frags) > 4000:
                        escrever_frags(frags)
                        frags = []
        except OSError:
            continue
        if achou:
            status = 0 if status != 2 else 2
        if "l" in flags and achou:
            frags = [("class:info", str(p)), ("", "\n")]
        elif "c" in flags:
            frags = ([("class:info", f"{p}"), ("class:secondary", ":")] if mostrar_nome else []) \
                + [("class:arg", str(achou)), ("", "\n")]
        if frags:
            escrever_frags(frags)
    return status


def escrever_frags(frags):
    # Remove a quebra final: print_formatted_text já adiciona uma
    if frags and frags[-1] == ("", "\n"):
        frags = frags[:-1]
    imprimir_ft(frags)


@comando("find", "[pasta] padrão [-t f|d]", "Procura arquivos pelo nome (aceita * e ?)", "Texto", glob_=False)
def cmd_find(args):
    flags, pos = parse(args, "", "t")
    if not pos or len(pos) > 2:
        return uso("find", "[pasta] padrão [-t f|d]")
    tipo = flags.get("t")
    if tipo not in (None, "f", "d"):
        return erro("O tipo (-t) deve ser <command>f</command> ou <command>d</command>.")
    raiz, padrao = (".", pos[0]) if len(pos) == 1 else (pos[0], pos[1])
    raiz = os.path.expanduser(raiz)
    if not os.path.isdir(raiz):
        return erro(f"Isso não é um diretório: {fmt(raiz)}")
    padrao = padrao.lower()
    achados, limite = 0, 1000
    for base, dirs, nomes in os.walk(raiz, onerror=lambda e: None):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        candidatos = []
        if tipo != "f":
            candidatos += [(d, True) for d in dirs]
        if tipo != "d":
            candidatos += [(n, False) for n in sorted(nomes)]
        for nome, eh_d in candidatos:
            if fnmatch.fnmatchcase(nome.lower(), padrao):
                achados += 1
                caminho = os.path.join(base, nome)
                imprimir_ft([("class:info" if eh_d else "", caminho + ("/" if eh_d else ""))])
                if achados >= limite:
                    imprimir(f"<secondary>… (limite de {limite} resultados)</secondary>")
                    return 0
    if not achados:
        imprimir("<secondary>Nada encontrado.</secondary>")
        return 1
    imprimir(f"<secondary>{achados} resultado(s)</secondary>")
    return 0


@comando("echo", "texto...", "Imprime um texto", "Texto")
def cmd_echo(args):
    escrever(" ".join(args) + "\n")
    return 0


# ── Sistema ──────────────────────────────────────────────────────────────────

@comando("which", "comando...", "Mostra onde está um comando", "Sistema")
def cmd_which(args):
    if not args:
        return uso("which", "comando")
    status = 0
    for nome in args:
        if nome in ALIASES:
            imprimir(f"<command>{esc(nome)}</command><secondary>: alias para</secondary> <arg>'{esc(ALIASES[nome])}'</arg>")
        elif nome.lower() in COMANDOS:
            imprimir(f"<command>{esc(nome)}</command><secondary>: comando interno do JShell</secondary>")
        else:
            caminho = shutil.which(nome)
            if caminho:
                imprimir(f"<command>{esc(nome)}</command><secondary>:</secondary> {fmt(caminho)}")
            else:
                status |= erro(f"Não encontrado: <command>{esc(nome)}</command>")
    return status


@comando("env", "", "Lista as variáveis de ambiente", "Sistema")
def cmd_env(args):
    for k in sorted(os.environ):
        imprimir_ft([("class:arg", k), ("class:secondary", "="), ("", os.environ[k])])
    return 0


@comando("export", "VAR=valor...", "Define variáveis de ambiente (sem argumentos: lista)", "Sistema", glob_=False)
def cmd_export(args):
    if not args:
        return cmd_env([])
    status = 0
    for a in args:
        if "=" not in a or a.startswith("="):
            status |= erro("Use o formato <arg>VAR=valor</arg>.")
            continue
        k, v = a.split("=", 1)
        os.environ[k] = v
    return status


@comando("unset", "VAR...", "Remove variáveis de ambiente", "Sistema")
def cmd_unset(args):
    if not args:
        return uso("unset", "VAR")
    for k in args:
        os.environ.pop(k, None)
    return 0


@comando("alias", "[nome=comando]", "Cria ou lista atalhos (ex.: alias gs='git status')", "Sistema", glob_=False)
def cmd_alias(args):
    if not args:
        for k in sorted(ALIASES):
            imprimir(f"<command>{esc(k)}</command><secondary>=</secondary><arg>'{esc(ALIASES[k])}'</arg>")
        return 0
    status = 0
    for a in args:
        if "=" not in a:
            if a in ALIASES:
                imprimir(f"<command>{esc(a)}</command><secondary>=</secondary><arg>'{esc(ALIASES[a])}'</arg>")
            else:
                status |= erro(f"Alias não encontrado: <command>{esc(a)}</command>")
            continue
        k, v = a.split("=", 1)
        if not k or any(c.isspace() for c in k):
            status |= erro("Nome de alias inválido.")
        elif k.lower() in COMANDOS:
            status |= erro(f"<command>{esc(k)}</command> é um comando interno e não pode virar alias.")
        elif not v.strip():
            status |= erro("O alias precisa de um comando.")
        else:
            ALIASES[k] = v
    return status


@comando("unalias", "nome...", "Remove um alias", "Sistema")
def cmd_unalias(args):
    if not args:
        return uso("unalias", "nome")
    status = 0
    for k in args:
        if ALIASES.pop(k, None) is None:
            status |= erro(f"Alias não encontrado: <command>{esc(k)}</command>")
    return status


@comando("history", "[n]", "Mostra os últimos comandos digitados (padrão: 25)", "Sistema")
def cmd_history(args):
    try:
        n = int(args[0]) if args else 25
    except ValueError:
        return erro("Informe um número.")
    historico = SESSAO.history.get_strings() if SESSAO else []
    inicio = max(0, len(historico) - n)
    for i, h in enumerate(historico[inicio:], inicio + 1):
        imprimir_ft([("class:secondary", f"{i:>5}  "), ("", h.replace("\n", " "))])
    return 0


@comando("date", "", "Mostra a data e a hora", "Sistema")
def cmd_date(args):
    imprimir(f"<info>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</info>")
    return 0


@comando("whoami", "", "Mostra o usuário atual", "Sistema")
def cmd_whoami(args):
    imprimir(f"<info>{esc(getpass.getuser())}</info>")
    return 0


@comando("open", "[caminho]", "Abre um arquivo/pasta com o programa padrão do sistema", "Sistema")
def cmd_open(args):
    alvo = args[0] if args else "."
    try:
        if IS_WIN:
            os.startfile(alvo)
        else:
            abridor = "open" if sys.platform == "darwin" else "xdg-open"
            if not shutil.which(abridor):
                return erro(f"<command>{abridor}</command> não encontrado.")
            subprocess.Popen([abridor, alvo], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return erro(esc(str(e)))
    return 0


@comando("git", "operacao", "Executa o git (ex.: git status)", "Sistema", glob_=False)
def cmd_git(args):
    if not args:
        imprimir("<info>Uso:</info> <command>git</command> <arg>operacao</arg>")
        return 1
    status = externo(["git", *args])
    if status is None:
        return erro("<command>git</command> não encontrado no sistema.")
    return status


# ── JShell ───────────────────────────────────────────────────────────────────

@comando("jcode", "arquivo", "Abre um arquivo no JCode", "JShell")
def cmd_jcode(args):
    aqui = "--aqui" in args
    args = [a for a in args if a != "--aqui"]
    if not args:
        imprimir("<info>Uso:</info> <command>jcode</command> [--aqui] <arg>arquivo</arg>")
        return 1

    if args[0].lower() == "new":
        if len(args) < 2:
            imprimir("<info>Uso:</info> <command>jcode new</command> <arg>arquivo</arg>")
            return 1

        caminho = Path(args[1]).expanduser()

        if not caminho.is_absolute():
            caminho = Path.cwd() / caminho

        if caminho.exists():
            return erro(f"Arquivo já existe: {fmt(caminho)}")

        return abrir_jcode(args[1], criar=True, aqui=aqui)

    return abrir_jcode(args[0], aqui=aqui)


# Entrada separada só para aparecer no help (o comando é o mesmo)
AJUDA.append(("JShell", "jcode new", "arquivo", "Cria um arquivo novo no JCode"))


@comando("jfiles", "", "Abre o JFiles", "JShell")
def cmd_jfiles(args):
    return abrir_jfiles()


@comando("clear", "", "Limpa a tela", "JShell", aliases=("cls",))
def cmd_clear(args):
    limpar_tela()
    return 0


@comando("help", "[comando]", "Mostra esta ajuda", "JShell")
def cmd_help(args):
    if args:
        nome = args[0].lower()
        achados = [a for a in AJUDA if a[1] == nome]
        if not achados:
            return erro(f"Sem ajuda para <command>{esc(nome)}</command>.")
        for _, n, u, d in achados:
            imprimir(f"<command>{esc(n)}</command> <arg>{esc(u)}</arg>\n<secondary>{esc(d)}</secondary>")
        return 0

    largura = max(len(n) + 1 + len(u) for _, n, u, _ in AJUDA)
    linhas, grupo_atual = [], None
    for grupo, n, u, d in AJUDA:
        if grupo != grupo_atual:
            linhas.append(f"{'' if grupo_atual is None else chr(10)}<secondary>{grupo}:</secondary>")
            grupo_atual = grupo
        pad = " " * (largura - len(n) - 1 - len(u) + 2)
        linhas.append(f"  <command>{esc(n)}</command> <arg>{esc(u)}</arg>{pad}<secondary>{esc(d)}</secondary>")
    linhas.append("")
    linhas.append("<secondary>Dicas:</secondary>")
    linhas.append("  <secondary>• Encadeie com</secondary> <arg>&amp;&amp;</arg> <arg>||</arg> <arg>;</arg>"
                  "<secondary> · curingas</secondary> <arg>*</arg> <arg>?</arg>"
                  "<secondary> · variáveis</secondary> <arg>$HOME</arg>")
    linhas.append("  <secondary>• Pipes simples (|) e redirecionamentos (&lt;, &gt;, &gt;&gt;) entre programas externos"
                  " rodam sem iniciar um shell; sintaxe avançada usa o shell POSIX do sistema.</secondary>")
    linhas.append("  <secondary>• Tab completa comandos e caminhos · ↑/↓ navegam no histórico · Ctrl+D sai.</secondary>")
    imprimir("\n".join(linhas))
    return 0


@comando("exit", "", "Sai do JShell", "JShell", aliases=("quit", "sair"))
def cmd_exit(args):
    raise SairShell()


# ══════════════════════════════════════════════════════════════════════════════
#  Execução
# ══════════════════════════════════════════════════════════════════════════════

SEPARADORES = {"&&", "||", ";"}
PONTUACAO = set("();<>|&")


def tokenizar(linha):
    lex = shlex.shlex(linha, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def eh_operador(token):
    return bool(token) and all(c in PONTUACAO for c in token)


def externo(argv):
    """Executa um programa do sistema. Retorna None se não existir."""
    exe = shutil.which(argv[0])
    if not exe:
        return None
    sys.stdout.flush()
    try:
        codigo = subprocess.run([exe, *argv[1:]]).returncode
    except PermissionError:
        return erro(f"Sem permissão para executar: <command>{esc(argv[0])}</command>")
    except OSError as e:
        return erro(esc(str(e)))
    if codigo != 0:
        imprimir(f"<secondary>[código {codigo}]</secondary>")
    return codigo


def shell_externo(linha):
    """Compatibilidade POSIX para sintaxe avançada ainda não implementada no JShell."""
    primeira = linha.split(None, 1)
    if primeira and primeira[0] in ALIASES:
        linha = ALIASES[primeira[0]] + (" " + primeira[1] if len(primeira) > 1 else "")
    sys.stdout.flush()
    codigo = subprocess.run(linha, shell=True).returncode
    if codigo != 0:
        imprimir(f"<secondary>[código {codigo}]</secondary>")
    return codigo


def executar_pipeline_nativo(tokens):
    """Executa pipelines/redirecionamentos simples sem iniciar /bin/sh.

    Suporta comandos externos encadeados por | e redirecionamentos <, > e >>.
    Retorna None quando a linha precisa do fallback POSIX (sintaxe avançada ou
    comando interno do JShell), permitindo compatibilidade sem fingir ser Bash.
    """
    if not any(t in {"|", ">", ">>", "<"} for t in tokens):
        return None

    grupos, atual = [], []
    for token in tokens:
        if token == "|":
            if not atual:
                return None
            grupos.append(atual)
            atual = []
        elif token in {">", ">>", "<"} or token in {";", "&&", "||"}:
            # Separadores de fluxo já são tratados em executar_linha; redirecionamentos
            # são mantidos no grupo para serem processados abaixo.
            atual.append(token)
        elif eh_operador(token) and token not in {">", ">>", "<"}:
            return None
        else:
            atual.append(token)
    if not atual:
        return None
    grupos.append(atual)

    comandos, redirs = [], []
    tem_pipe = len(grupos) > 1
    for grupo in grupos:
        argv, redirects, i = [], [], 0
        while i < len(grupo):
            token = grupo[i]
            if token in {">", ">>", "<"}:
                if i + 1 >= len(grupo) or eh_operador(grupo[i + 1]):
                    return None
                # shlex separa alguns descritores (ex.: 2>arquivo) em tokens.
                # Deixa esses casos para o shell compatível em vez de interpretá-los errado.
                if token in {">", ">>"} and argv and argv[-1] in {"1", "2"}:
                    return None
                redirects.append((token, os.path.expandvars(os.path.expanduser(grupo[i + 1]))))
                i += 2
                continue
            if eh_operador(token):
                return None
            argv.append(token)
            i += 1
        if not argv:
            return None
        # Alias vai pelo executor normal. Em pipes, usa-se o utilitário do sistema
        # (ex.: ls | grep); redirecionar a saída de um comando interno continua no fallback.
        if argv[0] in ALIASES or (argv[0].lower() in COMANDOS and not tem_pipe):
            return None
        exe = shutil.which(os.path.expanduser(os.path.expandvars(argv[0])))
        if not exe:
            return None
        argv[0] = exe
        argv = [argv[0], *expandir(argv[1:])]
        comandos.append(argv)
        redirs.append(redirects)

    # `comando > arquivo | próximo` precisa semântica de descritor específica; delega
    # esse caso raro em vez de conectar o processo seguinte ao stdin errado.
    for redirects in redirs[:-1]:
        if any(op in {">", ">>"} for op, _ in redirects):
            return None

    processos = []
    abertos = []
    anterior = None
    try:
        for indice, (argv, redirects) in enumerate(zip(comandos, redirs, strict=True)):
            entrada = anterior
            saida = subprocess.PIPE if indice < len(comandos) - 1 else None
            # Redirecionamentos explícitos prevalecem sobre stdin/stdout do pipeline,
            # como nos shells tradicionais.
            for operador, caminho in redirects:
                if operador == "<":
                    if entrada is not None and entrada is not subprocess.DEVNULL:
                        try:
                            entrada.close()
                        except Exception:
                            pass
                    f = open(caminho, "rb")
                    abertos.append(f)
                    entrada = f
                elif operador == ">":
                    f = open(caminho, "wb")
                    abertos.append(f)
                    saida = f
                elif operador == ">>":
                    f = open(caminho, "ab")
                    abertos.append(f)
                    saida = f
            proc = subprocess.Popen(argv, stdin=entrada, stdout=saida)
            processos.append(proc)
            if anterior is not None:
                try:
                    anterior.close()
                except Exception:
                    pass
            anterior = proc.stdout if indice < len(comandos) - 1 else None
        codigos = [p.wait() for p in processos]
        codigo = codigos[-1] if codigos else 0
    except (OSError, ValueError) as exc:
        for proc in processos:
            if proc.poll() is None:
                proc.terminate()
        for proc in processos:
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        return erro(f"Falha no pipeline: {esc(str(exc))}")
    finally:
        for f in abertos:
            try:
                f.close()
            except OSError:
                pass
    if codigo != 0:
        imprimir(f"<secondary>[código {codigo}]</secondary>")
    return codigo


def executar_tokens(tokens):
    # Expansão de aliases (com proteção contra recursão)
    vistos = set()
    while tokens[0] in ALIASES and tokens[0] not in vistos:
        vistos.add(tokens[0])
        try:
            novo = shlex.split(ALIASES[tokens[0]])
        except ValueError:
            break
        if not novo:
            break
        tokens = novo + tokens[1:]

    nome = tokens[0]
    chave = nome.lower()
    entrada = COMANDOS.get(chave)

    try:
        if entrada:
            fn, glob_ = entrada
            return fn(expandir(tokens[1:], glob_)) or 0
        argv = [nome, *expandir(tokens[1:])]
        codigo = externo(argv)
        if codigo is not None:
            return codigo
    except SairShell:
        raise
    except ErroArgs as e:
        return erro(esc(str(e)))
    except Exception as e:
        return erro(f"Falha inesperada em <command>{esc(chave)}</command>: "
                    f"<secondary>{esc(repr(e))}</secondary>")

    imprimir(f"<error>Comando desconhecido:</error> <command>{esc(chave)}</command>")
    sugestao = difflib.get_close_matches(chave, list(COMANDOS) + list(ALIASES), n=1)
    if sugestao:
        imprimir(f"<secondary>Você quis dizer</secondary> <command>{esc(sugestao[0])}</command><secondary>?</secondary>")
    return 127


def _executar_linha_classica(linha):
    """Modo sem motor bash (comportamento antigo). Retorna o código de saída."""
    global STATUS
    linha = linha.strip()
    if not linha or linha.startswith("#"):
        return STATUS

    try:
        tokens = tokenizar(linha)
    except ValueError as erro_:
        imprimir(f"<error>Comando inválido:</error> <secondary>{esc(str(erro_))}</secondary>")
        STATUS = 1
        return STATUS

    if not tokens:
        return STATUS

    # Pipes/redirecionamentos comuns são executados diretamente com subprocess.
    # Sintaxe mais avançada continua compatível via o shell POSIX do sistema.
    if any(eh_operador(t) and t not in SEPARADORES for t in tokens):
        STATUS = executar_pipeline_nativo(tokens)
        if STATUS is None:
            STATUS = shell_externo(linha)
        return STATUS

    segmentos, atual = [], []
    for t in tokens:
        if t in SEPARADORES:
            segmentos.append((atual, t))
            atual = []
        else:
            atual.append(t)
    segmentos.append((atual, ";"))

    status, anterior = STATUS, ";"
    for seg, depois in segmentos:
        rodar = anterior == ";" or (anterior == "&&" and status == 0) or (anterior == "||" and status != 0)
        if seg and rodar:
            status = executar_tokens(seg)
            sys.stdout.flush()
        anterior = depois

    STATUS = status
    return STATUS


# ── motor bash ───────────────────────────────────────────────────────────────
MOTOR = None  # jbash.Motor quando o bash está disponível

# Comandos do JShell que ficam NA FRENTE do bash (visual próprio). Para tudo o resto, vale o
# bash de verdade. Um alias/função do usuário com o mesmo nome vence; `\\ls` ou `command ls`
# forçam o do sistema; `jls` é sempre o bonito.
NATIVOS_BONITOS = {"ls", "jls", "tree", "du", "df", "help", "clear", "cls", "exit", "quit", "sair",
                   "history", "jcode", "jfiles", "open", "rank", "hud"}
RE_META = re.compile(r"[|&;<>(){}$`\\!#\n]")
RESERVADAS = {"if", "for", "while", "until", "case", "select", "function", "{", "[[", "time", "coproc", "!"}
RE_PLANA = re.compile(r"[\w@%+=:,./~ -]+")


def eh_simples(linha):
    """Uma linha sem sintaxe de shell: um comando e seus argumentos."""
    return not RE_META.search(linha)


_SIG_PATH = {"t": 0.0, "v": ()}
_PATH_CACHE = {"sig": None, "nomes": []}
_WHICH = {}


def _assinatura_path():
    """(dir, mtime) de cada pasta do PATH, relido no máximo 1x por segundo."""
    agora = time.monotonic()
    if agora - _SIG_PATH["t"] < 1.0:
        return _SIG_PATH["v"]
    partes = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        try:
            partes.append((d, os.stat(d).st_mtime_ns))
        except OSError:
            pass
    _SIG_PATH.update(t=agora, v=tuple(partes))
    return _SIG_PATH["v"]


def executaveis_path():
    """Nomes executáveis do PATH (cache invalidado quando uma pasta do PATH muda)."""
    sig = _assinatura_path()
    if _PATH_CACHE["sig"] != sig:
        nomes = set()
        for d, _ in sig:
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if os.access(e.path, os.X_OK) and not e.is_dir():
                                nomes.add(e.name)
                        except OSError:
                            pass
            except OSError:
                pass
        _PATH_CACHE.update(sig=sig, nomes=sorted(nomes))
    return _PATH_CACHE["nomes"]


def comando_existe(nome):
    """`nome` é algo que o shell consegue executar? (interno, alias, função, builtin ou PATH)"""
    if nome in COMANDOS or nome in ALIASES or nome in RESERVADAS:
        return True
    if MOTOR is not None and (MOTOR.conhece(nome) or nome in MOTOR.nativos):
        return True
    if "/" in nome:
        caminho = os.path.expanduser(nome)
        return os.path.isfile(caminho) and os.access(caminho, os.X_OK)
    chave = (nome, _assinatura_path())
    achou = _WHICH.get(chave)
    if achou is None:
        if len(_WHICH) > 3000:
            _WHICH.clear()
        achou = _WHICH[chave] = shutil.which(nome) is not None
    return achou


def _tentar_nativo(linha):
    """Roda `linha` pelo comando bonito do JShell, se for o caso. None = deixa para o bash."""
    if "\n" in linha or not eh_simples(linha):
        return None
    try:
        tokens = tokenizar(linha)
    except ValueError:
        return None
    if not tokens:
        return None
    # aliases embutidos do JShell (ll, ..) só valem se o bash não tiver os seus
    vistos = set()
    while tokens[0] in ALIASES and tokens[0] not in vistos and not MOTOR.conhece(tokens[0]):
        vistos.add(tokens[0])
        try:
            novo = shlex.split(ALIASES[tokens[0]])
        except ValueError:
            return None
        if not novo:
            return None
        tokens = novo + tokens[1:]
    nome = tokens[0]
    if nome not in NATIVOS_BONITOS or nome not in COMANDOS or MOTOR.conhece(nome):
        return None
    fn, glob_ = COMANDOS[nome]
    try:
        return fn(expandir(tokens[1:], glob_)) or 0
    except SairShell:
        raise
    except ErroArgs:
        return None   # opção que o JShell não conhece (ls -a, ls -h...): o do sistema resolve
    except Exception as e:
        return erro(f"Falha inesperada em <command>{esc(nome)}</command>: <secondary>{esc(repr(e))}</secondary>")


def _desconhecido(linha):
    """Comando inexistente: mensagem no estilo do JShell (+ sugestão) em vez do erro seco do bash."""
    if "\n" in linha or not eh_simples(linha):
        return None
    try:
        tokens = tokenizar(linha)
    except ValueError:
        return None
    if not tokens:
        return None
    nome = tokens[0]
    if re.match(r"\w+=", nome) or any(c in nome for c in "$~`'\"*?[{"):
        return None
    if comando_existe(nome):
        return None
    imprimir(f"<error>Comando desconhecido:</error> <command>{esc(nome)}</command>")
    proprios = set(COMANDOS) | set(ALIASES) | set(MOTOR.aliases) | set(MOTOR.funcoes) | MOTOR.nativos
    sugestao = (difflib.get_close_matches(nome, sorted(proprios), n=1)
                or difflib.get_close_matches(nome, executaveis_path(), n=1))
    if sugestao:
        imprimir(f"<secondary>Você quis dizer</secondary> <command>{esc(sugestao[0])}</command><secondary>?</secondary>")
    return 127


def executar_linha(linha):
    """Executa uma linha. Com o motor: bash de verdade, com os comandos bonitos do JShell na frente."""
    global STATUS
    if MOTOR is None:
        return _executar_linha_classica(linha)
    if not linha.strip() or linha.lstrip().startswith("#"):
        return STATUS
    st = _tentar_nativo(linha)
    if st is None:
        st = _desconhecido(linha)
    if st is None:
        st = MOTOR.executar(linha)
        if st is None:  # motor indisponível: volta ao modo clássico
            return _executar_linha_classica(linha)
    STATUS = st
    return STATUS


def executar_comando(comando_):
    """Compatibilidade: retorna False quando o shell deve encerrar."""
    try:
        executar_linha(comando_)
    except SairShell:
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  HUD: combo, vida e rank (osu!) no prompt
# ══════════════════════════════════════════════════════════════════════════════
# Cada comando é uma "nota": exit 0 acerta (combo +1, vida sobe); exit 1 é um "100"
# (grep sem resultado, diff...: não quebra o combo); exit >= 2 é um miss (combo zera, vida cai).
# Ctrl+C (130) não conta. Sem vida, "respawn" (a vida volta a 100). Desligue: `hud off`.
HUD = {"hp": 100, "combo": 0, "max": 0, "ok": 0, "cem": 0, "miss": 0, "total": 0,
       "dur": 0.0, "t0": time.time()}
META = {"rank", "hud", "help", "clear", "cls", "history", "exit", "quit", "sair"}


def hud_ligado():
    return os.environ.get("JSHELL_HUD", "1") != "0"


def hud_registrar(linha, status, dur):
    h = HUD
    h["dur"] = dur
    primeira = linha.split(None, 1)[0] if linha.split() else ""
    if primeira in META or status == 130:
        return
    h["total"] += 1
    if status == 0:
        h["ok"] += 1
        h["combo"] += 1
        h["max"] = max(h["max"], h["combo"])
        h["hp"] = min(100, h["hp"] + 2)
        if h["combo"] and h["combo"] % 50 == 0 and hud_ligado():
            imprimir_ft([("class:hp.full", f"» {h['combo']}x combo")])
    elif status == 1:
        h["cem"] += 1
        h["hp"] = max(1, h["hp"] - 3)
    else:
        h["miss"] += 1
        h["combo"] = 0
        h["hp"] = max(0, h["hp"] - 12)
        if h["hp"] == 0 and hud_ligado():
            imprimir_ft([("class:hp.low", "// sem vida · respawn")])
            h["hp"] = 100


def hud_precisao():
    t = HUD["total"]
    return 100.0 if not t else 100.0 * (HUD["ok"] + HUD["cem"] / 3) / t


def hud_rank():
    t, acc = HUD["total"], hud_precisao()
    if t < 5:
        return "--", "secondary"
    if acc >= 100 and HUD["miss"] == 0 and HUD["cem"] == 0:
        return "SS", "hp.mid"
    for corte, letra, cor in ((90, "S", "hp.mid"), (80, "A", "hp.full"), (70, "B", "info"),
                              (60, "C", "op"), (0, "D", "hp.low")):
        if acc > corte or (corte == 0):
            return letra, cor
    return "D", "hp.low"


def fmt_dur(seg):
    if seg < 1:
        return f"{seg * 1000:.0f}ms"
    if seg < 60:
        return f"{seg:.1f}s"
    m, s_ = divmod(int(seg), 60)
    return f"{m}m{s_:02d}s" if m < 60 else f"{m // 60}h{m % 60:02d}m"


def hud_resumo():
    letra, cor = hud_rank()
    h = HUD
    imprimir_ft([
        ("class:secondary", "─── rank "), (f"class:{cor}", letra), ("class:secondary", " ───  "),
        ("class:info", f"{h['total']} comandos"), ("class:secondary", " · precisão "),
        ("class:info", f"{hud_precisao():.1f}%"), ("class:secondary", " · combo máx "),
        ("class:info", str(h["max"])), ("class:secondary", " · "),
        ("class:success", f"{h['ok']} ok"), ("class:secondary", " "),
        ("class:arg", f"{h['cem']} meh"), ("class:secondary", " "),
        ("class:error", f"{h['miss']} miss"), ("class:secondary", " · "),
        ("class:secondary", fmt_dur(time.time() - h["t0"])),
    ])


@comando("rank", "", "Mostra seu desempenho na sessão (combo, precisão, rank estilo osu!)", "JShell")
def cmd_rank(args):
    hud_resumo()
    return 0


@comando("hud", "[on|off]", "Liga/desliga o combo e a barra de vida no prompt", "JShell")
def cmd_hud(args):
    if args and args[0] in ("on", "off"):
        valor = "1" if args[0] == "on" else "0"
        if MOTOR is not None:
            MOTOR.executar(f"export JSHELL_HUD={valor}")
        else:
            os.environ["JSHELL_HUD"] = valor
        return ok(f"HUD {'ligado' if valor == '1' else 'desligado'}")
    imprimir(f"<secondary>HUD:</secondary> <info>{'ligado' if hud_ligado() else 'desligado'}</info> "
             f"<secondary>· use</secondary> <command>hud</command> <arg>on|off</arg> "
             f"<secondary>(ou</secondary> <arg>export JSHELL_HUD=0</arg> <secondary>no ~/.jshellrc)</secondary>")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Prompt
# ══════════════════════════════════════════════════════════════════════════════

def ramo_git():
    """Lê o ramo atual direto de .git/HEAD (sem chamar o git)."""
    try:
        atual = Path.cwd()
        for d in (atual, *atual.parents):
            g = d / ".git"
            if g.is_dir():
                head = (g / "HEAD").read_text().strip()
                return head[16:] if head.startswith("ref: refs/heads/") else head[:7]
            if g.exists():
                return None
    except OSError:
        pass
    return None


# "sujo?" vem de `git status` numa thread: o prompt nunca espera por ele.
_GIT = {"chave": None, "sujo": False, "t": 0.0, "rodando": False}


def _git_worker(chave, app):
    try:
        r = subprocess.run(["git", "status", "--porcelain", "-uno"], cwd=chave[0],
                           capture_output=True, text=True, timeout=1.5)
        sujo = r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        sujo = False
    mudou = _GIT["chave"] == chave and _GIT["sujo"] != sujo
    if _GIT["chave"] == chave:
        _GIT["sujo"] = sujo
    _GIT["rodando"] = False
    if mudou and app is not None:
        try:
            app.invalidate()
        except Exception:
            pass


def git_sujo(ramo):
    try:
        chave = (os.getcwd(), ramo)
    except OSError:
        return False
    agora = time.monotonic()
    if chave != _GIT["chave"]:
        _GIT.update(chave=chave, sujo=False, t=0.0)
    if agora - _GIT["t"] > 5 and not _GIT["rodando"]:
        _GIT.update(t=agora, rodando=True)
        threading.Thread(target=_git_worker, args=(chave, get_app_or_none()), daemon=True).start()
    return _GIT["sujo"]


def garantir_cwd():
    try:
        os.getcwd()
    except OSError:
        os.chdir(Path.home())
        imprimir("<error>O diretório atual foi removido.</error> <secondary>Voltando para a home.</secondary>")
        if MOTOR is not None:
            MOTOR.executar(f"cd {shlex.quote(str(Path.home()))}")


def cwd_curto():
    cwd = str(Path.cwd())
    home = str(Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + os.sep):
        return "~" + cwd[len(home):]
    return cwd


def _nivel_hp(hp):
    return "full" if hp > 60 else "mid" if hp > 30 else "low"


def montar_prompt():
    """Uma linha, em "pílulas" (fundo colorido, sem setas): [combo] [pasta] [git] [exit]"""
    try:
        cwd = cwd_curto()
    except OSError:
        cwd = "?"
    frags = []
    if hud_ligado():
        frags += [(f"class:combo.{_nivel_hp(HUD['hp'])}", f" {HUD['combo']} "), ("", " ")]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        frags += [("class:pill.root", " root "), ("", " ")]
    frags.append(("class:pill.cwd", f" {cwd} "))
    ramo = ramo_git()
    if ramo:
        sujo = git_sujo(ramo)
        frags += [("", " "), ("class:pill.gitdirty" if sujo else "class:pill.git", f" {ramo}{'*' if sujo else ''} ")]
    if STATUS:
        frags += [("", " "), ("class:pill.err", f" {STATUS} ")]
    frags.append(("", " "))
    return FormattedText(frags)


def montar_rprompt():
    if not hud_ligado():
        return FormattedText([])
    hp = HUD["hp"]
    cheios = max(0, min(5, round(hp / 20)))
    frags = [(f"class:hp.{_nivel_hp(hp)}", "━" * cheios), ("class:hp.empty", "─" * (5 - cheios))]
    if HUD["dur"] >= 0.3:
        frags.append(("class:rprompt", f"  {fmt_dur(HUD['dur'])}"))
    frags.append(("class:rprompt", "  " + time.strftime("%H:%M")))
    return FormattedText(frags)


def montar_continuacao(*_):
    return FormattedText([("class:continuation", " > ")])


# ══════════════════════════════════════════════════════════════════════════════
#  Escaneamento da linha (usado pelo realce e pela completion)
# ══════════════════════════════════════════════════════════════════════════════
RE_OP = re.compile(r"\d*(?:&>>?|>>|>&|>\||<<<|<<-?|<&|<>|>|<)|&&|\|\||\|&|\||;;&|;;|;&|;|&|\(|\)")
FRONTEIRAS = {"|", "||", "|&", "&&", ";", ";;", "&", "(", "then", "do", "else", "elif", "if", "while",
              "until", "!", "{", "time", "coproc"}
ENVOLTORIOS = {"sudo", "doas", "nohup", "exec", "command", "builtin", "env", "xargs", "watch", "nice",
               "strace", "setsid", "time"}


def escanear(linha):
    """Tokens (ini, fim, tipo, texto, aspa_aberta). tipo: 'w' palavra · 'o' operador · 'c' comentário."""
    toks, i, n = [], 0, len(linha)
    while i < n:
        c = linha[i]
        if c.isspace():
            i += 1
            continue
        if c == "#" and (i == 0 or linha[i - 1].isspace()):
            toks.append((i, n, "c", linha[i:], None))
            break
        m = RE_OP.match(linha, i) if (c in "|&;()<>" or c.isdigit()) else None
        if m and m.end() > i:
            toks.append((i, m.end(), "o", m.group(), None))
            i = m.end()
            continue
        j, q = i, None
        while j < n:
            ch = linha[j]
            if q:
                if ch == q:
                    q = None
                elif ch == "\\" and q == '"' and j + 1 < n:
                    j += 1
            else:
                if ch in "'\"":
                    q = ch
                elif ch == "\\" and j + 1 < n:
                    j += 1
                elif ch.isspace() or ch in "|&;()<>":
                    break
            j += 1
        toks.append((i, j, "w", linha[i:j], q))
        i = j
    return toks


RE_VAR = re.compile(r"\$(?:\{[^}]*\}?|\w+|[?$!#@*-])")


def _estilo_palavra(p, comando):
    """Fragmentos (estilo, texto) de uma palavra."""
    if comando:
        m = re.match(r"(\w+)(=)(.*)$", p, re.S)
        if m:  # VAR=valor
            return [("class:var", m.group(1) + "="), ("", m.group(3))]
        if p in RESERVADAS or p in {"then", "do", "else", "elif", "fi", "done", "esac", "}", "in"}:
            return [("class:kw", p)]
        if any(c in p for c in "$`'\"*?[{~") and not p.startswith("~/") and p != "~":
            return [("", p)]
        return [("class:cmd.ok" if comando_existe(p) else "class:cmd.bad", p)]
    if p[:1] in "'\"":
        return [("class:str", p)]
    if p.startswith("-") and len(p) > 1:
        return [("class:flag", p)]
    if "$" in p:
        frags, pos = [], 0
        for m in RE_VAR.finditer(p):
            if m.start() > pos:
                frags.append(("", p[pos:m.start()]))
            frags.append(("class:var", m.group()))
            pos = m.end()
        if pos < len(p):
            frags.append(("", p[pos:]))
        return frags
    try:
        if len(p) < 300 and os.path.exists(os.path.expanduser(p.replace("\\", ""))):
            return [("class:path", p)]
    except OSError:
        pass
    return [("", p)]


def colorir(linha):
    """Fragmentos coloridos que reproduzem `linha` exatamente (só muda o estilo)."""
    frags, pos, comando = [], 0, True
    for ini, fim, tipo, texto, _ in escanear(linha):
        if ini > pos:
            frags.append(("", linha[pos:ini]))
        pos = fim
        if tipo == "c":
            frags.append(("class:comment", texto))
        elif tipo == "o":
            frags.append(("class:op", texto))
            if texto in FRONTEIRAS:
                comando = True
        else:
            frags.extend(_estilo_palavra(texto, comando))
            if comando:
                comando = texto in FRONTEIRAS or texto in ENVOLTORIOS or re.match(r"\w+=", texto) is not None
    if pos < len(linha):
        frags.append(("", linha[pos:]))
    return frags


class JLexer(Lexer):
    def lex_document(self, document):
        linhas = document.lines

        def get_line(i):
            try:
                return colorir(linhas[i])
            except Exception:
                return [("", linhas[i])]
        return get_line


# ══════════════════════════════════════════════════════════════════════════════
#  Completion (comandos, caminhos, variáveis e as completions programáveis do bash)
# ══════════════════════════════════════════════════════════════════════════════
RE_ESCAPAR = re.compile(r"""([\s\\"'`$&|;<>()*?\[\]{}!#])""")
SO_PASTAS = {"cd", "pushd", "rmdir"}


def escapar(nome):
    return RE_ESCAPAR.sub(r"\\\1", nome)


def desescapar(texto):
    return re.sub(r"\\(.)", r"\1", texto)


def completar_caminho(cru, so_pastas=False):
    """`cru` = palavra como digitada. Devolve [(texto_que_substitui_cru, nome_exibido, é_pasta)]."""
    aspa = cru[0] if cru[:1] in ("'", '"') else None
    corpo = cru[1:] if aspa else cru
    if corpo == "~":
        return [(("~/" if not aspa else aspa + "~/"), "~/", True)]
    dir_cru, barra, base_cru = corpo.rpartition("/")
    prefixo = dir_cru + barra
    base = base_cru if aspa else desescapar(base_cru)
    alvo = os.path.expandvars(os.path.expanduser(prefixo if aspa else desescapar(prefixo))) or "."
    try:
        with os.scandir(alvo) as it:
            entradas = [(e.name, _eh_pasta(e)) for e in it]
    except OSError:
        return []
    mostrar_ocultos = base.startswith(".")

    def filtrar(f):
        return [(n, d) for n, d in entradas
                if f(n) and (mostrar_ocultos or not n.startswith(".")) and (d or not so_pastas)]
    achados = filtrar(lambda n: n.startswith(base)) or filtrar(lambda n: n.lower().startswith(base.lower()))
    achados.sort(key=lambda x: (not x[1], x[0].lower()))
    saida = []
    for nome, eh_dir in achados[:500]:
        corpo_novo = prefixo + (nome if aspa else escapar(nome)) + ("/" if eh_dir else "")
        saida.append(((aspa or "") + corpo_novo, nome + ("/" if eh_dir else ""), eh_dir))
    return saida


def _eh_pasta(e):
    try:
        return e.is_dir()
    except OSError:
        return False


def palavras_do_comando(texto):
    """(tokens da palavra atual, cru, índice_palavra, palavras) para o comando em edição.
    `palavras` são as palavras do comando simples atual (como o COMP_WORDS do bash)."""
    toks = escanear(texto)
    termina_em_espaco = texto == "" or texto[-1].isspace()
    inicio = 0
    for k, (_, _, tipo, t, _) in enumerate(toks):
        if tipo == "o" and t in FRONTEIRAS:
            inicio = k + 1
        elif tipo == "w" and t in FRONTEIRAS and k < len(toks) - 1 or (tipo == "w" and t in FRONTEIRAS and termina_em_espaco):
            inicio = k + 1
    atuais = toks[inicio:]
    palavras = [t for _, _, tp, t, _ in atuais if tp == "w"]
    if termina_em_espaco or (atuais and atuais[-1][2] != "w"):
        cru = ""
        palavras.append("")
    else:
        cru = atuais[-1][3] if atuais else ""
    ult_op = atuais[-2][3] if (len(atuais) >= 2 and atuais[-2][2] == "o") else (atuais[-1][3] if atuais and atuais[-1][2] == "o" else "")
    if termina_em_espaco and atuais and atuais[-1][2] == "o":
        ult_op = atuais[-1][3]
    return cru, len(palavras) - 1, palavras, ult_op


def nomes_de_comando(prefixo):
    universo = set(COMANDOS) | set(ALIASES) | set(executaveis_path())
    if MOTOR is not None:
        universo |= MOTOR.aliases | MOTOR.funcoes | MOTOR.nativos
    universo |= {"cd", "export", "source", "alias", "unalias", "type", "exec", "eval"}
    achados = sorted(n for n in universo if n.startswith(prefixo))
    if not achados and prefixo:
        baixo = prefixo.lower()
        achados = sorted(n for n in universo if n.lower().startswith(baixo))
    return achados[:300]


def gerar_completions(texto):
    """Lógica pura da completion. Devolve (tamanho_da_palavra_substituída, [(texto, exibir, é_pasta)])."""
    cru, cword, palavras, ult_op = palavras_do_comando(texto)
    redirecionando = bool(ult_op) and re.fullmatch(r"\d*(?:>>?|<|&>>?|>\|)", ult_op) is not None
    # atribuições VAR=x no começo não contam como o comando
    pular = 0
    while pular < len(palavras) - 1 and re.match(r"\w+=", palavras[pular]):
        pular += 1
    posicao_comando = (cword == pular) and not redirecionando

    if cru.startswith("$") and not cru.startswith("${") and not cru.startswith("$("):
        nome = cru[1:]
        vars_ = sorted(k for k in os.environ if k.startswith(nome))
        return len(cru), [("$" + k, "$" + k, False) for k in vars_[:300]]

    if posicao_comando and "/" not in cru and not cru.startswith(("~", ".")):
        return len(cru), [(n + " ", n, False) for n in nomes_de_comando(cru)]

    if redirecionando or posicao_comando:
        return len(cru), completar_caminho(cru)

    cmd = palavras[pular] if palavras else ""
    # 1) completion programável do bash (git, xbps, ssh, systemctl...)
    if MOTOR is not None and cmd:
        ultima = cru
        quebra = max(ultima.rfind("="), ultima.rfind(":")) if ultima[:1] not in ("'", '"') else -1
        palavras_bash = palavras[pular:]
        cword_bash = cword - pular
        cur_bash = ultima
        if quebra >= 0:
            cur_bash = ultima[quebra + 1:]
            palavras_bash = palavras_bash[:-1] + [ultima[:quebra], ultima[quebra], cur_bash]
            cword_bash += 2
        opts, cands = MOTOR.completar(texto, palavras_bash, cword_bash)
        if cands:
            aspa = cur_bash[:1] in ("'", '"')
            saida = []
            for cand in cands[:500]:
                bruto = cand.rstrip(" ")
                eh_dir = False
                if "filenames" in opts:
                    try:
                        eh_dir = os.path.isdir(os.path.expanduser(bruto))
                    except OSError:
                        pass
                    shown = bruto + ("/" if eh_dir and not bruto.endswith("/") else "")
                    corpo = (aspa and cur_bash[0] or "") + (bruto if aspa else escapar(bruto))
                    corpo += "/" if eh_dir and not bruto.endswith("/") else ""
                else:
                    shown = bruto
                    corpo = bruto
                if cand.endswith(" "):      # o próprio completion pediu o espaço (git faz isso)
                    fim = " "
                else:
                    fim = "" if ("nospace" in opts or corpo.endswith(("/", "=")) or eh_dir) else " "
                saida.append((corpo + fim, shown, eh_dir))
            return len(cur_bash), saida
    # 2) caminhos (só pastas para cd e afins)
    return len(cru), completar_caminho(cru, so_pastas=cmd in SO_PASTAS)


class JCompleter(Completer):
    """Tab como no bash: completa a parte comum e, na segunda vez, lista as opções."""

    def get_completions(self, document, complete_event):
        try:
            tamanho, itens = gerar_completions(document.text_before_cursor)
        except Exception:
            return
        for texto, exibir, eh_dir in itens:
            estilo = "class:dir" if eh_dir else ""
            yield Completion(texto, start_position=-tamanho, display=FormattedText([(estilo, exibir)]))


# ══════════════════════════════════════════════════════════════════════════════
#  Laço principal
# ══════════════════════════════════════════════════════════════════════════════

def carregar_rc():
    """Modo clássico: executa ~/.jshellrc linha a linha. Com o motor bash, o próprio bash o lê."""
    try:
        if RC.is_file():
            for linha in RC.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    executar_linha(linha)
                except SairShell:
                    pass
    except OSError:
        pass


def iniciar_motor():
    """Sobe o bash escondido. Devolve o Motor ou None (JSHELL_MOTOR=off, sem bash, ou falha)."""
    if jbash is None or os.environ.get("JSHELL_MOTOR", "").lower() in ("off", "0", "no"):
        return None
    # Ctrl+Z pararia o JShell inteiro (não há controle de jobs): ignora, e o bash herda isso.
    try:
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    except (AttributeError, ValueError, OSError):
        pass
    motor = jbash.Motor()
    if not motor.iniciar():
        imprimir(f"<secondary>Motor bash indisponível ({esc(motor.ultimo_erro or 'sem detalhes')}); "
                 f"usando o modo clássico.</secondary>")
        return None
    return motor


def ler_comando(sessao):
    """Lê um comando (várias linhas se a sintaxe pedir: if/for/aspas abertas/here-doc/\\)."""
    texto = sessao.prompt(montar_prompt, rprompt=montar_rprompt, style=estilo_jshell)
    if MOTOR is None:
        return texto
    primeira = texto.split(None, 1)[0] if texto.split() else ""
    while texto.strip() and (not RE_PLANA.fullmatch(texto) or primeira in RESERVADAS or texto.endswith("\\")):
        estado, msg = MOTOR.checar(texto)
        if estado == "incompleto":
            texto += "\n" + sessao.prompt(montar_continuacao, style=estilo_jshell, lexer=JLexer(),
                                          rprompt=None, enable_history_search=False)
            continue
        if estado == "erro":
            linhas = [l for l in msg.splitlines() if l.strip()]
            detalhe = linhas[0].split(": ", 2)[-1] if linhas else "erro de sintaxe"
            imprimir(f"<error>Sintaxe:</error> <secondary>{esc(detalhe)}</secondary>")
            return ""
        break
    return texto


def main():
    global SESSAO, STATUS, MOTOR

    imprimir("<prompt>JShell</prompt>")
    MOTOR = iniciar_motor()
    if MOTOR is not None:
        imprimir("<command>help</command><secondary>' mostra os comandos do JShell</secondary>\n")
    else:
        imprimir("<secondary>Digite '</secondary><command>help</command><secondary>' para ver os comandos.</secondary>\n")

    try:
        historico = FileHistory(str(HISTORICO)) if os.access(Path.home(), os.W_OK) else InMemoryHistory()
    except OSError:
        historico = InMemoryHistory()

    SESSAO = PromptSession(
        completer=JCompleter(),
        history=historico,
        auto_suggest=AutoSuggestFromHistory(),
        lexer=JLexer(),
        complete_style=CompleteStyle.READLINE_LIKE,
        complete_while_typing=False,
        complete_in_thread=True,
        enable_history_search=True,
    )

    if MOTOR is None:
        carregar_rc()
    STATUS = MOTOR.status if MOTOR is not None else 0
    HUD["t0"] = time.time()

    try:
        while True:
            garantir_cwd()
            try:
                comando_ = ler_comando(SESSAO)
            except KeyboardInterrupt:
                continue          # Ctrl+C só cancela a linha atual
            except EOFError:
                print()
                break             # Ctrl+D sai

            if not comando_.strip():
                continue
            inicio = time.monotonic()
            try:
                executar_linha(comando_)
            except SairShell:
                break
            except KeyboardInterrupt:
                print("^C")
                STATUS = 130
            except Exception as e:
                imprimir(f"<error>Erro inesperado:</error> <secondary>{esc(repr(e))}</secondary>")
                STATUS = 1
            hud_registrar(comando_, STATUS, time.monotonic() - inicio)
            _GIT["t"] = 0.0       # o próximo prompt reconfere o git
    finally:
        if HUD["total"] >= 3 and hud_ligado():
            hud_resumo()
        if MOTOR is not None:
            MOTOR.fechar()


if __name__ == "__main__":
    main()
