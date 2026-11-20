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
  Ctrl+F buscar (Enter/↓ próximo, ↑ anterior, Esc fecha) · Ctrl+↓/↑ rolar a tela sem mover o texto
  F3 quebra de linha visual · F4 auto-fechar ( [ { " '
Comandos:  jcode <arquivo> · jcode -map <arquivo> (mapa da estrutura no terminal) · jcode -setup (configurar)
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

try:
    import jstatus
except ImportError:   # sem o jstatus.py a barra fica mínima
    jstatus = None

try:
    import jicons
    NERD = jicons.MODO == "nerd"
except ImportError:
    NERD = False

try:
    import jcursor
except ImportError:   # sem o jcursor.py o cursor fica como o terminal quiser
    jcursor = None

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound

# Paleta: usa o jtheme.py se estiver na mesma pasta; senão, o Tokyo Night embutido abaixo.
try:
    import jtheme
    _ESTILO = jtheme.estilo_jcode()
    _ESTILO_IDLE = jtheme.estilo_jcode_idle()
except (ImportError, AttributeError):
    jtheme = None
    _ESTILO = {
        "": "#c0caf5 bg:#1a1b26",
        "background": "bg:#1a1b26",
        "header": "#c0caf5 bold bg:#292e42",
        "status": "#c0caf5 bg:#292e42",
        "status.error": "#f7768e bold bg:#292e42",
        "line-number": "#444b6a",
        "line-number.current": "#7aa2f7 bold",
        "line-number.separator": "#3b4261",
        "indent-guide": "#3b4261",
        "pygments.keyword": "#bb9af7",
        "pygments.string": "#9ece6a",
        "pygments.comment": "#636da6",
        "pygments.number": "#ff9e64",
        "pygments.name": "#9aa5ce",
        "pygments.name.function": "#7aa2f7",
        "pygments.name.namespace": "#7dcfff",
        "pygments.operator": "#89ddff",
        "pygments.decorator": "#e0af68",
        "pygments.name.decorator": "#e0af68",
        "outline": "bg:#16161e",
        "outline.header": "#7aa2f7 bold",
        "outline.selected": "#e0af68 bold bg:#292e42",
        "outline.item": "#c0caf5",
        "outline.empty": "#636da6",
        "completion-menu": "bg:#292e42 #c0caf5",
        "completion-menu.completion": "bg:#292e42 #c0caf5",
        "completion-menu.completion.current": "bg:#7aa2f7 #1a1b26 bold",
        "completion-menu.meta.completion": "bg:#292e42 #636da6",
    }
    _ESTILO_IDLE = {
        "": "bg:#1a1b26 #c0caf5",
        "titulo": "#7aa2f7 bold",
        "texto": "#c0caf5",
        "dim": "#636da6",
    }

try:  # canal de mensagens do JDesk (opcional: sem ele o JCode funciona como sempre)
    import jipc
except ImportError:
    jipc = None

PEDIDOS: List[str] = []  # arquivos que o JDesk pediu para abrir (preenchido pela thread do jipc)


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
EXT_SEM_AUTO_FECHAR = {".txt", ".md", ".markdown", ".rst"}  # prosa: aspas e parênteses ficam como digitados
LIMITE_BUSCA = 20_000                # máximo de ocorrências marcadas na busca
PASSO_ROLAGEM = 3                   # linhas por Ctrl+↓/↑
EXT_SEM_LIMPEZA = {".md", ".markdown"}  # nelas dois espaços no fim da linha significam quebra de linha

# Mapa do arquivo (minimapa): cada célula de braille tem 2x4 pontos.
MAPA_COLUNAS = 14                 # largura do mapa em colunas do terminal
MAPA_CHARS_POR_PX = 3             # quantos caracteres do texto cabem em 1 ponto de largura
MAPA_LARGURA_MIN = 72             # só mostra o mapa se sobrar pelo menos isso para o editor
LIMITE_MAPA_CHARS = 600_000       # acima disso o mapa não é calculado


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
RE_NAO_ESPACO = re.compile(r"\S+")
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


def limpar_espacos_finais(texto: str, linha_cursor: Optional[int] = None, coluna_cursor: int = 0) -> Tuple[str, int]:
    """Tira espaços/tabs do fim de cada linha. Devolve (texto, quantas_linhas_mudaram).

    A linha do cursor é poupada quando o cursor está dentro do espaço final (ex.: a
    indentação automática acabou de ser inserida): senão o cursor "pularia" para a coluna 0.
    """
    linhas = texto.split("\n")
    mudou = 0
    for i, linha in enumerate(linhas):
        limpa = linha.rstrip(" \t")
        if limpa == linha:
            continue
        if i == linha_cursor and coluna_cursor > len(limpa):
            continue
        linhas[i] = limpa
        mudou += 1
    return "\n".join(linhas), mudou


def tab_ignorar(linha: str, coluna: int) -> bool:
    """True se o Tab deve ser ignorado: cursor no fim de uma linha que já tem código.

    Em linha vazia (ou só com espaços) o Tab continua indentando.
    """
    coluna = max(0, min(coluna, len(linha)))
    return not linha[coluna:].strip() and bool(linha[:coluna].strip())


# ── Auto-fechar pares ( ) [ ] { } " ' ───────────────────────────────────────────
_ABRE = {"(": ")", "[": "]", "{": "}"}
_FECHA = {v: k for k, v in _ABRE.items()}
_PARES_VAZIOS = {("(", ")"), ("[", "]"), ("{", "}"), ('"', '"'), ("'", "'")}
_PREFIXOS_STR = {"f", "r", "b", "u", "rb", "br", "fr", "rf"}
RE_PREFIXO_STR = re.compile(r"(?<!\w)([A-Za-z]{1,2})$")


def _livre_a_direita(proximo: str) -> bool:
    """Só fecha automaticamente se a direita do cursor está livre (fim, espaço ou outro fechamento)."""
    return proximo == "" or proximo.isspace() or proximo in ")]},;:"


def decidir_auto_fechar(c: str, antes: str, depois: str) -> Tuple[str, str, int]:
    """O que fazer ao digitar `c`. Devolve (acao, texto, recuo):

      ("normal", c, 0)        insere só o caractere
      ("inserir", texto, n)   insere `texto` e volta o cursor `n` casas (par: "()" com cursor no meio)
      ("pular", "", 0)        o caractere já está à direita: só anda por cima dele

    `antes` é o trecho antes do cursor (basta o final) e `depois` o começo do que vem depois.
    Na dúvida devolve "normal": o pior caso é o editor se comportar como sempre.
    """
    prox = depois[:1]
    if c in _ABRE:
        return ("inserir", c + _ABRE[c], 1) if _livre_a_direita(prox) else ("normal", c, 0)
    if c in _FECHA:
        if prox == c and antes.count(_FECHA[c]) > antes.count(c):   # há um abre esperando
            return ("pular", "", 0)
        return ("normal", c, 0)
    if c in "\"'":
        linha = antes.rsplit("\n", 1)[-1]
        anterior = linha[-1:]
        if anterior == "\\":                      # aspa escapada
            return ("normal", c, 0)
        dentro = linha.count(c) % 2 == 1        # já há uma aspa igual aberta nesta linha
        if dentro:
            return ("pular", "", 0) if prox == c else ("normal", c, 0)
        if linha.endswith(c * 2) and not linha.endswith(c * 3) and _livre_a_direita(prox):
            return ("inserir", c * 4, 3)         # terceira aspa: abre """ ... """
        if anterior.isalnum() or anterior == "_":   # don't, it's... (exceto prefixos f"", r'', b"")
            m = RE_PREFIXO_STR.search(linha)
            if not (m and m.group(1).lower() in _PREFIXOS_STR):
                return ("normal", c, 0)
        outra = "'" if c == '"' else '"'
        if linha.count(outra) % 2 == 1:         # aspa de outro tipo aberta: esta é texto
            return ("normal", c, 0)
        return ("inserir", c + c, 1) if _livre_a_direita(prox) else ("normal", c, 0)
    return ("normal", c, 0)


def par_vazio(antes: str, depois: str) -> bool:
    """True se o cursor está entre um par vazio: () [] {} "" ''."""
    return (antes[-1:], depois[:1]) in _PARES_VAZIOS


def ignorar_sequencias_modificadas() -> int:
    """Teclas combinadas desconhecidas (Ctrl+PageUp, Shift+F5...) viram <ignore> em vez de texto.

    O terminal manda algo como ESC [ 5 ; 5 ~ ; se o prompt_toolkit não conhece a sequência,
    ela chegava ao editor como os caracteres "[5;5~". Devolve quantas sequências foram adicionadas.
    """
    try:
        from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    except ImportError:
        return 0
    novos = 0
    for mod in range(2, 9):
        candidatas = [f"\x1b[1;{mod}{letra}" for letra in "ABCDHFPQRS"]
        candidatas += [f"\x1b[{n};{mod}~" for n in (2, 3, 5, 6, 7, 8, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 23, 24)]
        for seq in candidatas:
            if seq not in ANSI_SEQUENCES:
                ANSI_SEQUENCES[seq] = Keys.Ignore
                novos += 1
    return novos


# ── Busca (Ctrl+F) ──────────────────────────────────────────────────────────────
def compilar_busca(termo: str):
    """Regex literal do termo. Sem maiúsculas no termo, ignora maiúsculas/minúsculas (smart case)."""
    if not termo:
        return None
    flags = 0 if any(c.isupper() for c in termo) else re.IGNORECASE
    return re.compile(re.escape(termo), flags)


def buscar_ocorrencias(texto: str, termo: str, limite: int = LIMITE_BUSCA) -> List[int]:
    """Posições (índices no texto) onde o termo começa, sem sobreposição, até `limite`."""
    rx = compilar_busca(termo)
    if rx is None:
        return []
    saida: List[int] = []
    for m in rx.finditer(texto):
        saida.append(m.start())
        if len(saida) >= limite:
            break
    return saida


def escolher_ocorrencia(posicoes: List[int], pos: int, sentido: int = 1) -> int:
    """Índice da próxima ocorrência a partir de `pos` (sentido 1: em `pos` ou depois; -1: antes de `pos`).
    Dá a volta no arquivo. -1 se não há ocorrências."""
    if not posicoes:
        return -1
    if sentido >= 0:
        i = bisect.bisect_left(posicoes, pos)
        return i if i < len(posicoes) else 0
    i = bisect.bisect_left(posicoes, pos) - 1
    return i if i >= 0 else len(posicoes) - 1


# ── Mapa no terminal (jcode -map) ───────────────────────────────────────────────
def mapa_em_texto(texto: str, extensao: str, nome: str = "", largura: int = 80, altura: int = 30,
                  cor: bool = False) -> str:
    """Mapa da estrutura do arquivo: densidade em braille + intervalo de linhas + blocos de cada trecho."""
    if len(texto) > LIMITE_MAPA_CHARS:
        return f"{nome}: arquivo grande demais para mapear ({len(texto)} caracteres)\n"
    perfil = perfil_linhas(texto)
    if texto.endswith("\n"):
        perfil = perfil[:-1]      # a "linha" depois do último \n não existe
    total = len(perfil)
    if total == 0 or not texto.strip():
        return f"{nome}: arquivo vazio\n"
    dim, reset, azul, vermelho = ("\x1b[2m", "\x1b[0m", "\x1b[36m", "\x1b[31m") if cor else ("", "", "", "")
    linhas_mapa = max(4, min(60, altura - 5))
    colunas = MAPA_COLUNAS     # o perfil tem 2 pontos por coluna de braille
    blocos = montar_mapa(perfil, linhas_mapa, colunas)

    if extensao == ".py":
        itens = [(l, nome_bloco) for l, _, nome_bloco in extrair_outline(texto)]
    elif extensao in (".md", ".markdown"):
        itens = [(i, l.strip()) for i, l in enumerate(texto.splitlines()) if l.startswith("#")]
    else:
        itens = []
    erro = None
    if extensao == ".py" and len(texto) <= LIMITE_SINTAXE_CHARS:
        try:
            ast.parse(texto)
        except SyntaxError as e:
            erro = (e.lineno or 0) - 1, e.msg
        except Exception:
            pass

    saida = [f"{nome}  ·  {total} linhas  ·  {len(itens)} bloco(s)" + (f"  ·  {vermelho}erro de sintaxe L{erro[0] + 1}{reset}" if erro else ""), ""]
    largura_nomes = max(10, largura - colunas - 16)
    for braille, a, b in blocos:
        achados = [n for l, n in itens if a <= l < b]
        nomes = ", ".join(achados)
        if len(nomes) > largura_nomes:
            nomes = nomes[:largura_nomes - 1] + "…"
        marca = f" {vermelho}✗{reset}" if erro and a <= erro[0] < b else ""
        intervalo = f"L{a + 1}" if b - a <= 1 else f"L{a + 1}-{b}"
        saida.append(f"{dim}{braille.ljust(colunas)}{reset}  {dim}{intervalo:<11}{reset}{azul}{nomes}{reset}{marca}".rstrip())
    return "\n".join(saida) + "\n"


# ── Configuração (jcode -setup) ─────────────────────────────────────────────────
def _perguntar(entrada, saida, titulo: str, opcoes: List[str], atual: int) -> Optional[int]:
    """Menu numerado. Devolve o índice escolhido, o `atual` se der só Enter, ou None se cancelou (Ctrl+C/Ctrl+D)."""
    saida(titulo)
    for i, nome in enumerate(opcoes, 1):
        saida(f"  {i}) {nome}")
    for _ in range(3):
        try:
            resp = entrada(f"Escolha [1-{len(opcoes)}] (Enter mantém: {opcoes[atual]}): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not resp:
            return atual
        if resp.isdigit() and 1 <= int(resp) <= len(opcoes):
            return int(resp) - 1
        saida("  Opção inválida.")
    return atual


def executar_setup(entrada=input, saida=print, caminho: Optional[Path] = None) -> bool:
    """Menu de configuração do JCode. True se salvou."""
    if jcursor is None:
        saida("jcode -setup precisa do jcursor.py (está na pasta do JDev).")
        return False
    cfg = jcursor.carregar(caminho)
    formas = list(jcursor.FORMAS)
    nomes = [jcursor.NOMES_FORMA[f] for f in formas]
    saida("JCode — configuração (Ctrl+C cancela)\n")
    i = _perguntar(entrada, saida, "Tipo do cursor:", nomes, formas.index(cfg["cursor"]))
    if i is None:
        saida("\nCancelado, nada foi alterado.")
        return False
    saida("")
    j = _perguntar(entrada, saida, "Cursor piscando?", ["Sim", "Não"], 0 if cfg["piscar"] else 1)
    if j is None:
        saida("\nCancelado, nada foi alterado.")
        return False
    cfg = {"cursor": formas[i], "piscar": j == 0}
    arq = jcursor.salvar(cfg, caminho)
    saida(f"\nSalvo em {arq}")
    saida("Vale na próxima vez que abrir o JCode.")
    return True


def perfil_linhas(texto: str, px: int = MAPA_COLUNAS * 2, chars: int = MAPA_CHARS_POR_PX) -> List[int]:
    """Uma máscara de bits por linha: o bit i vale 1 se há texto entre as colunas [i*chars, (i+1)*chars)."""
    saida: List[int] = []
    for linha in texto.split("\n"):
        mascara = 0
        if linha and not linha.isspace():
            for m in RE_NAO_ESPACO.finditer(linha.expandtabs(4)):
                a = m.start() // chars
                if a >= px:
                    break
                b = min(px - 1, (m.end() - 1) // chars)
                mascara |= ((1 << (b + 1)) - 1) & ~((1 << a) - 1)
        saida.append(mascara)
    return saida


# Posição do ponto (linha 0-3, coluna 0-1) dentro de um caractere braille (U+2800 + bits).
_BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def montar_mapa(perfil: List[int], altura: int, colunas: int = MAPA_COLUNAS) -> List[Tuple[str, int, int]]:
    """Comprime o arquivo inteiro em até `altura` linhas de braille.

    Devolve [(texto, primeira_linha, fim_exclusivo)]: o intervalo de linhas do arquivo que cada
    linha do mapa representa (usado para marcar cursor/janela e para o clique pular até lá).
    """
    n = len(perfil)
    if n == 0 or altura <= 0:
        return []
    pixels = min(4 * altura, n)            # linhas de ponto realmente usadas
    passo = max(1.0, n / (4 * altura))     # linhas do arquivo por linha de ponto
    inicio = [min(n - 1, int(k * passo)) for k in range(pixels)]
    fim = [n if k == pixels - 1 else max(inicio[k] + 1, int((k + 1) * passo)) for k in range(pixels)]
    mascaras = []
    for a, b in zip(inicio, fim, strict=True):
        m = 0
        for i in range(a, min(b, n)):
            m |= perfil[i]
        mascaras.append(m)

    saida = []
    for r in range((pixels + 3) // 4):
        celulas = []
        for c in range(colunas):
            codigo = 0
            for j in range(4):
                k = 4 * r + j
                if k >= pixels:
                    break
                m = mascaras[k] >> (2 * c)
                if m & 1:
                    codigo |= _BRAILLE[j][0]
                if m & 2:
                    codigo |= _BRAILLE[j][1]
            celulas.append(chr(0x2800 + codigo) if codigo else " ")
        k0, k1 = 4 * r, min(pixels, 4 * r + 4) - 1
        saida.append(("".join(celulas), inicio[k0], fim[k1]))
    return saida


def _cor_estilo(valor, fundo: bool = False) -> Optional[str]:
    for t in (valor or "").split():
        if fundo and t.startswith("bg:#"):
            return t[3:]
        if not fundo and t.startswith("#"):
            return t
    return None


def estilo_mapa(base: dict) -> dict:
    """Estilos do mapa derivados da paleta atual (jtheme ou embutida)."""
    def fg(chave, padrao):
        return _cor_estilo(base.get(chave)) or padrao

    ponto = fg("pygments.comment", "#636da6")
    return {
        "minimap": ponto,
        "minimap.def": fg("pygments.keyword", "#bb9af7"),
        "minimap.cursor": fg("line-number.current", "#7aa2f7") + " bold",
        "minimap.erro": fg("status.error", "#f7768e") + " bold",
        "minimap.view": "bg:" + (_cor_estilo(base.get("header"), True) or _cor_estilo(base.get("status"), True) or "#292e42"),
        "minimap.vazio": ponto + " italic",
    }


class ResultadoAnalise(NamedTuple):
    erro_sintaxe: Optional[Tuple[Optional[int], str]]  # (linha, mensagem)
    indice: List[str]                                   # identificadores ORDENADOS
    outline: List[Tuple[int, int, str]]
    desativada: bool
    perfil: Optional[List[int]] = None                  # máscara por linha (mapa do arquivo)


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


class DestaqueBuscaProcessor(Processor):
    """Marca as ocorrências do termo buscado (e a atual, em destaque) sem mexer no texto."""

    def __init__(self, estado):
        self.estado = estado

    def apply_transformation(self, transformation_input):
        fragmentos = transformation_input.fragments
        try:
            rx = self.estado["rx"]
            if not self.estado["ativa"] or rx is None:
                return Transformation(fragmentos)
            linha = "".join(f[1] for f in fragmentos)
            achados = [(m.start(), m.end()) for m in rx.finditer(linha) if m.end() > m.start()]
            if not achados:
                return Transformation(fragmentos)
            letras: StyleAndTextTuples = []
            for f in fragmentos:
                resto = tuple(f[2:])
                letras.extend((f[0], c) + resto for c in f[1])
            doc_linha = transformation_input.lineno
            atual = self.estado["atual"]       # (linha, coluna) da ocorrência selecionada ou None
            for a, b in achados:
                classe = "class:busca.atual" if atual == (doc_linha, a) else "class:busca"
                for i in range(a, min(b, len(letras))):
                    f = letras[i]
                    letras[i] = (f"{f[0]} {classe}".strip(), f[1]) + tuple(f[2:])
            return Transformation(letras)
        except Exception:
            return Transformation(fragmentos)


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
def editar(arg_caminho: str) -> None:
    """Abre o editor para um arquivo e só volta quando o usuário sai dele."""
    # ast.parse pode emitir SyntaxWarning (ex.: "\d" em string); no meio da TUI isso suja a tela.
    warnings.simplefilter("ignore", SyntaxWarning)

    caminho = Path(arg_caminho)
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
    analise = {"indice": sorted(palavras_linguagem), "erro": None, "desativada": False, "perfil": None}
    inicial = analisar_documento(texto, extensao, palavras_linguagem, 0)
    analise.update(indice=inicial.indice, erro=inicial.erro_sintaxe, desativada=inicial.desativada,
                   perfil=inicial.perfil)

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
    modo_comando = {"ativo": False, "texto": "", "erro": "", "tipo": "linha"}   # tipo: "linha" (Ctrl+G) ou "busca" (Ctrl+F)
    busca = {"ativa": False, "rx": None, "posicoes": [], "indice": -1, "origem": 0, "ultimo": "", "atual": None}
    alteracao_bloco = [False]

    outline = {"visivel": False, "foco": False, "itens": [], "indice": 0}
    quebra = {"ativa": True}
    auto = {"ativo": extensao not in EXT_SEM_AUTO_FECHAR}
    csi = {"ativo": False, "ate": 0.0}     # descarta restos de sequências de tecla desconhecidas

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
    cond_auto = Condition(lambda: cond_normal() and auto["ativo"] and buffer.selection_state is None)
    cond_csi = Condition(lambda: csi["ativo"] and time.monotonic() < csi["ate"])

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

    def centralizar_linha(row: int, forcar: bool = False) -> None:
        """Se a linha-alvo está fora da tela (ou `forcar`), rola para deixá-la no meio."""
        try:
            altura = altura_janela(editor, 0)
            if altura <= 0:
                return
            topo = editor.vertical_scroll
            if forcar or row < topo or row >= topo + altura:
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
        elif tab_ignorar(buf.document.current_line, buf.document.cursor_position_col):
            avisar("Tab ignorado no fim da linha", 1.5)   # quase sempre foi sem querer
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
        col = doc.cursor_position_col
        if auto["ativo"] and (doc.current_line[col - 1:col], doc.current_line[col:col + 1]) in (("(", ")"), ("[", "]"), ("{", "}")):
            # Enter entre um par vazio: abre o bloco com o fechamento embaixo
            base = _indentacao_inicial(doc.current_line[:col])
            fundo = base + ("\t" if "\t" in base else INDENT)
            buf.insert_text("\n" + fundo + "\n" + base)
            buf.cursor_position -= len(base) + 1
            return
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

        if extensao not in EXT_SEM_LIMPEZA:
            doc = buffer.document
            row, col = doc.cursor_position_row, doc.cursor_position_col
            limpo, mudadas = limpar_espacos_finais(buffer.text, row, col)
            if mudadas:
                selecao_linha["ativa"] = False
                buffer.exit_selection()
                buffer.save_to_undo_stack()      # Ctrl+Z desfaz a limpeza
                buffer.text = limpo
                buffer.cursor_position = buffer.document.translate_row_col_to_index(row, col)
                avisar(f"Espaços finais removidos em {mudadas} linha(s)")

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
        modo_comando.update(ativo=True, texto="", erro="", tipo="linha")

    @atalho("enter", filter=cond_comando, eager=True)
    def confirmar_comando(event):
        if modo_comando["tipo"] == "busca":
            if not modo_comando["texto"] and busca["ultimo"]:     # Enter sem digitar: repete a última busca
                modo_comando["texto"] = busca["ultimo"]
                atualizar_busca()
            else:
                ir_ocorrencia(1, depois_do_cursor=True)
            return
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
        if modo_comando["tipo"] == "busca":
            fechar_busca()
            return
        modo_comando.update(ativo=False, texto="", erro="")

    @atalho("backspace", filter=cond_comando, eager=True)
    def apagar_comando(event):
        modo_comando["texto"] = modo_comando["texto"][:-1]
        if modo_comando["tipo"] == "busca":
            atualizar_busca()

    @atalho("c-u", filter=cond_comando, eager=True)
    def limpar_comando(event):
        modo_comando["texto"] = ""
        if modo_comando["tipo"] == "busca":
            atualizar_busca()

    @atalho(Keys.Any, filter=cond_comando)
    def digitar_comando(event):
        if event.data.isprintable() and len(modo_comando["texto"]) < (200 if modo_comando["tipo"] == "busca" else 32):
            modo_comando["texto"] += event.data
            if modo_comando["tipo"] == "busca":
                atualizar_busca()

    # ── Buscar (Ctrl+F) ───────────────────────────────────────────────────────
    # Digitou, já pula para a primeira ocorrência a partir de onde estava. Enter/↓/Ctrl+F: próxima;
    # ↑/Ctrl+P: anterior; Esc: fecha e o cursor fica na ocorrência. Ctrl+G continua sendo "ir para linha".
    def posicao_da_ocorrencia(pos: int) -> Tuple[int, int]:
        doc = buffer.document
        return doc.translate_index_to_position(pos)

    def atualizar_busca(manter: bool = False) -> None:
        termo = modo_comando["texto"]
        busca["rx"] = compilar_busca(termo)
        busca["ativa"] = bool(termo)
        busca["posicoes"] = buscar_ocorrencias(buffer.text, termo)
        busca["atual"] = None
        busca["indice"] = -1
        modo_comando["erro"] = ""
        if not busca["posicoes"]:
            if termo:
                modo_comando["erro"] = "sem resultados"
            return
        ir_ocorrencia(1, partir_de=busca["origem"] if not manter else buffer.cursor_position)

    def ir_ocorrencia(sentido: int, depois_do_cursor: bool = False, partir_de: Optional[int] = None) -> None:
        if not busca["posicoes"]:
            return
        if partir_de is None:
            partir_de = buffer.cursor_position
            if sentido >= 0 and depois_do_cursor and busca["indice"] >= 0:
                partir_de += 1                     # já estou numa ocorrência: vai para a seguinte
        i = escolher_ocorrencia(busca["posicoes"], partir_de, sentido)
        if i < 0:
            return
        busca["indice"] = i
        pos = busca["posicoes"][i]
        linha, coluna = posicao_da_ocorrencia(pos)
        busca["atual"] = (linha, coluna)
        buffer.cursor_position = pos
        centralizar_linha(linha)
        app.invalidate()

    def fechar_busca() -> None:
        if modo_comando["texto"]:
            busca["ultimo"] = modo_comando["texto"]
        modo_comando.update(ativo=False, texto="", erro="", tipo="linha")
        busca.update(ativa=False, rx=None, posicoes=[], indice=-1, atual=None)

    @atalho("c-f", filter=cond_normal)
    def abrir_busca(event):
        busca["origem"] = buffer.cursor_position
        modo_comando.update(ativo=True, texto="", erro="", tipo="busca")
        busca.update(ativa=False, rx=None, posicoes=[], indice=-1, atual=None)
        if busca["ultimo"]:
            avisar("Enter repete a última busca: " + busca["ultimo"], 3.0)

    cond_busca = Condition(lambda: modo_comando["ativo"] and modo_comando["tipo"] == "busca")

    @atalho("c-f", filter=cond_busca, eager=True)
    @atalho("down", filter=cond_busca, eager=True)
    def busca_proxima(event):
        ir_ocorrencia(1, depois_do_cursor=True)

    @atalho("c-p", filter=cond_busca, eager=True)
    @atalho("up", filter=cond_busca, eager=True)
    def busca_anterior(event):
        ir_ocorrencia(-1)

    # ── Rolar a tela sem mover o texto (Ctrl+↓ / Ctrl+↑) ──────────────────────
    # Ctrl+↓ sobe o código na tela, inclusive no fim do arquivo (dá para ler as últimas linhas
    # no meio da tela, sem criar linhas vazias). O cursor acompanha só o necessário para não sumir.
    def rolar_vista(n: int) -> None:
        doc = buffer.document
        total = len(doc.lines)
        linha = doc.cursor_position_row
        altura = altura_janela(editor, 12)
        topo = max(0, min(editor.vertical_scroll + n, total - 1))
        if linha < topo:
            buffer.cursor_down(count=topo - linha)
        elif linha > topo + altura - 1:
            buffer.cursor_up(count=linha - (topo + altura - 1))
        editor.vertical_scroll = topo
        app.invalidate()

    @atalho("c-down", filter=cond_normal | cond_explorar)
    def rolar_para_baixo(event):
        rolar_vista(PASSO_ROLAGEM)

    @atalho("c-up", filter=cond_normal | cond_explorar)
    def rolar_para_cima(event):
        rolar_vista(-PASSO_ROLAGEM)

    # ── Quebra de linha (F3) ──────────────────────────────────────────────────
    @atalho("f3", filter=cond_atalho_global)
    def alternar_quebra(event):
        quebra["ativa"] = not quebra["ativa"]
        avisar("Quebra de linha: " + ("ligada" if quebra["ativa"] else "desligada"), 2.0)

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

    # ── Auto-fechar pares, backspace em par vazio, digitação segura ───────────
    def registrar_auto(c: str) -> None:
        @atalho(c, filter=cond_auto)
        def _auto(event):
            buf = event.current_buffer
            pos = buf.cursor_position
            acao, texto, recuo = decidir_auto_fechar(c, buf.text[max(0, pos - 4000):pos], buf.text[pos:pos + 3])
            if acao == "pular":
                buf.cursor_position = pos + 1
            else:
                buf.insert_text(texto)
                if recuo:
                    buf.cursor_position -= recuo

    for _c in "([{)]}\"'":
        registrar_auto(_c)

    @atalho("backspace", filter=cond_auto)
    def apagar_par_vazio(event):
        buf = event.current_buffer
        pos = buf.cursor_position
        if pos > 0 and par_vazio(buf.text[pos - 1:pos], buf.text[pos:pos + 1]):
            buf.delete_before_cursor(1)
            buf.delete(1)
        else:
            buf.delete_before_cursor(count=event.arg)

    @atalho("f4", filter=cond_atalho_global)
    def alternar_auto_fechar(event):
        auto["ativo"] = not auto["ativo"]
        avisar("Auto-fechar: " + ("ligado" if auto["ativo"] else "desligado"), 2.0)

    # Só texto de verdade entra no buffer: teclas combinadas sem ação (Ctrl+PageUp...) não viram "^[[5;5~".
    @atalho(Keys.Any, filter=cond_editor)
    def inserir_texto(event):
        dados = event.data
        if dados and dados.isprintable():
            event.current_buffer.insert_text(dados * event.arg)

    # Resto de sequência de tecla que nenhuma camada reconheceu (ESC [ 5 ; 5 ~): descarta até o fim dela.
    @atalho("escape", "[", filter=cond_atalho_global, eager=True)
    def iniciar_descarte_csi(event):
        csi.update(ativo=True, ate=time.monotonic() + 0.25)

    @atalho(Keys.Any, filter=cond_csi, eager=True)
    def descartar_csi(event):
        dados = event.data or ""
        csi["ate"] = time.monotonic() + 0.25
        if len(dados) == 1 and "@" <= dados <= "~":   # byte final da sequência
            csi["ativo"] = False

    # ── Layout ────────────────────────────────────────────────────────────────
    try:
        lexer_inst = get_lexer_for_filename(caminho.name)
        lexer = LexerAdaptativo(lexer_inst.__class__)
    except (ClassNotFound, Exception):
        lexer = None

    controle = BufferControl(
        buffer=buffer,
        lexer=lexer,
        input_processors=[DestaqueBuscaProcessor(busca), IndentGuideProcessor()],
    )

    def prefixo_continuacao(numero_linha: int, quebras: int):
        """Linhas quebradas pela largura da tela recebem a indentação da linha de origem e um marcador."""
        if quebras == 0:
            return ""
        try:
            linha = buffer.document.lines[numero_linha]
        except IndexError:
            return ""
        recuo = min(len(linha) - len(linha.lstrip(" \t")), 24)
        return [("class:indent-guide", " " * recuo + "› ")]

    editor = Window(
        content=controle,
        wrap_lines=Condition(lambda: quebra["ativa"]),
        left_margins=[CustomNumberedMargin(separator="│")],
        get_line_prefix=prefixo_continuacao,
        allow_scroll_beyond_bottom=True,
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

    ramo_cache = {"valor": None, "t": -999.0}

    def ramo_atual() -> Optional[str]:
        """Ramo do git lendo .git/HEAD; refeito a cada 5 s (nunca a cada tecla)."""
        agora = time.monotonic()
        if jstatus is not None and agora - ramo_cache["t"] > 5.0:
            ramo_cache.update(valor=jstatus.ramo_git(caminho), t=agora)
        return ramo_cache["valor"]

    def texto_status():
        if jstatus is None:
            return [("class:status", f" {caminho.name}")]
        doc = buffer.document
        modo = modo_texto = None
        if modo_comando["ativo"] and modo_comando["tipo"] == "busca":
            n = len(busca["posicoes"])
            modo = "busca"
            modo_texto = modo_comando["texto"] + (f" {busca['indice'] + 1}/{n}" if n else (" sem resultados" if modo_comando["texto"] else ""))
        elif modo_comando["ativo"]:
            modo, modo_texto = "ir", modo_comando["texto"] + (f"  {modo_comando['erro']}" if modo_comando["erro"] else "")
        elif modo_explorar["ativo"]:
            modo = "exp"
        elif selecao_linha["ativa"]:
            modo = "sel"

        flags = []
        if not quebra["ativa"]:
            flags.append("sem quebra")
        if formato["fim_linha"] != "\n":
            flags.append({"\r\n": "CRLF", "\r": "CR"}.get(formato["fim_linha"], "?"))
        if formato["encoding"] != "utf-8":
            flags.append(formato["encoding"])

        mensagens = []
        if mensagem["texto"] and time.monotonic() < mensagem["expira"]:
            mensagens.append(mensagem["texto"])
        if analise["desativada"]:
            mensagens.append("análise desativada (arquivo grande)")
        erro = analise["erro"] if extensao == ".py" else None
        try:
            largura = app.output.get_size().columns
        except Exception:
            largura = 80
        estado = {
            "nome": caminho.name, "modificado": buffer.text != texto_salvo[0], "salvo_ok": salvamento["ok"],
            "erro_salvar": None if salvamento["ok"] else (salvamento["erro"] or "erro ao salvar"),
            "modo": modo, "modo_texto": modo_texto or "", "linha": doc.cursor_position_row,
            "coluna": doc.cursor_position_col, "total": len(doc.lines), "ramo": ramo_atual(),
            "flags": flags, "erro_sintaxe": erro, "mensagens": mensagens,
        }
        try:
            return jstatus.montar_status(estado, largura, NERD)
        except Exception as exc:     # a barra é enfeite: se falhar, não derruba o editor
            registrar_erro(exc)
            return [("class:status", f" {caminho.name}")]

    status = Window(
        content=FormattedTextControl(text=texto_status),
        height=1,
        style="class:st.bar",
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

    # tema: jtheme.py se existir; senão o embutido
    estilo = Style.from_dict({"busca": "reverse", "busca.atual": "bg:#e0af68 #1a1b26 bold",
                              **(jstatus.estilos_status(jtheme) if jstatus else {}), **_ESTILO})

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

    # ── Pedidos de abertura vindos do JDesk ───────────────────────────────────
    # Sem alterações pendentes: troca de arquivo na hora. Com alterações: avisa e
    # espera o usuário salvar (Ctrl+S) ou sair (Ctrl+Q); nada é descartado sozinho.
    async def vigiar_pedidos() -> None:
        avisado = False
        while True:
            await asyncio.sleep(0.15)
            if not PEDIDOS:
                avisado = False
                continue
            if buffer.text == texto_salvo[0]:
                app.exit()
                return
            if not avisado:
                avisado = True
                avisar(f"Pedido para abrir {Path(PEDIDOS[-1]).name}: salve (Ctrl+S) ou saia (Ctrl+Q).", 8.0)

    def iniciar_vigia() -> None:
        criar = getattr(app, "create_background_task", None)
        if criar is not None:
            criar(vigiar_pedidos())

    # ── Análise em segundo plano ──────────────────────────────────────────────
    # A digitação só faz trabalho O(1): marca a versão e agenda. Parse, índice de
    # autocomplete e sumário rodam numa única thread, depois de uma pausa, e só
    # o resultado da versão mais recente é aplicado.
    executor_analise = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jcode-analysis")
    timer_analise = [None]
    versao_documento = [0]
    estado_analise = {"em_andamento": False, "pendente": False}

    def aplicar_resultado(res: ResultadoAnalise) -> None:
        analise.update(indice=res.indice, erro=res.erro_sintaxe, desativada=res.desativada, perfil=res.perfil)
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
        if tty and jcursor is not None:
            sys.stdout.write(jcursor.sequencia(jcursor.carregar()))
            sys.stdout.flush()
        app.run(pre_run=iniciar_vigia)
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
        if tty and jcursor is not None:
            sys.stdout.write("\033[0 q")    # devolve o cursor ao padrão do terminal
            sys.stdout.flush()


# ══════════════════════════════════════════════════════════════════════════════
#  Modo idle (painel JCode do JDesk) e laço principal
# ══════════════════════════════════════════════════════════════════════════════
def _receber(msg: dict) -> None:
    """Chamado na thread do jipc."""
    if msg.get("cmd") == "open" and msg.get("path"):
        PEDIDOS.append(str(msg["path"]))


def tela_idle(ultimo: Optional[str]) -> Optional[str]:
    """Tela de espera. Devolve o caminho pedido, ou None se o usuário saiu (Ctrl+Q)."""
    if PEDIDOS:
        caminho = PEDIDOS.pop()
        PEDIDOS.clear()
        return caminho

    from prompt_toolkit.layout import WindowAlign
    from prompt_toolkit.layout.containers import VerticalAlign

    def texto():
        linhas = [
            ("class:titulo", "J C o d e\n"),
            ("class:dim", "modo idle\n\n"),
            ("class:texto", "Aguardando um arquivo.\n"),
            ("class:dim", "Enter no JFiles (ou  jcode arquivo  no JShell) abre aqui.\n\n"),
        ]
        if ultimo:
            linhas.append(("class:dim", f"último: {ultimo}\n\n"))
        linhas.append(("class:dim", "Ctrl+Q sai"))
        return linhas

    kb = KeyBindings()

    @kb.add("c-q")
    def _(event):
        event.app.exit(result=None)

    async def vigiar() -> None:
        while True:
            await asyncio.sleep(0.15)
            if PEDIDOS:
                caminho = PEDIDOS.pop()
                PEDIDOS.clear()
                app_idle.exit(result=caminho)
                return

    corpo = Window(FormattedTextControl(texto), align=WindowAlign.CENTER, dont_extend_height=True)
    app_idle = Application(
        layout=Layout(HSplit([corpo], align=VerticalAlign.CENTER)),
        key_bindings=kb,
        full_screen=True,
        style=Style.from_dict(_ESTILO_IDLE),
    )

    def pre_run() -> None:
        criar = getattr(app_idle, "create_background_task", None)
        if criar is not None:
            criar(vigiar())

    return app_idle.run(pre_run=pre_run)


AJUDA = """Uso:
  jcode <arquivo>          abre o editor
  jcode -map <arquivo>     mostra no terminal o mapa da estrutura do arquivo (sem abrir o editor)
  jcode -setup             menu de configuração (formato do cursor e piscar)
  jcode -h                 esta ajuda
"""


def comando_map(arquivo: str) -> int:
    caminho = Path(arquivo).expanduser()
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"jcode -map: não consegui ler {arquivo}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    tam = shutil.get_terminal_size((100, 30))
    print(mapa_em_texto(texto, caminho.suffix.lower(), caminho.name, tam.columns, tam.lines,
                        cor=sys.stdout.isatty()), end="")
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "-help"):
        print(AJUDA, end="")
        return
    if args and args[0] in ("-setup", "--setup"):
        sys.exit(0 if executar_setup() else 1)
    if args and args[0] in ("-map", "--map"):
        if len(args) < 2:
            print("Uso: jcode -map <arquivo>", file=sys.stderr)
            sys.exit(2)
        sys.exit(comando_map(args[1]))
    ignorar_sequencias_modificadas()
    # Só o painel "jcode" do JDesk vira um editor residente (idle + recebe pedidos).
    # Um JCode aberto pelo JShell/JFiles dentro do JDesk continua efêmero, como sempre.
    residente = jipc is not None and jipc.disponivel() and os.environ.get("JDESK_PANE") == "jcode"

    if not args and not residente:
        print(AJUDA, end="")
        return

    receptor = None
    if residente:
        receptor = jipc.Receptor("jcode", _receber)
        receptor.iniciar()

    proximo: Optional[str] = args[0] if args else None
    ultimo: Optional[str] = None
    try:
        while True:
            if proximo is None:
                proximo = tela_idle(ultimo)
                if proximo is None:
                    return
            try:
                editar(proximo)
            except Exception as exc:
                registrar_erro(exc)
                if not residente:
                    raise
            ultimo = Path(proximo).name
            proximo = PEDIDOS.pop() if PEDIDOS else None
            PEDIDOS.clear()
            if proximo is None:
                if not residente:
                    return
                jipc.enviar({"cmd": "focus", "target": "jfiles"})  # fechou o arquivo: devolve o foco
    finally:
        if receptor:
            receptor.parar()


if __name__ == "__main__":
    main()
