import sys
import ast
import re
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import Callable, List, Tuple, Set

import pyperclip
from prompt_toolkit.filters import Condition
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit, WindowRenderInfo
from prompt_toolkit.layout.containers import ConditionalContainer, FloatContainer, Float
from prompt_toolkit.layout.controls import BufferControl, UIContent, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from prompt_toolkit.styles import Style
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.formatted_text import StyleAndTextTuples

from prompt_toolkit.keys import Keys


def calcular_indentacao_enter(linha: str, coluna: int) -> str:
    """Retorna a indentação anterior ao cursor, limitada à indentação da linha."""
    indent = len(linha) - len(linha.lstrip(" "))
    prefixo = linha[:max(0, min(coluna, len(linha)))]
    antes = min(len(prefixo) - len(prefixo.lstrip(" ")), indent)
    base = " " * antes
    if coluna >= len(linha) and linha.rstrip().endswith(":"):
        base += "    "
    return base


def interpretar_ir_linha(comando: str, linha_atual: int, total_linhas: int):
    """Retorna (linha, coluna_1based_ou_None), ou levanta ValueError."""
    comando = comando.strip()
    if not comando:
        raise ValueError("Digite uma linha.")
    if ":" in comando:
        partes = comando.split(":")
        if len(partes) != 2 or not all(x.isdigit() for x in partes):
            raise ValueError("Use linha:coluna, por exemplo 42:8.")
        linha, coluna = map(int, partes)
        if not 1 <= linha <= total_linhas or coluna < 1:
            raise ValueError("Linha ou coluna fora do intervalo.")
        return linha - 1, coluna - 1
    if comando[0] in "+-":
        if not comando[1:].isdigit():
            raise ValueError("Deslocamento inválido.")
        linha = linha_atual + int(comando)
    elif comando.isdigit():
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
            n = len(resultado[i]) - len(resultado[i].lstrip(" "))
            resultado[i] = resultado[i][min(4, n):]
        else:
            resultado[i] = "    " + resultado[i]
    return resultado


PALAVRAS_CHAVE_PYTHON = [
    "def", "class", "import", "from", "return", "if", "elif", "else",
    "for", "while", "try", "except", "finally", "with", "as", "pass",
    "break", "continue", "lambda", "yield", "async", "await", "print",
    "len", "range", "str", "int", "float", "list", "dict", "set", "tuple", "bool"
]


def extrair_identificadores(texto: str, arvore) -> Set[str]:
    """Extrai palavras-chave, variáveis, funções e classes a partir de um AST já pronto."""
    identificadores: Set[str] = set(PALAVRAS_CHAVE_PYTHON)

    if arvore is not None:
        for no in ast.walk(arvore):
            if isinstance(no, ast.Name):
                identificadores.add(no.id)
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identificadores.add(no.name)
            elif isinstance(no, ast.arg):
                identificadores.add(no.arg)

    tokens = re.findall(r"\b[a-zA-Z_]\w*\b", texto)
    identificadores.update(tokens)

    return identificadores


class DynamicPythonCompleter(Completer):
    """Completer personalizado que sugere a partir de um conjunto de identificadores precalculado."""

    def __init__(self, get_identificadores_func: Callable[[], Set[str]]) -> None:
        self.get_identificadores_func = get_identificadores_func

    def get_completions(self, document, complete_event):
        word_before_cursor = document.get_word_before_cursor()
        if not word_before_cursor:
            return

        palavras = self.get_identificadores_func()
        for palavra in sorted(palavras):
            if palavra.startswith(word_before_cursor) and palavra != word_before_cursor:
                yield Completion(
                    palavra,
                    start_position=-len(word_before_cursor)
                )


class IndentGuideProcessor(Processor):
    """Substitui os espaços de indentação no início das linhas por guias visuais."""

    def apply_transformation(self, transformation_input):
        line = transformation_input.fragments
        new_line: StyleAndTextTuples = []
        in_indentation = True

        for style, text in line:
            if in_indentation:
                new_text = []
                for char in text:
                    if char == " " and in_indentation:
                        new_text.append("·")
                    else:
                        in_indentation = False
                        new_text.append(char)
                
                transformed_text = "".join(new_text)
                if transformed_text != text:
                    new_line.append(("class:indent-guide", transformed_text))
                else:
                    new_line.append((style, text))
            else:
                new_line.append((style, text))

        return Transformation(new_line)


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

        for y, lineno in enumerate(window_render_info.displayed_lines):
            if lineno != last_lineno:
                if lineno is not None:
                    num_style = style_current if lineno == current_lineno else style_number
                    num_str = str(lineno + 1).rjust(digits_width)

                    result.append((num_style, num_str))
                    result.append(("", " "))
                    result.append((style_separator, self.separator))
                    result.append(("", " "))

            last_lineno = lineno
            result.append(("", "\n"))

        return result


def sanitizar_texto_clipboard(texto: str) -> str:
    """Remove caracteres nulos e sequências de controle ANSI que causam crash em navegadores."""
    texto = texto.replace("\0", "")
    texto = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', texto)
    return texto


def main():
    if len(sys.argv) < 2:
        print("Uso: python JCode.py <arquivo>")
        return

    caminho = Path(sys.argv[1])
    
    texto = ""
    erro_leitura = False
    if caminho.exists() and caminho.is_file():
        lido_com_sucesso = False
        for enc in ["utf-8", "cp1252", "latin-1"]:
            try:
                texto = caminho.read_text(encoding=enc)
                lido_com_sucesso = True
                break
            except (UnicodeDecodeError, PermissionError):
                continue
        if not lido_com_sucesso:
            erro_leitura = True
    elif caminho.is_dir():
        print(f"Erro: '{caminho}' é um diretório.")
        return

    LINGUAGENS = {
        ".py": set(PALAVRAS_CHAVE_PYTHON),
        ".c": set("auto break case char const continue default do double else enum extern float for goto if int long register return short signed sizeof static struct switch typedef union unsigned void volatile while printf scanf NULL size_t".split()),
        ".h": set("char const define elif else endif error if ifdef ifndef include line pragma undef auto break case enum extern float for goto int long register return short signed sizeof static struct typedef union unsigned void volatile while NULL size_t".split()),
    }
    extensao = caminho.suffix.lower()
    palavras_linguagem = LINGUAGENS.get(extensao, set(PALAVRAS_CHAVE_PYTHON))
    analise = {"arvore": None, "erro_sintaxe": None, "identificadores": set(palavras_linguagem)}

    def atualizar_analise():
        texto_atual = buffer.text
        try:
            if extensao != ".py":
                analise["arvore"] = None
                analise["erro_sintaxe"] = None
            else:
                analise["arvore"] = ast.parse(texto_atual)
            analise["erro_sintaxe"] = None
        except SyntaxError as e:
            analise["arvore"] = None
            analise["erro_sintaxe"] = e
        except Exception:
            analise["arvore"] = None
            analise["erro_sintaxe"] = None

        if extensao == ".py":
            analise["identificadores"] = extrair_identificadores(texto_atual, analise["arvore"])
        else:
            analise["identificadores"] = set(palavras_linguagem) | set(re.findall(r"\b[a-zA-Z_]\w*\b", texto_atual))

    buffer = Buffer(complete_while_typing=True, auto_suggest=AutoSuggestFromHistory())
    completer_dinamico = DynamicPythonCompleter(
        get_identificadores_func=lambda: analise["identificadores"]
    )
    buffer.completer = completer_dinamico
    buffer.text = texto
    atualizar_analise()

    texto_salvo = [texto]
    estado_salvamento = ["ERRO: falha ao ler o arquivo — salvar está bloqueado" if erro_leitura else "SALVO"]
    leitura_falhou = [erro_leitura]

    selecao_linha = {"ativa": False, "inicio": 0, "fim": 0}
    modo_explorar = {"ativo": False, "posicao": 0}
    modo_comando = {"ativo": False, "texto": "", "erro": ""}
    clipboard_interno = [""]
    mensagem_status = [""]
    alteracao_bloco = [False]

    outline_visivel = [False]
    outline_foco = [False]
    outline_itens: List[Tuple[int, str]] = []
    outline_index = [0]

    def atualizar_outline():
        outline_itens.clear()

        if caminho.suffix != ".py" or analise["arvore"] is None:
            return

        for no in ast.walk(analise["arvore"]):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                outline_itens.append(
                    (no.lineno - 1, f"def {no.name}")
                )
            elif isinstance(no, ast.ClassDef):
                outline_itens.append(
                    (no.lineno - 1, f"class {no.name}")
                )

        outline_itens.sort(key=lambda item: item[0])

        if outline_itens:
            outline_index[0] = min(
                outline_index[0],
                len(outline_itens) - 1
            )

    def obter_texto_outline():
        if not outline_itens:
            return [("class:outline.empty", " Nenhum bloco encontrado\n")]
        
        status_foco = " (Focado)" if outline_foco[0] else ""
        resultado = [("class:outline.header", f" ── SUMÁRIO{status_foco} ──\n\n")]
        for idx, (lineno, nome) in enumerate(outline_itens):
            if idx == outline_index[0]:
                resultado.append(("class:outline.selected", f"> {nome}\n"))
            else:
                resultado.append(("class:outline.item", f"  {nome}\n"))
        return resultado

    teclas = KeyBindings()
    cond_outline_foco = Condition(lambda: outline_visivel[0] and outline_foco[0])
    cond_comando = Condition(lambda: modo_comando["ativo"])
    cond_editor = Condition(lambda: not modo_comando["ativo"] and not cond_outline_foco())
    cond_atalho_global = Condition(lambda: not modo_comando["ativo"])
    cond_selecao = Condition(lambda: cond_editor() and selecao_linha["ativa"] and not modo_explorar["ativo"])
    cond_explorar = Condition(lambda: cond_editor() and modo_explorar["ativo"] and not selecao_linha["ativa"])
    cond_normal = Condition(lambda: cond_editor() and not selecao_linha["ativa"] and not modo_explorar["ativo"])

    def atualizar_selecao(buf):
        total = len(buf.document.lines) - 1
        r1 = max(0, min(selecao_linha["inicio"], total))
        r2 = max(0, min(selecao_linha["fim"], total))
        baixo, cima = sorted((r1, r2))
        a = buf.document.translate_row_col_to_index(baixo, 0)
        b = buf.document.translate_row_col_to_index(cima, len(buf.document.lines[cima]))
        buf.cursor_position = a
        buf.start_selection()
        buf.cursor_position = b

    def aceitar_selecao(buf):
        if selecao_linha["ativa"]:
            atualizar_selecao(buf)

    def transformar_linhas_selecionadas(buf, remover=False):
        """Indenta as linhas cobertas por qualquer seleção, sem substituir o buffer inteiro."""
        doc = buf.document
        estado = buf.selection_state
        if estado is None:
            return False
        a, b = sorted((estado.original_cursor_position, buf.cursor_position))
        inicio = doc.translate_index_to_position(a).row
        fim = doc.translate_index_to_position(b).row
        linhas = buf.text.split("\n")
        novas = indentar_bloco(linhas, inicio, fim, remover)
        novo_texto = "\n".join(novas)
        delta_inicio = 0 if remover else 4
        # Aplicar como uma única edição mantém undo e evita saltos de cursor.
        buf.cursor_position = 0
        buf.delete(count=len(buf.text))
        buf.insert_text(novo_texto, fire_event=True)
        novo_a = doc.translate_row_col_to_index(inicio, 0) if False else sum(len(x) + 1 for x in novas[:inicio])
        novo_b = novo_a + len(novas[inicio])
        buf.cursor_position = novo_a
        buf.start_selection()
        buf.cursor_position = novo_b
        return True

    @teclas.add("tab", filter=Condition(lambda: cond_editor() and (selecao_linha["ativa"] or True)))
    def tab_bloco(event):
        buf = event.current_buffer
        if selecao_linha["ativa"]:
            linhas = indentar_bloco(buf.text.split("\n"), selecao_linha["inicio"], selecao_linha["fim"])
            alteracao_bloco[0] = True
            try:
                buf.text = "\n".join(linhas)
            finally:
                alteracao_bloco[0] = False
            aceitar_selecao(buf)
        elif buf.selection_state:
            transformar_linhas_selecionadas(buf)

    @teclas.add("c-d", filter=Condition(lambda: cond_editor() and selecao_linha["ativa"]))
    @teclas.add("s-tab", filter=Condition(lambda: cond_editor() and selecao_linha["ativa"]))
    def dedent_bloco(event):
        buf = event.current_buffer
        if selecao_linha["ativa"]:
            linhas = indentar_bloco(buf.text.split("\n"), selecao_linha["inicio"], selecao_linha["fim"], True)
            alteracao_bloco[0] = True
            try:
                buf.text = "\n".join(linhas)
            finally:
                alteracao_bloco[0] = False
            aceitar_selecao(buf)
        elif buf.selection_state:
            transformar_linhas_selecionadas(buf, remover=True)

    @teclas.add("escape", "backspace", filter=cond_normal, eager=True)
    def alt_backspace_seguro(event):
        buf = event.current_buffer
        doc = buf.document
        col = doc.cursor_position_col
        linha = doc.current_line
        inicio_linha = doc.cursor_position - col
        if col == 0:
            return
        prefixo = linha[:col]
        if prefixo.isspace():
            apagar = len(prefixo)
        else:
            m = re.search(r"[\w]+$", prefixo)
            apagar = len(m.group(0)) if m else 1
        buf.cursor_position = inicio_linha + col
        buf.delete_before_cursor(count=apagar)

    @teclas.add("tab", filter=cond_normal)
    def tab(event):
        buf = event.current_buffer
        if buf.complete_state and buf.complete_state.current_completion:
            buf.apply_completion(buf.complete_state.current_completion)
        else:
            buf.insert_text("    ")

    @teclas.add("enter", filter=cond_normal)
    def enter_editor(event):
        buf = event.current_buffer
        doc = buf.document
        indent = calcular_indentacao_enter(doc.current_line, doc.cursor_position_col) if extensao == ".py" else " " * min(len(doc.current_line) - len(doc.current_line.lstrip(" ")), doc.cursor_position_col)
        buf.insert_text("\n" + indent)

    @teclas.add("right", filter=Condition(lambda: cond_normal() or cond_explorar()))
    def aceitar_sugestao_seta(event):
        buf = event.current_buffer
        if cond_normal() and doc_sugestao(buf):
            buf.insert_text(buf.suggestion.text)
        else:
            buf.cursor_position = min(buf.cursor_position + 1, len(buf.text))

    def doc_sugestao(buf):
        return buf.document.is_cursor_at_the_end_of_line and bool(buf.suggestion)

    @teclas.add("left", filter=Condition(lambda: cond_normal() or cond_explorar()))
    def esquerda(event):
        buf = event.current_buffer
        if buf.document.cursor_position_col == 0 and buf.document.cursor_position_row > 0:
            buf.cursor_position = buf.document.translate_row_col_to_index(buf.document.cursor_position_row - 1, len(buf.document.lines[buf.document.cursor_position_row - 1]))
        else:
            buf.cursor_position = max(0, buf.cursor_position - 1)

    @teclas.add("c-s", filter=cond_atalho_global)
    def salvar(event):
        if leitura_falhou[0]:
            estado_salvamento[0] = "ERRO: leitura original falhou — salvamento bloqueado por segurança"
            return
        try:
            caminho.write_text(buffer.text, encoding="utf-8")
            texto_salvo[0] = buffer.text
            estado_salvamento[0] = "SALVO"
        except PermissionError:
            estado_salvamento[0] = "ERRO: sem permissão para salvar"
        except OSError as e:
            estado_salvamento[0] = f"ERRO AO SALVAR: {e}"

    @teclas.add("c-a", filter=cond_editor)
    def selecionar_tudo(event):
        buf = event.current_buffer
        buf.cursor_position = 0
        buf.start_selection()
        buf.cursor_position = len(buf.text)

    @teclas.add("c-k", filter=cond_editor)
    def deletar_linha(event):
        buf = event.current_buffer
        doc = buf.document
        pos_original = buf.cursor_position
        line_start = doc.get_start_of_line_position()
        line_end = doc.get_end_of_line_position()
        fim_absoluto = pos_original + line_end
        buf.cursor_position += line_start
        buf.delete(count=(line_end - line_start) + (1 if fim_absoluto < len(buf.text) else 0))

    def clipboard_escrever(texto):
        texto = sanitizar_texto_clipboard(texto)
        erros = []

        # 1. Suporte Wayland (previne crash no Firefox/GTK3)
        if shutil.which("wl-copy"):
            try:
                subprocess.run(["wl-copy"], input=texto, text=True, timeout=2, check=True)
                return "wl-clipboard (Wayland)"
            except Exception as e:
                erros.append(type(e).__name__)

        # 2. Suporte Termux
        exe_termux = shutil.which("termux-clipboard-set")
        if exe_termux:
            try:
                subprocess.run([exe_termux], input=texto, text=True, timeout=2, check=True)
                return "Termux"
            except Exception as e:
                erros.append(type(e).__name__)

        # 3. Suporte xclip (X11 com seleção explicita)
        if shutil.which("xclip"):
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=texto, text=True, timeout=2, check=True)
                return "xclip"
            except Exception as e:
                erros.append(type(e).__name__)

        # 4. Fallback Pyperclip
        try:
            pyperclip.copy(texto)
            return "pyperclip"
        except Exception as e:
            erros.append(type(e).__name__)

        clipboard_interno[0] = texto
        return "memória" + (" (externo indisponível)" if erros else "")

    def clipboard_ler():
        # 1. Wayland
        if shutil.which("wl-paste"):
            try:
                r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2, check=True)
                if r.stdout:
                    return sanitizar_texto_clipboard(r.stdout), "wl-clipboard"
            except Exception:
                pass

        # 2. Termux
        exe_termux = shutil.which("termux-clipboard-get")
        if exe_termux:
            try:
                r = subprocess.run([exe_termux], capture_output=True, text=True, timeout=2, check=True)
                if r.stdout:
                    return sanitizar_texto_clipboard(r.stdout), "Termux"
            except Exception:
                pass

        # 3. Pyperclip
        try:
            valor = pyperclip.paste()
            if valor:
                return sanitizar_texto_clipboard(valor), "pyperclip"
        except Exception:
            pass

        return clipboard_interno[0], "memória" if clipboard_interno[0] else "vazio/indisponível"

    @teclas.add("c-c", filter=cond_editor, eager=True)
    def copiar(event):
        buf = event.current_buffer
        if buf.selection_state:
            mensagem_status[0] = "Clipboard: " + clipboard_escrever(buf.copy_selection().text)
            buf.exit_selection()
            selecao_linha["ativa"] = False

    @teclas.add("c-v", filter=cond_editor)
    def colar(event):
        texto_colar, backend = clipboard_ler()
        if texto_colar:
            if selecao_linha["ativa"]:
                selecao_linha["ativa"] = False
                event.current_buffer.exit_selection()
            event.current_buffer.insert_text(texto_colar, fire_event=True)
            mensagem_status[0] = "Colado: " + backend
        else:
            mensagem_status[0] = "Clipboard vazio ou indisponível"

    @teclas.add("c-z", filter=cond_atalho_global)
    def desfazer(event): event.current_buffer.undo()
    @teclas.add("c-y", filter=cond_atalho_global)
    @teclas.add("c-r", filter=cond_atalho_global)
    def refazer(event): event.current_buffer.redo()
    @teclas.add("c-q", filter=cond_atalho_global)
    def sair(event): event.app.exit()

    @teclas.add("c-o", filter=Condition(lambda: not modo_comando["ativo"]))
    def toggle_outline(event):
        outline_visivel[0] = not outline_visivel[0]
        outline_foco[0] = outline_visivel[0]
        if outline_visivel[0]:
            selecao_linha["ativa"] = False; modo_explorar["ativo"] = False
            atualizar_outline()

    @teclas.add("up", filter=cond_outline_foco)
    def outline_cima(event):
        if outline_itens: outline_index[0] = max(0, outline_index[0] - 1)
    @teclas.add("down", filter=cond_outline_foco)
    def outline_baixo(event):
        if outline_itens: outline_index[0] = min(len(outline_itens) - 1, outline_index[0] + 1)
    @teclas.add("enter", filter=cond_outline_foco)
    def outline_confirmar(event):
        if outline_itens:
            linha_alvo, _ = outline_itens[outline_index[0]]
            buffer.cursor_position = buffer.document.translate_row_col_to_index(linha_alvo, 0)
        outline_foco[0] = False; outline_visivel[0] = False
    @teclas.add("escape", filter=cond_outline_foco)
    def outline_fechar(event):
        outline_foco[0] = False; outline_visivel[0] = False

    @teclas.add("c-l", filter=cond_normal)
    def iniciar_selecao_linha(event):
        row = event.current_buffer.document.cursor_position_row
        selecao_linha.update(ativa=True, inicio=row, fim=row)
        atualizar_selecao(event.current_buffer)

    @teclas.add("up", filter=cond_selecao)
    def selecao_cima(event):
        selecao_linha["fim"] = max(0, selecao_linha["fim"] - 1)
        atualizar_selecao(event.current_buffer)
    @teclas.add("down", filter=cond_selecao)
    def selecao_baixo(event):
        maxrow = len(event.current_buffer.document.lines) - 1
        selecao_linha["fim"] = min(maxrow, selecao_linha["fim"] + 1)
        atualizar_selecao(event.current_buffer)
    @teclas.add("escape", filter=cond_selecao)
    def cancelar_selecao(event):
        selecao_linha["ativa"] = False
        event.current_buffer.exit_selection()

    @teclas.add("c-g", filter=cond_normal)
    def abrir_ir_linha(event):
        modo_comando.update(ativo=True, texto="", erro="")

    @teclas.add("escape", filter=cond_explorar)
    def sair_explorar(event):
        event.current_buffer.cursor_position = modo_explorar["posicao"]
        modo_explorar["ativo"] = False
    @teclas.add("enter", filter=cond_explorar)
    def confirmar_explorar(event): modo_explorar["ativo"] = False
    @teclas.add("c-e", filter=Condition(lambda: cond_normal() or cond_explorar()))
    def explorar(event):
        if modo_explorar["ativo"]:
            modo_explorar["ativo"] = False
        else:
            modo_explorar.update(ativo=True, posicao=event.current_buffer.cursor_position)

    @teclas.add("up", filter=Condition(lambda: cond_explorar()))
    def explorar_cima(event): event.current_buffer.cursor_up()
    @teclas.add("down", filter=Condition(lambda: cond_explorar()))
    def explorar_baixo(event): event.current_buffer.cursor_down()
    @teclas.add("pageup", filter=Condition(lambda: cond_normal() or cond_explorar()))
    def pagina_cima(event): event.current_buffer.cursor_up(count=10)
    @teclas.add("pagedown", filter=Condition(lambda: cond_normal() or cond_explorar()))
    def pagina_baixo(event): event.current_buffer.cursor_down(count=10)

    @teclas.add("enter", filter=cond_comando)
    def confirmar_comando(event):
        try:
            row, col = interpretar_ir_linha(modo_comando["texto"], buffer.document.cursor_position_row + 1, len(buffer.document.lines))
            buffer.cursor_position = buffer.document.translate_row_col_to_index(row, col if col is not None else 0)
            modo_comando.update(ativo=False, erro="")
        except ValueError as e:
            modo_comando["erro"] = str(e)
    @teclas.add("escape", filter=cond_comando)
    def cancelar_comando(event): modo_comando.update(ativo=False, texto="", erro="")
    @teclas.add("backspace", filter=cond_comando)
    def apagar_comando(event): modo_comando["texto"] = modo_comando["texto"][:-1]
    @teclas.add("c-u", filter=cond_comando)
    def limpar_comando(event): modo_comando["texto"] = ""
    for tecla_bloqueada in ("left", "right", "up", "down", "delete", "home", "end", "c-k"):
        @teclas.add(tecla_bloqueada, filter=cond_comando, eager=True)
        def bloquear_tecla_comando(event):
            pass

    @teclas.add(Keys.Any, filter=cond_comando)
    def digitar_comando(event):
        if event.data.isprintable():
            modo_comando["texto"] += event.data

    try:
        lexer_inst = get_lexer_for_filename(caminho.name)
        lexer = PygmentsLexer(lexer_inst.__class__)
    except ClassNotFound:
        lexer = None

    controle = BufferControl(
        buffer=buffer,
        lexer=lexer,
        input_processors=[IndentGuideProcessor()]
    )

    editor = Window(
        content=controle,
        wrap_lines=False,
        left_margins=[CustomNumberedMargin(separator="│")]
    )

    janela_outline = Window(
        content=FormattedTextControl(text=obter_texto_outline),
        width=35,
        style="class:outline"
    )

    def validar_sintaxe():
        modificado = buffer.text != texto_salvo[0]

        if modificado:
            estado = "MODIFICADO"
        else:
            estado = estado_salvamento[0]

        doc = buffer.document
        posicao = f"{doc.cursor_position_row + 1}:{doc.cursor_position_col + 1}"
        modo = "[IR] " + modo_comando["texto"] + "_" if modo_comando["ativo"] else ("[EXP]" if modo_explorar["ativo"] else ("[SEL]" if selecao_linha["ativa"] else ""))
        estado_curto = "● MOD" if modificado else ("✓ SALVO" if estado == "SALVO" else "! ERRO")
        base = f" {caminho.name}  │  {estado_curto}  │  {posicao}"
        if modo:
            base += f"  │  {modo}"
        extra = ("  ·  " + mensagem_status[0]) if mensagem_status[0] else ""
        if caminho.suffix == ".py" and analise["erro_sintaxe"] is not None:
            e = analise["erro_sintaxe"]
            linha = e.lineno if e.lineno is not None else "?"
            return [("class:status.error", f"{base}  │  Sintaxe L{linha}: {e.msg}{extra}")]
        if modo_comando["ativo"] and modo_comando["erro"]:
            extra += "  ·  " + modo_comando["erro"]
        return [("class:status", base + extra)]

    status = Window(
        content=FormattedTextControl(text=validar_sintaxe),
        height=1,
        style="class:status"
    )

    corpo = VSplit([
        editor,
        ConditionalContainer(
            Window(width=1, char="│", style="class:line-number.separator"),
            filter=Condition(lambda: outline_visivel[0])
        ),
        ConditionalContainer(
            janela_outline,
            filter=Condition(lambda: outline_visivel[0])
        )
    ])

    layout = HSplit(
        [corpo, status],
        style="class:background"
    )

    layout_completions = FloatContainer(
        content=layout,
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                content=CompletionsMenu(
                    max_height=8,
                    scroll_offset=1,
                ),
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
        layout=Layout(layout_completions),
        key_bindings=teclas,
        full_screen=True,
        style=estilo,
        mouse_support=True,
    )

    timer_analise = [None]

    def texto_alterado(_):
        if selecao_linha["ativa"] and not alteracao_bloco[0]:
            selecao_linha["ativa"] = False
            buffer.exit_selection()

        lines_count = buffer.document.line_count
        
        # Debounce: se o arquivo tiver mais de 250 linhas, atrasa a analise sintatica pesada
        if lines_count > 250:
            if timer_analise[0] is not None:
                timer_analise[0].cancel()
            
            loop = asyncio.get_event_loop()
            
            def reprocessar():
                atualizar_analise()
                if outline_visivel[0]:
                    atualizar_outline()
                app.invalidate()

            timer_analise[0] = loop.call_later(0.3, reprocessar)
        else:
            atualizar_analise()
            if outline_visivel[0]:
                atualizar_outline()

        app.invalidate()

    buffer.on_text_changed += texto_alterado

    try:
        sys.stdout.write("\033[1 q")
        sys.stdout.flush()
        app.run()
    finally:
        sys.stdout.write("\033[6 q")
        sys.stdout.flush()

if __name__ == "__main__":
    main()