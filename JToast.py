#!/usr/bin/env python3
"""
JToast - notificações do JDev.

Fala o protocolo de notificações do desktop (org.freedesktop.Notifications, D-Bus): tudo que usa
`notify-send` ou uma biblioteca de notificação do sistema passa por aqui e aparece como um balão
no canto superior direito do monitor principal. Clicar no balão fecha.

  python3 JToast.py            sobe o serviço (precisa de:  pip install jeepney)
  python3 JToast.py --demo     mostra balões de exemplo, sem D-Bus (testa só o visual)
  notify-send "Oi" "corpo"     (pacote libnotify) manda uma notificação de teste

Princípios:
  * o núcleo (Gerente) é puro e testado: ids, substituição, tempo de vida, limite de enxurrada;
  * texto de fora nunca é confiável: tags viram texto, controles somem, tamanho é limitado;
  * a interface só lê o Gerente; o D-Bus roda em outra thread e nunca toca no Tk;
  * se outro daemon de notificação já está ativo (dunst, mako...), avisa e sai sem brigar.

Estado para a JBar: ~/.cache/jtoast-state.json  ({"pid": N, "count": quantidade_na_tela}).
"""
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

VERSAO = "0.1.0"
NOME_BUS = "org.freedesktop.Notifications"
CAMINHO_BUS = "/org/freedesktop/Notifications"

# ── Ajustes ──────────────────────────────────────────────────────────────────
MAX_VISIVEIS = 5            # balões na tela ao mesmo tempo (os mais novos)
MAX_GUARDADAS = 50          # teto de notificações vivas (as mais antigas expiram)
ESPERA_NORMAL = 6.0         # segundos na tela (urgência normal)
ESPERA_BAIXA = 4.0
ESPERA_MAXIMA = 60.0        # nem um pedido explícito passa disso (0 = fica até clicar)
LIMITE_RESUMO = 120
LIMITE_CORPO = 400
LINHAS_CORPO = 6
ENXURRADA = (20, 2.0)       # mais de 20 notificações do mesmo app em 2 s: o excesso é descartado
LARGURA = 340
MARGEM = 16
ESPACO = 8
TICK_MS = 200

RE_TAG = re.compile(r"<[^>]*>")
RE_CONTROLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MOTIVO_EXPIROU, MOTIVO_CLIQUE, MOTIVO_CHAMADA, MOTIVO_OUTRO = 1, 2, 3, 4


# ══════════════════════════════════════════════════════════════════════════════
#  Núcleo (sem Tk e sem D-Bus: fácil de testar)
# ══════════════════════════════════════════════════════════════════════════════
def limpar_texto(texto, limite: int, linhas: int = 1) -> str:
    """Texto de fora -> texto seguro: sem tags, sem caracteres de controle, tamanho limitado."""
    if not isinstance(texto, str):
        texto = "" if texto is None else str(texto)
    texto = html.unescape(RE_TAG.sub("", texto))
    texto = RE_CONTROLE.sub("", texto).replace("\r", "")
    partes = [p.strip() for p in texto.split("\n")]
    saida = "\n".join([p for p in partes if p][:linhas])
    if len(saida) > limite:
        saida = saida[: limite - 1].rstrip() + "…"
    return saida


@dataclass
class Notificacao:
    id: int
    app: str
    resumo: str
    corpo: str
    urgencia: int           # 0 baixa, 1 normal, 2 crítica
    criada: float
    expira_em: Optional[float]
    versao: int = 0         # sobe quando o app substitui o conteúdo (a interface redesenha)


class Gerente:
    """Guarda as notificações vivas. Seguro entre threads (D-Bus escreve, a interface lê)."""

    def __init__(self, max_visiveis=MAX_VISIVEIS, max_guardadas=MAX_GUARDADAS, enxurrada=ENXURRADA):
        self.max_visiveis = max_visiveis
        self.max_guardadas = max_guardadas
        self.enxurrada = enxurrada
        self._lock = threading.RLock()
        self._itens: dict = {}
        self._seq = 0
        self._fechadas: list = []
        self._recentes: dict = {}      # app -> instantes das últimas notificações
        self._ultimo_id: dict = {}

    # ── entrada ──
    def notificar(self, app, replaces_id, resumo, corpo, urgencia=1, timeout_ms=-1, agora=None) -> int:
        agora = time.monotonic() if agora is None else agora
        app = limpar_texto(app, 40) or "app"
        resumo = limpar_texto(resumo, LIMITE_RESUMO)
        corpo = limpar_texto(corpo, LIMITE_CORPO, LINHAS_CORPO)
        if not resumo and not corpo:
            resumo = "(sem texto)"
        urgencia = urgencia if urgencia in (0, 1, 2) else 1
        expira = self._expiracao(urgencia, timeout_ms, agora)
        with self._lock:
            if replaces_id in self._itens:
                n = self._itens[replaces_id]
                n.app, n.resumo, n.corpo, n.urgencia = app, resumo, corpo, urgencia
                n.criada, n.expira_em, n.versao = agora, expira, n.versao + 1
                return n.id
            if self._enxurrada(app, agora):
                return self._ultimo_id.get(app, 0)
            nid = self._novo_id()
            self._itens[nid] = Notificacao(nid, app, resumo, corpo, urgencia, agora, expira)
            self._ultimo_id[app] = nid
            while len(self._itens) > self.max_guardadas:
                mais_velha = min(self._itens.values(), key=lambda x: x.criada)
                self._fechar(mais_velha.id, MOTIVO_EXPIROU)
            return nid

    def fechar(self, nid, motivo=MOTIVO_CHAMADA) -> bool:
        with self._lock:
            return self._fechar(nid, motivo)

    def expirar(self, agora=None) -> list:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            vencidas = [n.id for n in self._itens.values() if n.expira_em is not None and n.expira_em <= agora]
            for nid in vencidas:
                self._fechar(nid, MOTIVO_EXPIROU)
            return vencidas

    # ── saída ──
    def visiveis(self) -> list:
        """As mais novas primeiro, no máximo `max_visiveis`."""
        with self._lock:
            itens = sorted(self._itens.values(), key=lambda n: (n.criada, n.id), reverse=True)
            return itens[: self.max_visiveis]

    def total(self) -> int:
        with self._lock:
            return len(self._itens)

    def pegar_fechadas(self) -> list:
        """[(id, motivo)] fechadas desde a última chamada (o D-Bus transforma em sinais)."""
        with self._lock:
            saida, self._fechadas = self._fechadas, []
            return saida

    # ── internos ──
    def _fechar(self, nid, motivo) -> bool:
        if nid not in self._itens:
            return False
        del self._itens[nid]
        self._fechadas.append((nid, motivo))
        return True

    def _novo_id(self) -> int:
        for _ in range(0xFFFFFFFF):
            self._seq = self._seq + 1 if self._seq < 0xFFFFFFFF else 1
            if self._seq not in self._itens:
                return self._seq
        raise RuntimeError("sem ids livres")

    def _enxurrada(self, app, agora) -> bool:
        limite, janela = self.enxurrada
        fila = self._recentes.setdefault(app, deque())
        while fila and agora - fila[0] > janela:
            fila.popleft()
        if len(fila) >= limite:
            return True
        fila.append(agora)
        if len(self._recentes) > 200:   # app que nunca mais volta não fica na memória
            for chave in [k for k, f in self._recentes.items() if not f or agora - f[-1] > janela]:
                self._recentes.pop(chave, None)
        return False

    @staticmethod
    def _expiracao(urgencia, timeout_ms, agora):
        if not isinstance(timeout_ms, int) or timeout_ms < 0:    # -1: a daemon decide
            if urgencia >= 2:
                return None                                       # crítica: fica até clicar
            return agora + (ESPERA_BAIXA if urgencia == 0 else ESPERA_NORMAL)
        if timeout_ms == 0:
            return None
        return agora + min(timeout_ms / 1000.0, ESPERA_MAXIMA)


def parse_monitor(saida_xrandr: str):
    """(x, y, largura, altura) do monitor primário numa saída de `xrandr --current`; None se não achar."""
    achados = re.findall(r"^(\S+) connected( primary)? (\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saida_xrandr or "", re.M)
    if not achados:
        return None
    escolhido = next((a for a in achados if a[1]), achados[0])
    _nome, _prim, w, h, x, y = escolhido
    return int(x), int(y), int(w), int(h)


# ── D-Bus: despacho das chamadas (puro; a conexão fica em outra camada) ──────────
INTROSPECT_XML = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities"><arg direction="out" type="as"/></method>
    <method name="Notify">
      <arg direction="in" type="s"/><arg direction="in" type="u"/><arg direction="in" type="s"/>
      <arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="in" type="as"/>
      <arg direction="in" type="a{sv}"/><arg direction="in" type="i"/><arg direction="out" type="u"/>
    </method>
    <method name="CloseNotification"><arg direction="in" type="u"/></method>
    <method name="GetServerInformation">
      <arg direction="out" type="s"/><arg direction="out" type="s"/>
      <arg direction="out" type="s"/><arg direction="out" type="s"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  </interface>
</node>"""


def _urgencia(dicas) -> int:
    try:
        v = dicas.get("urgency", 1)
        v = v[1] if isinstance(v, (tuple, list)) else v
        return int(v)
    except (AttributeError, TypeError, ValueError):
        return 1


def despachar(gerente: Gerente, interface, membro, corpo):
    """Responde a uma chamada de método: devolve (assinatura, valores). LookupError = método desconhecido;
    ValueError = argumentos inválidos."""
    corpo = tuple(corpo or ())
    if interface in (None, NOME_BUS):
        if membro == "GetServerInformation":
            return "ssss", ("JToast", "JDev", VERSAO, "1.2")
        if membro == "GetCapabilities":
            return "as", (["body"],)
        if membro == "Notify":
            try:
                app, rid, _icone, resumo, texto, _acoes, dicas, timeout = corpo
                nid = gerente.notificar(app, rid, resumo, texto, _urgencia(dicas), timeout)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Notify inválido: {exc}") from exc
            return "u", (nid,)
        if membro == "CloseNotification":
            try:
                gerente.fechar(int(corpo[0]), MOTIVO_CHAMADA)
            except (IndexError, TypeError, ValueError) as exc:
                raise ValueError("CloseNotification inválido") from exc
            return "", ()
    if interface == "org.freedesktop.DBus.Introspectable" and membro == "Introspect":
        return "s", (INTROSPECT_XML,)
    if interface == "org.freedesktop.DBus.Peer" and membro == "Ping":
        return "", ()
    raise LookupError(f"{interface}.{membro}")


# ══════════════════════════════════════════════════════════════════════════════
#  D-Bus (jeepney) numa thread própria
# ══════════════════════════════════════════════════════════════════════════════
def conectar_dbus():
    """Abre a conexão e toma o nome de serviço. Levanta RuntimeError com mensagem clara se não der."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError as exc:
        raise RuntimeError("falta o jeepney:  pip install --user --break-system-packages jeepney") from exc
    try:
        conn = open_dbus_connection(bus="SESSION")
    except Exception as exc:
        raise RuntimeError(f"sem barramento D-Bus de sessão ({exc})") from exc
    bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus", interface="org.freedesktop.DBus")
    resposta = conn.send_and_get_reply(new_method_call(bus, "RequestName", "su", (NOME_BUS, 4)), timeout=3)
    codigo = resposta.body[0] if resposta.body else 0
    if codigo not in (1, 4):   # 1 = dono; 4 = já era
        conn.close()
        raise RuntimeError("outro programa de notificação já está ativo (dunst, mako...). Feche-o antes.")
    return conn


def servir(conn, gerente: Gerente, parar: threading.Event):
    """Laço do D-Bus: responde às chamadas e emite NotificationClosed. Nunca mexe no Tk."""
    from jeepney import DBusAddress, HeaderFields, MessageType, new_error, new_method_return, new_signal
    emissor = DBusAddress(CAMINHO_BUS, interface=NOME_BUS)
    while not parar.is_set():
        try:
            for nid, motivo in gerente.pegar_fechadas():
                conn.send(new_signal(emissor, "NotificationClosed", "uu", (nid, motivo)))
            try:
                msg = conn.receive(timeout=0.2)
            except TimeoutError:
                continue
            campos = msg.header.fields
            if msg.header.message_type != MessageType.method_call:
                continue
            try:
                assinatura, valores = despachar(gerente, campos.get(HeaderFields.interface),
                                                campos.get(HeaderFields.member), msg.body)
                resposta = new_method_return(msg, assinatura, valores)
            except LookupError:
                resposta = new_error(msg, "org.freedesktop.DBus.Error.UnknownMethod", "s", ("método desconhecido",))
            except ValueError as exc:
                resposta = new_error(msg, "org.freedesktop.DBus.Error.InvalidArgs", "s", (str(exc),))
            conn.send(resposta)
        except (OSError, EOFError):   # a conexão caiu: não há o que fazer além de sair
            break
        except Exception as exc:      # um pedido ruim nunca derruba o serviço
            print(f"JToast: erro ao tratar mensagem: {exc!r}", file=sys.stderr)
    try:
        conn.close()
    except Exception:
        pass
    parar.set()      # perdeu o D-Bus (ex.: a sessão acabou): a interface também encerra


# ══════════════════════════════════════════════════════════════════════════════
#  Interface (Tk)
# ══════════════════════════════════════════════════════════════════════════════
def _estado_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "jtoast-state.json")


def escrever_estado(count: int, caminho: Optional[str] = None) -> None:
    """Escrita atômica do estado que a JBar lê. Nunca levanta."""
    caminho = caminho or _estado_path()
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        tmp = f"{caminho}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "count": int(count)}, f)
        os.replace(tmp, caminho)
    except OSError:
        pass


_cache_monitor = {"quando": 0.0, "valor": None}


def monitor_principal(tk_root):
    """Retângulo do monitor primário (via xrandr, lembrado por 5 s); sem xrandr, a tela inteira do Tk."""
    agora = time.monotonic()
    if _cache_monitor["valor"] is None or agora - _cache_monitor["quando"] > 5.0:
        _cache_monitor.update(quando=agora, valor=_consultar_monitor(tk_root))
    return _cache_monitor["valor"]


def _consultar_monitor(tk_root):
    try:
        saida = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=2).stdout
        achado = parse_monitor(saida)
        if achado:
            return achado
    except (OSError, subprocess.SubprocessError):
        pass
    return 0, 0, tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()


class Interface:
    def __init__(self, root, gerente: Gerente, parar: Optional[threading.Event] = None):
        import tkinter as tk
        from tkinter import font
        self.tk = tk
        self.root = root
        self.g = gerente
        self.parar = parar
        self.janelas: dict = {}          # id -> (versao, Toplevel)
        self.geometrias: dict = {}       # id -> última geometria aplicada
        self.ultimo_count = None
        self._carregar_tema(font)
        self.root.after(TICK_MS, self.tick)

    def _carregar_tema(self, font):
        try:
            import jtheme as t
            self.cores = {"fundo": t.PILL_BG, "linha": t.LINE, "fg": t.FG, "dim": t.DIM,
                          0: t.DIM, 1: t.BLUE, 2: t.RED}
            tamanho = max(9, int(getattr(t, "BAR_FONT", 12)) - 1)
            escolher = getattr(t, "escolher_fonte", None)
            familia = escolher(set(font.families())) if escolher else None
        except (ImportError, AttributeError):
            self.cores = {"fundo": "#1f2335", "linha": "#292e42", "fg": "#a9b1d6", "dim": "#565f89",
                          0: "#565f89", 1: "#7aa2f7", 2: "#f7768e"}
            tamanho, familia = 11, None
        familia = familia or "TkDefaultFont"
        self.f_normal = font.Font(family=familia, size=tamanho)
        self.f_negrito = font.Font(family=familia, size=tamanho, weight="bold")
        self.f_pequena = font.Font(family=familia, size=max(8, tamanho - 2))

    # ── laço ──
    def tick(self):
        if self.parar is not None and self.parar.is_set():
            self.root.quit()
            return
        try:
            self.g.expirar()
            self._reconciliar()
            total = self.g.total()
            if total != self.ultimo_count:
                self.ultimo_count = total
                escrever_estado(total)
        except Exception as exc:    # a interface nunca morre por causa de um balão
            print(f"JToast: erro na interface: {exc!r}", file=sys.stderr)
        self.root.after(TICK_MS, self.tick)

    def _reconciliar(self):
        visiveis = self.g.visiveis()
        ids = {n.id for n in visiveis}
        if not visiveis and not self.janelas:
            return
        for nid in [i for i in self.janelas if i not in ids]:
            self._destruir(nid)
        mx, my, mw, _mh = monitor_principal(self.root)
        x = mx + mw - LARGURA - MARGEM
        y = my + MARGEM
        for n in visiveis:
            atual = self.janelas.get(n.id)
            if atual is None or atual[0] != n.versao:
                if atual is not None:
                    self._destruir(n.id)
                self.janelas[n.id] = (n.versao, self._criar(n))
            top = self.janelas[n.id][1]
            top.update_idletasks()
            h = top.winfo_reqheight()
            geom = f"{LARGURA}x{h}+{x}+{y}"
            if self.geometrias.get(n.id) != geom:
                top.geometry(geom)
                self.geometrias[n.id] = geom
            y += h + ESPACO

    def _destruir(self, nid):
        _v, top = self.janelas.pop(nid, (0, None))
        self.geometrias.pop(nid, None)
        if top is not None:
            try:
                top.destroy()
            except self.tk.TclError:
                pass

    def _criar(self, n: Notificacao):
        tk, c = self.tk, self.cores
        top = tk.Toplevel(self.root)
        top.withdraw()
        top.overrideredirect(True)          # o JWM não gerencia: sem foco, mosaico ou borda
        for atributo, valor in (("-type", "notification"), ("-topmost", True)):
            try:
                top.wm_attributes(atributo, valor)
            except tk.TclError:
                pass
        quadro = tk.Frame(top, bg=c["fundo"], highlightthickness=1, highlightbackground=c["linha"])
        quadro.pack(fill=tk.BOTH, expand=True)
        tk.Frame(quadro, bg=c.get(n.urgencia, c[1]), width=5).pack(side=tk.LEFT, fill=tk.Y)
        miolo = tk.Frame(quadro, bg=c["fundo"])
        miolo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)
        espaco = LARGURA - 5 - 24 - 2
        tk.Label(miolo, text=n.app.upper(), bg=c["fundo"], fg=c["dim"], font=self.f_pequena,
                 anchor="w").pack(fill=tk.X)
        if n.resumo:
            tk.Label(miolo, text=n.resumo, bg=c["fundo"], fg=c["fg"], font=self.f_negrito, anchor="w",
                     justify="left", wraplength=espaco).pack(fill=tk.X)
        if n.corpo:
            tk.Label(miolo, text=n.corpo, bg=c["fundo"], fg=c["fg"], font=self.f_normal, anchor="w",
                     justify="left", wraplength=espaco).pack(fill=tk.X, pady=(2, 0))
        self._ligar_clique(top, n.id)
        top.deiconify()
        top.lift()
        return top

    def _ligar_clique(self, widget, nid):
        widget.bind("<Button-1>", lambda _e, i=nid: self.g.fechar(i, MOTIVO_CLIQUE))
        for filho in widget.winfo_children():
            self._ligar_clique(filho, nid)


# ══════════════════════════════════════════════════════════════════════════════
def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print(f"JToast {VERSAO}")
        return 0
    demo = "--demo" in argv
    gerente = Gerente()
    conn = None
    if not demo:
        try:
            conn = conectar_dbus()
        except RuntimeError as exc:
            print(f"JToast: {exc}", file=sys.stderr)
            return 1
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    parar = threading.Event()
    Interface(root, gerente, parar)
    if demo:
        gerente.notificar("JToast", 0, "Notificação normal", "Sem D-Bus: só o visual.", 1, 15000)
        gerente.notificar("JBar", 0, "Baixa urgência", "Some em 4 segundos.", 0, -1)
        gerente.notificar("Sistema", 0, "Crítica", "Fica até você clicar.\nSegunda linha do corpo.", 2, -1)
    else:
        threading.Thread(target=servir, args=(conn, gerente, parar), daemon=True).start()
    try:
        root.mainloop()
    finally:
        parar.set()
        escrever_estado(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
