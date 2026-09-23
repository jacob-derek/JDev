from pathlib import Path
import subprocess
import sys

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition


# ============================================================
# ESTADO
# ============================================================

diretorio_atual = Path.cwd().resolve()

itens = []
indice_selecionado = 0
inicio_janela = 0

JCODE = Path(__file__).resolve().parent / "JCode.py"
arquivo_para_abrir = None

# Menu
menu_visivel = False

menu_itens = [
    "Novo Arquivo",
    "Nova Pasta",
    "Deletar Selecionado",
]

menu_index = 0


# Input
modo_input = False
prompt_titulo = ""
input_texto = ""

# Guarda qual operação está sendo executada
acao_input = None

# Mensagem temporária exibida no rodapé
mensagem_status = ""


# ============================================================
# UTILIDADES
# ============================================================

def definir_status(mensagem):
    global mensagem_status
    mensagem_status = mensagem


def formatar_tamanho(tamanho_bytes):
    for unidade in ["B", "KB", "MB", "GB"]:
        if tamanho_bytes < 1024.0:
            return f"{tamanho_bytes:.1f} {unidade}"

        tamanho_bytes /= 1024.0

    return f"{tamanho_bytes:.1f} TB"


def corrigir_indice():
    global indice_selecionado

    if not itens:
        indice_selecionado = 0
        return

    indice_selecionado = min(
        indice_selecionado,
        len(itens) - 1
    )


def item_selecionado():
    corrigir_indice()

    if not itens:
        return None

    return itens[indice_selecionado]


# ============================================================
# SISTEMA DE ARQUIVOS
# ============================================================

def obter_itens():
    try:
        if not diretorio_atual.exists():
            definir_status(
                "O diretório atual não existe mais."
            )
            return []

        conteudo = list(diretorio_atual.iterdir())

        pastas = sorted(
            [
                item
                for item in conteudo
                if item.is_dir()
            ],
            key=lambda item: item.name.lower()
        )

        arquivos = sorted(
            [
                item
                for item in conteudo
                if item.is_file()
            ],
            key=lambda item: item.name.lower()
        )

        return pastas + arquivos

    except PermissionError:
        definir_status(
            "Sem permissão para acessar este diretório."
        )
        return []

    except OSError as erro:
        definir_status(
            f"Erro ao acessar diretório: {erro}"
        )
        return []


def atualizar_lista():
    global itens
    global inicio_janela

    itens = obter_itens()

    corrigir_indice()

    if not itens:
        inicio_janela = 0


# ============================================================
# CRIAÇÃO
# ============================================================

def criar_arquivo(nome):
    nome = nome.strip()

    if not nome:
        definir_status(
            "O nome do arquivo não pode estar vazio."
        )
        return

    destino = diretorio_atual / nome

    try:
        destino.touch(exist_ok=False)

        definir_status(
            f"✓ Arquivo criado: {nome}"
        )

        atualizar_lista()

    except FileExistsError:
        definir_status(
            f"Já existe um item chamado '{nome}'."
        )

    except PermissionError:
        definir_status(
            "Sem permissão para criar o arquivo."
        )

    except OSError as erro:
        definir_status(
            f"Erro ao criar arquivo: {erro}"
        )


def criar_pasta(nome):
    nome = nome.strip()

    if not nome:
        definir_status(
            "O nome da pasta não pode estar vazio."
        )
        return

    destino = diretorio_atual / nome

    try:
        destino.mkdir()

        definir_status(
            f"✓ Pasta criada: {nome}"
        )

        atualizar_lista()

    except FileExistsError:
        definir_status(
            f"Já existe um item chamado '{nome}'."
        )

    except PermissionError:
        definir_status(
            "Sem permissão para criar a pasta."
        )

    except OSError as erro:
        definir_status(
            f"Erro ao criar pasta: {erro}"
        )


# ============================================================
# REMOÇÃO
# ============================================================

def remover_item():
    item = item_selecionado()

    if item is None:
        definir_status(
            "Nenhum item selecionado."
        )
        return

    nome = item.name

    try:
        if item.is_dir():

            # IMPORTANTE:
            # Não removemos pastas recursivamente.
            #
            # rmdir() só funciona se a pasta estiver vazia.
            item.rmdir()

        else:
            item.unlink()

        definir_status(
            f"✓ Removido: {nome}"
        )

        atualizar_lista()

    except OSError as erro:

        if item.is_dir():
            definir_status(
                f"Não foi possível remover '{nome}'. "
                f"A pasta pode não estar vazia."
            )
        else:
            definir_status(
                f"Não foi possível remover '{nome}': {erro}"
            )

        atualizar_lista()


# ============================================================
# INTERFACE
# ============================================================

def gerar_cabecalho():
    return [
        (
            "class:header",
            " 📂 NAVEGADOR DE ARQUIVOS "
        ),
        (
            "class:path",
            f" \n{diretorio_atual}"
        ),
    ]

def gerar_corpo():
    global inicio_janela

    linhas = []

    if not itens:
        linhas.append(
            (
                "class:empty",
                "  (diretório vazio ou sem permissão de leitura)\n"
            )
        )

        return linhas

    altura_maxima_itens = 15

    try:
        tamanho_tela = app.renderer.output.get_size()

        altura_maxima_itens = max(
            3,
            tamanho_tela.rows - 6
        )

    except Exception:
        pass

    # Mantém o item selecionado dentro da área visível
    if indice_selecionado < inicio_janela:

        inicio_janela = indice_selecionado

    elif (
        indice_selecionado
        >= inicio_janela + altura_maxima_itens
    ):

        inicio_janela = (
            indice_selecionado
            - altura_maxima_itens
            + 1
        )

    itens_visiveis = itens[
        inicio_janela:
        inicio_janela + altura_maxima_itens
    ]

    for i, item in enumerate(itens_visiveis):

        indice_real = inicio_janela + i

        try:
            eh_pasta = item.is_dir()
        except OSError:
            eh_pasta = False

        icone = "📁" if eh_pasta else "📄"

        if not eh_pasta:

            try:
                tamanho = formatar_tamanho(
                    item.stat().st_size
                )

                detalhes = f" [{tamanho}]"

            except OSError:
                detalhes = " [erro]"

        else:
            detalhes = "/"

        nome_formatado = (
            f" {icone}  "
            f"{item.name}"
            f"{detalhes}\n"
        )

        if indice_real == indice_selecionado:

            linhas.append(
                (
                    "class:selected",
                    f" ➔ {nome_formatado}"
                )
            )

        else:

            linhas.append(
                (
                    "class:item",
                    f"   {nome_formatado}"
                )
            )

    return linhas


def obter_texto_menu():

    resultado = [
        (
            "class:outline.header",
            " ── AÇÕES ──\n\n"
        ),

        (
            "class:outline.help",
            " ↑/↓ escolher\n"
            " ENTER confirmar\n"
            " ESC fechar\n\n"
        ),
    ]

    for idx, nome in enumerate(menu_itens):

        if idx == menu_index:

            resultado.append(
                (
                    "class:outline.selected",
                    f" ➜ {nome}\n"
                )
            )

        else:

            resultado.append(
                (
                    "class:outline.item",
                    f"   {nome}\n"
                )
            )

    return resultado


def gerar_rodape():
    linhas = []

    if modo_input:
        linhas.append(
            (
                "class:prompt",
                f" {prompt_titulo}: "
                f"{input_texto}_"
                f"  (ENTER confirmar │ ESC cancelar)"
            )
        )
    else:
        linhas.append(
            (
                "class:footer",
                " ↑/↓ Navegar │ ENTER Abrir │ "
                "BACKSPACE Voltar │ CTRL+O Opções │ "
                "CTRL+Q Sair"
            )
        )

    if mensagem_status:
        linhas.append(
            (
                "class:status",
                f" {mensagem_status}"
            )
        )

    return linhas

# ============================================================
# KEYBINDINGS
# ============================================================

teclas = KeyBindings()

# ------------------------------------------------------------
# FILTROS
# ------------------------------------------------------------

menu_ativo = Condition(
    lambda: menu_visivel and not modo_input
)

navegacao_ativa = Condition(
    lambda: not menu_visivel and not modo_input
)

input_ativo = Condition(
    lambda: modo_input
)


# ============================================================
# NAVEGAÇÃO
# ============================================================

@teclas.add("up", filter=navegacao_ativa)
def mover_cima(event):

    global indice_selecionado

    if itens:

        indice_selecionado = max(
            0,
            indice_selecionado - 1
        )

        event.app.invalidate()


@teclas.add("down", filter=navegacao_ativa)
def mover_baixo(event):

    global indice_selecionado

    if itens:

        indice_selecionado = min(
            len(itens) - 1,
            indice_selecionado + 1
        )

        event.app.invalidate()

@teclas.add("enter", filter=navegacao_ativa)
def entrar(event):
    global diretorio_atual, indice_selecionado
    global arquivo_para_abrir, mensagem_status

    mensagem_status = ""

    item = item_selecionado()

    if item is None:
        return

    if item.is_dir():
        try:
            list(item.iterdir())

            diretorio_atual = item.resolve()
            indice_selecionado = 0

            atualizar_lista()
            definir_status(f"Entrou em: {diretorio_atual.name}")

        except PermissionError:
            definir_status("Sem permissão para acessar esta pasta.")

        except OSError as erro:
            definir_status(f"Erro ao abrir pasta: {erro}")

        event.app.invalidate()
        return

    if item.is_file():
        arquivo_para_abrir = item.resolve()
        event.app.exit()

@teclas.add("backspace", filter=navegacao_ativa)
def voltar(event):

    global diretorio_atual
    global indice_selecionado

    if diretorio_atual.parent == diretorio_atual:

        definir_status(
            "Você já está no diretório raiz."
        )

        event.app.invalidate()

        return

    diretorio_atual = diretorio_atual.parent

    indice_selecionado = 0

    atualizar_lista()

    event.app.invalidate()


# ============================================================
# MENU
# ============================================================

@teclas.add(
    "c-o",
    filter=Condition(lambda: not modo_input)
)
def toggle_menu(event):

    global menu_visivel
    global menu_index

    menu_visivel = not menu_visivel

    menu_index = 0

    event.app.invalidate()


@teclas.add("up", filter=menu_ativo)
def menu_cima(event):

    global menu_index

    menu_index = max(
        0,
        menu_index - 1
    )

    event.app.invalidate()


@teclas.add("down", filter=menu_ativo)
def menu_baixo(event):

    global menu_index

    menu_index = min(
        len(menu_itens) - 1,
        menu_index + 1
    )

    event.app.invalidate()


@teclas.add("escape", filter=menu_ativo)
def menu_fechar(event):

    global menu_visivel

    menu_visivel = False

    event.app.invalidate()


@teclas.add("enter", filter=menu_ativo)
def menu_confirmar(event):
    global modo_input
    global prompt_titulo
    global input_texto
    global acao_input
    global menu_visivel
    global mensagem_status

    escolha = menu_index

    if escolha == 0:
        modo_input = True
        prompt_titulo = "Nome do Novo Arquivo"
        input_texto = ""
        acao_input = "arquivo"

    elif escolha == 1:
        modo_input = True
        prompt_titulo = "Nome da Nova Pasta"
        input_texto = ""
        acao_input = "pasta"

    elif escolha == 2:
        item = item_selecionado()

        if item is None:
            definir_status("Nenhum item selecionado.")
            menu_visivel = False

        else:
            modo_input = True
            prompt_titulo = f"Excluir '{item.name}'? (digite SIM)"
            input_texto = ""
            acao_input = "deletar"

    event.app.invalidate()

# ============================================================
# INPUT
# ============================================================

@teclas.add("escape", filter=input_ativo)
def cancelar_input(event):

    global modo_input
    global menu_visivel
    global input_texto
    global acao_input

    modo_input = False
    menu_visivel = False

    input_texto = ""
    acao_input = None

    definir_status(
        "Operação cancelada."
    )

    event.app.invalidate()


@teclas.add("backspace", filter=input_ativo)
def apagar_caractere(event):

    global input_texto

    input_texto = input_texto[:-1]

    event.app.invalidate()

@teclas.add("enter", filter=input_ativo)
def executar_acao_input(event):
    global modo_input
    global menu_visivel
    global input_texto
    global acao_input

    nome = input_texto.strip()
    acao = acao_input

    modo_input = False
    menu_visivel = False
    input_texto = ""
    acao_input = None

    if not nome:
        definir_status("Operação cancelada: nome vazio.")
        event.app.invalidate()
        return

    if acao == "arquivo":
        criar_arquivo(nome)

    elif acao == "pasta":
        criar_pasta(nome)

    elif acao == "deletar":
        if nome.lower() in ("sim", "s"):
            remover_item()
        else:
            definir_status("Exclusão cancelada.")

    event.app.invalidate()

@teclas.add("<any>", filter=input_ativo)
def capturar_texto(event):

    global input_texto

    for key in event.key_sequence:

        caractere = key.data

        if caractere and caractere.isprintable():

            input_texto += caractere

    event.app.invalidate()


# ============================================================
# SAIR
# ============================================================

@teclas.add(
    "c-q",
    filter=Condition(lambda: not modo_input)
)
def sair(event):

    event.app.exit()


# ============================================================
# LAYOUT
# ============================================================

janela_cabecalho = Window(
    content=FormattedTextControl(
        text=gerar_cabecalho
    ),
    height=2,
    style="class:path"
)


janela_conteudo = Window(
    content=FormattedTextControl(
        text=gerar_corpo
    )
)


janela_menu = Window(
    content=FormattedTextControl(
        text=obter_texto_menu
    ),
    width=32,
    style="class:outline"
)

janela_borda_cabecalho = Window(
    height=1,
    char="─",
    style="class:border"
)

corpo_layout = VSplit([

    janela_conteudo,

    ConditionalContainer(
        Window(
            width=1,
            char="│",
            style="class:line-number.separator"
        ),
        filter=Condition(
            lambda: menu_visivel
        )
    ),

    ConditionalContainer(
        janela_menu,
        filter=Condition(
            lambda: menu_visivel
        )
    ),
])


janela_borda_rodape = Window(
    height=1,
    char="─",
    style="class:border"
)

janela_rodape = Window(
    content=FormattedTextControl(
        text=gerar_rodape
    ),
    height=2,
    style="class:footer"
)

layout = Layout(
    HSplit([
        janela_cabecalho,
        janela_borda_cabecalho,

        corpo_layout,

        janela_borda_rodape,
        janela_rodape,
    ])
)

estilo = Style.from_dict({
    "": "#ebdbb2 bg:#282828",
    "header":
        "bg:#fe8019 fg:#1d2021 bold",
    "path":
        "bg:#3c3836 fg:#ebdbb2 bold",
    "border":
        "fg:#504945 bg:#282828",
    "selected":
        "bg:#3c3836 fg:#fabd2f bold",
    "item":
        "fg:#ebdbb2 bg:#282828",
    "empty":
        "fg:#928374 bg:#282828 italic",
    "footer":
        "bg:#1d2021 fg:#a89984 bold",
    "status":
        "bg:#3c3836 fg:#b8bb26 bold",
    "prompt":
        "bg:#fb4934 fg:#1d2021 bold",
    "outline":
        "bg:#1d2021",
    "outline.header":
        "fg:#fe8019 bold",
    "outline.help":
        "fg:#928374",
    "outline.selected":
        "bg:#3c3836 fg:#fabd2f bold",

    "outline.item":
        "fg:#ebdbb2",
    "line-number.separator":
        "fg:#504945 bg:#282828",
})


# ============================================================
# APLICAÇÃO
# ============================================================

app = Application(
    layout=layout,
    key_bindings=teclas,
    style=estilo,
    full_screen=True,
    mouse_support=True,
)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    while True:
        atualizar_lista()
        app.run()

        if arquivo_para_abrir is None:
            break

        try:
            subprocess.run(
                [
                    sys.executable,
                    str(JCODE),
                    str(arquivo_para_abrir)
                ],
                check=False
            )

        except OSError as erro:
            definir_status(
                f"Erro ao abrir o JCode: {erro}"
            )

        arquivo_para_abrir = None