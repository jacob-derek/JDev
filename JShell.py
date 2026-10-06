import difflib
import fnmatch
import getpass
import glob
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections import deque
from datetime import datetime
from html import escape as esc
from itertools import islice
from pathlib import Path

from prompt_toolkit import PromptSession, print_formatted_text, HTML
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, PathCompleter, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.shortcuts import clear as pt_clear
from prompt_toolkit.styles import Style

BASE_DIR = Path(__file__).resolve().parent
JCODE = BASE_DIR / "JCode.py"
JFILES = BASE_DIR / "JFiles.py"
HISTORICO = Path.home() / ".jshell_history"
RC = Path.home() / ".jshellrc"
IS_WIN = os.name == "nt"

# Tema elegante, minimalista e de alta legibilidade (Inspiração: Tokyo Night)
estilo_jshell = Style.from_dict({
    'prompt': '#7dcfff bold',       # Ciano/Azul claro para destaque da entrada
    'error': '#f7768e',             # Vermelho suave (não agressivo)
    'success': '#9ece6a',           # Verde suave
    'info': '#7aa2f7',              # Azul elegante para caminhos/ênfase
    'secondary': '#565f89',         # Cinza azulado para descrições e apoios
    'command': '#bb9af7',           # Roxo pastel para comandos reconhecidos
    'arg': '#e0af68',               # Amarelo pastel para argumentos
    'auto-suggestion': '#565f89',   # Sugestão do histórico
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
                        raise ErroArgs(f"a opção -{c} precisa de um valor")
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
    pt_clear()


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
        raise ErroArgs(f"Sem permissão para ler: {p}")


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


def listar(alvo=None, detalhes=False, ordem="nome", inverter=False):
    pasta = Path(alvo).expanduser() if alvo else Path.cwd()

    try:
        with os.scandir(pasta) as it:
            entradas = list(it)
    except FileNotFoundError:
        return erro(f"Não encontrado: {fmt(pasta)}")
    except NotADirectoryError:
        return erro(f"Isso não é um diretório: {fmt(pasta)}")
    except PermissionError:
        imprimir(f"<info>📂 {esc(str(pasta))}</info>")
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
        f"<info>📂 {esc(str(pasta))}</info>",
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
            linhas.append(f"  <command>📁</command> {extra}<info>{nome}/</info>")
        elif t == "f":
            n_arquivos += 1
            if detalhes:
                linhas.append(f"  <arg>📄</arg> {extra}<secondary>{nome}</secondary>")
            else:
                tamanho = formatar_tamanho(st.st_size) if st else "?"
                linhas.append(
                    f"  <arg>📄</arg> <secondary>{nome}</secondary> <secondary>[{tamanho}]</secondary>"
                )
        else:
            n_outros += 1
            linhas.append(f"  <arg>🔗</arg> {extra}<secondary>{nome}</secondary>")

    linhas.append("<secondary>" + "─" * 55 + "</secondary>")
    resumo = f"{n_pastas} pasta(s) · {n_arquivos} arquivo(s)"
    if n_outros:
        resumo += f" · {n_outros} outro(s)"
    linhas.append(f"<secondary>{resumo}</secondary>")
    imprimir("\n".join(linhas))
    return 0


def abrir_jcode(caminho, criar=False):
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
         "Navegação", aliases=("dir",))
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
        raise ErroArgs("número de linhas inválido")


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
    if not args:
        imprimir("<info>Uso:</info> <command>jcode</command> <arg>arquivo</arg>")
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

        return abrir_jcode(args[1], criar=True)

    return abrir_jcode(args[0])


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
    linhas.append("  <secondary>• Programas externos (python, nano...) e pipes/redirecionamentos"
                  " (|, &gt;, &lt;) são repassados ao sistema.</secondary>")
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
    """Repassa a linha inteira ao shell do sistema (pipes, redirecionamentos...)."""
    primeira = linha.split(None, 1)
    if primeira and primeira[0] in ALIASES:
        linha = ALIASES[primeira[0]] + (" " + primeira[1] if len(primeira) > 1 else "")
    sys.stdout.flush()
    codigo = subprocess.run(linha, shell=True).returncode
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


def executar_linha(linha):
    """Executa uma linha (com &&, ||, ;). Retorna o código de saída."""
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

    # Pipes, redirecionamentos e segundo plano: o shell do sistema resolve
    if any(eh_operador(t) and t not in SEPARADORES for t in tokens):
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


def executar_comando(comando_):
    """Compatibilidade: retorna False quando o shell deve encerrar."""
    try:
        executar_linha(comando_)
    except SairShell:
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  Prompt, completion e laço principal
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


def montar_prompt():
    try:
        cwd = str(Path.cwd())
    except OSError:
        os.chdir(Path.home())
        imprimir("<error>O diretório atual foi removido.</error> <secondary>Voltando para a home.</secondary>")
        cwd = str(Path.cwd())

    home = str(Path.home())
    if cwd == home:
        cwd = "~"
    elif cwd.startswith(home + os.sep):
        cwd = "~" + cwd[len(home):]

    ramo = ramo_git()
    sufixo = f" <command>({esc(ramo)})</command>" if ramo else ""
    cor = "prompt" if STATUS == 0 else "error"
    return HTML(f"<info>{esc(cwd)}</info>{sufixo}\n<{cor}>JShell></{cor}>")


class JCompleter(Completer):
    """Comandos na primeira palavra; caminhos nas demais."""

    def __init__(self):
        self.comandos = WordCompleter(lambda: sorted(set(COMANDOS) | set(ALIASES)), ignore_case=True)
        self.caminhos = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        texto = document.text_before_cursor
        if " " not in texto.lstrip():
            yield from self.comandos.get_completions(document, complete_event)
            return
        ultima = texto.rsplit(" ", 1)[-1]
        sub = Document(ultima, len(ultima))
        yield from self.caminhos.get_completions(sub, complete_event)


def carregar_rc():
    """Executa ~/.jshellrc (um comando por linha; ideal para aliases)."""
    try:
        if RC.is_file():
            for linha in RC.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    executar_linha(linha)
                except SairShell:
                    pass
    except OSError:
        pass


def main():
    global SESSAO, STATUS

    imprimir("<prompt>JShell</prompt>")
    imprimir("<secondary>Digite '</secondary><command>help</command><secondary>' para ver os comandos.</secondary>\n")

    try:
        historico = FileHistory(str(HISTORICO)) if os.access(Path.home(), os.W_OK) else InMemoryHistory()
    except OSError:
        historico = InMemoryHistory()

    SESSAO = PromptSession(
        completer=JCompleter(),
        history=historico,
        auto_suggest=AutoSuggestFromHistory(),
        complete_in_thread=True,
        enable_history_search=True,
    )

    carregar_rc()
    STATUS = 0

    while True:
        try:
            comando_ = SESSAO.prompt(montar_prompt(), style=estilo_jshell)
        except KeyboardInterrupt:
            continue          # Ctrl+C só cancela a linha atual
        except EOFError:
            print()
            break             # Ctrl+D sai

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


if __name__ == "__main__":
    main()
