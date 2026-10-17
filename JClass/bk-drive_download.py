"""Download de anexos pela Drive API: em blocos, com exportação e política de conflitos."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from classroom_api import ERROS_REDE, JClassError, traduzir_erro
from testar_classroom import TOKEN_FILE

CHUNK = 1024 * 1024  # 1 MiB por bloco: memória baixa e progresso real
PREFIXO_GOOGLE = "application/vnd.google-apps."

# Formatos de exportação para documentos nativos do Google (edite à vontade).
# A API limita a exportação a 10 MB por arquivo.
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORTACOES: dict[str, tuple[str, str]] = {
    PREFIXO_GOOGLE + "document": ("application/pdf", ".pdf"),
    PREFIXO_GOOGLE + "presentation": ("application/pdf", ".pdf"),
    PREFIXO_GOOGLE + "drawing": ("application/pdf", ".pdf"),
    PREFIXO_GOOGLE + "spreadsheet": (XLSX, ".xlsx"),
}
NAO_BAIXAVEIS = {
    PREFIXO_GOOGLE + "folder": "É uma pasta do Drive; abra pelo navegador.",
    PREFIXO_GOOGLE + "form": "Formulário do Google não pode ser baixado; abra pelo navegador.",
    PREFIXO_GOOGLE + "shortcut": "É um atalho do Drive; abra pelo navegador.",
}


@dataclass
class Resultado:
    status: str  # ok | ignorado | cancelado
    caminho: Path | None
    mensagem: str = ""
    bytes: int = 0


def criar_servico_drive() -> Any:
    """Cria o cliente do Drive reutilizando o token.json existente (somente leitura)."""
    if not TOKEN_FILE.exists():
        raise JClassError("token.json não encontrado. Execute o JClass para autorizar primeiro.")
    # Sem 'scopes': a renovação usa exatamente o que foi concedido, e um escopo
    # faltante aparece como erro 403 claro na chamada, em vez de falha de refresh.
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def nome_seguro(nome: str) -> str:
    """Nome de arquivo válido no Linux, sem separadores de caminho nem controles."""
    limpo = "".join("_" if (c in "/\\" or ord(c) < 32) else c for c in nome).strip().lstrip(".")
    p = Path(limpo)
    stem, ext = p.stem, p.suffix
    while len((stem + ext).encode()) > 240 and stem:
        stem = stem[:-1]
    return (stem + ext) or "arquivo"


def caminho_livre(destino: Path) -> Path:
    """Devolve 'nome (1).ext', 'nome (2).ext'... até achar um nome livre."""
    n = 1
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def _transferir(
    req: Any,
    destino: Path,
    ao_progredir: Callable[[int, int | None], None],
    cancelar: threading.Event,
) -> Resultado:
    parcial = destino.with_name(destino.name + ".part")
    concluido = False
    try:
        with open(parcial, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req, chunksize=CHUNK)
            feito = False
            while not feito:
                if cancelar.is_set():
                    return Resultado("cancelado", None, "cancelado pelo usuário")
                status, feito = dl.next_chunk(num_retries=3)
                if status:
                    ao_progredir(status.resumable_progress, status.total_size)
        os.replace(parcial, destino)
        concluido = True
        return Resultado("ok", destino, "", destino.stat().st_size)
    finally:
        if not concluido:
            parcial.unlink(missing_ok=True)  # nunca deixa arquivo parcial para trás


def baixar_arquivo(
    drive: Any,
    file_id: str,
    titulo: str,
    pasta: Path,
    politica: str,  # "renomear" | "ignorar" | "substituir"
    ao_progredir: Callable[[int, int | None], None],
    cancelar: threading.Event,
) -> Resultado:
    try:
        meta = (
            drive.files()
            .get(fileId=file_id, fields="id,name,mimeType,size", supportsAllDrives=True)
            .execute(num_retries=2)
        )
        mime = meta.get("mimeType", "")
        nome = nome_seguro(meta.get("name") or titulo)

        if mime.startswith(PREFIXO_GOOGLE):
            if mime in NAO_BAIXAVEIS:
                raise JClassError(NAO_BAIXAVEIS[mime])
            if mime not in EXPORTACOES:
                raise JClassError(f"Tipo nativo do Google sem exportação suportada ({mime}).")
            mime_exp, ext = EXPORTACOES[mime]
            if not nome.lower().endswith(ext):
                nome += ext
            req = drive.files().export_media(fileId=file_id, mimeType=mime_exp)
        else:
            req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)

        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / nome
        if destino.exists():
            if politica == "ignorar":
                return Resultado("ignorado", destino, "já existe; ignorado")
            if politica == "renomear":
                destino = caminho_livre(destino)
            # "substituir": decisão explícita do usuário na tela de confirmação

        return _transferir(req, destino, ao_progredir, cancelar)

    except JClassError:
        raise
    except Exception as exc:
        if isinstance(exc, OSError) and not isinstance(exc, ERROS_REDE):
            raise JClassError(f"Erro de disco em {pasta}: {exc.strerror or exc}") from exc
        raise traduzir_erro(exc, "drive") from exc
