import sys
import ast
import re
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

PALAVRAS_CHAVE_PYTHON = [
    "def", "class", "import", "from", "return", "if", "elif", "else",
    "for", "while", "try", "except", "finally", "with", "as", "pass",
    "break", "continue", "lambda", "yield", "async", "await", "print",
    "len", "range", "str", "int", "float", "list", "dict", "set", "tuple", "bool"
]

def extrair_identificadores(texto: str, arvore) -> Set[str]:
    """Extrai palavras-chave, variáveis, funções e classes a partir de um AST já pronto
    (ou, se o parse falhou, apenas por regex). Não faz parsing por conta própria — quem
    chama é responsável por fornecer a árvore (ou None) já calculada uma única vez."""
    identificadores: Set[str] = set(PALAVRAS_CHAVE_PYTHON)

    # 1. Extração por AST (Nomes de variáveis, funções, argumentos e classes)
    if arvore is not None:
        for no in ast.walk(arvore):
            if isinstance(no, ast.Name):
                identificadores.add(no.id)
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identificadores.add(no.name)
            elif isinstance(no, ast.arg):
                identificadores.add(no.arg)

    # 2. Extração por Regex (fallback para código com erros de sintaxe durante a digitação)
    tokens = re.findall(r"\b[a-zA-Z_]\w*\b", texto)
    identificadores.update(tokens)

    return identificadores


class DynamicPythonCompleter(Completer):
    """Completer personalizado que sugere a partir de um conjunto de identificadores
    já calculado (ver `extrair_identificadores`), evitando reparsear o buffer a cada tecla."""

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

    # Cache de análise: um único ast.parse() por mudança de texto, compartilhado entre
    # o completer, o outline e a validação de sintaxe da status bar (antes eram 3 parses
    # independentes a cada tecla digitada).
    analise = {
        "arvore": None,
        "erro_sintaxe": None,
        "identificadores": set(PALAVRAS_CHAVE_PYTHON),
    }

    def atualizar_analise():
        texto_atual = buffer.text
        try:
            analise["arvore"] = ast.parse(texto_atual)
            analise["erro_sintaxe"] = None
        except SyntaxError as e:
            analise["arvore"] = None
            analise["erro_sintaxe"] = e
        except Exception:
            analise["arvore"] = None
            analise["erro_sintaxe"] = None

        analise["identificadores"] = extrair_identificadores(texto_atual, analise["arvore"])

    # Configuração do Autocomplete Dinâmico
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

    # Estado do menu lateral (Outline)
    outline_visivel = [False]
    outline_foco = [False]
    outline_itens: List[Tuple[int, str]] = []
    outline_index = [0]

    def atualizar_outline():
        """Monta o Outline a partir da árvore AST já calculada em `atualizar_analise`."""
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
        """Gera o texto formatado para a barra lateral do Outline."""
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

    @teclas.add("tab")
    def tab(event):
        buf = event.current_buffer

        if buf.complete_state:
            completion = buf.complete_state.current_completion

            if completion:
                buf.apply_completion(completion)
                return

        buf.insert_text("    ")

    @teclas.add("right")
    def aceitar_sugestao_seta(event):
        """Aceita a sugestão ao pressionar a seta para a direita se o cursor estiver no fim da linha."""
        buf = event.current_buffer
        if buf.document.is_cursor_at_the_end_of_line and buf.suggestion:
            buf.insert_text(buf.suggestion.text)
        else:
            buf.cursor_position += 1

    @teclas.add("c-s")
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
    
    @teclas.add("c-a")
    def selecionar_tudo(event):
        buf = event.current_buffer
        buf.cursor_position = 0
        buf.start_selection()
        buf.cursor_position = len(buf.text)

    @teclas.add("c-k")
    def deletar_linha(event):
        buf = event.current_buffer
        doc = buf.document
        pos_original = buf.cursor_position
        line_start = doc.get_start_of_line_position()
        line_end = doc.get_end_of_line_position()
        fim_absoluto = pos_original + line_end

        buf.cursor_position += line_start
        length = (line_end - line_start) + (1 if fim_absoluto < len(buf.text) else 0)
        buf.delete(count=length)

    @teclas.add("c-c")
    def copiar(event):
        buf = event.current_buffer
        if buf.selection_state:
            try:
                pyperclip.copy(buf.copy_selection().text)
            except Exception:
                pass

    @teclas.add("c-v")
    def colar(event):
        try:
            texto_colar = pyperclip.paste()
            if texto_colar:
                event.current_buffer.insert_text(texto_colar)
        except Exception:
            pass

    @teclas.add("c-z")
    def desfazer(event):
        event.current_buffer.undo()

    @teclas.add("c-y")
    @teclas.add("c-r")
    def refazer(event):
        event.current_buffer.redo()

    @teclas.add("c-q")
    def sair(event):
        event.app.exit()

    # Atalho para abrir/fechar o Painel Sumário (Outline)
    @teclas.add("c-o")
    def toggle_outline(event):
        outline_visivel[0] = not outline_visivel[0]
        outline_foco[0] = outline_visivel[0]
        if outline_visivel[0]:
            atualizar_outline()

    # Condição restrita ao foco do Sumário
    cond_outline_foco = Condition(lambda: outline_visivel[0] and outline_foco[0])

    @teclas.add("up", filter=cond_outline_foco)
    def outline_cima(event):
        if outline_itens:
            outline_index[0] = max(0, outline_index[0] - 1)

    @teclas.add("down", filter=cond_outline_foco)
    def outline_baixo(event):
        if outline_itens:
            outline_index[0] = min(len(outline_itens) - 1, outline_index[0] + 1)

    @teclas.add("enter", filter=cond_outline_foco)
    def outline_confirmar(event):
        if outline_itens:
            linha_alvo, _ = outline_itens[outline_index[0]]
            buffer.cursor_position = buffer.document.translate_row_col_to_index(linha_alvo, 0)
        # Fecha e desafoca o sumário
        outline_foco[0] = False
        outline_visivel[0] = False

    @teclas.add("escape", filter=cond_outline_foco)
    def outline_fechar(event):
        # Fecha e desafoca o sumário
        outline_foco[0] = False
        outline_visivel[0] = False

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

        if caminho.suffix == ".py" and analise["erro_sintaxe"] is not None:
            e = analise["erro_sintaxe"]
            linha = e.lineno if e.lineno is not None else "?"
            coluna = e.offset if e.offset is not None else "?"
            return [
                (
                    "class:status.error",
                    f"  {caminho.name}  |  {estado}  |  Erro na linha {linha}, coluna {coluna}: {e.msg}"
                )
            ]

        return [
            (
                "class:status",
                f"  {estado}  |  Ctrl+S: salvar  |  Ctrl+O: sumário"
            )
        ]

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

    # Menu de autocomplete flutuante, no estilo de editor
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
    
    def texto_alterado(_):
        atualizar_analise()
        if outline_visivel[0]:
            atualizar_outline()
        app.invalidate()

    buffer.on_text_changed += texto_alterado

    try:
        sys.stdout.write("\033[2 q")
        sys.stdout.flush()
        app.run()
    finally:
        sys.stdout.write("\033[6 q")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
