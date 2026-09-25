import sys
import ast
from pathlib import Path
from typing import Callable

import pyperclip
from prompt_toolkit.filters import Condition

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit, WindowRenderInfo
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, UIContent, FormattedTextControl
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import FormattedTextToolbar
from prompt_toolkit.lexers import PygmentsLexer

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

from prompt_toolkit.styles import Style
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.formatted_text import StyleAndTextTuples


class PythonCompleter(Completer):
    """Autocomplete simples para Python baseado no AST do arquivo."""

    def __init__(self, buffer: Buffer):
        self.buffer = buffer

    def _coletar_nomes(self, arvore):
        nomes = set()

        # Palavras-chave e builtins mais comuns.
        nomes.update({
            "and", "as", "assert", "async", "await", "break", "case",
            "class", "continue", "def", "del", "elif", "else", "except",
            "False", "finally", "for", "from", "global", "if", "import",
            "in", "is", "lambda", "match", "None", "nonlocal", "not",
            "or", "pass", "raise", "return", "True", "try", "while",
            "with", "yield",
        })

        nomes.update({
            "abs", "all", "any", "bool", "dict", "dir", "enumerate",
            "filter", "float", "input", "int", "isinstance", "len",
            "list", "map", "max", "min", "open", "print", "range",
            "repr", "reversed", "round", "set", "sorted", "str", "sum",
            "super", "tuple", "type", "zip",
        })

        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nomes.add(no.name)

                if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for argumento in no.args.posonlyargs + no.args.args + no.args.kwonlyargs:
                        nomes.add(argumento.arg)
                    if no.args.vararg:
                        nomes.add(no.args.vararg.arg)
                    if no.args.kwarg:
                        nomes.add(no.args.kwarg.arg)

            elif isinstance(no, ast.Import):
                for alias in no.names:
                    nomes.add(alias.asname or alias.name.split(".")[0])

            elif isinstance(no, ast.ImportFrom):
                for alias in no.names:
                    if alias.name != "*":
                        nomes.add(alias.asname or alias.name)

            elif isinstance(no, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
                for alvo in alvos:
                    for nome in self._nomes_do_alvo(alvo):
                        nomes.add(nome)

            elif isinstance(no, (ast.For, ast.AsyncFor)):
                for nome in self._nomes_do_alvo(no.target):
                    nomes.add(nome)

            elif isinstance(no, (ast.With, ast.AsyncWith)):
                for item in no.items:
                    if item.optional_vars:
                        nomes.update(self._nomes_do_alvo(item.optional_vars))

            elif isinstance(no, ast.ExceptHandler) and no.name:
                nomes.add(no.name)

        return nomes

    def _nomes_do_alvo(self, alvo):
        if isinstance(alvo, ast.Name):
            return {alvo.id}

        if isinstance(alvo, (ast.Tuple, ast.List)):
            nomes = set()
            for elemento in alvo.elts:
                nomes.update(self._nomes_do_alvo(elemento))
            return nomes

        return set()

    def get_completions(self, document, complete_event):
        prefixo = document.get_word_before_cursor(WORD=True)

        if not prefixo:
            return

        try:
            arvore = ast.parse(self.buffer.text)
            nomes = self._coletar_nomes(arvore)
        except SyntaxError:
            # Enquanto o usuário está digitando, o arquivo pode estar inválido.
            # Ainda oferecemos keywords/builtins básicos.
            nomes = {
                "def", "class", "if", "elif", "else", "for", "while",
                "try", "except", "finally", "with", "import", "from",
                "return", "True", "False", "None", "print", "len",
                "range", "str", "int", "list", "dict", "set", "open",
            }

        for nome in sorted(nomes):
            if nome.startswith(prefixo) and nome != prefixo:
                yield Completion(
                    nome,
                    start_position=-len(prefixo),
                    display=nome,
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

    # Autocomplete Python baseado no AST.
    if caminho.suffix == ".py":
        buffer.completer = PythonCompleter(buffer)

    # Buffer temporário usado pelo comando Ctrl+G
    buffer_goto = Buffer()

    texto_salvo = [texto]
    estado_salvamento = ["SALVO"]

    # Estado do menu lateral (Outline)
    outline_visivel = [False]
    outline_itens = []      # Lista de tuplas (número_linha, texto_item)
    outline_index = [0]     # Índice do item selecionado no menu

    def atualizar_outline():
        """Analisa o arquivo Python e monta o Outline usando AST."""
        outline_itens.clear()

        if caminho.suffix != ".py":
            return

        try:
            arvore = ast.parse(buffer.text)

            for no in ast.walk(arvore):
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

        except SyntaxError:
            # Se o código estiver temporariamente inválido,
            # o Outline simplesmente fica vazio.
            return

    def obter_texto_outline():
        """Gera o texto formatado para a barra lateral do Outline."""
        if not outline_itens:
            return [("class:outline.empty", " Nenhum bloco encontrado\n")]
        
        resultado = [("class:outline.header", " ── SUMÁRIO ──\n\n")]
        for idx, (lineno, nome) in enumerate(outline_itens):
            if idx == outline_index[0]:
                resultado.append(("class:outline.selected", f"> {nome}\n"))
            else:
                resultado.append(("class:outline.item", f"  {nome}\n"))
        return resultado

    # Estado do prompt "Ir para linha"
    goto_visivel = [False]

    def executar_goto():
        try:
            linha = int(buffer_goto.text.strip())
        except ValueError:
            return

        if linha < 1 or linha > len(buffer.document.lines):
            return

        buffer.cursor_position = buffer.document.translate_row_col_to_index(
            linha - 1,
            0
        )
        goto_visivel[0] = False
        buffer_goto.reset()
        app.layout.focus(buffer)
        app.invalidate()

    teclas = KeyBindings()

    @teclas.add("tab")
    def tab(event):
        buffer_atual = event.current_buffer

        # Se o autocomplete estiver aberto, Tab aceita a próxima sugestão.
        if buffer_atual.complete_state:
            buffer_atual.complete_next()
        else:
            # Caso contrário, Tab continua funcionando como indentação.
            buffer_atual.insert_text("    ")

    @teclas.add("c-space")
    def autocomplete(event):
        # Abre o autocomplete manualmente.
        event.current_buffer.start_completion(select_first=False)

    @teclas.add("c-s")
    def salvar(event):
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
        buf.cursor_position += buf.document.get_start_of_line_position()
        buf.delete(count=len(buf.document.current_line))

    @teclas.add("c-c", eager=True)
    def copiar(event):
        buf = event.current_buffer

        if buf.selection_state:
            texto = buf.copy_selection().text
            pyperclip.copy(texto)
            buf.exit_selection()

    @teclas.add("c-v")
    def colar(event):
        texto_colar = pyperclip.paste()
        if texto_colar:
            event.current_buffer.insert_text(texto_colar)

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
        if outline_visivel[0]:
            atualizar_outline()

    # Ir diretamente para uma linha com Ctrl+G
    @teclas.add("c-g")
    def abrir_goto(event):
        goto_visivel[0] = True
        buffer_goto.reset()
        app.layout.focus(buffer_goto)
        app.invalidate()

    @teclas.add("enter", filter=Condition(lambda: goto_visivel[0]))
    def goto_confirmar(event):
        executar_goto()

    @teclas.add("escape", filter=Condition(lambda: goto_visivel[0]))
    def goto_cancelar(event):
        goto_visivel[0] = False
        buffer_goto.reset()
        app.layout.focus(buffer)
        app.invalidate()

    # Navegação dentro do menu Outline com as Setas para Cima/Baixo e Enter
    @teclas.add("up", filter=Condition(lambda: outline_visivel[0]))
    def outline_cima(event):
        if outline_itens:
            outline_index[0] = max(0, outline_index[0] - 1)

    @teclas.add("down", filter=Condition(lambda: outline_visivel[0]))
    def outline_baixo(event):
        if outline_itens:
            outline_index[0] = min(len(outline_itens) - 1, outline_index[0] + 1)

    @teclas.add("enter", filter=Condition(lambda: outline_visivel[0]))
    def outline_confirmar(event):
        if outline_itens:
            linha_alvo, _ = outline_itens[outline_index[0]]
            buffer.cursor_position = buffer.document.translate_row_col_to_index(linha_alvo, 0)
        outline_visivel[0] = False

    @teclas.add("escape", filter=Condition(lambda: outline_visivel[0]))
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
        left_margins=[CustomNumberedMargin(separator="│")]
    )

    # Painel do Sumário
    janela_outline = Window(
        content=FormattedTextControl(text=obter_texto_outline),
        width=35,
        style="class:outline"
    )

    # Função para checar a sintaxe em tempo real
    def validar_sintaxe():
        modificado = buffer.text != texto_salvo[0]

        if modificado:
            estado = "MODIFICADO"
        else:
            estado = estado_salvamento[0]

        linha_atual = buffer.document.cursor_position_row + 1
        coluna_atual = buffer.document.cursor_position_col + 1

        posicao = f"Ln {linha_atual}, Col {coluna_atual}"

        if caminho.suffix == ".py":
            try:
                ast.parse(buffer.text)
            except SyntaxError as e:
                linha = e.lineno if e.lineno is not None else "?"
                coluna = e.offset if e.offset is not None else "?"

                return [
                    (
                        "class:status.error",
                        f"  {caminho.name}  |  {estado}  |  {posicao}  |  "
                        f"Erro na linha {linha}, coluna {coluna}: {e.msg}"
                    )
                ]

        return [
            (
                "class:status",
                f"  {caminho.name}  |  {estado}  |  {posicao}  |  "
                f"Ctrl+S: salvar  |  Ctrl+O: sumário"
            )
        ]
    # Substitua a variável status antiga por esta:

    status = Window(
        content=FormattedTextControl(text=validar_sintaxe),
        height=1,
        style="class:status"
    )

    cabecalho = Window(
        content=FormattedTextControl(
            text=lambda: [
                ("class:header", f" JCODE  │  {caminho.name}")
            ]
        ),
        height=1, style="class:header"
    )

    # Exibe o separador e a barra lateral do sumário apenas quando ativados com Ctrl+O
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

    janela_goto = ConditionalContainer(
        Window(
            content=BufferControl(buffer=buffer_goto),
            height=1,
            style="class:goto"
        ),
        filter=Condition(lambda: goto_visivel[0])
    )

    layout = HSplit(
        [corpo, janela_goto, status],
        style="class:background"
    )

    estilo = Style.from_dict({
        "": "#ebdbb2 bg:#282828",
        "background": "bg:#282828",
        "header": "#ebdbb2 bold bg:#3c3836",
        "status": "#ebdbb2 bg:#3c3836",
        "status.error": "#fb4934 bold bg:#3c3836",
        "goto": "#ebdbb2 bg:#3c3836",
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

    def cursor_movido(_):
        app.invalidate()

    buffer.on_cursor_position_changed += cursor_movido

    try:
        sys.stdout.write("\033[2 q")
        sys.stdout.flush()
        app.run()
    finally:
        sys.stdout.write("\033[6 q")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
