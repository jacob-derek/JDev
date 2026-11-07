#!/usr/bin/env python3
"""JClass — JDev Classroom Manager: baixador/visualizador de materiais do Classroom no terminal."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import FormattedTextControl, Layout, Window

from classroom_api import (
    Aviso,
    Item,
    JClassError,
    extrair_itens,
    listar_avisos,
    listar_turmas,
    traduzir_erro,
)
from drive_download import baixar_arquivo, criar_servico_drive, nome_seguro
from testar_classroom import BASE, CREDENTIALS_FILE, SCOPES, TOKEN_FILE, autenticar

# jipc.py fica na raiz do JDev (pasta acima de JClass/); é opcional.
sys.path.append(str(Path(__file__).resolve().parent.parent))
try:
    import jipc
except ImportError:
    jipc = None

COURSE_ID_PADRAO = "869369061852"
MIN_COLS, MIN_ROWS = 60, 14
LOG_FILE = BASE / "jclass.log"

PASSOS = (
    "Verificando credenciais",
    "Autenticando no Google",
    "Carregando turmas",
    "Carregando avisos",
    "Extraindo anexos",
)
TIPOS_FILTRO = (("Tudo", None), ("Arquivos", "drive"), ("Links", "link"), ("Vídeos", "youtube"))
POLITICAS = (
    ("renomear", "manter os dois (nome (1).ext)"),
    ("ignorar", "pular o que já existe"),
    ("substituir", "sobrescrever o arquivo existente"),
)
FINAIS = ("ok", "ignorado", "erro", "cancelado")
DIM = "ansibrightblack"
ACC = "ansicyan"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
class Glifos:
    """Conjunto de símbolos; ASCII puro para o console Linux (TERM=linux)."""

    def __init__(self, ascii_: bool) -> None:
        if ascii_:
            self.ptr, self.sep, self.cheio, self.vazio = ">", "-", "#", "-"
            self.ok, self.erro, self.ponto, self.dot = "ok", "x", "*", "|"
            self.spin, self.setas, self.espera = "|/-\\", "Up/Dn", "."
        else:
            self.ptr, self.sep, self.cheio, self.vazio = "❯", "─", "█", "░"
            self.ok, self.erro, self.ponto, self.dot = "✔", "✘", "●", "·"
            self.spin, self.setas, self.espera = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "↑↓", "·"


def corta(txt: str, n: int) -> str:
    txt = txt.replace("\n", " ")
    if n <= 0:
        return ""
    if len(txt) <= n:
        return txt
    return txt[: n - 3] + "..." if n > 3 else txt[:n]


def pad(txt: str, n: int) -> str:
    return corta(txt, n).ljust(n)


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)).casefold()


def fmt_bytes(n: float) -> str:
    for un in ("B", "KB", "MB", "GB"):
        if n < 1024 or un == "GB":
            return f"{n:.0f} {un}" if un == "B" else f"{n:.1f} {un}"
        n /= 1024
    return ""


def curto(p: Path | str) -> str:
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home):] if s.startswith(home) else s


def estilo(base: str, atual: bool) -> str:
    return (base + (" reverse" if atual else "")).strip()


def log_erro(exc: BaseException) -> None:
    """Guarda o traceback em jclass.log (sem segredos) para depuração."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n")
            f.write("".join(traceback.format_exception(exc)))
    except OSError:
        pass


def estado_token() -> str:
    if not CREDENTIALS_FILE.exists():
        return "sem_credentials"
    if not TOKEN_FILE.exists():
        return "sem_token"
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except Exception:
        return "token_invalido"
    if creds.valid or (creds.expired and creds.refresh_token):
        return "ok"
    return "reautorizar"


# --------------------------------------------------------------------------
# Aplicação
# --------------------------------------------------------------------------
class JClass:
    def __init__(self, args: argparse.Namespace) -> None:
        ascii_ = args.ascii or os.environ.get("TERM") == "linux" or "utf" not in (sys.stdout.encoding or "").lower()
        self.g = Glifos(ascii_)
        self.curso_pref = args.curso or COURSE_ID_PADRAO
        self.destino_arg = Path(args.destino).expanduser() if args.destino else None

        self.app: Application | None = None
        self.service = None
        self.turmas: list[dict] = []
        self.turma: dict | None = None
        self.avisos: list[Aviso] = []
        self.itens: list[Item] = []
        self.visiveis: list[Item] = []

        self.tela = "carregando"
        self.passos: list[list[str]] = [[p, "pend", ""] for p in PASSOS]
        self.erro: JClassError | None = None
        self.msg = ""
        self.msg_estilo = ""

        self.idx = self.topo = 0
        self.filtro_tipo = 0
        self.busca = ""
        self.editando = False
        self.turmas_idx = 0
        self.menu_itens: list[tuple[str, Callable[[], None]]] = []
        self.menu_idx = 0
        self.texto_aviso: Aviso | None = None
        self.texto_topo = 0

        self.fila: list[Item] = []
        self.politica = "renomear"
        self.conflitos = 0
        self.baixando = False
        self.concluido = False
        self.cancelar = threading.Event()
        self.sair_ao_fim = False
        self.dl_topo = 0
        self.anim = threading.Event()

    # ---------------- infraestrutura ----------------
    @property
    def destino(self) -> Path:
        if self.destino_arg:
            return self.destino_arg
        nome = nome_seguro(self.turma["name"]) if self.turma else "turma"
        return BASE / "downloads" / nome

    def invalidar(self) -> None:
        if self.app:
            self.app.invalidate()

    def avisar(self, texto: str, estilo_: str = "ansicyan") -> None:
        self.msg, self.msg_estilo = texto, estilo_

    def _pulso(self) -> None:
        """Só acorda para animar enquanto há trabalho em andamento (ocioso = 0% CPU)."""
        while True:
            self.anim.wait()
            time.sleep(0.12)
            if self.anim.is_set():
                self.invalidar()

    def _atualizar_anim(self) -> None:
        if (self.tela == "carregando" and not self.erro) or self.baixando:
            self.anim.set()
        else:
            self.anim.clear()

    def executar(self) -> None:
        layout = Layout(Window(FormattedTextControl(self.render, show_cursor=False), always_hide_cursor=True))
        self.app = Application(
            layout=layout,
            key_bindings=self._teclas(),
            full_screen=True,
            mouse_support=False,
            min_redraw_interval=0.04,
        )
        self.app.ttimeoutlen = 0.05  # Esc responde rápido
        threading.Thread(target=self._pulso, daemon=True).start()
        self.app.run(pre_run=self.iniciar_carga)

    def sair(self) -> None:
        if self.baixando:
            self.cancelar.set()
            self.sair_ao_fim = True
            self.avisar("Cancelando downloads e saindo...", "ansiyellow")
            return
        self._sair_agora()

    def _sair_agora(self) -> None:
        if self.app and self.app.is_running:
            self.app.exit()

    # ---------------- carga de dados ----------------
    def iniciar_carga(self) -> None:
        if self.baixando:
            self.avisar("Aguarde os downloads terminarem antes de atualizar.", "ansiyellow")
            return
        self.erro = None
        self.tela = "carregando"
        self.passos = [[p, "pend", ""] for p in PASSOS]
        self._atualizar_anim()
        threading.Thread(target=self._carga, daemon=True).start()

    def _passo(self, i: int, est: str, detalhe: str = "") -> None:
        self.passos[i] = [PASSOS[i], est, detalhe]
        self.invalidar()

    def _carga(self) -> None:
        passo = 0
        try:
            if self.service is None:
                self._passo(0, "ativo")
                if not CREDENTIALS_FILE.exists():
                    raise FileNotFoundError("Não encontrei credentials.json na pasta do projeto.")
                self._passo(0, "ok")
                passo = 1
                self._passo(1, "ativo")
                self.service = autenticar()
                self._passo(1, "ok")
            else:
                self._passo(0, "ok", "já autenticado")
                self._passo(1, "ok", "sessão ativa")

            passo = 2
            self._passo(2, "ativo")
            if self.turma is None:
                self.turmas = listar_turmas(self.service)
                if not self.turmas:
                    raise JClassError("Nenhuma turma encontrada para esta conta.")
                por_id = {t["id"]: t for t in self.turmas}
                escolhida = por_id.get(self.curso_pref) or (self.turmas[0] if len(self.turmas) == 1 else None)
                if escolhida is None:
                    self._passo(2, "ok", f"{len(self.turmas)} turmas")
                    self.turmas_idx = 0
                    self.tela = "turmas"
                    self._atualizar_anim()
                    self.invalidar()
                    return
                self.turma = escolhida
            self._passo(2, "ok", self.turma["name"])

            passo = 3
            self._passo(3, "ativo")
            brutos = listar_avisos(
                self.service,
                self.turma["id"],
                on_pagina=lambda p, n: self._passo(3, "ativo", f"página {p} · {n} avisos"),
            )
            self._passo(3, "ok", f"{len(brutos)} avisos")

            passo = 4
            self._passo(4, "ativo")
            avisos, itens = extrair_itens(brutos)
            self._aplicar_dados(avisos, itens)
            self._passo(4, "ok", f"{len(itens)} anexos")

            self.tela = "lista"
            if not avisos:
                self.avisar("Nenhum aviso encontrado nesta turma.", "ansiyellow")
            elif not itens:
                self.avisar("Há avisos, mas nenhum anexo ou link.", "ansiyellow")
            else:
                self.avisar(f"{len(itens)} itens carregados de {len(avisos)} avisos.", "ansigreen")
        except Exception as exc:
            self.erro = traduzir_erro(exc, "classroom")
            log_erro(exc)
            self._passo(passo, "erro")
        finally:
            self._atualizar_anim()
            self.invalidar()

    def _aplicar_dados(self, avisos: list[Aviso], itens: list[Item]) -> None:
        antigos = {(i.tipo, i.chave): i for i in self.itens}
        for it in itens:  # preserva marcações e downloads já feitos ao atualizar
            ant = antigos.get((it.tipo, it.chave))
            if ant:
                it.selecionado = ant.selecionado
                if ant.status == "ok":
                    it.status, it.caminho = "ok", ant.caminho
        self.avisos, self.itens = avisos, itens
        self.idx = self.topo = 0
        self.aplicar_filtros()

    def escolher_turma(self) -> None:
        if not self.turmas:
            return
        self.turma = self.turmas[self.turmas_idx]
        self.itens, self.avisos, self.visiveis = [], [], []
        self.busca, self.filtro_tipo = "", 0
        self.iniciar_carga()

    # ---------------- filtros e seleção ----------------
    def item_atual(self) -> Item | None:
        return self.visiveis[self.idx] if 0 <= self.idx < len(self.visiveis) else None

    def aplicar_filtros(self) -> None:
        atual = self.item_atual()
        alvo = TIPOS_FILTRO[self.filtro_tipo][1]
        q = sem_acento(self.busca)
        self.visiveis = [
            i
            for i in self.itens
            if (alvo is None or i.tipo == alvo)
            and (not q or q in sem_acento(f"{i.titulo} {i.aviso.titulo} {i.url}"))
        ]
        if atual in self.visiveis:
            self.idx = self.visiveis.index(atual)
        else:
            self.idx = min(self.idx, max(0, len(self.visiveis) - 1))

    def nav(self, delta: int = 0, para: str = "") -> None:
        def mover(valor: int, n: int) -> int:
            if para == "inicio":
                return 0
            if para == "fim":
                return max(0, n - 1)
            return max(0, min(valor + delta, max(0, n - 1)))

        t = self.tela
        if t == "lista":
            self.idx = mover(self.idx, len(self.visiveis))
        elif t == "turmas":
            self.turmas_idx = mover(self.turmas_idx, len(self.turmas))
        elif t == "menu":
            self.menu_idx = mover(self.menu_idx, len(self.menu_itens))
        elif t == "texto":
            self.texto_topo = mover(self.texto_topo, 100000)
        elif t == "baixando" and self.concluido:
            self.dl_topo = mover(self.dl_topo, len(self.fila))

    def alternar(self) -> None:
        it = self.item_atual()
        if not it:
            return
        if not it.baixavel:
            self.avisar("Links e vídeos não são baixáveis. Enter abre o menu de ações.", "ansiyellow")
            return
        it.selecionado = not it.selecionado
        self.nav(1)

    def marcar_todos(self) -> None:
        n = 0
        for it in self.visiveis:
            if it.baixavel:
                it.selecionado = True
                n += 1
        self.avisar(f"{n} arquivos marcados.", "ansigreen")

    def desmarcar_todos(self) -> None:
        for it in self.itens:
            it.selecionado = False
        self.avisar("Seleção limpa.")

    def ciclar_tipo(self) -> None:
        self.filtro_tipo = (self.filtro_tipo + 1) % len(TIPOS_FILTRO)
        self.aplicar_filtros()

    # ---------------- ações sobre itens ----------------
    def abrir_menu(self) -> None:
        it = self.item_atual()
        if not it:
            return
        ops: list[tuple[str, Callable[[], None]]] = []
        if it.baixavel:
            ops.append(("Baixar este arquivo", lambda: self.pedir_download([it])))
            ops.append(("Desmarcar" if it.selecionado else "Marcar para download", lambda: setattr(it, "selecionado", not it.selecionado)))
            if it.caminho and it.caminho.exists():
                ops.append(("Abrir arquivo baixado", lambda: self.abrir_baixado(it.caminho)))
        ops.append(("Abrir no navegador", lambda: self.abrir_url(it.url)))
        ops.append(("Copiar link", lambda: self.copiar(it.url)))
        ops.append(("Ver aviso completo", lambda: self.abrir_texto(it.aviso)))
        if it.aviso.link:
            ops.append(("Abrir aviso no Classroom", lambda: self.abrir_url(it.aviso.link)))
        ops.append(("Voltar", lambda: None))
        self.menu_itens, self.menu_idx, self.tela = ops, 0, "menu"

    def executar_menu(self) -> None:
        _, fn = self.menu_itens[self.menu_idx]
        self.tela = "lista"
        fn()

    def abrir_texto(self, aviso: Aviso) -> None:
        self.texto_aviso, self.texto_topo, self.tela = aviso, 0, "texto"

    def abrir_url(self, url: str) -> None:
        if not url.lower().startswith(("http://", "https://")):
            self.avisar("Só abro links http(s).", "ansired")
            return
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            self.avisar("Sem ambiente gráfico aqui (TTY). Use 'Copiar link' ou leia a URL no painel.", "ansiyellow")
            return
        self.abrir_externo(url)

    def abrir_baixado(self, caminho: Path) -> None:
        """Dentro do JDesk abre no painel certo; senão, no programa padrão do sistema."""
        if jipc is not None and jipc.enviar({"cmd": "open", "path": str(caminho)}):
            self.avisar("Aberto no JDesk.", "ansigreen")
            return
        self.abrir_externo(str(caminho))

    def abrir_externo(self, alvo: str) -> None:
        opener = shutil.which("xdg-open")
        if not opener:
            self.avisar("xdg-open não encontrado (pacote xdg-utils).", "ansiyellow")
            return
        try:
            subprocess.Popen(
                [opener, alvo],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.avisar("Aberto com xdg-open.", "ansigreen")
        except OSError as exc:
            self.avisar(f"Não consegui abrir: {exc}", "ansired")

    def copiar(self, texto: str) -> None:
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(
                        cmd, input=texto.encode(), check=True, timeout=3,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    self.avisar("Link copiado para a área de transferência.", "ansigreen")
                    return
                except (subprocess.SubprocessError, OSError):
                    continue
        self.avisar("Sem clipboard disponível (wl-copy/xclip/xsel). URL: " + texto, "ansiyellow")

    # ---------------- downloads ----------------
    def k_baixar(self) -> None:
        marcados = [i for i in self.itens if i.selecionado and i.baixavel]
        if marcados:
            self.pedir_download(marcados)
            return
        it = self.item_atual()
        if it and it.baixavel:
            self.pedir_download([it])
        else:
            self.avisar("Nada para baixar: marque arquivos com Espaço.", "ansiyellow")

    def pedir_download(self, itens: list[Item]) -> None:
        itens = [i for i in itens if i.baixavel]
        if not itens:
            self.avisar("Nada baixável na seleção.", "ansiyellow")
            return
        if self.baixando:
            self.avisar("Já existe um download em andamento.", "ansiyellow")
            return
        self.fila = itens
        self.conflitos = sum(1 for i in itens if (self.destino / nome_seguro(i.titulo)).exists())
        self.tela = "confirmar"

    def ciclar_politica(self) -> None:
        nomes = [p[0] for p in POLITICAS]
        self.politica = nomes[(nomes.index(self.politica) + 1) % len(nomes)]

    def confirmar_download(self) -> None:
        for it in self.fila:
            it.status, it.progresso, it.bytes_baixados, it.mensagem = "fila", 0.0, 0, ""
        self._lancar(list(self.fila))

    def tentar_novamente(self) -> None:
        if not self.concluido:
            return
        falhos = [i for i in self.fila if i.status in ("erro", "cancelado")]
        if not falhos:
            self.avisar("Nenhum download com falha.", "ansiyellow")
            return
        for it in falhos:
            it.status, it.progresso, it.bytes_baixados, it.mensagem = "fila", 0.0, 0, ""
        self._lancar(falhos)

    def _lancar(self, fila: list[Item]) -> None:
        self.baixando, self.concluido = True, False
        self.cancelar = threading.Event()
        self.tela, self.dl_topo = "baixando", 0
        self._atualizar_anim()
        threading.Thread(target=self._worker_download, args=(fila, self.cancelar), daemon=True).start()

    def _worker_download(self, fila: list[Item], cancelar: threading.Event) -> None:
        try:
            drive = criar_servico_drive()
        except Exception as exc:
            erro = traduzir_erro(exc, "drive")
            log_erro(exc)
            for it in fila:
                it.status, it.mensagem = "erro", str(erro)
            self._fim_download()
            return

        for it in fila:
            if cancelar.is_set():
                it.status = "cancelado"
                continue
            it.status, it.progresso, it.bytes_baixados = "baixando", 0.0, 0
            self.invalidar()

            def progresso(feito: int, total: int | None, it: Item = it) -> None:
                it.bytes_baixados = feito
                it.progresso = (feito / total) if total else None
                self.invalidar()

            try:
                r = baixar_arquivo(drive, it.chave, it.titulo, self.destino, self.politica, progresso, cancelar)
                it.status, it.mensagem, it.caminho = r.status, r.mensagem, r.caminho
                if r.status in ("ok", "ignorado"):
                    it.selecionado = False
                if r.status == "ok":
                    it.progresso = 1.0
                    if jipc is not None and r.caminho:  # JFiles relê a pasta na hora (≤0,3 s, nunca falha)
                        jipc.enviar({"cmd": "refresh", "path": str(Path(r.caminho).parent)})
            except Exception as exc:
                it.status, it.mensagem = "erro", str(traduzir_erro(exc, "drive"))
                if not isinstance(exc, (JClassError, HttpError)):
                    log_erro(exc)
            self.invalidar()
        self._fim_download()

    def _fim_download(self) -> None:
        self.baixando, self.concluido = False, True
        self.avisar("Download cancelado." if self.cancelar.is_set() else "Download finalizado.",
                    "ansiyellow" if self.cancelar.is_set() else "ansigreen")
        self._atualizar_anim()
        self.invalidar()
        if self.sair_ao_fim and self.app and self.app.loop:
            self.app.loop.call_soon_threadsafe(self._sair_agora)

    def voltar_lista(self) -> None:
        self.tela = "lista"
        self.aplicar_filtros()

    # ---------------- teclado ----------------
    def k_esc(self) -> None:
        t = self.tela
        if t == "lista":
            if self.editando:
                self.editando, self.busca = False, ""
                self.aplicar_filtros()
            elif self.busca:
                self.busca = ""
                self.aplicar_filtros()
            elif self.filtro_tipo:
                self.filtro_tipo = 0
                self.aplicar_filtros()
            elif any(i.selecionado for i in self.itens):
                self.desmarcar_todos()
            else:
                self.avisar("Use q para sair.")
        elif t in ("menu", "texto", "ajuda", "confirmar"):
            self.tela = "lista"
        elif t == "turmas":
            if self.turma is not None:
                self.tela = "lista"
        elif t == "carregando":
            if self.erro and self.turma is not None and self.itens:
                self.erro = None
                self.tela = "lista"
        elif t == "baixando":
            if self.concluido:
                self.voltar_lista()
            else:
                self.cancelar.set()
                self.avisar("Cancelando após o bloco atual...", "ansiyellow")

    def k_enter(self) -> None:
        t = self.tela
        if self.editando:
            self.editando = False
        elif t == "lista":
            self.abrir_menu()
        elif t == "turmas":
            self.escolher_turma()
        elif t == "menu":
            self.executar_menu()
        elif t == "confirmar":
            self.confirmar_download()
        elif t == "baixando" and self.concluido:
            self.voltar_lista()
        elif t in ("texto", "ajuda"):
            self.tela = "lista"

    def k_backspace(self) -> None:
        if self.editando and self.tela == "lista":
            self.busca = self.busca[:-1]
            self.aplicar_filtros()

    def k_atualizar(self) -> None:
        if self.tela == "carregando" and not self.erro:
            return
        self.iniciar_carga()

    def k_turma(self) -> None:
        if self.turmas:
            self.turmas_idx = next((i for i, t in enumerate(self.turmas) if self.turma and t["id"] == self.turma["id"]), 0)
            self.tela = "turmas"

    def _teclas(self) -> KeyBindings:
        kb = KeyBindings()

        def reg(teclas: tuple[str, ...], telas: tuple[str, ...] | None, fn: Callable[[], None],
                ignora_busca: bool = False, eager: bool = False) -> None:
            def filtro() -> bool:
                return (ignora_busca or not self.editando) and (telas is None or self.tela in telas)

            @kb.add(*teclas, filter=Condition(filtro), eager=eager)
            def _(event) -> None:
                self.msg = ""
                fn()
                self.invalidar()

        L = ("lista",)
        reg(("up",), None, lambda: self.nav(-1), True)
        reg(("down",), None, lambda: self.nav(1), True)
        reg(("k",), None, lambda: self.nav(-1))
        reg(("j",), None, lambda: self.nav(1))
        reg(("pageup",), None, lambda: self.nav(-10), True)
        reg(("pagedown",), None, lambda: self.nav(10), True)
        reg(("home", "g"), None, lambda: self.nav(para="inicio"))
        reg(("end", "G"), None, lambda: self.nav(para="fim"))
        reg((" ",), L, self.alternar)
        reg(("a",), L, self.marcar_todos)
        reg(("n",), L, self.desmarcar_todos)
        reg(("/",), L, lambda: setattr(self, "editando", True))
        reg(("tab",), L, self.ciclar_tipo)
        reg(("d",), L, self.k_baixar)
        reg(("c",), L, self.k_turma)
        reg(("?",), L, lambda: setattr(self, "tela", "ajuda"))
        reg(("r",), ("lista", "carregando"), self.k_atualizar)
        reg(("p",), ("confirmar",), self.ciclar_politica)
        reg(("t",), ("baixando",), self.tentar_novamente)
        reg(("escape",), None, self.k_esc, True, eager=True)
        reg(("enter",), None, self.k_enter, True)
        reg(("backspace",), None, self.k_backspace, True)
        reg(("q",), None, self.sair)
        reg(("c-c",), None, self.sair, True)

        @kb.add(Keys.Any, filter=Condition(lambda: self.editando and self.tela == "lista"))
        def _(event) -> None:
            if event.data and event.data.isprintable():
                self.busca += event.data
                self.aplicar_filtros()
                self.invalidar()

        return kb

    # ---------------- renderização ----------------
    def render(self) -> list[tuple[str, str]]:
        size = self.app.output.get_size() if self.app else None
        cols, rows = (size.columns, size.rows) if size else (80, 24)
        if cols < MIN_COLS or rows < MIN_ROWS:
            return [
                ("bold ansired", "Terminal muito pequeno\n"),
                ("", f"Mínimo {MIN_COLS}x{MIN_ROWS}; atual {cols}x{rows}.\nAumente a janela ou pressione q para sair."),
            ]
        corpo_h = rows - 6
        linhas = self._cabecalho(cols)
        corpo = getattr(self, f"_corpo_{self.tela}")(cols, corpo_h)[:corpo_h]
        corpo += [[] for _ in range(corpo_h - len(corpo))]
        linhas += corpo + self._rodape(cols)
        out: list[tuple[str, str]] = []
        for i, linha in enumerate(linhas):
            out.extend(linha)
            if i < len(linhas) - 1:
                out.append(("", "\n"))
        return out

    def _badge(self) -> tuple[str, str]:
        if self.erro:
            return "ERRO", "bold ansired"
        if self.tela == "carregando" or self.baixando:
            return "CARREGANDO", "ansiyellow"
        if self.tela == "baixando" and self.concluido:
            return "CONCLUÍDO", ACC
        return "ONLINE", "ansigreen"

    def _cabecalho(self, cols: int) -> list[list[tuple[str, str]]]:
        g = self.g
        txt, est = self._badge()
        badge = f"{g.ponto} {txt} "
        esq = " JCLASS "
        sub = "  JDev Classroom Manager"
        espaco = max(1, cols - 1 - len(esq) - len(sub) - len(badge))
        l1 = [("bold ansicyan reverse", esq), (DIM, sub), ("", " " * espaco), (est, badge)]
        nome = self.turma["name"] if self.turma else "nenhuma turma selecionada"
        info = f" {g.dot} {len(self.avisos)} avisos {g.dot} {len(self.itens)} anexos" if self.turma else ""
        l2 = [("", " "), ("bold", corta(nome, cols - 2 - len(info))), (DIM, info)]
        return [l1, l2, [(DIM, g.sep * (cols - 1))]]

    def _dicas(self) -> list[tuple[str, str]]:
        g, t = self.g, self.tela
        if t == "lista":
            return [(g.setas, "mover"), ("Espaço", "marcar"), ("d", "baixar"), ("Enter", "ações"), ("/", "buscar"),
                    ("a", "todos"), ("n", "nenhum"), ("Tab", "tipo"), ("r", "atualizar"), ("c", "turma"),
                    ("?", "ajuda"), ("q", "sair")]
        if t == "carregando":
            d = [("r", "tentar de novo")] if self.erro else []
            if self.erro and self.turma and self.itens:
                d.append(("Esc", "voltar"))
            return d + [("q", "sair")]
        if t == "turmas":
            return [(g.setas, "mover"), ("Enter", "escolher"), ("Esc", "voltar"), ("q", "sair")]
        if t == "menu":
            return [(g.setas, "mover"), ("Enter", "executar"), ("Esc", "voltar"), ("q", "sair")]
        if t == "texto":
            return [(g.setas + "/PgUp/PgDn", "rolar"), ("Esc", "voltar"), ("q", "sair")]
        if t == "confirmar":
            return [("Enter", "baixar"), ("p", "se já existir"), ("Esc", "cancelar"), ("q", "sair")]
        if t == "baixando":
            if not self.concluido:
                return [("Esc", "cancelar"), ("q", "cancelar e sair")]
            d = [("Enter", "voltar"), (g.setas, "rolar")]
            if any(i.status in ("erro", "cancelado") for i in self.fila):
                d.insert(1, ("t", "tentar de novo"))
            return d + [("q", "sair")]
        return [("Esc", "voltar"), ("q", "sair")]

    def _rodape(self, cols: int) -> list[list[tuple[str, str]]]:
        sel = sum(1 for i in self.itens if i.selecionado)
        if self.msg:
            msg = [(self.msg_estilo, " " + corta(self.msg, cols - 2))]
        else:
            msg = [(DIM, corta(f" {sel} marcados {self.g.dot} destino: {curto(self.destino)}", cols - 1))]
        dicas: list[tuple[str, str]] = [("", " ")]
        usado = 1
        for tecla, rot in self._dicas():
            tam = len(tecla) + len(rot) + 4  # tecla + " " + rótulo + 3 espaços
            if usado + tam > cols - 1:
                break
            dicas += [("bold ansicyan", tecla), (DIM, f" {rot}   ")]
            usado += tam
        return [[(DIM, self.g.sep * (cols - 1))], msg, dicas]

    # ----- corpo: carregando -----
    def _corpo_carregando(self, cols: int, h: int):
        g = self.g
        spin = g.spin[int(time.monotonic() * 8) % len(g.spin)]
        L: list[list[tuple[str, str]]] = [[], [("bold", "  Iniciando JClass")], []]
        for rot, est, det in self.passos:
            icone, cor = {
                "pend": (g.espera, DIM), "ativo": (spin, "ansiyellow"),
                "ok": (g.ok, "ansigreen"), "erro": (g.erro, "bold ansired"),
            }[est]
            L.append([("", "   "), (cor, pad(icone, 3)), (DIM if est == "pend" else "", pad(rot, 26)), (DIM, corta(det, cols - 34))])
        if self.erro:
            L.append([])
            for i, linha in enumerate(textwrap.wrap(str(self.erro), cols - 6) or [""]):
                L.append([("bold ansired" if i == 0 else "ansired", "   " + linha)])
            if self.erro.detalhe:
                L.append([(DIM, "   " + corta(self.erro.detalhe, cols - 6))])
            L.append([(DIM, f"   Detalhes técnicos em {curto(LOG_FILE)}")])
        return L

    # ----- corpo: turmas -----
    def _corpo_turmas(self, cols: int, h: int):
        L = [[], [("bold", "  Escolha a turma")], []]
        livre = h - 3
        topo = max(0, min(self.turmas_idx - livre // 2, max(0, len(self.turmas) - livre)))
        for i, t in enumerate(self.turmas[topo: topo + livre], start=topo):
            atual = i == self.turmas_idx
            L.append([(estilo("", atual), f" {self.g.ptr if atual else ' '} "),
                      (estilo("bold" if atual else "", atual), pad(t.get("name", "?"), cols - 30)),
                      (estilo(DIM, atual), f" ID {t.get('id', '')}")])
        return L

    # ----- corpo: lista -----
    def _tag(self, it: Item) -> tuple[str, str]:
        if it.tipo == "drive":
            return (Path(it.titulo).suffix.lstrip(".").upper()[:4] or "ARQ"), ACC
        return ("VIDEO", "ansimagenta") if it.tipo == "youtube" else ("LINK", "ansiyellow")

    def _status_item(self, it: Item) -> tuple[str, str]:
        s = it.status
        if s == "baixando":
            return (f"{int((it.progresso or 0) * 100):>3}%" if it.progresso is not None else "baixando"), "ansiyellow"
        return {
            "ok": ("baixado", "ansigreen"), "fila": ("na fila", DIM), "ignorado": ("ignorado", DIM),
            "erro": ("ERRO", "bold ansired"), "cancelado": ("cancelado", "ansiyellow"),
        }.get(s, ("", ""))

    def _linha_item(self, it: Item, atual: bool, cols: int):
        g = self.g
        caixa = ("[x]" if it.selecionado else "[ ]") if it.baixavel else " - "
        tag, cor_tag = self._tag(it)
        stxt, scor = self._status_item(it)
        usavel = cols - 1 - 24
        cw = (usavel - 2) * 38 // 100 if cols >= 100 else 0
        tw = usavel - cw - (2 if cw else 0)
        f = [
            (estilo("", atual), f" {g.ptr if atual else ' '} "),
            (estilo("bold ansigreen" if it.selecionado else (DIM if not it.baixavel else ""), atual), caixa),
            (estilo("", atual), " "),
            (estilo(cor_tag, atual), pad(tag, 5)),
            (estilo("", atual), " "),
            (estilo("bold" if atual else "", atual), pad(it.titulo, tw)),
        ]
        if cw:
            f += [(estilo("", atual), "  "), (estilo(DIM, atual), pad(it.aviso.titulo, cw))]
        f += [(estilo("", atual), " "), (estilo(scor, atual), pad(stxt, 10))]
        return f

    def _corpo_lista(self, cols: int, h: int):
        g = self.g
        abas: list[tuple[str, str]] = [("", " ")]
        for i, (nome, _) in enumerate(TIPOS_FILTRO):
            abas += [("bold ansicyan reverse" if i == self.filtro_tipo else DIM, f" {nome} "), ("", " ")]
        if self.editando or self.busca:
            abas += [("ansiyellow", " /"), ("", self.busca)]
            if self.editando:
                abas.append(("reverse", " "))
        total = len(self.visiveis)
        abas.append((DIM, f"   {self.idx + 1 if total else 0}/{total}"))

        det_n = 3 if h >= 14 else (1 if h >= 9 else 0)
        lista_h = h - 1 - det_n
        if self.idx < self.topo:
            self.topo = self.idx
        if self.idx >= self.topo + lista_h:
            self.topo = self.idx - lista_h + 1
        self.topo = max(0, min(self.topo, max(0, total - lista_h)))

        L = [abas]
        if not self.visiveis:
            vazio = "Nada corresponde ao filtro/busca atual." if self.itens else "Nenhum anexo ou link nesta turma."
            L += [[], [(DIM, "  " + vazio)]]
        for i in range(self.topo, min(total, self.topo + lista_h)):
            L.append(self._linha_item(self.visiveis[i], i == self.idx, cols))
        L += [[] for _ in range(1 + lista_h - len(L))]

        it = self.item_atual()
        if det_n and it:
            nome_tipo = {"drive": "Drive", "link": "Link", "youtube": "YouTube"}[it.tipo]
            det = [[(DIM, " Aviso: "), ("", corta(f"{it.aviso.titulo}  ({it.aviso.data})", cols - 10))]]
            if det_n == 3:
                det.append([(DIM, f" {nome_tipo}: "), ("", corta(it.url, cols - 12))])
                if it.status == "erro":
                    det.append([("bold ansired", " Erro: "), ("ansired", corta(it.mensagem, cols - 9))])
                elif it.status == "ok" and it.caminho:
                    det.append([("ansigreen", " Salvo em: "), ("", corta(curto(it.caminho), cols - 14))])
                else:
                    det.append([(DIM, " Enter: ações do item (baixar, abrir, copiar link, ver aviso)")])
            L += det
        return L

    # ----- corpo: menu / texto / ajuda / confirmar -----
    def _corpo_menu(self, cols: int, h: int):
        it = self.item_atual()
        L = [[], [("bold", "  " + corta(it.titulo if it else "", cols - 4))],
             [(DIM, "  " + corta(f"Aviso: {it.aviso.titulo}" if it else "", cols - 4))], []]
        for i, (rot, _) in enumerate(self.menu_itens):
            atual = i == self.menu_idx
            L.append([(estilo(ACC, atual), f"  {self.g.ptr if atual else ' '} "), (estilo("bold" if atual else "", atual), pad(rot, 32))])
        return L

    def _corpo_texto(self, cols: int, h: int):
        av = self.texto_aviso
        if not av:
            return []
        linhas: list[str] = []
        for par in (av.texto or "(aviso sem texto)").splitlines():
            linhas += textwrap.wrap(par, cols - 6) or [""]
        livre = h - 3
        self.texto_topo = max(0, min(self.texto_topo, max(0, len(linhas) - livre)))
        L = [[("bold", "  " + corta(av.titulo, cols - 4))], [(DIM, f"  {av.data}")], []]
        for linha in linhas[self.texto_topo: self.texto_topo + livre]:
            L.append([("", "   " + linha)])
        return L

    def _corpo_ajuda(self, cols: int, h: int):
        teclas = [
            (f"{self.g.setas} / j k", "navegar"), ("PgUp PgDn Home End", "pular"), ("Espaço", "marcar/desmarcar arquivo"),
            ("a / n", "marcar todos visíveis / desmarcar tudo"), ("/", "buscar por título (Enter fixa, Esc limpa)"),
            ("Tab", "alternar Tudo/Arquivos/Links/Vídeos"), ("Enter", "menu de ações do item"),
            ("d", "baixar marcados (ou o item atual)"), ("c", "trocar de turma"), ("r", "atualizar dados da turma"),
            ("Esc", "voltar / limpar busca / limpar seleção"), ("q", "sair com segurança"),
        ]
        L = [[], [("bold", "  Atalhos")], []]
        for k, d in teclas:
            L.append([("bold ansicyan", "  " + pad(k, 22)), ("", corta(d, cols - 26))])
        L += [[], [(DIM, corta("  Links e vídeos são só listados: abra ou copie pelo menu (Enter).", cols - 1))],
              [(DIM, corta("  Arquivos existentes nunca são sobrescritos sem você escolher 'substituir'.", cols - 1))]]
        return L

    def _corpo_confirmar(self, cols: int, h: int):
        g = self.g
        L = [[], [("bold", f"  Baixar {len(self.fila)} arquivo(s)")],
             [(DIM, "  Destino: "), ("", corta(curto(self.destino), cols - 14))], [],
             [("", "  Se o arquivo já existir:")]]
        for nome, desc in POLITICAS:
            ativo = nome == self.politica
            L.append([("bold ansicyan" if ativo else DIM, f"   ({'*' if ativo else ' '}) {pad(nome, 11)}"), (DIM, desc)])
        if self.conflitos:
            L += [[], [("ansiyellow", f"  {self.conflitos} arquivo(s) com o mesmo nome já estão na pasta.")]]
        if self.politica == "substituir":
            L.append([("bold ansired", "  ATENÇÃO: arquivos existentes serão sobrescritos.")])
        L.append([])
        livre = h - len(L)
        for it in self.fila[:livre]:
            L.append([(DIM, f"   {g.dot} "), ("", corta(it.titulo, cols - 8))])
        if len(self.fila) > livre > 0:
            L[-1] = [(DIM, f"   ... e mais {len(self.fila) - livre + 1} arquivo(s)")]
        return L

    # ----- corpo: baixando -----
    def barra(self, frac: float, w: int) -> str:
        n = max(0, min(w, int(round(frac * w))))
        return self.g.cheio * n + self.g.vazio * (w - n)

    def _corpo_baixando(self, cols: int, h: int):
        g = self.g
        fila, total = self.fila, len(self.fila)
        feitos = sum(1 for i in fila if i.status in FINAIS)
        atual = next((i for i in fila if i.status == "baixando"), None)
        parcial = (atual.progresso or 0.0) if atual else 0.0
        geral = (feitos + parcial) / total if total else 1.0
        titulo = "Baixando arquivos" if self.baixando else "Download finalizado"
        bw = max(10, min(40, cols - 24))
        L = [[("", "  "), ("bold", titulo), (DIM, f"   {feitos}/{total}")],
             [("", "  geral "), (ACC, self.barra(geral, bw)), ("", f" {int(geral * 100):>3}%")], []]

        extra = 6 if self.concluido else 1
        lista_h = max(1, h - len(L) - extra)
        if self.baixando:
            foco = fila.index(atual) if atual else 0
            self.dl_topo = max(0, min(foco - lista_h // 2, max(0, total - lista_h)))
        else:
            self.dl_topo = max(0, min(self.dl_topo, max(0, total - lista_h)))

        rw = 30
        tw = cols - 1 - 6 - rw
        spin = g.spin[int(time.monotonic() * 8) % len(g.spin)]
        linhas = []
        for it in fila[self.dl_topo: self.dl_topo + lista_h]:
            icone, cor = {
                "": (g.espera, DIM), "fila": (g.espera, DIM), "baixando": (spin, "ansiyellow"), "ok": (g.ok, "ansigreen"),
                "erro": (g.erro, "bold ansired"), "ignorado": ("-", DIM), "cancelado": ("!", "ansiyellow"),
            }[it.status]
            if it.status == "baixando":
                if it.progresso is not None:
                    dire = f"{self.barra(it.progresso, 12)} {int(it.progresso * 100):>3}% {fmt_bytes(it.bytes_baixados)}"
                else:
                    dire = f"exportando {fmt_bytes(it.bytes_baixados)}"
                dcor = "ansiyellow"
            else:
                dire, dcor = self._status_item(it)
                if it.status == "ok" and it.caminho:
                    dire += f" {fmt_bytes(it.caminho.stat().st_size) if it.caminho.exists() else ''}"
            linhas.append([("", "  "), (cor, pad(icone, 3)), ("", pad(it.titulo, tw)), (dcor, " " + pad(dire, rw - 1))])
        L += linhas
        L += [[] for _ in range(h - len(L) - extra)]

        if self.concluido:
            cont = {s: sum(1 for i in fila if i.status == s) for s in FINAIS}
            tot_bytes = sum(i.caminho.stat().st_size for i in fila if i.status == "ok" and i.caminho and i.caminho.exists())
            L.append([("bold", "  Resumo: "), ("ansigreen", f"{cont['ok']} ok"), (DIM, f" {g.dot} {cont['ignorado']} ign. {g.dot} "),
                      ("bold ansired" if cont["erro"] else DIM, f"{cont['erro']} erros"), (DIM, f" {g.dot} {cont['cancelado']} canc. {g.dot} {fmt_bytes(tot_bytes)}")])
            falhas = [i for i in fila if i.status == "erro"]
            for it in falhas[:3]:
                L.append([("ansired", f"  {g.erro} "), ("", corta(it.titulo, 28)), (DIM, ": "), ("ansired", corta(it.mensagem, cols - 38))])
            if len(falhas) > 3:
                L.append([(DIM, f"  (+{len(falhas) - 3} erros; role a lista com {g.setas})")])
            L.append([(DIM, f"  Pasta: {corta(curto(self.destino), cols - 12)}")])
        else:
            L.append([(DIM, f"  Pasta: {corta(curto(self.destino), cols - 12)}")])
        return L


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jclass", description="JClass — JDev Classroom Manager")
    p.add_argument("--curso", help=f"ID da turma (padrão: {COURSE_ID_PADRAO})")
    p.add_argument("--destino", help="pasta de downloads (padrão: ./downloads/<nome da turma>)")
    p.add_argument("--ascii", action="store_true", help="força símbolos ASCII (automático no console TERM=linux)")
    return p.parse_args()


def garantir_autorizacao() -> bool:
    """Só chega ao navegador se NÃO houver token utilizável, e apenas com confirmação."""
    estado = estado_token()
    if estado == "ok":
        return True
    if estado == "sem_credentials":
        print(f"Não encontrei {CREDENTIALS_FILE.name} em {BASE}.\n"
              "Baixe o OAuth client (Desktop) no Google Cloud Console e salve com esse nome.")
        return False
    motivos = {
        "sem_token": "Ainda não há token.json (primeira execução).",
        "token_invalido": "O token.json existe, mas está ilegível.",
        "reautorizar": "O token.json expirou e não pode ser renovado.",
    }
    print(motivos[estado])
    if input("Abrir o navegador para autorizar agora? [s/N] ").strip().lower() not in ("s", "sim", "y"):
        return False
    try:
        autenticar()
    except Exception as exc:
        log_erro(exc)
        print(f"Falha na autorização: {traduzir_erro(exc)}")
        return False
    return True


def main() -> int:
    args = parse_args()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("O JClass precisa de um terminal interativo.")
        return 1
    if not garantir_autorizacao():
        return 1
    app = JClass(args)
    try:
        app.executar()
    except KeyboardInterrupt:
        pass
    baixados = [i for i in app.itens if i.status == "ok"]
    if baixados:
        print(f"{len(baixados)} arquivo(s) em {curto(app.destino)}")
    print("Até logo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
