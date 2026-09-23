import sys
import ast
from pathlib import Path
from typing import Callable

import pyperclip
from prompt_toolkit.filters import Condition

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit, WindowRenderInfo
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, UIContent, FormattedTextControl
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from prompt_toolkit.styles import Style
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.formatted_text import StyleAndTextTuples


class IndentGuideProcessor(Processor):
    """Substitui a indentação por guias visuais verticais sutis."""

    def apply_transformation(self, transformation_input):
        line = transformation_input.fragments
        new_line: StyleAndTextTuples = []
        in_indentation = True

        for style, text in line:
            if in_indentation:
                new_text = []
                for char in text:
                    if char == " " and in_indentation:
                        new_text.append("┊")
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
    """Margem personalizada com números de linha e separador."""

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

        digits_width = max(1, width - len(self.separator) - 2)

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
        print("Uso: python main.py <arquivo>")
        return

    caminho = Path(sys.argv[1])
    
    texto = ""
    if caminho.exists():
        for enc in ["utf-8", "cp1252", "latin-1"]:
            try:
                texto = caminho.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, PermissionError):
                continue

    buffer = Buffer()
    buffer.text = texto

    texto_salvo = [texto]
    estado_salvamento = ["SALVO"]

    outline_visivel = [False]
    outline_itens = []
    outline_index = [0]

    # Condições isoladas para evitar duplicação de teclas
    is_outline_open = Condition(lambda: outline_visivel[0])
    is_outline_closed = Condition(lambda: not outline_visivel[0])

    def atualizar_outline():
        outline_itens.clear()

        if caminho.suffix != ".py":
            return

        try:
            arvore = ast.parse(buffer.text)

            for no in ast.walk(arvore):
                if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    outline_itens.append(
                        (no.lineno - 1, f"λ  {no.name}")
                    )
                elif isinstance(no, ast.ClassDef):
                    outline_itens.append(
                        (no.lineno - 1, f"◈  {no.name}")
                    )

            outline_itens.sort(key=lambda item: item[0])

            if outline_itens:
                outline_index[0] = min(
                    outline_index[0],
                    len(outline_itens) - 1
                )
            else:
                outline_index[0] = 0

        except Exception:
            # Captura com segurança qualquer erro de parsing sem quebrar a UI
            outline_itens.clear()

    def obter_texto_outline():
        if not outline_itens:
            return [("class:outline.empty", "\n  (Nenhum bloco)")]
        
        resultado = [
            ("class:outline.header", "\n  OUTLINE\n"),
            ("class:outline.border", " ───────────────\n")
        ]
        for idx, (lineno, nome) in enumerate(outline_itens):
            if idx == outline_index[0]:
                resultado.append(("class:outline.selected", f" ▶ {nome}\n"))
            else:
                resultado.append(("class:outline.item", f"   {nome}\n"))
        return resultado

    teclas = KeyBindings()

    @teclas.add("tab")
    def indentacao(event):
        buf = event.current_buffer

        if not buf.selection_state:
            buf.insert_text("    ")
            return

        inicio, fim = buf.document.selection_range()
        texto = buf.text

        # Começo da primeira linha selecionada
        inicio_linha = texto.rfind("\n", 0, inicio) + 1

        # Descobre a última linha selecionada
        fim_linha = texto.find("\n", fim)

        if fim_linha == -1:
            fim_linha = len(texto)

        bloco = texto[inicio_linha:fim_linha]

        # Adiciona 4 espaços em cada linha
        bloco_indentado = "\n".join(
            "    " + linha
            for linha in bloco.split("\n")
        )

        buf.cursor_position = inicio_linha
        buf.delete(count=fim_linha - inicio_linha)
        buf.insert_text(bloco_indentado)

        # Mantém a seleção cobrindo o bloco inteiro
        novo_fim = inicio_linha + len(bloco_indentado)
        buf.cursor_position = inicio_linha
        buf.start_selection()
        buf.cursor_position = novo_fim

    @teclas.add("c-a")
    def selecionar_tudo(event):
        buf = event.current_buffer
        buf.cursor_position = 0
        buf.start_selection()
        buf.cursor_position = len(buf.text)

    @teclas.add("c-k")
    def deletar_linha(event):
        buf = event.current_buffer

        if buf.selection_state:
            inicio, fim = buf.document.selection_range()
            buf.cursor_position = inicio
            buf.delete(count=fim - inicio)
            return

        inicio = buf.document.get_start_of_line_position()
        fim = buf.document.get_end_of_line_position()

        buf.cursor_position += inicio
        quantidade = fim - inicio

        if quantidade > 0:
            buf.delete(count=quantidade)

        if buf.cursor_position < len(buf.text):
            buf.delete(count=1)

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

    @teclas.add("c-o")
    def toggle_outline(event):
        outline_visivel[0] = not outline_visivel[0]
        if outline_visivel[0]:
            atualizar_outline()

    # Teclas de navegação do Outline com filtro exclusivo
    @teclas.add("up", filter=is_outline_open)
    def outline_cima(event):
        if outline_itens:
            outline_index[0] = max(0, outline_index[0] - 1)

    @teclas.add("down", filter=is_outline_open)
    def outline_baixo(event):
        if outline_itens:
            outline_index[0] = min(len(outline_itens) - 1, outline_index[0] + 1)

    @teclas.add("enter", filter=is_outline_open)
    def outline_confirmar(event):
        if outline_itens and 0 <= outline_index[0] < len(outline_itens):
            linha_alvo, _ = outline_itens[outline_index[0]]
            buffer.cursor_position = buffer.document.translate_row_col_to_index(linha_alvo, 0)
        outline_visivel[0] = False

    @teclas.add("escape", filter=is_outline_open)
    def outline_fechar(event):
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
        cursorline=True,
        left_margins=[CustomNumberedMargin(separator="│")]
    )

    janela_outline = Window(
        content=FormattedTextControl(text=obter_texto_outline),
        width=30,
        style="class:outline"
    )

    def validar_sintaxe():
        modificado = buffer.text != texto_salvo[0]

        if modificado:
            estado_texto = "MODIFICADO"
            estado_estilo = "class:status.modified"
        else:
            estado_texto = estado_salvamento[0]
            if estado_texto.startswith("ERRO"):
                estado_estilo = "class:status.error"
            else:
                estado_estilo = "class:status.saved"

        linha_cursor = buffer.document.cursor_position_row + 1
        coluna_cursor = buffer.document.cursor_position_col + 1
        tamanho_bytes = len(buffer.text.encode("utf-8"))

        if tamanho_bytes < 1024:
            tamanho = f"{tamanho_bytes} B"
        else:
            tamanho = f"{tamanho_bytes / 1024:.1f} KB"

        if caminho.suffix == ".py":
            try:
                ast.parse(buffer.text)
            except SyntaxError as e:
                linha = e.lineno if e.lineno is not None else "?"
                coluna = e.offset if e.offset is not None else "?"
                return [
                    ("class:status.text", f"  {caminho.name}  "),
                    ("class:status.separator", "│"),
                    (estado_estilo, f"  {estado_texto}  "),
                    ("class:status.separator", "│"),
                    ("class:status.error", f"  Erro Ln {linha}, Col {coluna}: {e.msg}")
                ]
            except Exception:
                pass

        return [
            (estado_estilo, f"  {estado_texto}  "),
            ("class:status.separator", "│"),
            ("class:status.text", f"  Ln {linha_cursor}, Col {coluna_cursor}  "),
            ("class:status.separator", "│"),
            ("class:status.hint", f"  {tamanho}  ")
        ]

    status = Window(
        content=FormattedTextControl(text=validar_sintaxe),
        height=1,
        style="class:status"
    )

    cabecalho = Window(
        content=FormattedTextControl(
            text=lambda: [
                ("class:header.icon", " 🐍 "),
                ("class:header.title", " JCODE "),
                ("class:header.sep", " › "),
                ("class:header.filename", f"{caminho.name}"),
            ]
        ),
        height=1,
        style="class:header"
    )

    corpo = VSplit([
        editor,
        ConditionalContainer(
            Window(width=1, char="│", style="class:line-number.separator"),
            filter=is_outline_open
        ),
        ConditionalContainer(
            janela_outline,
            filter=is_outline_open
        )
    ])

    layout = HSplit(
        [cabecalho, corpo, status],
        style="class:background"
    )

    estilo = Style.from_dict({
        "": "#ebdbb2 bg:#282828",
        "background": "bg:#282828",
        
        # Cabeçalho
        "header": "bg:#3c3836",
        "header.icon": "#fe8019 bold bg:#3c3836",
        "header.title": "#fbf1c7 bold bg:#3c3836",
        "header.sep": "#928374 bg:#3c3836",
        "header.filename": "#8ec07c bg:#3c3836",

        # Barra de Status
        "status": "#ebdbb2 bg:#3c3836",
        "status.text": "#ebdbb2 bg:#3c3836",
        "status.saved": "#b8bb26 bold bg:#3c3836",
        "status.modified": "#fabd2f bold bg:#3c3836",
        "status.error": "#fb4934 bold bg:#3c3836",
        "status.hint": "#a89984 bg:#3c3836",
        "status.separator": "#665c54 bg:#3c3836",

        # Editor
        "cursor-line": "bg:#32302f",
        "line-number": "#7c6f64",
        "line-number.current": "#fe8019 bold",
        "line-number.separator": "#3c3836",
        "indent-guide": "#3c3836",

        # Pygments (Sintaxe)
        "pygments.keyword": "#fb4934 bold",
        "pygments.string": "#b8bb26",
        "pygments.comment": "#928374 italic",
        "pygments.number": "#d3869b",
        "pygments.name": "#ebdbb2",
        "pygments.name.function": "#8ec07c bold",
        "pygments.name.class": "#fabd2f bold",
        "pygments.name.namespace": "#8ec07c",
        "pygments.operator": "#fe8019",
        "pygments.decorator": "#d3869b",

        # Outline / Sidebar
        "outline": "bg:#1d2021",
        "outline.header": "#fe8019 bold",
        "outline.border": "#3c3836",
        "outline.selected": "#fabd2f bold bg:#3c3836",
        "outline.item": "#ebdbb2",
        "outline.empty": "#928374 italic",
    })

    app = Application(
        layout=Layout(layout),
        key_bindings=teclas,
        full_screen=True,
        style=estilo,
        mouse_support=True,
    )

    def texto_alterado(_):
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