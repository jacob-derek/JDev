#!/usr/bin/env python3
"""JCode — editor de terminal em Python (prompt_toolkit).

Princípios:
  * digitar nunca espera por análise, realce ou I/O lento;
  * nada que o usuário digite/cole pode derrubar o programa;
  * o arquivo em disco só é tocado de forma atômica e consciente.

Atalhos principais:
  Ctrl+S salvar · Ctrl+Q sair · Ctrl+Z/Y desfazer/refazer · Ctrl+G ir para linha
  Ctrl+O sumário · Ctrl+E explorar (setas ignoram o autocomplete) · Ctrl+L selecionar linhas
  Ctrl+K apagar linha · Ctrl+A selecionar tudo · Ctrl+C/V copiar/colar
  Tab/Shift+Tab indentar/recuar · Alt+Backspace apagar palavra
"""
import ast
import asyncio
import bisect
import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, List, NamedTuple, Optional, Tuple

try:
    import pyperclip
except ImportError:  # o clipboard externo é opcional
    pyperclip = None

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit, WindowRenderInfo
from prompt_toolkit.layout.containers import ConditionalContainer, FloatContainer, Float
from prompt_toolkit.layout.controls import BufferControl, UIContent, FormattedTextControl
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.lexers import Lexer, PygmentsLexer
from prompt_toolkit.styles import Style

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound


# ──────────────────────────────────────────────────────────────────────────────
# Ajustes (mexa aqui se quiser mudar o comportamento)
# ──────────────────────────────────────────────────────────────────────────────
INDENT = "    "
MIN_CHARS_AUTOCOMPLETE = 2        # só sugere a partir de N letras (1 = como antes)
MAX_SUGESTOES = 50                # teto de itens no menu de autocomplete
LIMITE_ARQUIVO_BYTES = 30 * 1024 * 1024
LIMITE_SINTAXE_CHARS = 400_000    # acima disso não roda ast.parse (segura a GIL)
LIMITE_ANALISE_CHARS = 2_000_000  # acima disso nem identificadores/sumário
LIMITE_SYNC_LEXER_LINHAS = 2000   # acima disso o realce não relê o arquivo desde o início
ANALISE_DEBOUNCE_BASE = 0.3       # segundos de pausa antes de analisar
ANALISE_DEBOUNCE_MAX = 2.0
ORCAMENTO_UNDO_CHARS = 100_000_000  # memória máxima (em caracteres) do histórico de undo
ESC_TIMEOUT = 0.05                # espera para distinguir Esc de Alt+tecla/setas
MOUSE_ATIVO = True


PALAVRAS_CHAVE_PYTHON = [
    "def", "class", "import", "from", "return", "if", "elif", "else",
    "for", "while", "try", "except", "finally", "with", "as", "pass",
    "break", "continue", "lambda", "yield", "async", "await", "print",
    "len", "range", "str", "int", "float", "list", "dict", "set", "tuple", "bool",
    "and", "or", "not", "in", "is", "None", "True", "False", "self",
    "raise", "assert", "del", "global", "nonlocal",
]

PALAVRAS_POR_EXTENSAO = {
    ".py": set(PALAVRAS_CHAVE_PYTHON),
    ".c": set("auto break case char const continue default do double else enum extern float for goto if int long register return short signed sizeof static struct switch typedef union unsigned void volatile while printf scanf NULL size_t".split()),
    ".h": set("char const define elif else endif error if ifdef ifndef include line pragma undef auto break case enum extern float for goto int long register return short signed sizeof static struct typedef union unsigned void volatile while NULL size_t".split()),
}

RE_IDENTIFICADOR = re.compile(r"[^\W\d]\w*")          # aceita acentos (área, índice…)
RE_FINAL_PALAVRA = re.compile(r"\w+$")
RE_DEF = re.compile(r"^([ \t]*)(async[ \t]+def|def|class)[ \t]+([^\W\d]\w*)", re.MULTILINE)


# ──────────────────────────────────────────────────────────────────────────────
# Funções puras (sem prompt_toolkit): fáceis de testar
# ──────────────────────────────────────────────────────────────────────────────
def _indentacao_inicial(texto: str) -> str:
    return texto[: len(texto) - len(texto.lstrip(" \t"))]


def _so_digitos(texto: str) -> bool:
    return texto.isascii() and texto.isdigit()


def calcular_indentacao_enter(linha: str, coluna: int) -> str:
    """Retorna a indentação anterior ao cursor, limitada à indentação da linha."""
    coluna = max(0, min(coluna, len(linha)))
    base = _indentacao_inicial(linha[:coluna])
    if coluna >= len(linha) and linha.rstrip().endswith(":"):
        base += "\t" if "\t" in base else INDENT
    return base


def interpretar_ir_linha(comando: str, linha_atual: int, total_linhas: int):
    """Retorna (linha, coluna_1based_ou_None), ou levanta ValueError."""
    comando = comando.strip()
    if not comando:
        raise ValueError("Digite uma linha.")
    if ":" in comando:
        partes = comando.split(":")
        if len(partes) != 2 or not all(_so_digitos(x) for x in partes):
            raise ValueError("Use linha:coluna, por exemplo 42:8.")
        linha, coluna = map(int, partes)
        if not 1 <= linha <= total_linhas or coluna < 1:
            raise ValueError("Linha ou coluna fora do intervalo.")
        return linha - 1, coluna - 1
    if comando[0] in "+-":
        if not _so_digitos(comando[1:]):
            raise ValueError("Deslocamento inválido.")
        linha = linha_atual + int(comando)
    elif _so_digitos(comando):
        linha = int(comando)
    else:
        raise ValueError("Digite um número, +N, -N ou linha:coluna.")
    if not 1 <= linha <= total_linhas:
        raise ValueError(f"A linha deve estar entre 1 e {total_linhas}.")
    return linha - 1, None


def indentar_bloco(linhas, inicio, fim, remover=False):
    """Transforma linhas inclusivamente entre inicio e fim (índices zero-based)."""
    resultado = list(linhas)
    if not resultado:
        return resultado
    inicio = max(0, min(inicio, len(resultado) - 1))
    fim = max(0, min(fim, len(resultado) - 1))
    a, b = sorted((inicio, fim))
    for i in range(a, b + 1):
        if remover:
            if resultado[i].startswith("\t"):
                resultado[i] = resultado[i][1:]
            else:
                n = len(resultado[i]) - len(resultado[i].lstrip(" "))
                resultado[i] = resultado[i][min(4, n):]
        else:
            resultado[i] = INDENT + resultado[i]
    return resultado


def remover_linhas(linhas, inicio, fim):
    """Remove as linhas entre inicio e fim (inclusive). Nunca devolve lista vazia."""
    if not linhas:
        return [""]
    limite = len(linhas) - 1
    a, b = sorted((max(0, min(inicio, limite)), max(0, min(fim, limite))))
    return list(linhas[:a]) + list(linhas[b + 1:]) or [""]


def sanitizar_texto_clipboard(texto: str) -> str:
    """Remove caracteres nulos e sequências de controle ANSI que causam crash em navegadores."""
    texto = texto.replace("\0", "")
    texto = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', texto)
    return texto


def normalizar_colagem(texto: str) -> str:
    """Sanitiza e padroniza o texto antes de entrar no buffer (CRLF/CR → LF, sem surrogates)."""
    texto = sanitizar_texto_clipboard(texto)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return texto.encode("utf-8", "ignore").decode("utf-8")


def extrair_identificadores(texto: str, arvore=None) -> set:
    """Palavras-chave + todos os identificadores do texto.

    O argumento `arvore` é mantido por compatibilidade: todo nome que o AST
    enxerga já aparece no texto, então percorrer a árvore só custava tempo.
    """
    identificadores = set(PALAVRAS_CHAVE_PYTHON)
    identificadores.update(RE_IDENTIFICADOR.findall(texto))
    return identificadores


def palavra_no_cursor(texto: str, pos: int) -> str:
    """Palavra (limitada a ~80 chars para cada lado) que contém a posição `pos`."""
    pos = max(0, min(pos, len(texto)))
    ini, lim = pos, max(0, pos - 80)
    while ini > lim and (texto[ini - 1].isalnum() or texto[ini - 1] == "_"):
        ini -= 1
    fim, lim = pos, min(len(texto), pos + 80)
    while fim < lim and (texto[fim].isalnum() or texto[fim] == "_"):
        fim += 1
    return texto[ini:fim]


def extrair_outline(texto: str) -> List[Tuple[int, int, str]]:
    """Lista (linha_zero_based, profundidade, rótulo) de defs/classes.

    Baseado em regex de propósito: funciona mesmo com o código quebrado no meio
    da digitação e custa uma fração de um ast.parse.
    """
    itens = []
    pilha: List[int] = []
    linha = 0
    ultimo = 0
    for m in RE_DEF.finditer(texto):
        linha += texto.count("\n", ultimo, m.start())
        ultimo = m.start()
        recuo = len(m.group(1).expandtabs(4))
        while pilha and pilha[-1] >= recuo:
            pilha.pop()
        profundidade = len(pilha)
        pilha.append(recuo)
        tipo = "class" if m.group(2) == "class" else "def"
        itens.append((linha, profundidade, f"{tipo} {m.group(3)}"))
    return itens


def indice_outline_para_linha(itens, linha: int) -> int:
    """Índice do último bloco que começa em `linha` ou antes (0 se não houver)."""
    if not itens:
        return 0
    return max(0, bisect.bisect_right([i[0] for i in itens], linha) - 1)


def buscar_sugestoes(indice: List[str], prefixo: str, limite: int = MAX_SUGESTOES) -> List[str]:
    """Prefixo em lista ordenada: O(log n + k), sem ordenar nada a cada tecla."""
    if not prefixo:
        return []
    i = bisect.bisect_left(indice, prefixo)
    saida: List[str] = []
    n = len(indice)
    while i < n and len(saida) < limite:
        palavra = indice[i]
        if not palavra.startswith(prefixo):
            break
        if palavra != prefixo:
            saida.append(palavra)
        i += 1
    return saida


class ResultadoAnalise(NamedTuple):
    erro_sintaxe: Optional[Tuple[Optional[int], str]]  # (linha, mensagem)
    indice: List[str]                                   # identificadores ORDENADOS
    outline: List[Tuple[int, int, str]]
    desativada: bool


def analisar_documento(texto: str, extensao: str, palavras_base, cursor: Optional[int] = None) -> ResultadoAnalise:
    """Roda numa thread de trabalho. Não guarda AST (economiza memória) e nunca levanta."""
    try:
        if len(texto) > LIMITE_ANALISE_CHARS:
            return ResultadoAnalise(None, sorted(set(palavras_base)), [], True)

        erro = None
        if extensao == ".py" and len(texto) <= LIMITE_SINTAXE_CHARS:
            try:
                ast.parse(texto)
            except SyntaxError as e:
                erro = (e.lineno, e.msg)
            except Exception:  # RecursionError, MemoryError, ValueError…
                pass

        contagem = Counter(RE_IDENTIFICADOR.findall(texto))
        if cursor is not None:
            # A palavra que está sendo digitada agora não deve virar sugestão dela mesma.
            atual = palavra_no_cursor(texto, cursor)
            if atual in contagem:
                contagem[atual] -= 1
        identificadores = {p for p, c in contagem.items() if c > 0}
        identificadores.update(palavras_base)

        outline = extrair_outline(texto) if extensao == ".py" else []
        return ResultadoAnalise(erro, sorted(identificadores), outline, False)
    except Exception:
        return ResultadoAnalise(None, sorted(set(palavras_base)), [], False)


# ── Arquivo: leitura/escrita robustas ─────────────────────────────────────────
class ConteudoArquivo(NamedTuple):
    texto: str
    encoding: str
    fim_linha: str
    bom: bool
    erro: Optional[str]


def decodificar_bytes(dados: bytes) -> Tuple[str, str, str, bool]:
    """(texto_com_\\n, encoding, fim_de_linha_original, tinha_bom)."""
    bom = dados.startswith(b"\xef\xbb\xbf")
    corpo = dados[3:] if bom else dados
    texto, usado = None, "utf-8"
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            texto, usado = corpo.decode(enc), enc
            break
        except UnicodeDecodeError:
            continue
    if texto is None or (bom and usado != "utf-8"):
        bom = False
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                texto, usado = dados.decode(enc), enc
                break
            except UnicodeDecodeError:
                continue

    crlf = texto.count("\r\n")
    lf = texto.count("\n") - crlf
    cr = texto.count("\r") - crlf
    fim = "\n"
    if crlf > lf and crlf >= cr:
        fim = "\r\n"
    elif cr > lf and cr > crlf:
        fim = "\r"
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return texto, usado, fim, bom


def ler_arquivo(caminho: Path) -> ConteudoArquivo:
    padrao = ConteudoArquivo("", "utf-8", "\n", False, None)
    try:
        if not caminho.exists():
            return padrao  # arquivo novo
        if not caminho.is_file():
            return padrao._replace(erro="não é um arquivo regular")
        if caminho.stat().st_size > LIMITE_ARQUIVO_BYTES:
            return padrao._replace(erro="arquivo grande demais")
        dados = caminho.read_bytes()
    except PermissionError:
        return padrao._replace(erro="sem permissão de leitura")
    except OSError as e:
        return padrao._replace(erro=str(e.strerror or e))
    if b"\x00" in dados[:8192]:
        return padrao._replace(erro="arquivo binário")
    texto, enc, fim, bom = decodificar_bytes(dados)
    return ConteudoArquivo(texto, enc, fim, bom, None)


def codificar_para_salvar(texto: str, encoding: str, fim_linha: str, bom: bool) -> Tuple[bytes, str]:
    """Reaplica fim de linha/BOM originais. Se o encoding original não comporta o texto, cai para UTF-8."""
    if fim_linha != "\n":
        texto = texto.replace("\n", fim_linha)
    usado = encoding
    try:
        dados = texto.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        usado = "utf-8"
        dados = texto.encode("utf-8", errors="replace")
    if bom and usado == "utf-8":
        dados = b"\xef\xbb\xbf" + dados
    return dados, usado


def assinatura_arquivo(caminho: Path):
    try:
        st = caminho.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def gravar_arquivo(caminho: Path, dados: bytes) -> None:
    """Grava via arquivo temporário + os.replace: se der erro no meio, o original continua intacto."""
    destino = caminho.resolve() if caminho.exists() else caminho
    if destino.exists():
        try:
            fd, tmp = tempfile.mkstemp(prefix=f".{destino.name}.", suffix=".jcode-tmp", dir=str(destino.parent))
        except OSError:
            fd = tmp = None  # pasta sem escrita: tenta direto no arquivo
        if fd is not None:
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(dados)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                try:
                    shutil.copymode(destino, tmp)
                except OSError:
                    pass
                os.replace(tmp, destino)
                return
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    with open(destino, "wb") as f:
        f.write(dados)


# ── Clipboard ─────────────────────────────────────────────────────────────────
_clipboard_interno = [""]


def clipboard_escrever(texto: str) -> str:
    texto = sanitizar_texto_clipboard(texto)
    comandos = []
    if shutil.which("wl-copy"):
        comandos.append((["wl-copy"], "wl-clipboard (Wayland)"))
    exe_termux = shutil.which("termux-clipboard-set")
    if exe_termux:
        comandos.append(([exe_termux], "Termux"))
    if shutil.which("xclip"):
        comandos.append((["xclip", "-selection", "clipboard"], "xclip"))

    erros = []
    for cmd, nome in comandos:
        try:
            # DEVNULL: erros desses programas não podem vazar para a tela do editor.
            subprocess.run(cmd, input=texto, text=True, timeout=2, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return nome
        except Exception as e:
            erros.append(type(e).__name__)

    if pyperclip is not None:
        try:
            pyperclip.copy(texto)
            return "pyperclip"
        except Exception as e:
            erros.append(type(e).__name__)

    _clipboard_interno[0] = texto
    return "memória" + (" (externo indisponível)" if erros else "")


def clipboard_ler() -> Tuple[str, str]:
    comandos = []
    if shutil.which("wl-paste"):
        comandos.append((["wl-paste", "--no-newline"], "wl-clipboard"))
    exe_termux = shutil.which("termux-clipboard-get")
    if exe_termux:
        comandos.append(([exe_termux], "Termux"))
    for cmd, nome in comandos:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=True)
            if r.stdout:
                return normalizar_colagem(r.stdout), nome
        except Exception:
            pass
    if pyperclip is not None:
        try:
            valor = pyperclip.paste()
            if valor:
                return normalizar_colagem(valor), "pyperclip"
        except Exception:
            pass
    return _clipboard_interno[0], "memória" if _clipboard_interno[0] else "vazio/indisponível"


# ── Log de erros internos ─────────────────────────────────────────────────────
def caminho_log() -> Optional[Path]:
    try:
        return Path.home() / ".jcode-erros.log"
    except Exception:
        return None


def registrar_erro(exc: BaseException) -> None:
    try:
        log = caminho_log()
        if log is None:
            return
        if log.exists() and log.stat().st_size > 512 * 1024:
            log.write_text("", encoding="utf-8")
        with log.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) + "\n")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Componentes de interface
# ──────────────────────────────────────────────────────────────────────────────
class DynamicPythonCompleter(Completer):
    """Sugere a partir de um índice ORDENADO de identificadores (busca binária, sem sort por tecla)."""

    def __init__(self, get_identificadores_func: Callable[[], Iterable[str]],
                 minimo: int = MIN_CHARS_AUTOCOMPLETE, limite: int = MAX_SUGESTOES) -> None:
        self.get_identificadores_func = get_identificadores_func
        self.minimo = minimo
        self.limite = limite

    def get_completions(self, document, complete_event):
        try:
            m = RE_FINAL_PALAVRA.search(document.current_line_before_cursor[-80:])
            if not m:
                return
            prefixo = m.group(0)
            if len(prefixo) < self.minimo or prefixo[0].isdigit():
                return
            indice = self.get_identificadores_func()
            if not isinstance(indice, list):  # aceita set/qualquer iterável (mais lento)
                indice = sorted(indice)
            for palavra in buscar_sugestoes(indice, prefixo, self.limite):
                yield Completion(palavra, start_position=-len(prefixo))
        except Exception:
            return


class LexerAdaptativo(Lexer):
    """Realce Pygments que não degrada em arquivos grandes e nunca derruba a tela.

    PygmentsLexer(sync_from_start=True) reanalisa o arquivo INTEIRO desde a
    linha 1 a cada tecla — é isso que trava arquivos grandes. Acima de
    LIMITE_SYNC_LEXER_LINHAS usamos a sincronização por regex (começa perto da
    linha visível). Se o Pygments falhar numa linha, ela aparece sem cor.
    """

    def __init__(self, classe_pygments) -> None:
        self._completo = PygmentsLexer(classe_pygments, sync_from_start=True)
        self._rapido = PygmentsLexer(classe_pygments, sync_from_start=False)

    def lex_document(self, document):
        interno = self._completo if document.line_count <= LIMITE_SYNC_LEXER_LINHAS else self._rapido
        try:
            get_linha = interno.lex_document(document)
        except Exception:
            get_linha = None
        linhas = document.lines

        def lex(i: int) -> StyleAndTextTuples:
            if get_linha is not None:
                try:
                    return get_linha(i)
                except Exception:
                    pass
            return [("", linhas[i])] if 0 <= i < len(linhas) else []

        return lex


class IndentGuideProcessor(Processor):
    """Troca os espaços de indentação por guias visuais, preservando o estilo do resto da linha."""

    def apply_transformation(self, transformation_input):
        fragmentos = transformation_input.fragments
        try:
            novo: StyleAndTextTuples = []
            em_indent = True
            for fragmento in fragmentos:
                if not em_indent:
                    novo.append(fragmento)
                    continue
                estilo, texto = fragmento[0], fragmento[1]
                resto = tuple(fragmento[2:])
                n = len(texto) - len(texto.lstrip(" "))
                if n:
                    novo.append((f"{estilo} class:indent-guide".strip(), "·" * n) + resto)
                if n < len(texto):
                    novo.append((estilo, texto[n:]) + resto)
                    em_indent = False
            return Transformation(novo)
        except Exception:
            return Transformation(fragmentos)


class CustomNumberedMargin(Margin):
    """Margem personalizada com números de linha e um caractere separador."""

    def __init__(self, separator: str = "│") -> None:
        self.separator = separator

    def get_width(self, get_ui_content: Callable[[], UIContent]) -> int:
        line_count = get_ui_content().line_count
        return len(str(line_count)) + 2 + len(self.separator)

    def create_margin(
        self, window_render_info: WindowRenderInfo, width: int, height: int
    ) -> StyleAndTextTuples:
        style_number = "class:line-number"
        style_current = "class:line-number.current"
        style_separator = "class:line-number.separator"

        current_lineno = window_render_info.ui_content.cursor_position.y
        result: StyleAndTextTuples = []
        last_lineno = None
        digits_width = width - len(self.separator) - 2

        for lineno in window_render_info.displayed_lines:
            if lineno != last_lineno and lineno is not None:
                num_style = style_current if lineno == current_lineno else style_number
                result.append((num_style, str(lineno + 1).rjust(digits_width)))
                result.append(("", " "))
                result.append((style_separator, self.separator))
                result.append(("", " "))
            last_lineno = lineno
            result.append(("", "\n"))

        return result


# ──────────────────────────────────────────────────────────────────────────────
# Programa principal
# ──────────────────────────────────────────────────────────────────────────────
def main():
    # ast.parse pode emitir SyntaxWarning (ex.: "\d" em string); no meio da TUI isso suja a tela.
    warnings.simplefilter("ignore", SyntaxWarning)

    if len(sys.argv) < 2:
        print("Uso: python JCode.py <arquivo>")
        return

    caminho = Path(sys.argv[1])
    if caminho.is_dir():
        print(f"Erro: '{caminho}' é um diretório.")
        return

    conteudo = ler_arquivo(caminho)
    texto = conteudo.texto
    extensao = caminho.suffix.lower()
    leitura_falhou = conteudo.erro is not None
    formato = {"encoding": conteudo.encoding, "fim_linha": conteudo.fim_linha, "bom": conteudo.bom}
    palavras_linguagem = set(PALAVRAS_POR_EXTENSAO.get(extensao, PALAVRAS_CHAVE_PYTHON))

    # ── Estado ────────────────────────────────────────────────────────────────
    analise = {"indice": sorted(palavras_linguagem), "erro": None, "desativada": False}
    inicial = analisar_documento(texto, extensao, palavras_linguagem, 0)
    analise.update(indice=inicial.indice, erro=inicial.erro_sintaxe, desativada=inicial.desativada)

    texto_salvo = [texto]
    salvamento = {
        "ok": not leitura_falhou,
        "erro": f"falha ao ler o arquivo ({conteudo.erro}) — salvar está bloqueado" if leitura_falhou else "",
    }
    assinatura_disco = [assinatura_arquivo(caminho)]
    confirmar = {"saida": False, "sobrescrita": False}
    mensagem = {"texto": "", "expira": 0.0}

    selecao_linha = {"ativa": False, "inicio": 0, "fim": 0}
    modo_explorar = {"ativo": False, "posicao": 0}
    modo_comando = {"ativo": False, "texto": "", "erro": ""}
    alteracao_bloco = [False]

    outline = {"visivel": False, "foco": False, "itens": [], "indice": 0}

    buffer = Buffer(
        complete_while_typing=True,
        completer=DynamicPythonCompleter(lambda: analise["indice"]),
    )
    buffer.text = texto

    def avisar(txt: str, duracao: float = 4.0) -> None:
        """Mensagem temporária na barra de status."""
        mensagem["texto"] = txt
        mensagem["expira"] = time.monotonic() + duracao
        try:
            asyncio.get_running_loop().call_later(duracao + 0.05, app.invalidate)
        except RuntimeError:
            pass

    # ── Condições ─────────────────────────────────────────────────────────────
    teclas = KeyBindings()
    cond_comando = Condition(lambda: modo_comando["ativo"])
    cond_outline_foco = Condition(lambda: outline["visivel"] and outline["foco"])
    cond_editor = Condition(lambda: not modo_comando["ativo"] and not cond_outline_foco())
    cond_atalho_global = Condition(lambda: not modo_comando["ativo"])
    cond_selecao = Condition(lambda: cond_editor() and selecao_linha["ativa"] and not modo_explorar["ativo"])
    cond_explorar = Condition(lambda: cond_editor() and modo_explorar["ativo"] and not selecao_linha["ativa"])
    cond_normal = Condition(lambda: cond_editor() and not selecao_linha["ativa"] and not modo_explorar["ativo"])
    cond_tem_selecao = Condition(lambda: buffer.selection_state is not None)
    cond_selecao_linha = Condition(lambda: selecao_linha["ativa"])

    def atalho(*keys, filter=None, eager=False):
        """Registra um atalho; qualquer exceção vira aviso na barra + log, nunca derruba o editor."""
        def decorador(funcao):
            @functools.wraps(funcao)
            def protegido(event):
                try:
                    return funcao(event)
                except Exception as exc:
                    registrar_erro(exc)
                    avisar(f"Erro interno: {type(exc).__name__}: {exc} (veja {caminho_log()})", 8.0)

            kwargs = {"eager": eager}
            if filter is not None:
                kwargs["filter"] = filter
            teclas.add(*keys, **kwargs)(protegido)
            return protegido
        return decorador

    # ── Utilidades de edição/navegação ────────────────────────────────────────
    def altura_janela(janela, padrao: int) -> int:
        try:
            info = janela.render_info
            if info is not None:
                return max(1, info.window_height)
        except Exception:
            pass
        return padrao

    def linhas_por_pagina() -> int:
        return max(1, altura_janela(editor, 12) - 1)

    def centralizar_linha(row: int) -> None:
        """Se a linha-alvo está fora da tela, rola para deixá-la no meio (mais contexto ao pular)."""
        try:
            altura = altura_janela(editor, 0)
            if altura <= 0:
                return
            topo = editor.vertical_scroll
            if row < topo or row >= topo + altura:
                editor.vertical_scroll = max(0, row - altura // 2)
        except Exception:
            pass

    def atualizar_selecao(buf):
        """Seleciona linhas inteiras; o cursor fica na ponta que o usuário está movendo."""
        doc = buf.document
        linhas = doc.lines
        total = len(linhas) - 1
        r_ini = max(0, min(selecao_linha["inicio"], total))
        r_fim = max(0, min(selecao_linha["fim"], total))
        if r_fim >= r_ini:
            ancora = doc.translate_row_col_to_index(r_ini, 0)
            ponta = doc.translate_row_col_to_index(r_fim, len(linhas[r_fim]))
        else:
            ancora = doc.translate_row_col_to_index(r_ini, len(linhas[r_ini]))
            ponta = doc.translate_row_col_to_index(r_fim, 0)
        buf.cursor_position = ancora
        buf.start_selection()
        buf.cursor_position = ponta

    def faixa_de_linhas(buf):
        """(primeira, última) linha cobertas pela seleção atual, ou None."""
        if selecao_linha["ativa"]:
            return tuple(sorted((selecao_linha["inicio"], selecao_linha["fim"])))
        estado = buf.selection_state
        if estado is None:
            return None
        a, b = sorted((estado.original_cursor_position, buf.cursor_position))
        doc = buf.document
        return doc.translate_index_to_position(a)[0], doc.translate_index_to_position(b)[0]

    def aplicar_indentacao(buf, remover: bool) -> None:
        faixa = faixa_de_linhas(buf)
        if faixa is None:
            return
        inicio, fim = faixa
        linhas = buf.text.split("\n")
        novas = indentar_bloco(linhas, inicio, fim, remover)
        if novas == linhas:
            return
        alteracao_bloco[0] = True
        try:
            buf.text = "\n".join(novas)
        finally:
            alteracao_bloco[0] = False
        selecao_linha.update(ativa=True, inicio=inicio, fim=fim)
        atualizar_selecao(buf)

    def recuar_linha_atual(buf) -> None:
        doc = buf.document
        col = doc.cursor_position_col
        linha = doc.current_line
        if linha.startswith("\t"):
            n = 1
        else:
            n = min(4, len(linha) - len(linha.lstrip(" ")))
        if n == 0:
            return
        inicio = buf.cursor_position - col
        buf.cursor_position = inicio
        buf.delete(count=n)
        buf.cursor_position = inicio + max(0, col - n)

    # ── Indentação / Tab ──────────────────────────────────────────────────────
    @atalho("tab", filter=cond_editor)
    def tab(event):
        buf = event.current_buffer
        if buf.selection_state is not None:
            aplicar_indentacao(buf, remover=False)
        elif buf.complete_state and buf.complete_state.current_completion:
            buf.apply_completion(buf.complete_state.current_completion)
        else:
            buf.insert_text(INDENT)

    @atalho("s-tab", filter=cond_editor)
    def shift_tab(event):
        buf = event.current_buffer
        if buf.selection_state is not None:
            aplicar_indentacao(buf, remover=True)
        else:
            recuar_linha_atual(buf)

    @atalho("c-d", filter=cond_editor & cond_selecao_linha)
    def dedent_bloco(event):
        aplicar_indentacao(event.current_buffer, remover=True)

    @atalho("escape", "backspace", filter=cond_normal, eager=True)
    def alt_backspace_seguro(event):
        buf = event.current_buffer
        doc = buf.document
        col = doc.cursor_position_col
        if col == 0:
            return
        prefixo = doc.current_line[:col]
        if prefixo.isspace():
            apagar = len(prefixo)
        else:
            m = re.search(r"\w+$", prefixo)
            apagar = len(m.group(0)) if m else 1
        buf.delete_before_cursor(count=apagar)

    @atalho("enter", filter=cond_normal | cond_selecao)
    def enter_editor(event):
        buf = event.current_buffer
        doc = buf.document
        if extensao == ".py":
            indent = calcular_indentacao_enter(doc.current_line, doc.cursor_position_col)
        else:
            indent = _indentacao_inicial(doc.current_line[:doc.cursor_position_col])
        buf.insert_text("\n" + indent)

    # ── Movimento ─────────────────────────────────────────────────────────────
    @atalho("right", filter=cond_normal | cond_explorar)
    def direita(event):
        buf = event.current_buffer
        buf.cursor_position = min(buf.cursor_position + 1, len(buf.text))

    @atalho("left", filter=cond_normal | cond_explorar)
    def esquerda(event):
        buf = event.current_buffer
        buf.cursor_position = max(0, buf.cursor_position - 1)

    @atalho("pageup", filter=cond_normal | cond_explorar)
    def pagina_cima(event):
        event.current_buffer.cursor_up(count=linhas_por_pagina())

    @atalho("pagedown", filter=cond_normal | cond_explorar)
    def pagina_baixo(event):
        event.current_buffer.cursor_down(count=linhas_por_pagina())

    # ── Arquivo: salvar / sair ────────────────────────────────────────────────
    @atalho("c-s", filter=cond_atalho_global)
    def salvar(event):
        if leitura_falhou:
            salvamento.update(ok=False, erro="leitura original falhou — salvamento bloqueado por segurança")
            return

        atual = assinatura_arquivo(caminho)
        if atual is not None and atual != assinatura_disco[0] and not confirmar["sobrescrita"]:
            confirmar["sobrescrita"] = True
            avisar("O arquivo mudou no disco! Ctrl+S de novo para sobrescrever.", 6.0)
            return

        texto_atual = buffer.text
        try:
            dados, usado = codificar_para_salvar(texto_atual, formato["encoding"], formato["fim_linha"], formato["bom"])
            gravar_arquivo(caminho, dados)
        except PermissionError:
            salvamento.update(ok=False, erro="sem permissão para salvar")
            return
        except OSError as e:
            salvamento.update(ok=False, erro=f"ERRO AO SALVAR: {e}")
            return

        if usado != formato["encoding"]:
            formato["encoding"] = usado
            avisar(f"Salvo em {usado.upper()}: o texto tem caracteres que o encoding original não comporta.", 6.0)
        texto_salvo[0] = texto_atual
        assinatura_disco[0] = assinatura_arquivo(caminho)
        confirmar["sobrescrita"] = False
        confirmar["saida"] = False
        salvamento.update(ok=True, erro="")

    @atalho("c-q", filter=cond_atalho_global)
    def sair(event):
        if buffer.text != texto_salvo[0] and not confirmar["saida"]:
            confirmar["saida"] = True
            avisar("Alterações não salvas! Ctrl+Q de novo para sair sem salvar.", 6.0)
            return
        event.app.exit()

    @atalho("c-z", filter=cond_atalho_global)
    def desfazer(event):
        buffer.undo()

    @atalho("c-y", filter=cond_atalho_global)
    @atalho("c-r", filter=cond_atalho_global)
    def refazer(event):
        buffer.redo()

    # ── Seleção / edição de linhas / clipboard ────────────────────────────────
    @atalho("c-a", filter=cond_editor)
    def selecionar_tudo(event):
        buf = event.current_buffer
        buf.cursor_position = 0
        buf.start_selection()
        buf.cursor_position = len(buf.text)

    @atalho("c-k", filter=cond_editor)
    def deletar_linha(event):
        buf = event.current_buffer
        if selecao_linha["ativa"]:
            ini, fim = faixa_de_linhas(buf)
            novas = remover_linhas(buf.text.split("\n"), ini, fim)
            alvo = min(ini, len(novas) - 1)
            selecao_linha["ativa"] = False
            buf.exit_selection()
            buf.text = "\n".join(novas)
            buf.cursor_position = buf.document.translate_row_col_to_index(alvo, 0)
            return
        doc = buf.document
        pos = buf.cursor_position
        inicio = pos + doc.get_start_of_line_position()
        fim = pos + doc.get_end_of_line_position()
        if fim < len(buf.text):
            fim += 1          # leva o \n junto
        elif inicio > 0:
            inicio -= 1       # última linha: leva o \n anterior, sem deixar linha vazia sobrando
        buf.cursor_position = inicio
        buf.delete(count=fim - inicio)

    @atalho("c-c", filter=cond_editor, eager=True)
    def copiar(event):
        buf = event.current_buffer
        if buf.selection_state:
            avisar("Clipboard: " + clipboard_escrever(buf.copy_selection().text))
            buf.exit_selection()
            selecao_linha["ativa"] = False

    def colar_texto(buf, texto_colar: str, backend: str) -> None:
        if not texto_colar:
            avisar("Clipboard vazio ou indisponível")
            return
        if selecao_linha["ativa"]:
            selecao_linha["ativa"] = False
            buf.exit_selection()
        buf.insert_text(texto_colar, fire_event=True)
        avisar("Colado: " + backend)

    @atalho("c-v", filter=cond_editor)
    def colar(event):
        texto_colar, backend = clipboard_ler()
        colar_texto(event.current_buffer, texto_colar, backend)

    @atalho(Keys.BracketedPaste, filter=cond_editor)
    def colar_do_terminal(event):
        # Colagem do próprio terminal (Ctrl+Shift+V): também passa pela sanitização.
        colar_texto(event.current_buffer, normalizar_colagem(event.data), "terminal")

    @atalho("c-l", filter=cond_normal)
    def iniciar_selecao_linha(event):
        row = event.current_buffer.document.cursor_position_row
        selecao_linha.update(ativa=True, inicio=row, fim=row)
        atualizar_selecao(event.current_buffer)

    @atalho("up", filter=cond_selecao)
    def selecao_cima(event):
        selecao_linha["fim"] = max(0, selecao_linha["fim"] - 1)
        atualizar_selecao(event.current_buffer)

    @atalho("down", filter=cond_selecao)
    def selecao_baixo(event):
        maxrow = len(event.current_buffer.document.lines) - 1
        selecao_linha["fim"] = min(maxrow, selecao_linha["fim"] + 1)
        atualizar_selecao(event.current_buffer)

    @atalho("escape", filter=cond_editor & cond_tem_selecao, eager=True)
    def cancelar_selecao(event):
        selecao_linha["ativa"] = False
        event.current_buffer.exit_selection()

    # ── Modo explorar (setas ignoram o menu de autocomplete) ─────────────────
    @atalho("c-e", filter=cond_normal | cond_explorar)
    def explorar(event):
        if modo_explorar["ativo"]:
            modo_explorar["ativo"] = False
        else:
            modo_explorar.update(ativo=True, posicao=event.current_buffer.cursor_position)

    @atalho("escape", filter=cond_explorar, eager=True)
    def sair_explorar(event):
        event.current_buffer.cursor_position = modo_explorar["posicao"]
        modo_explorar["ativo"] = False

    @atalho("enter", filter=cond_explorar)
    def confirmar_explorar(event):
        modo_explorar["ativo"] = False

    @atalho("up", filter=cond_explorar)
    def explorar_cima(event):
        event.current_buffer.cursor_up()

    @atalho("down", filter=cond_explorar)
    def explorar_baixo(event):
        event.current_buffer.cursor_down()

    # ── Modais: tudo que não é do modo ativo é engolido (nada vaza para o texto) ──
    nomes_basicos = ("left", "right", "up", "down", "home", "end", "delete", "insert",
                     "pageup", "pagedown", "tab", "s-tab")
    nomes_ctrl = tuple(f"c-{c}" for c in "abcdefghijklmnopqrstuvwxyz")
    globais_outline = {"c-s", "c-q", "c-z", "c-y", "c-r", "c-o"}

    for nome in nomes_basicos + nomes_ctrl:
        @atalho(nome, filter=cond_comando, eager=True)
        def _engolir_comando(event):
            pass

        if nome not in globais_outline:
            @atalho(nome, filter=cond_outline_foco, eager=True)
            def _engolir_outline(event):
                pass

    @atalho(Keys.BracketedPaste, filter=cond_comando | cond_outline_foco)
    def _engolir_colagem(event):
        pass

    @atalho(Keys.Any, filter=cond_outline_foco)
    def _engolir_texto_outline(event):
        pass

    # ── Ir para linha (Ctrl+G) ────────────────────────────────────────────────
    @atalho("c-g", filter=cond_normal)
    def abrir_ir_linha(event):
        modo_comando.update(ativo=True, texto="", erro="")

    @atalho("enter", filter=cond_comando, eager=True)
    def confirmar_comando(event):
        try:
            doc = buffer.document
            row, col = interpretar_ir_linha(modo_comando["texto"], doc.cursor_position_row + 1, len(doc.lines))
            buffer.cursor_position = doc.translate_row_col_to_index(row, col if col is not None else 0)
            modo_comando.update(ativo=False, erro="")
            centralizar_linha(row)
        except ValueError as e:
            modo_comando["erro"] = str(e)

    @atalho("escape", filter=cond_comando, eager=True)
    def cancelar_comando(event):
        modo_comando.update(ativo=False, texto="", erro="")

    @atalho("backspace", filter=cond_comando, eager=True)
    def apagar_comando(event):
        modo_comando["texto"] = modo_comando["texto"][:-1]

    @atalho("c-u", filter=cond_comando, eager=True)
    def limpar_comando(event):
        modo_comando["texto"] = ""

    @atalho(Keys.Any, filter=cond_comando)
    def digitar_comando(event):
        if event.data.isprintable() and len(modo_comando["texto"]) < 32:
            modo_comando["texto"] += event.data

    # ── Sumário (Ctrl+O) ──────────────────────────────────────────────────────
    def obter_texto_outline():
        itens = outline["itens"]
        if not itens:
            return [("class:outline.empty", " Nenhum bloco encontrado\n")]
        foco = " (Focado)" if outline["foco"] else ""
        resultado = [("class:outline.header", f" ── SUMÁRIO{foco} ──\n\n")]
        for idx, (_, profundidade, nome) in enumerate(itens):
            recuo = "  " * profundidade
            if idx == outline["indice"]:
                resultado.append(("class:outline.selected", f"> {recuo}{nome}\n"))
            else:
                resultado.append(("class:outline.item", f"  {recuo}{nome}\n"))
        return resultado

    def cursor_outline():
        # O Window rola sozinho para manter este ponto visível: é isso que faz
        # o sumário funcionar com qualquer quantidade de funções.
        if not outline["itens"]:
            return None
        return Point(0, outline["indice"] + 2)  # 2 = cabeçalho + linha em branco

    def fechar_outline():
        outline.update(visivel=False, foco=False)

    def mover_outline(delta=None, absoluto=None):
        itens = outline["itens"]
        if not itens:
            return
        alvo = absoluto if absoluto is not None else outline["indice"] + delta
        outline["indice"] = max(0, min(len(itens) - 1, alvo))

    @atalho("c-o", filter=cond_atalho_global)
    def alternar_outline(event):
        if outline["visivel"]:
            fechar_outline()
            return
        selecao_linha["ativa"] = False
        modo_explorar["ativo"] = False
        buffer.exit_selection()
        if extensao == ".py" and len(buffer.text) <= LIMITE_ANALISE_CHARS:
            outline["itens"] = extrair_outline(buffer.text)  # sempre fresco ao abrir
        outline["indice"] = indice_outline_para_linha(outline["itens"], buffer.document.cursor_position_row)
        outline.update(visivel=True, foco=True)

    @atalho("up", filter=cond_outline_foco, eager=True)
    def outline_cima(event):
        mover_outline(delta=-1)

    @atalho("down", filter=cond_outline_foco, eager=True)
    def outline_baixo(event):
        mover_outline(delta=1)

    @atalho("pageup", filter=cond_outline_foco, eager=True)
    def outline_pagina_cima(event):
        mover_outline(delta=-max(1, altura_janela(janela_outline, 12) - 3))

    @atalho("pagedown", filter=cond_outline_foco, eager=True)
    def outline_pagina_baixo(event):
        mover_outline(delta=max(1, altura_janela(janela_outline, 12) - 3))

    @atalho("home", filter=cond_outline_foco, eager=True)
    def outline_inicio(event):
        mover_outline(absoluto=0)

    @atalho("end", filter=cond_outline_foco, eager=True)
    def outline_fim(event):
        mover_outline(absoluto=max(0, len(outline["itens"]) - 1))

    @atalho("enter", filter=cond_outline_foco, eager=True)
    def outline_confirmar(event):
        if outline["itens"]:
            linha_alvo = outline["itens"][outline["indice"]][0]
            doc = buffer.document
            buffer.cursor_position = doc.translate_row_col_to_index(linha_alvo, 0)
            centralizar_linha(linha_alvo)
        fechar_outline()

    @atalho("escape", filter=cond_outline_foco, eager=True)
    def outline_fechar(event):
        fechar_outline()

    # ── Layout ────────────────────────────────────────────────────────────────
    try:
        lexer_inst = get_lexer_for_filename(caminho.name)
        lexer = LexerAdaptativo(lexer_inst.__class__)
    except (ClassNotFound, Exception):
        lexer = None

    controle = BufferControl(
        buffer=buffer,
        lexer=lexer,
        input_processors=[IndentGuideProcessor()],
    )

    editor = Window(
        content=controle,
        wrap_lines=False,
        left_margins=[CustomNumberedMargin(separator="│")],
    )

    janela_outline = Window(
        content=FormattedTextControl(
            text=obter_texto_outline,
            focusable=False,
            show_cursor=False,
            get_cursor_position=cursor_outline,
        ),
        width=35,
        style="class:outline",
    )

    def texto_status():
        modificado = buffer.text != texto_salvo[0]
        doc = buffer.document
        posicao = f"{doc.cursor_position_row + 1}:{doc.cursor_position_col + 1}"

        if modo_comando["ativo"]:
            modo = "[IR] " + modo_comando["texto"] + "_"
        elif modo_explorar["ativo"]:
            modo = "[EXP]"
        elif selecao_linha["ativa"]:
            modo = "[SEL]"
        else:
            modo = ""

        if modificado:
            estado_curto = "● MOD"
        elif salvamento["ok"]:
            estado_curto = "✓ SALVO"
        else:
            estado_curto = "! ERRO"

        base = f" {caminho.name}  │  {estado_curto}  │  {posicao}"
        if modo:
            base += f"  │  {modo}"
        detalhes_formato = []
        if formato["fim_linha"] != "\n":
            detalhes_formato.append({"\r\n": "CRLF", "\r": "CR"}.get(formato["fim_linha"], "?"))
        if formato["encoding"] != "utf-8":
            detalhes_formato.append(formato["encoding"])
        if detalhes_formato:
            base += "  │  " + " ".join(detalhes_formato)

        extras = []
        if not salvamento["ok"] and salvamento["erro"]:
            extras.append(salvamento["erro"])
        if modo_comando["ativo"] and modo_comando["erro"]:
            extras.append(modo_comando["erro"])
        if mensagem["texto"] and time.monotonic() < mensagem["expira"]:
            extras.append(mensagem["texto"])
        if analise["desativada"]:
            extras.append("análise desativada (arquivo grande)")
        extra = "".join("  ·  " + e for e in extras)

        erro = analise["erro"]
        if extensao == ".py" and erro is not None:
            linha_erro = erro[0] if erro[0] is not None else "?"
            return [("class:status.error", f"{base}  │  Sintaxe L{linha_erro}: {erro[1]}{extra}")]
        return [("class:status", base + extra)]

    status = Window(
        content=FormattedTextControl(text=texto_status),
        height=1,
        style="class:status",
    )

    corpo = VSplit([
        editor,
        ConditionalContainer(
            Window(width=1, char="│", style="class:line-number.separator"),
            filter=Condition(lambda: outline["visivel"]),
        ),
        ConditionalContainer(
            janela_outline,
            filter=Condition(lambda: outline["visivel"]),
        ),
    ])

    layout = HSplit([corpo, status], style="class:background")

    layout_completions = FloatContainer(
        content=layout,
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                content=CompletionsMenu(max_height=8, scroll_offset=1),
            )
        ],
    )

    estilo = Style.from_dict({
        "": "#ebdbb2 bg:#282828",
        "background": "bg:#282828",
        "header": "#ebdbb2 bold bg:#3c3836",
        "status": "#ebdbb2 bg:#3c3836",
        "status.error": "#fb4934 bold bg:#3c3836",
        "line-number": "#7c6f64",
        "line-number.current": "#fe8019 bold",
        "line-number.separator": "#504945",
        "indent-guide": "#504945",
        "pygments.keyword": "#fb4934",
        "pygments.string": "#b8bb26",
        "pygments.comment": "#928374",
        "pygments.number": "#d3869b",
        "pygments.name": "#a89984",
        "pygments.name.function": "#84B8B5",
        "pygments.name.namespace": "#84B8B5",
        "pygments.operator": "#fe8019",
        "pygments.decorator": "#d8a657",
        "pygments.name.decorator": "#d8a657",
        "outline": "bg:#1d2021",
        "outline.header": "#fe8019 bold",
        "outline.selected": "#fabd2f bold bg:#3c3836",
        "outline.item": "#ebdbb2",
        "outline.empty": "#928374",
        "completion-menu": "bg:#3c3836 #ebdbb2",
        "completion-menu.completion": "bg:#3c3836 #ebdbb2",
        "completion-menu.completion.current": "bg:#fe8019 #282828 bold",
        "completion-menu.meta.completion": "bg:#3c3836 #928374",
    })

    app = Application(
        layout=Layout(layout_completions, focused_element=editor),
        key_bindings=teclas,
        full_screen=True,
        style=estilo,
        mouse_support=MOUSE_ATIVO,
    )
    # Esc responde na hora em vez de esperar 0,5 s / 1 s por uma possível sequência Alt+tecla.
    app.ttimeoutlen = ESC_TIMEOUT
    app.timeoutlen = 0.3

    # ── Análise em segundo plano ──────────────────────────────────────────────
    # A digitação só faz trabalho O(1): marca a versão e agenda. Parse, índice de
    # autocomplete e sumário rodam numa única thread, depois de uma pausa, e só
    # o resultado da versão mais recente é aplicado.
    executor_analise = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jcode-analysis")
    timer_analise = [None]
    versao_documento = [0]
    estado_analise = {"em_andamento": False, "pendente": False}

    def aplicar_resultado(res: ResultadoAnalise) -> None:
        analise.update(indice=res.indice, erro=res.erro_sintaxe, desativada=res.desativada)
        if extensao == ".py":
            outline["itens"] = res.outline
            if outline["itens"]:
                outline["indice"] = max(0, min(outline["indice"], len(outline["itens"]) - 1))
            else:
                outline["indice"] = 0
        app.invalidate()

    def concluir_analise(futuro, versao: int) -> None:
        estado_analise["em_andamento"] = False
        resultado = None
        if not futuro.cancelled():
            try:
                resultado = futuro.result()
            except Exception:
                resultado = None
        if resultado is not None and versao == versao_documento[0]:
            aplicar_resultado(resultado)
        if estado_analise["pendente"] or versao != versao_documento[0]:
            estado_analise["pendente"] = False
            agendar_analise()

    def iniciar_analise(loop) -> None:
        timer_analise[0] = None
        if estado_analise["em_andamento"]:
            estado_analise["pendente"] = True  # nunca empilha análises
            return
        versao = versao_documento[0]
        try:
            futuro = executor_analise.submit(
                analisar_documento, buffer.text, extensao, palavras_linguagem, buffer.cursor_position
            )
        except RuntimeError:  # executor já encerrado
            return
        estado_analise["em_andamento"] = True

        def pronto(f):
            try:
                loop.call_soon_threadsafe(concluir_analise, f, versao)
            except RuntimeError:  # loop já fechado (editor saiu)
                pass

        futuro.add_done_callback(pronto)

    def agendar_analise() -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if timer_analise[0] is not None:
            timer_analise[0].cancel()
        atraso = min(ANALISE_DEBOUNCE_MAX, ANALISE_DEBOUNCE_BASE + len(buffer.text) / 600_000)
        timer_analise[0] = loop.call_later(atraso, iniciar_analise, loop)

    def limitar_undo() -> None:
        """Cada tecla empilha uma cópia do texto no undo; em arquivo grande isso come a RAM."""
        pilha = getattr(buffer, "_undo_stack", None)
        if not isinstance(pilha, list):
            return
        limite = max(100, min(5000, ORCAMENTO_UNDO_CHARS // (len(buffer.text) + 1)))
        if len(pilha) > limite + limite // 10:
            del pilha[: len(pilha) - limite]

    def texto_alterado(_):
        if selecao_linha["ativa"] and not alteracao_bloco[0]:
            selecao_linha["ativa"] = False
            buffer.exit_selection()
        confirmar["saida"] = False
        # Tem que ser barato: nada de AST/ast.walk/sumário aqui.
        versao_documento[0] += 1
        limitar_undo()
        agendar_analise()

    buffer.on_text_changed += texto_alterado

    tty = sys.stdout.isatty()
    try:
        if tty:
            sys.stdout.write("\033[1 q")
            sys.stdout.flush()
        app.run()
    except Exception as exc:
        # Última barreira: guarda o que estava no buffer antes de sair.
        registrar_erro(exc)
        try:
            copia = caminho.with_name(caminho.name + ".jcode-recover")
            copia.write_text(buffer.text, encoding="utf-8")
            print(f"JCode encontrou um erro inesperado ({type(exc).__name__}). "
                  f"Seu texto foi guardado em {copia}. Detalhes em {caminho_log()}.")
        except Exception:
            print(f"JCode encontrou um erro inesperado ({type(exc).__name__}). Detalhes em {caminho_log()}.")
    finally:
        if timer_analise[0] is not None:
            timer_analise[0].cancel()
        executor_analise.shutdown(wait=False, cancel_futures=True)
        if tty:
            sys.stdout.write("\033[6 q")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
