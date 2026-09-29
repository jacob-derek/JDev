from pathlib import Path
import subprocess
import sys
import shutil
import datetime

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
    "Renomear",
    "Copiar",
    "Mover",
    "Informações",
    "Visualizar",
    "Deletar",
]

menu_index = 0

# Visualização (Preview ou Info)
modo_visualizacao = "preview"  # pode ser "preview" ou "info"

# Input
modo_input = False
prompt_titulo = ""
input_texto = ""

# Guarda qual operação está sendo executada
acao_input = None

# Mensagem temporária exibida no rodapé
mensagem_status = ""
modo_mover = False
item_para_mover = None


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
                "✗ O diretório atual não existe mais."
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
            "✗ Sem permissão para acessar este diretório."
        )
        return []

    except OSError as erro:
        definir_status(
            f"✗ Erro ao acessar diretório: {erro}"
        )
        return []


def atualizar_lista():
    global itens
    global inicio_janela
    global indice_selecionado

    nome_antigo = None
    if itens and indice_selecionado < len(itens):
        nome_antigo = itens[indice_selecionado].name

    itens = obter_itens()

    if not itens:
        inicio_janela = 0
        indice_selecionado = 0
        return

    if nome_antigo:
        try:
            indice_selecionado = next(
                i for i, item in enumerate(itens) if item.name == nome_antigo
            )
        except StopIteration:
            corrigir_indice()
    else:
        corrigir_indice()


# ============================================================
# AÇÕES DE ARQUIVO
# ============================================================

def criar_arquivo(nome):
    nome = nome.strip()
    if not nome:
        definir_status("✗ Nome inválido.")
        return

    destino = diretorio_atual / nome
    try:
        destino.touch(exist_ok=False)
        definir_status(f"✓ Arquivo criado")
        atualizar_lista()
    except FileExistsError:
        definir_status(f"✗ Já existe um item com este nome.")
    except Exception as erro:
        definir_status(f"✗ Erro: {erro}")


def criar_pasta(nome):
    nome = nome.strip()
    if not nome:
        definir_status("✗ Nome inválido.")
        return

    destino = diretorio_atual / nome
    try:
        destino.mkdir()
        definir_status(f"✓ Pasta criada")
        atualizar_lista()
    except FileExistsError:
        definir_status(f"✗ Já existe um item com este nome.")
    except Exception as erro:
        definir_status(f"✗ Erro: {erro}")


def remover_item():
    item = item_selecionado()
    if item is None:
        return

    try:
        if item.is_dir():
            item.rmdir()
        else:
            item.unlink()

        definir_status("✓ Item removido")
        atualizar_lista()
    except OSError:
        if item.is_dir():
            definir_status("✗ Erro: a pasta pode não estar vazia.")
        else:
            definir_status("✗ Erro ao remover item.")
        atualizar_lista()


# ============================================================
# INTERFACE E PREVIEW
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
        altura_maxima_itens = max(1, tamanho_tela.rows - 7)
    except Exception:
        pass

    if indice_selecionado < inicio_janela:
        inicio_janela = indice_selecionado
    elif indice_selecionado >= inicio_janela + altura_maxima_itens:
        inicio_janela = indice_selecionado - altura_maxima_itens + 1

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
                tamanho = formatar_tamanho(item.stat().st_size)
                detalhes = f" [{tamanho}]"
            except OSError:
                detalhes = " [erro]"
        else:
            detalhes = "/"

        nome_formatado = f" {icone}  {item.name}{detalhes}\n"

        if indice_real == indice_selecionado:
            linhas.append(("class:selected", f" ➔ {nome_formatado}"))
        else:
            linhas.append(("class:item", f"   {nome_formatado}"))

    return linhas


def gerar_preview():
    item = item_selecionado()
    if not item:
        return [("class:empty", " Nenhum item selecionado.\n")]

    linhas = [("class:outline.header", f" ── PREVIEW ──\n\n")]

    if modo_visualizacao == "info":
        linhas.append(("class:item", f" Nome: {item.name}\n"))
        linhas.append(("class:item", f" Caminho: {item.resolve()}\n"))
        linhas.append(("class:item", f" Tipo: {'Pasta' if item.is_dir() else 'Arquivo'}\n"))
        if item.is_file():
            linhas.append(("class:item", f" Extensão: {item.suffix or '(nenhuma)'}\n"))
        
        try:
            stat = item.stat()
            tamanho = formatar_tamanho(stat.st_size) if item.is_file() else "-"
            modificado = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M:%S')
            
            linhas.append(("class:item", f" Tamanho: {tamanho}\n"))
            linhas.append(("class:item", f" Modificado: {modificado}\n"))
            
            if item.is_dir():
                qtd = len(list(item.iterdir()))
                linhas.append(("class:item", f" Itens na pasta: {qtd}\n"))
        except OSError:
            linhas.append(("class:empty", " [Erro ao ler atributos]\n"))
            
        return linhas

    # Modo preview padrão
    try:
        if item.is_dir():
            conteudo = list(item.iterdir())
            if not conteudo:
                linhas.append(("class:empty", "  Pasta vazia\n"))
            else:
                for c in conteudo[:20]:
                    icone = "📁" if c.is_dir() else "📄"
                    linhas.append(("class:item", f"  {icone} {c.name}\n"))
                if len(conteudo) > 20:
                    linhas.append(("class:empty", f"  ... e mais {len(conteudo)-20} itens\n"))
        else:
            with open(item, 'r', encoding='utf-8') as f:
                for _ in range(25):
                    linha = f.readline()
                    if not linha:
                        break
                    linhas.append(("class:item", f" {linha}"))
                if f.readline():
                    linhas.append(("class:empty", "\n [Conteúdo longo cortado...]"))
    except UnicodeDecodeError:
        linhas.append(("class:empty", " [Arquivo binário — preview indisponível]\n"))
    except PermissionError:
        linhas.append(("class:empty", " [Sem permissão de leitura]\n"))
    except OSError:
        linhas.append(("class:empty", " [Erro ao ler conteúdo]\n"))

    return linhas


def obter_texto_menu():
    resultado = [
        ("class:outline.header", " ── AÇÕES ──\n\n"),
        ("class:outline.help", " ↑/↓ escolher\n ENTER confirmar\n ESC fechar\n\n"),
    ]

    for idx, nome in enumerate(menu_itens):
        if idx == menu_index:
            resultado.append(("class:outline.selected", f" ➜ {nome}\n"))
        else:
            resultado.append(("class:outline.item", f"   {nome}\n"))

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
                (" ↑/↓ Navegar │ ENTER Abrir │ BACKSPACE Voltar │ CTRL+O Opções │ CTRL+Q Sair" if not modo_mover else " MODO MOVER │ ENTER entrar na pasta │ M confirmar destino │ BACKSPACE voltar │ ESC cancelar")
            )
        )

    if mensagem_status:
        linhas.append(("class:status", f" {mensagem_status}"))

    return linhas

# ============================================================
# KEYBINDINGS
# ============================================================

teclas = KeyBindings()

menu_ativo = Condition(lambda: menu_visivel and not modo_input)
navegacao_ativa = Condition(lambda: not menu_visivel and not modo_input)
input_ativo = Condition(lambda: modo_input)

# ============================================================
# NAVEGAÇÃO
# ============================================================

@teclas.add("up", filter=navegacao_ativa)
def mover_cima(event):
    global indice_selecionado, modo_visualizacao
    modo_visualizacao = "preview"
    if itens:
        indice_selecionado = max(0, indice_selecionado - 1)
        event.app.invalidate()

@teclas.add("down", filter=navegacao_ativa)
def mover_baixo(event):
    global indice_selecionado, modo_visualizacao
    modo_visualizacao = "preview"
    if itens:
        indice_selecionado = min(len(itens) - 1, indice_selecionado + 1)
        event.app.invalidate()

@teclas.add("enter", filter=navegacao_ativa)
def entrar(event):
    global diretorio_atual, indice_selecionado
    global arquivo_para_abrir, mensagem_status
    global modo_visualizacao

    modo_visualizacao = "preview"
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
        except PermissionError:
            definir_status("✗ Sem permissão.")
        except OSError as erro:
            definir_status(f"✗ Erro: {erro}")
        event.app.invalidate()
        return

    if item.is_file() and not modo_mover:
        arquivo_para_abrir = item.resolve()
        event.app.exit()

@teclas.add("backspace", filter=navegacao_ativa)
def voltar(event):
    global diretorio_atual, indice_selecionado, modo_visualizacao
    modo_visualizacao = "preview"

    if diretorio_atual.parent == diretorio_atual:
        definir_status("Você já está na raiz.")
        event.app.invalidate()
        return

    diretorio_atual = diretorio_atual.parent
    indice_selecionado = 0
    atualizar_lista()
    event.app.invalidate()


@teclas.add("m", filter=Condition(lambda: modo_mover and not modo_input and not menu_visivel))
def confirmar_destino_mover(event):
    global modo_mover, item_para_mover
    if item_para_mover is None:
        modo_mover = False
        return
    destino = diretorio_atual / item_para_mover.name
    try:
        if destino.exists():
            definir_status("✗ Já existe um item com esse nome no destino.")
        elif item_para_mover.is_dir() and (diretorio_atual == item_para_mover or diretorio_atual in item_para_mover.parents):
            definir_status("✗ Não é possível mover uma pasta para dentro dela mesma.")
        else:
            shutil.move(str(item_para_mover), str(destino))
            definir_status(f"✓ Movido para: {diretorio_atual}")
            modo_mover = False
            item_para_mover = None
            atualizar_lista()
    except OSError as erro:
        definir_status(f"✗ Erro ao mover: {erro}")
    event.app.invalidate()

@teclas.add("escape", filter=Condition(lambda: modo_mover and not modo_input and not menu_visivel))
def cancelar_mover(event):
    global modo_mover, item_para_mover
    modo_mover = False
    item_para_mover = None
    definir_status("Movimentação cancelada.")
    event.app.invalidate()

# ============================================================
# MENU
# ============================================================

@teclas.add("c-o", filter=Condition(lambda: not modo_input))
def toggle_menu(event):
    global menu_visivel, menu_index
    menu_visivel = not menu_visivel
    menu_index = 0
    event.app.invalidate()

@teclas.add("up", filter=menu_ativo)
def menu_cima(event):
    global menu_index
    menu_index = max(0, menu_index - 1)
    event.app.invalidate()

@teclas.add("down", filter=menu_ativo)
def menu_baixo(event):
    global menu_index
    menu_index = min(len(menu_itens) - 1, menu_index + 1)
    event.app.invalidate()

@teclas.add("escape", filter=menu_ativo)
def menu_fechar(event):
    global menu_visivel
    menu_visivel = False
    event.app.invalidate()

@teclas.add("enter", filter=menu_ativo)
def menu_confirmar(event):
    global modo_input, prompt_titulo, input_texto, acao_input
    global menu_visivel, mensagem_status, modo_visualizacao

    escolha = menu_index
    item = item_selecionado()

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

    elif escolha == 2: # Renomear
        if not item:
            definir_status("✗ Nenhum item.")
            menu_visivel = False
        else:
            modo_input = True
            prompt_titulo = "Renomear para"
            input_texto = item.name
            acao_input = "renomear"

    elif escolha == 3: # Copiar
        if not item:
            definir_status("✗ Nenhum item.")
            menu_visivel = False
        else:
            modo_input = True
            prompt_titulo = "Copiar para"
            input_texto = f"{item.stem}_copia{item.suffix}" if item.is_file() else f"{item.name}_copia"
            acao_input = "copiar"

    elif escolha == 4: # Mover
        global modo_mover, item_para_mover
        if not item:
            definir_status("✗ Nenhum item.")
            menu_visivel = False
        elif item.is_dir() and (diretorio_atual == item or diretorio_atual in item.parents):
            definir_status("✗ Não é possível mover uma pasta para dentro dela mesma.")
            menu_visivel = False
        else:
            item_para_mover = item
            modo_mover = True
            menu_visivel = False
            definir_status(f"Destino: {diretorio_atual} — navegue e pressione M para confirmar.")

    elif escolha == 5: # Informações
        modo_visualizacao = "info"
        menu_visivel = False

    elif escolha == 6: # Visualizar
        modo_visualizacao = "preview"
        menu_visivel = False

    elif escolha == 7: # Deletar
        if not item:
            definir_status("✗ Nenhum item.")
            menu_visivel = False
        else:
            modo_input = True
            prompt_titulo = f"Excluir '{item.name}'? [s/N]"
            input_texto = ""
            acao_input = "deletar"

    event.app.invalidate()


# ============================================================
# INPUT
# ============================================================

@teclas.add("escape", filter=input_ativo)
def cancelar_input(event):
    global modo_input, menu_visivel, input_texto, acao_input
    modo_input = False
    menu_visivel = False
    input_texto = ""
    acao_input = None
    definir_status("Operação cancelada.")
    event.app.invalidate()

@teclas.add("backspace", filter=input_ativo)
def apagar_caractere(event):
    global input_texto
    input_texto = input_texto[:-1]
    event.app.invalidate()

@teclas.add("enter", filter=input_ativo)
def executar_acao_input(event):
    global modo_input, menu_visivel, input_texto, acao_input

    nome = input_texto.strip()
    acao = acao_input

    modo_input = False
    menu_visivel = False
    input_texto = ""
    acao_input = None

    if acao == "deletar":
        if nome.lower() in ("sim", "s"):
            remover_item()
        else:
            definir_status("Exclusão cancelada.")
        event.app.invalidate()
        return

    if not nome:
        definir_status("✗ Cancelado: nome vazio.")
        event.app.invalidate()
        return

    item = item_selecionado()
    destino = diretorio_atual / nome

    if acao == "arquivo":
        criar_arquivo(nome)

    elif acao == "pasta":
        criar_pasta(nome)

    elif acao == "renomear" and item:
        if destino.exists():
            definir_status("✗ Conflito: item já existe.")
        else:
            try:
                item.rename(destino)
                definir_status(f"✓ Item renomeado")
                atualizar_lista()
            except OSError as e:
                definir_status(f"✗ Erro: {e}")

    elif acao == "copiar" and item:
        if destino.exists():
            definir_status("✗ Conflito: item já existe.")
        else:
            try:
                if item.is_dir():
                    shutil.copytree(item, destino)
                else:
                    shutil.copy2(item, destino)
                definir_status("✓ Item copiado")
                atualizar_lista()
            except OSError as e:
                definir_status(f"✗ Erro: {e}")

    elif acao == "mover" and item:
        if destino.exists():
            definir_status("✗ Conflito: item já existe.")
        else:
            try:
                shutil.move(str(item), str(destino))
                definir_status("✓ Item movido")
                atualizar_lista()
            except OSError as e:
                definir_status(f"✗ Erro: {e}")

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

@teclas.add("c-q", filter=Condition(lambda: not modo_input))
def sair(event):
    event.app.exit()


# ============================================================
# LAYOUT
# ============================================================

janela_cabecalho = Window(
    content=FormattedTextControl(text=gerar_cabecalho),
    height=2,
    style="class:path"
)

janela_conteudo = Window(
    content=FormattedTextControl(text=gerar_corpo)
)

janela_preview = Window(
    content=FormattedTextControl(text=gerar_preview),
    wrap_lines=False
)

janela_menu = Window(
    content=FormattedTextControl(text=obter_texto_menu),
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
        Window(width=1, char="│", style="class:line-number.separator"),
        filter=Condition(lambda: app.renderer.output.get_size().columns >= 90)
    ),
    
    ConditionalContainer(
        janela_preview,
        filter=Condition(lambda: app.renderer.output.get_size().columns >= 90)
    ),

    ConditionalContainer(
        Window(
            width=1,
            char="│",
            style="class:line-number.separator"
        ),
        filter=Condition(lambda: menu_visivel)
    ),

    ConditionalContainer(
        janela_menu,
        filter=Condition(lambda: menu_visivel)
    ),
])

janela_borda_rodape = Window(
    height=1,
    char="─",
    style="class:border"
)

janela_rodape = Window(
    content=FormattedTextControl(text=gerar_rodape),
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
    "header": "bg:#fe8019 fg:#1d2021 bold",
    "path": "bg:#3c3836 fg:#ebdbb2 bold",
    "border": "fg:#504945 bg:#282828",
    "selected": "bg:#3c3836 fg:#fabd2f bold",
    "item": "fg:#ebdbb2 bg:#282828",
    "empty": "fg:#928374 bg:#282828 italic",
    "footer": "bg:#1d2021 fg:#a89984 bold",
    "status": "bg:#3c3836 fg:#b8bb26 bold",
    "prompt": "bg:#fb4934 fg:#1d2021 bold",
    "outline": "bg:#1d2021",
    "outline.header": "fg:#fe8019 bold",
    "outline.help": "fg:#928374",
    "outline.selected": "bg:#3c3836 fg:#fabd2f bold",
    "outline.item": "fg:#ebdbb2",
    "line-number.separator": "fg:#504945 bg:#282828",
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