#!/usr/bin/env python3
"""
jipc - canal de mensagens entre os programas do JDev dentro do JDesk (Fase 3).

Como funciona
  * O JDesk sobe um servidor TCP em 127.0.0.1 (porta aleatória) e entrega aos panes
    as variáveis JDESK_SOCK="127.0.0.1:PORTA" e JDESK_TOKEN (segredo da sessão),
    além de JDESK_WS (workspace) e JDESK_PANE (nome do pane).
  * Quem QUER AVISAR alguém usa  enviar({...}) -> bool   (conexão curta, ~0,3 s).
  * Quem QUER RECEBER usa  Receptor("jfiles", callback).iniciar()  (thread; reconecta sozinho).
  * Fora do JDesk (sem JDESK_SOCK) tudo vira no-op: enviar() devolve False e Receptor
    não faz nada. Assim cada programa pode cair no comportamento antigo.

Mensagens (JSON, uma por linha)
  {"cmd":"open","path":"/x/a.py"}                 abre no JCode (ou no visualizador, por extensão)
  {"cmd":"open","path":"...","target":"jcode","focus":false}
  {"cmd":"focus","target":"jfiles"}               leva o foco do teclado para um pane
  {"cmd":"refresh","path":"/pasta"}               avisa todos os JFiles para relerem
Toda mensagem leva "token" (checado pelo servidor), "ws" e "de" (preenchidos aqui).
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import secrets
import socket
import threading
from typing import Callable

LIMITE_LINHA = 65536


# ══════════════════════════════════════════════════════════════════════════════
#  Cliente
# ══════════════════════════════════════════════════════════════════════════════
def _destino():
    sock, tok = os.environ.get("JDESK_SOCK"), os.environ.get("JDESK_TOKEN")
    if not sock or not tok:
        return None
    host, _, porta = sock.rpartition(":")
    try:
        return host or "127.0.0.1", int(porta), tok
    except ValueError:
        return None


def disponivel() -> bool:
    """True se este processo foi iniciado por um JDesk."""
    return _destino() is not None


def _completar(msg: dict, tok: str) -> dict:
    m = dict(msg)
    m["token"] = tok
    m.setdefault("ws", os.environ.get("JDESK_WS"))
    m.setdefault("de", os.environ.get("JDESK_PANE"))
    return m


def _ler_linha(s: socket.socket) -> bytes:
    buf = b""
    while b"\n" not in buf and len(buf) < LIMITE_LINHA:
        parte = s.recv(4096)
        if not parte:
            break
        buf += parte
    return buf.split(b"\n", 1)[0]


def enviar(msg: dict, timeout: float = 0.3) -> bool:
    """Envia uma mensagem ao JDesk. True só se ele aceitou e entregou.
    Nunca levanta exceção e nunca bloqueia por mais que `timeout`."""
    d = _destino()
    if not d:
        return False
    host, porta, tok = d
    try:
        with socket.create_connection((host, porta), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(_completar(msg, tok), ensure_ascii=False) + "\n").encode("utf-8"))
            resp = _ler_linha(s)
        return bool(resp) and bool(json.loads(resp).get("ok"))
    except Exception:
        return False


class Receptor:
    """Conecta ao JDesk, registra este programa pelo nome e chama ao_receber(msg)
    (em outra thread!) para cada mensagem. Reconecta se a conexão cair."""

    def __init__(self, nome: str, ao_receber: Callable[[dict], None]):
        self.nome = nome
        self.ao_receber = ao_receber
        self._parar = threading.Event()
        self._thread = None

    def iniciar(self) -> bool:
        if not disponivel() or self._thread:
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"jipc-{self.nome}")
        self._thread.start()
        return True

    def parar(self) -> None:
        self._parar.set()

    def _loop(self) -> None:
        while not self._parar.is_set():
            d = _destino()
            if d:
                host, porta, tok = d
                try:
                    with socket.create_connection((host, porta), timeout=2) as s:
                        s.settimeout(None)
                        reg = _completar({"cmd": "register", "name": self.nome}, tok)
                        s.sendall((json.dumps(reg) + "\n").encode("utf-8"))
                        self._ler(s)
                except OSError:
                    pass
            if self._parar.wait(1.0):  # tenta reconectar
                return

    def _ler(self, s: socket.socket) -> None:
        buf = b""
        while not self._parar.is_set():
            parte = s.recv(4096)
            if not parte:
                return
            buf += parte
            if len(buf) > LIMITE_LINHA * 4:
                return
            while b"\n" in buf:
                linha, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(linha)
                except ValueError:
                    continue
                if "cmd" not in msg:  # confirmação do registro etc.
                    continue
                try:
                    self.ao_receber(msg)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
#  Servidor (usado pelo JDesk)
# ══════════════════════════════════════════════════════════════════════════════
class Servidor:
    """Aceita conexões locais. Mensagens de comando vão para `self.fila` (o JDesk as
    consome na thread do Tk e responde com responder()). Registros de Receptor ficam
    em self.clientes, e entregar() empurra mensagens para eles."""

    def __init__(self):
        self.token = secrets.token_hex(16)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.porta = self.sock.getsockname()[1]
        self.fila: "queue.Queue[tuple[dict, socket.socket]]" = queue.Queue()
        self.clientes: dict[tuple[str, str], socket.socket] = {}
        self.lock = threading.Lock()
        self.fechado = False

    def env(self) -> dict:
        return {"JDESK_SOCK": f"127.0.0.1:{self.porta}", "JDESK_TOKEN": self.token}

    def iniciar(self) -> None:
        threading.Thread(target=self._aceitar, daemon=True, name="jipc-server").start()

    def fechar(self) -> None:
        self.fechado = True
        try:
            self.sock.close()
        except OSError:
            pass
        with self.lock:
            for c in self.clientes.values():
                try:
                    c.close()
                except OSError:
                    pass
            self.clientes.clear()

    def _aceitar(self) -> None:
        while not self.fechado:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._atender, args=(conn,), daemon=True).start()

    def _atender(self, conn: socket.socket) -> None:
        registro = None
        buf = b""
        try:
            conn.settimeout(5)  # quem conecta e não fala nada não prende a thread
            while not self.fechado:
                parte = conn.recv(4096)
                if not parte:
                    break
                buf += parte
                if len(buf) > LIMITE_LINHA and b"\n" not in buf:
                    break
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(linha)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict) or not hmac.compare_digest(
                            str(msg.get("token", "")), self.token):
                        return  # token errado: derruba a conexão
                    if msg.get("cmd") == "register":
                        registro = (str(msg.get("ws") or ""), str(msg.get("name") or ""))
                        with self.lock:
                            self.clientes[registro] = conn
                        self.responder(conn, True)
                        conn.settimeout(None)  # receptor fica pendurado esperando mensagens
                    else:
                        self.fila.put((msg, conn))
        except OSError:
            pass
        finally:
            if registro:
                with self.lock:
                    if self.clientes.get(registro) is conn:
                        del self.clientes[registro]
            try:  # sempre fecha: token errado, EOF, timeout ou receptor que caiu
                conn.close()
            except OSError:
                pass

    # ── chamadas feitas pela thread do Tk ──
    @staticmethod
    def responder(conn: socket.socket, ok: bool, erro: str = "") -> None:
        try:
            conn.sendall((json.dumps({"ok": ok, "erro": erro}) + "\n").encode("utf-8"))
        except OSError:
            pass

    def entregar(self, ws: str, nome: str, msg: dict) -> bool:
        """Empurra msg para o Receptor `nome` do workspace `ws`. False se não houver."""
        with self.lock:
            conn = self.clientes.get((str(ws), nome))
        if not conn:
            return False
        try:
            conn.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except OSError:
            with self.lock:
                if self.clientes.get((str(ws), nome)) is conn:
                    del self.clientes[(str(ws), nome)]
            return False

    def difundir(self, nome: str, msg: dict) -> int:
        """Entrega a todos os Receptores com esse nome (em qualquer workspace)."""
        with self.lock:
            alvos = [ws for (ws, n) in self.clientes if n == nome]
        return sum(1 for ws in alvos if self.entregar(ws, nome, msg))
