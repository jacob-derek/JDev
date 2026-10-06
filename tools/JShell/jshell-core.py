import os
import shlex
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
JCODE = BASE_DIR / "JCode.py"
JFILES = BASE_DIR / "JFiles.py"


def formatar_tamanho(tamanho_bytes):
    for unidade in ["B", "KB", "MB", "GB"]:
        if tamanho_bytes < 1024.0:
            return f"{tamanho_bytes:.1f} {unidade}"
        tamanho_bytes /= 1024.0

    return f"{tamanho_bytes:.1f} TB"


def mudar_diretorio(caminho):
    try:
        os.chdir(Path(caminho).expanduser())
        return f"Diretório atual: {Path.cwd()}"
    except FileNotFoundError:
        return "Erro: Diretório não encontrado."
    except NotADirectoryError:
        return "Erro: Isso não é um diretório."
    except PermissionError:
        return "Erro: Sem permissão para acessar este diretório."


def listar():
    pasta = Path.cwd()

    try:
        conteudo = list(pasta.iterdir())
    except PermissionError:
        return "Erro: Sem permissão para acessar este diretório."

    pastas = sorted(
        [item for item in conteudo if item.is_dir()],
        key=lambda item: item.name.lower()
    )

    arquivos = sorted(
        [item for item in conteudo if item.is_file()],
        key=lambda item: item.name.lower()
    )

    itens = pastas + arquivos

    if not itens:
        return f"{pasta}\n(diretório vazio)"

    linhas = [str(pasta), "─" * 55]

    for item in itens:
        if item.is_dir():
            linhas.append(f"📁 {item.name}/")
        else:
            try:
                tamanho = formatar_tamanho(item.stat().st_size)
            except OSError:
                tamanho = "?"

            linhas.append(f"📄 {item.name} [{tamanho}]")

    linhas.append("─" * 55)
    linhas.append(f"{len(pastas)} pasta(s) · {len(arquivos)} arquivo(s)")

    return "\n".join(linhas)


def executar_comando(comando):
    try:
        partes = shlex.split(comando)
    except ValueError as erro:
        return f"Comando inválido: {erro}", True

    if not partes:
        return "", True

    nome = partes[0].lower()

    if nome == "exit":
        return "Saindo...", False

    if nome == "pwd":
        return str(Path.cwd()), True

    if nome == "clear":
        # O C pode tratar isso depois como uma ação própria.
        return "__JSHELL_CLEAR__", True

    if nome == "cd":
        if len(partes) < 2:
            return "Uso: cd <pasta>", True

        return mudar_diretorio(partes[1]), True

    if nome == "ls":
        return listar(), True

    if nome == "mkdir":
        if len(partes) < 2:
            return "Uso: mkdir <pasta>", True

        pasta = Path(partes[1]).expanduser()

        if pasta.exists():
            return f"Erro: Já existe: {pasta}", True

        try:
            pasta.mkdir()
            return f"✓ Diretório criado: {pasta}", True
        except FileNotFoundError:
            return "Erro: O caminho pai não existe.", True
        except PermissionError:
            return "Erro: Sem permissão para criar o diretório.", True

    if nome == "touch":
        if len(partes) < 2:
            return "Uso: touch <arquivo>", True

        arquivo = Path(partes[1]).expanduser()

        if arquivo.exists():
            return f"Erro: Já existe: {arquivo}", True

        try:
            arquivo.touch()
            return f"✓ Arquivo criado: {arquivo}", True
        except FileNotFoundError:
            return "Erro: O diretório pai não existe.", True
        except PermissionError:
            return "Erro: Sem permissão para criar o arquivo.", True

    if nome == "ren":
        if len(partes) < 3:
            return "Uso: ren <antigo> <novo>", True

        origem = Path(partes[1]).expanduser()
        destino = Path(partes[2]).expanduser()

        if not origem.exists():
            return f"Erro: Não encontrado: {origem}", True

        if destino.exists():
            return f"Erro: Destino já existe: {destino}", True

        try:
            origem.rename(destino)
            return f"✓ {origem.name} → {destino}", True
        except PermissionError:
            return "Erro: Sem permissão para renomear.", True

    if nome == "jcode":
        if len(partes) < 2:
            return "Uso: jcode <arquivo>", True

        arquivo = Path(partes[1]).expanduser()

        if not arquivo.is_absolute():
            arquivo = Path.cwd() / arquivo

        arquivo = arquivo.resolve()

        if arquivo.exists() and not arquivo.is_file():
            return f"Erro: Isso não é um arquivo: {arquivo}", True

        if not arquivo.exists():
            return f"Erro: Arquivo não encontrado: {arquivo}", True

        if not JCODE.exists():
            return f"Erro: JCode não encontrado: {JCODE}", True

        try:
            subprocess.Popen([
                sys.executable,
                str(JCODE),
                str(arquivo)
            ])
            return f"✓ JCode aberto: {arquivo.name}", True
        except OSError as erro:
            return f"Erro ao abrir JCode: {erro}", True

    if nome == "jfiles":
        if not JFILES.exists():
            return f"Erro: JFiles não encontrado: {JFILES}", True

        try:
            subprocess.Popen([
                sys.executable,
                str(JFILES)
            ])
            return "✓ JFiles aberto.", True
        except OSError as erro:
            return f"Erro ao abrir JFiles: {erro}", True

    if nome == "help":
        return """Comandos:

  pwd                 Mostra o diretório atual
  ls                  Lista arquivos e pastas
  cd <pasta>          Muda o diretório
  mkdir <pasta>       Cria uma pasta
  touch <arquivo>     Cria um arquivo
  ren <antigo> <novo> Renomeia um item
  jcode <arquivo>     Abre um arquivo no JCode
  jfiles              Abre o JFiles
  clear               Limpa a saída
  help                Mostra esta ajuda
  exit                Fecha o JShell""", True

    return f"Comando desconhecido: {nome}", True


def main():
    # Cada linha recebida é um comando.
    # Cada resposta começa com RESULT e termina com END.
    for linha in sys.stdin:
        comando = linha.rstrip("\n")

        resultado, continuar = executar_comando(comando)

        sys.stdout.write("RESULT\n")
        sys.stdout.write(resultado)
        sys.stdout.write("\nEND\n")
        sys.stdout.flush()

        if not continuar:
            break


if __name__ == "__main__":
    main()
