import shlex
import subprocess
import sys
from pathlib import Path
import os

from prompt_toolkit import PromptSession, print_formatted_text, HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import WordCompleter

BASE_DIR = Path(__file__).resolve().parent
JCODE = BASE_DIR / "JCode.py"
JFILES = BASE_DIR / "JFiles.py"

# Definição do tema elegante, minimalista e de alta legibilidade (Inspiração: Tokyo Night)
estilo_jshell = Style.from_dict({
    'prompt': '#7dcfff bold',       # Ciano/Azul claro para destaque da entrada
    'error': '#f7768e',             # Vermelho suave (não agressivo)
    'success': '#9ece6a',           # Verde suave
    'info': '#7aa2f7',              # Azul elegante para caminhos/ênfase
    'secondary': '#565f89',         # Cinza azulado para descrições e apoios
    'command': '#bb9af7',           # Roxo pastel para comandos reconhecidos
    'arg': '#e0af68',               # Amarelo pastel para argumentos
})

def imprimir(texto):
    """Função auxiliar para imprimir texto formatado mantendo o código limpo."""
    print_formatted_text(HTML(texto), style=estilo_jshell)

def limpar_tela():
    os.system("cls" if os.name == "nt" else "clear")

def formatar_tamanho(tamanho_bytes):
    for unidade in ["B", "KB", "MB", "GB"]:
        if tamanho_bytes < 1024.0:
            return f"{tamanho_bytes:.1f} {unidade}"
        tamanho_bytes /= 1024.0

    return f"{tamanho_bytes:.1f} TB"

def mudar_diretorio(caminho):
    try:
        os.chdir(Path(caminho).expanduser())
    except FileNotFoundError:
        imprimir(f"<error>Erro:</error> Diretório não encontrado.")
    except NotADirectoryError:
        imprimir(f"<error>Erro:</error> Isso não é um diretório.")
    except PermissionError:
        imprimir(f"<error>Erro:</error> Sem permissão para acessar esse diretório.")


def remover_diretorio(caminho):
    pasta = Path(caminho).expanduser()

    if not pasta.exists():
        imprimir(f"<error>Erro:</error> Diretório não encontrado: <info>{pasta}</info>")
        return

    if not pasta.is_dir():
        imprimir(f"<error>Erro:</error> Isso não é um diretório: <info>{pasta}</info>")
        return

    try:
        pasta.rmdir()
        imprimir(f"<success>✓</success> Diretório removido: <info>{pasta}</info>")
    except OSError:
        imprimir("<error>Erro:</error> O diretório não está vazio.")


def criar_diretorio(caminho):
    pasta = Path(caminho).expanduser()

    if pasta.exists():
        imprimir(f"<error>Erro:</error> Já existe: <info>{pasta}</info>")
        return

    try:
        pasta.mkdir()
        imprimir(f"<success>✓</success> Diretório criado: <info>{pasta}</info>")
    except FileNotFoundError:
        imprimir("<error>Erro:</error> O caminho pai não existe.")
    except PermissionError:
        imprimir("<error>Erro:</error> Sem permissão para criar o diretório.")


def criar_arquivo(caminho):
    arquivo = Path(caminho).expanduser()

    if arquivo.exists():
        imprimir(f"<error>Erro:</error> Já existe: <info>{arquivo}</info>")
        return

    try:
        arquivo.touch()
        imprimir(f"<success>✓</success> Arquivo criado: <info>{arquivo}</info>")
    except FileNotFoundError:
        imprimir("<error>Erro:</error> O diretório pai não existe.")
    except PermissionError:
        imprimir("<error>Erro:</error> Sem permissão para criar o arquivo.")


def renomear(origem, destino):
    origem = Path(origem).expanduser()
    destino = Path(destino).expanduser()

    if not origem.exists():
        imprimir(f"<error>Erro:</error> Não encontrado: <info>{origem}</info>")
        return

    if destino.exists():
        imprimir(f"<error>Erro:</error> Destino já existe: <info>{destino}</info>")
        return

    try:
        origem.rename(destino)
        imprimir(
            f"<success>✓</success> "
            f"<info>{origem.name}</info> → <info>{destino}</info>"
        )
    except PermissionError:
        imprimir("<error>Erro:</error> Sem permissão para renomear.")

def listar():
    pasta = Path.cwd()

    imprimir(f"<info>📂 {pasta}</info>")
    imprimir("<secondary>" + "─" * 55 + "</secondary>")

    try:
        conteudo = list(pasta.iterdir())

        pastas = sorted(
            [item for item in conteudo if item.is_dir()],
            key=lambda item: item.name.lower()
        )

        arquivos = sorted(
            [item for item in conteudo if item.is_file()],
            key=lambda item: item.name.lower()
        )

        itens = pastas + arquivos

    except PermissionError:
        imprimir("<error>Erro:</error> Sem permissão para acessar este diretório.")
        return

    if not itens:
        imprimir("<secondary>  (diretório vazio)</secondary>")
        return

    for item in itens:
        if item.is_dir():
            imprimir(
                f"  <command>📁</command> "
                f"<info>{item.name}/</info>"
            )
        else:
            try:
                tamanho = formatar_tamanho(item.stat().st_size)
            except OSError:
                tamanho = "?"

            imprimir(
                f"  <arg>📄</arg> "
                f"<secondary>{item.name}</secondary> "
                f"<secondary>[{tamanho}]</secondary>"
            )

    imprimir("<secondary>" + "─" * 55 + "</secondary>")
    imprimir(f"<secondary>{len(pastas)} pasta(s) · {len(arquivos)} arquivo(s)</secondary>")

def abrir_jcode(caminho, criar=False):
    arquivo = Path(caminho).expanduser()

    if not arquivo.is_absolute():
        arquivo = Path.cwd() / arquivo

    arquivo = arquivo.resolve()

    if arquivo.exists() and not arquivo.is_file():
        imprimir(f"<error>Erro:</error> Isso não é um arquivo: <info>{arquivo}</info>")
        return

    if not arquivo.exists() and not criar:
        imprimir(f"<error>Erro:</error> Arquivo não encontrado: <info>{arquivo}</info>")
        return

    if not JCODE.exists():
        imprimir(f"<error>Erro:</error> JCode não encontrado: <info>{JCODE}</info>")
        return

    try:
        subprocess.run([
            sys.executable,
            str(JCODE),
            str(arquivo)
        ])
    except KeyboardInterrupt:
        imprimir("\n<secondary>JCode interrompido.</secondary>")

def abrir_jfiles():
    if not JFILES.exists():
        imprimir(
            f"<error>Erro:</error> "
            f"JFiles não encontrado: <info>{JFILES}</info>"
        )
        return

    try:
        subprocess.run([
            sys.executable,
            str(JFILES)
        ])
    except KeyboardInterrupt:
        imprimir("\n<secondary>JFiles interrompido.</secondary>")

def executar_comando(comando):
    try:
        partes = shlex.split(comando)
    except ValueError as erro:
        imprimir(f"<error>Comando inválido:</error> <secondary>{erro}</secondary>")
        return True

    if not partes:
        return True

    nome = partes[0].lower()

    if nome == "exit":
        return False

    if nome == "clear":
        limpar_tela()
        return True

    if nome == "cd":
        if len(partes) < 2:
            imprimir("<info>Uso:</info> <command>cd</command> <arg>pasta</arg>")
            return True

        mudar_diretorio(partes[1])
        return True

    if nome == "rd":
        if len(partes) < 2:
            imprimir("<info>Uso:</info> <command>rd</command> <arg>pasta</arg>")
            return True

        remover_diretorio(partes[1])
        return True

    if nome == "mkdir":
        if len(partes) < 2:
            imprimir("<info>Uso:</info> <command>mkdir</command> <arg>pasta</arg>")
            return True

        criar_diretorio(partes[1])
        return True

    if nome == "touch":
        if len(partes) < 2:
            imprimir("<info>Uso:</info> <command>touch</command> <arg>arquivo</arg>")
            return True

        criar_arquivo(partes[1])
        return True

    if nome == "ren":
        if len(partes) < 3:
            imprimir(
                "<info>Uso:</info> "
                "<command>ren</command> <arg>antigo</arg> <arg>novo</arg>"
            )
            return True

    if nome == "jfiles":
        abrir_jfiles()
        return True

        renomear(partes[1], partes[2])
        return True

    if nome == "ls":
        listar()
        return True

    if nome == "jcode":
        if len(partes) < 2:
            imprimir("<info>Uso:</info> <command>jcode</command> <arg><arquivo></arg>")
            return True

        if partes[1].lower() == "new":
            if len(partes) < 3:
                imprimir("<info>Uso:</info> <command>jcode new</command> <arg><arquivo></arg>")
                return True

            caminho = Path(partes[2]).expanduser()

            if not caminho.is_absolute():
                caminho = Path.cwd() / caminho

            if caminho.exists():
                imprimir(f"<error>Arquivo já existe:</error> <info>{caminho}</info>")
                return True

            abrir_jcode(partes[2], criar=True)
            return True

        abrir_jcode(partes[1])
        return True

    if nome == "help":
        imprimir("<secondary>Comandos:</secondary>")
        imprimir("  <command>jcode</command> <arg>arquivo</arg>      <secondary>Abre um arquivo no JCode</secondary>")
        imprimir("  <command>jcode new</command> <arg>arquivo</arg>  <secondary>Cria um arquivo novo no JCode</secondary>")
        imprimir("  <command>jfiles</command>                 <secondary>Abre o JFiles</secondary>")
        imprimir("  <command>ls</command>                 <secondary>Lista os arquivos</secondary>")
        imprimir("  <command>cd</command> <arg>pasta</arg>          <secondary>Muda o diretório atual</secondary>")
        imprimir("  <command>rd</command> <arg>pasta</arg>         <secondary>Remove uma pasta vazia</secondary>")
        imprimir("  <command>mkdir</command> <arg>pasta</arg>      <secondary>Cria uma pasta</secondary>")
        imprimir("  <command>touch</command> <arg>arquivo</arg>    <secondary>Cria um arquivo vazio</secondary>")
        imprimir("  <command>ren</command> <arg>antigo</arg> <arg>novo</arg>  <secondary>Renomeia um item</secondary>")
        imprimir("  <command>clear</command>              <secondary>Limpa a tela</secondary>")
        imprimir("  <command>help</command>               <secondary>Mostra esta ajuda</secondary>")
        imprimir("  <command>exit</command>               <secondary>Sai do JShell</secondary>")
        return True

    imprimir(f"<error>Comando desconhecido:</error> <command>{nome}</command>")
    return True


def main():
    imprimir("<prompt>JShell</prompt>")
    imprimir("<secondary>Digite '</secondary><command>help</command><secondary>' para ver os comandos.</secondary>\n")

    # Autocomplete discreto e elegante para os comandos conhecidos
    comandos_conhecidos = WordCompleter(
        [
            "exit",
            "clear",
            "ls",
            "cd",
            "rd",
            "mkdir",
            "touch",
            "ren",
            "jcode",
            "jfiles",
            "new",
            "help"
        ],
        ignore_case=True
    )

    sessao = PromptSession(completer=comandos_conhecidos)

    while True:
        try:
            comando = sessao.prompt(
                HTML(f'''<info>{Path.cwd()}</info>
<prompt>JShell></prompt>'''),
                style=estilo_jshell
            )
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not executar_comando(comando.strip()):
            break


if __name__ == "__main__":
    main()