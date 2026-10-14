"""Consultas ao Google Classroom, extração de anexos e tradução de erros."""
from __future__ import annotations

import json
import re
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

ESCOPO_CLASSROOM = "https://www.googleapis.com/auth/classroom.announcements.readonly"
ESCOPO_DRIVE = "https://www.googleapis.com/auth/drive.readonly"
SEM_TITULO = "Aviso sem título"

ERROS_REDE = (
    ServerNotFoundError,
    socket.gaierror,
    socket.timeout,
    ConnectionError,
    TimeoutError,
    ssl.SSLError,
    TransportError,
)


# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------
class JClassError(Exception):
    """Erro esperado, com mensagem pronta para o usuário."""

    def __init__(self, mensagem: str, detalhe: str = "") -> None:
        super().__init__(mensagem)
        self.detalhe = detalhe


def _corpo_http(exc: HttpError) -> str:
    try:
        erro = json.loads(exc.content.decode("utf-8", "replace")).get("error", {})
    except Exception:
        return ""
    if not isinstance(erro, dict):
        return str(erro)
    partes = [erro.get("status", ""), erro.get("message", "")]
    partes += [e.get("reason", "") for e in erro.get("errors", []) if isinstance(e, dict)]
    partes += [str(d.get("reason", "")) for d in erro.get("details", []) if isinstance(d, dict)]
    return " ".join(str(p) for p in partes if p)


def traduzir_erro(exc: BaseException, contexto: str = "classroom") -> JClassError:
    """Converte exceções da API/rede em mensagens claras e práticas."""
    if isinstance(exc, JClassError):
        return exc

    api = "Drive" if contexto == "drive" else "Classroom"

    if isinstance(exc, HttpError):
        codigo = int(exc.resp.status)
        bruto = _corpo_http(exc)
        b = bruto.lower()
        det = f"HTTP {codigo}: {bruto}".strip()

        if "scope_insufficient" in b or "insufficient authentication scopes" in b:
            escopo = ESCOPO_DRIVE if contexto == "drive" else ESCOPO_CLASSROOM
            return JClassError(
                f"Falta permissão (escopo) para o {api}: {escopo}. Confira SCOPES em "
                "testar_classroom.py e a tela de consentimento OAuth; depois remova "
                "apenas o token.json e rode de novo para reautorizar.",
                det,
            )
        if codigo == 401:
            return JClassError(
                "Credenciais recusadas (401). O token pode ter expirado ou sido revogado: "
                "remova apenas o token.json e rode de novo para reautorizar.",
                det,
            )
        if codigo == 429 or "ratelimit" in b or "quota" in b:
            return JClassError("Limite de requisições do Google atingido. Aguarde um pouco e tente de novo.", det)
        if codigo == 403:
            if "accessnotconfigured" in b or "service_disabled" in b or "has not been used" in b:
                return JClassError(f"A API do {api} não está ativada no projeto do Google Cloud.", det)
            if "exportsizelimit" in b:
                return JClassError("Documento grande demais para exportação pela API (limite de 10 MB).", det)
            if any(x in b for x in ("cannotdownload", "downloadrestricted", "filenotdownloadable")):
                return JClassError("O dono do arquivo bloqueou o download deste item.", det)
            if contexto == "drive":
                return JClassError("Sem permissão (403): este arquivo não está acessível para a sua conta.", det)
            return JClassError("Acesso negado (403): sua conta precisa fazer parte da turma.", det)
        if codigo == 404:
            if contexto == "drive":
                return JClassError(
                    "Arquivo não encontrado (404). O Drive responde assim também quando "
                    "a conta não tem acesso; ele pode ter sido removido ou não compartilhado.",
                    det,
                )
            return JClassError("Turma ou recurso não encontrado (404).", det)
        if codigo >= 500:
            return JClassError(f"O {api} está indisponível no momento ({codigo}). Tente de novo mais tarde.", det)
        return JClassError(f"Erro {codigo} retornado pelo {api}.", det)

    if isinstance(exc, RefreshError):
        return JClassError(
            "Não foi possível renovar o token (expirado ou revogado). Remova apenas o "
            "token.json e rode de novo para reautorizar. Obs.: apps OAuth em modo "
            "'Teste' perdem a autorização a cada 7 dias.",
            repr(exc),
        )
    if isinstance(exc, FileNotFoundError):
        return JClassError(str(exc))
    if isinstance(exc, ERROS_REDE):
        return JClassError(
            "Sem conexão com a internet (ou Google inacessível). Nada local foi apagado; tente de novo.",
            repr(exc),
        )
    return JClassError(f"{type(exc).__name__}: {exc}", repr(exc))


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
@dataclass(eq=False)
class Aviso:
    id: str
    titulo: str
    texto: str
    data: str
    link: str


@dataclass(eq=False)
class Item:
    tipo: str  # "drive" | "link" | "youtube"
    titulo: str
    chave: str  # id do Drive, id do vídeo ou URL normalizada
    url: str
    aviso: Aviso
    selecionado: bool = False
    status: str = ""  # "", fila, baixando, ok, ignorado, erro, cancelado
    progresso: float | None = 0.0  # None = tamanho desconhecido
    bytes_baixados: int = 0
    mensagem: str = ""
    caminho: Path | None = None

    @property
    def baixavel(self) -> bool:
        return self.tipo == "drive"


# --------------------------------------------------------------------------
# Consultas (paginadas)
# --------------------------------------------------------------------------
def _paginar(
    montar: Callable[[str | None], Any],
    chave: str,
    contexto: str = "classroom",
    on_pagina: Callable[[int, int], None] | None = None,
) -> list[dict]:
    itens: list[dict] = []
    token: str | None = None
    pagina = 0
    try:
        while True:
            resp = montar(token).execute(num_retries=3)
            itens.extend(resp.get(chave, []))
            pagina += 1
            if on_pagina:
                on_pagina(pagina, len(itens))
            token = resp.get("nextPageToken")
            if not token:
                return itens
    except Exception as exc:  # traduzido para mensagem amigável
        raise traduzir_erro(exc, contexto) from exc


def listar_turmas(service: Any) -> list[dict]:
    return _paginar(lambda t: service.courses().list(pageSize=100, pageToken=t), "courses")


def listar_avisos(
    service: Any, course_id: str, on_pagina: Callable[[int, int], None] | None = None
) -> list[dict]:
    return _paginar(
        lambda t: service.courses().announcements().list(courseId=course_id, pageSize=100, pageToken=t),
        "announcements",
        on_pagina=on_pagina,
    )


# --------------------------------------------------------------------------
# Extração
# --------------------------------------------------------------------------
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_YT = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^\s&]*&)*v=|embed/|shorts/|live/)|youtu\.be/)([\w-]{11})")
_DRIVE = re.compile(
    r"(?:drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^\s&]*&)*id=)"
    r"|docs\.google\.com/(?:document|spreadsheets|presentation|drawings)/d/)([\w-]{20,})"
)


def _titulo_aviso(texto: str) -> str:
    for linha in texto.splitlines():
        limpa = " ".join(linha.split())
        if limpa:
            return limpa if len(limpa) <= 70 else limpa[:67] + "..."
    return SEM_TITULO


def _data(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 else ""


def extrair_itens(brutos: list[dict]) -> tuple[list[Aviso], list[Item]]:
    """Transforma os avisos da API em avisos + itens únicos (sem duplicatas)."""
    avisos: list[Aviso] = []
    itens: list[Item] = []
    vistos: set[tuple[str, str]] = set()

    def novo(tipo: str, titulo: str, chave: str, url: str, aviso: Aviso) -> None:
        if (tipo, chave) in vistos:
            return
        vistos.add((tipo, chave))
        itens.append(Item(tipo=tipo, titulo=titulo, chave=chave, url=url, aviso=aviso))

    def por_url(titulo: str, url: str, aviso: Aviso) -> None:
        url = url.strip()
        if not url:
            return
        if m := _DRIVE.search(url):
            novo("drive", titulo if titulo != url else f"Arquivo do Drive ({m.group(1)[:8]})", m.group(1), url, aviso)
        elif m := _YT.search(url):
            novo("youtube", titulo or "Vídeo do YouTube", m.group(1), url, aviso)
        else:
            novo("link", titulo or url, url.rstrip("/"), url, aviso)

    for bruto in brutos:
        texto = (bruto.get("text") or "").strip()
        aviso = Aviso(
            id=bruto.get("id", ""),
            titulo=_titulo_aviso(texto),
            texto=texto,
            data=_data(bruto.get("updateTime") or bruto.get("creationTime") or ""),
            link=bruto.get("alternateLink", ""),
        )
        avisos.append(aviso)

        for mat in bruto.get("materials") or []:
            if "driveFile" in mat:
                arq = (mat["driveFile"] or {}).get("driveFile") or {}
                fid = arq.get("id")
                if fid:
                    novo(
                        "drive",
                        arq.get("title") or "Arquivo sem nome",
                        fid,
                        arq.get("alternateLink") or f"https://drive.google.com/file/d/{fid}/view",
                        aviso,
                    )
            elif "youtubeVideo" in mat:
                v = mat["youtubeVideo"] or {}
                if vid := v.get("id"):
                    novo(
                        "youtube",
                        v.get("title") or "Vídeo do YouTube",
                        vid,
                        v.get("alternateLink") or f"https://www.youtube.com/watch?v={vid}",
                        aviso,
                    )
            elif "link" in mat:
                lk = mat["link"] or {}
                por_url(lk.get("title") or lk.get("url") or "", lk.get("url") or "", aviso)
            elif "form" in mat:
                fm = mat["form"] or {}
                por_url(fm.get("title") or "Formulário", fm.get("formUrl") or "", aviso)

        for url in _URL.findall(texto):
            url = url.rstrip(".,;:!?")
            por_url(url, url, aviso)

    return avisos, itens
