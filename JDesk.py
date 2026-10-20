#!/usr/bin/env python3
"""
JDesk - ambiente de terminal com vários painéis (Fases 1-4).

  [ workspaces |      hora      | vol · ram · net · cpu ]
  [                    JFILES                    ]
  [ JSHELL ]       [ JCODE ]       [ JCLASS ]

Cada workspace tem seus próprios 4 painéis e proporções; é criado só na primeira vez
que você entra nele (os programas só sobem ali).

Navegação no estilo do sway (o $mod aqui é o Alt; o WM usa o Super):

    Alt+h/j/k/l ou Alt+setas          foco: esquerda / baixo / cima / direita
    Alt+Shift+h/j/k/l ou +setas       MOVE o painel (troca de lugar com o vizinho)
    Alt+1..4                          workspace 1..4 (ou clique na barra)
    Alt+f  (ou Alt+z)                 tela cheia do painel / restaurar
    Alt+r                             modo RESIZE (como o "mode resize" do sway):
                                        h/← diminui largura   l/→ aumenta largura
                                        k/↑ diminui altura    j/↓ aumenta altura
                                        Enter ou Esc sai do modo
    Alt+Shift+q                       mata o programa do painel (Enter reinicia)
    Alt+Shift+r                       reinicia o painel
    Alt+Shift+e                       fecha o JDesk (com confirmação)

    Teclas de mídia (sem modificador): volume, mudo e brilho, como no sway.
    Alt+= / Alt+- / Alt+m             volume +5% / -5% / mudo (para teclados sem teclas de mídia)

Visualizador (JSlides): arquivos .pptx/.ppt/.odp/.pdf pedidos pelo JFiles/JClass/JShell abrem
num painel que cobre o workspace; Esc ou q fecha e devolve o foco.

Dentro de cada painel valem os atalhos do JTerm (Ctrl+Shift+C/V, Shift+PgUp,
Ctrl+roda para zoom da fonte DAQUELE painel, etc.).

Dependências: pip install pyte psutil pymupdf python-pptx   (+ pywinpty, pycaw no Windows)
              psutil, pymupdf e python-pptx são opcionais (a barra e o visualizador degradam)
"""
import os
import queue
import sys
import tkinter as tk
from tkinter import messagebox

import jipc
from JBar import Metrics, StatusBar, adjust_volume, brilho, em_thread, toggle_mute
from JTerm import (ALT_MASK, BASE_DIR, BORDER_IDLE, DEFAULT_BG, Pump, PtyPane,
                   enable_dpi_awareness)

try:
    from JSlides import SlidesPane
except ImportError:  # JSlides.py ausente: os arquivos caem no comportamento antigo
    SlidesPane = None

ORDER = ["jfiles", "jshell", "jcode", "jclass"]  # ocupação inicial dos slots: 0 = topo, 1..3 = linha de baixo
N_WS = 4   # quantidade de workspaces (Alt+1..N)

MIN_ROW, MAX_ROW = 0.20, 0.80
MIN_COL = 0.12
STEP = 0.04

# Extensões que abrem no visualizador embutido (JSlides).
VIEWER_EXT = {".pptx", ".ppt", ".odp", ".pdf"}

# Teclas de mídia: chegam como keysym puro, sem Alt (iguais às do seu config do sway).
MIDIA = {
    "XF86AudioRaiseVolume": lambda: em_thread(adjust_volume, +1),
    "XF86AudioLowerVolume": lambda: em_thread(adjust_volume, -1),
    "XF86AudioMute": lambda: em_thread(toggle_mute),
    "XF86MonBrightnessUp": lambda: em_thread(brilho, +1),
    "XF86MonBrightnessDown": lambda: em_thread(brilho, -1),
}

DIRS = {"left": "left", "h": "left", "right": "right", "l": "right",
        "up": "up", "k": "up", "down": "down", "j": "down"}
# No modo resize o sway usa: h diminui largura, l aumenta, k diminui altura, j aumenta.
RESIZE = {"h": (-1, 0), "left": (-1, 0), "l": (1, 0), "right": (1, 0),
          "k": (0, -1), "up": (0, -1), "j": (0, 1), "down": (0, 1)}


def achar(nome):
    """Procura o script em JDev/<Nome>/ e depois em JDev/ (ex.: JDev/JClass/JClass.py)."""
    stem = os.path.splitext(nome)[0]
    candidatos = [  # a subpasta vem primeiro: JDev/JClass/JClass.py vence um JClass.py solto na raiz
        os.path.join(BASE_DIR, stem, nome),
        os.path.join(BASE_DIR, nome),
    ]
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return candidatos[1]  # inexistente: o painel mostra o erro e permite reiniciar


def programa(nome):
    return [sys.executable, achar(nome)]


def comandos():
    return {
        "jfiles": programa("JFiles.py"),
        "jshell": programa("JShell.py"),
        "jcode": programa("JCode.py"),  # sem argumentos: modo idle, espera o "open" do jipc
        "jclass": programa("JClass.py"),
    }


class Workspace:
    """Um conjunto de 4 painéis com layout próprio (criado sob demanda).

    O layout é feito de *slots* (0 = linha de cima, 1..3 = linha de baixo). Cada slot guarda o
    nome de um painel; mover um painel é trocar o conteúdo de dois slots, sem reiniciar nada."""

    def __init__(self, desk, index):
        self.desk = desk
        self.index = index
        self.frame = tk.Frame(desk.area, bg=BORDER_IDLE, bd=0, highlightthickness=0)
        self.slots = list(ORDER)
        self.row_split = 0.60                  # fração da altura ocupada pelo slot de cima
        self.col_w = [0.30, 0.40, 0.30]        # larguras dos 3 slots de baixo
        self.maximized = None
        self.active = None
        self.last_slot = 1                     # último slot de baixo focado (para ir "para baixo")
        self.viewer = None
        self.viewer_aberto = False
        self.retorno = "jfiles"

        self.panes = {}
        cmds = comandos()
        for nome in ORDER:
            self.panes[nome] = PtyPane(
                self.frame, cmds[nome], name=nome, header=True, exit_mode="restart",
                env_extra={"JDESK": "1", "JDESK_PANE": nome, "JDESK_WS": str(index + 1),
                           **desk.ipc.env()},
                on_title=desk.on_title, key_filter=desk.on_key, on_focus=self.set_active,
            )

    # ── exibição ──
    def show(self):
        self.frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        if not self.viewer_aberto:
            self.layout()

    def hide(self):
        self.frame.place_forget()
        for p in self.panes.values():
            p.set_visible(False)  # segue rodando, só não desenha

    def slot_de(self, nome):
        return self.slots.index(nome)

    def rects(self):
        h = self.row_split
        r = {self.slots[0]: (0.0, 0.0, 1.0, h)}
        x = 0.0
        for s in (1, 2, 3):
            w = self.col_w[s - 1]
            r[self.slots[s]] = (x, h, w, 1.0 - h)
            x += w
        return r

    def layout(self):
        if self.maximized:
            for nome, p in self.panes.items():
                if nome == self.maximized:
                    p.place(relx=0, rely=0, relwidth=1, relheight=1)
                    p.set_visible(True)
                else:
                    p.place_forget()
                    p.set_visible(False)
            return
        for nome, (x, y, w, h) in self.rects().items():
            p = self.panes[nome]
            p.place(relx=x, rely=y, relwidth=w, relheight=h)
            p.set_visible(True)

    def toggle_max(self, pane):
        self.maximized = None if self.maximized else pane.name
        self.layout()
        self.focus_pane(pane.name)

    # ── foco ──
    def set_active(self, pane):
        if self.active is pane:
            return
        if self.active is not None and not self.active.destroyed:
            self.active.set_active(False)
        self.active = pane
        pane.set_active(True)
        s = self.slot_de(pane.name)
        if s > 0:
            self.last_slot = s

    def focus_pane(self, nome):
        pane = self.panes[nome]
        self.set_active(pane)
        pane.focus_text()

    def focus_current(self):
        if self.viewer_aberto and self.viewer is not None:
            self.viewer.focus_canvas()
        else:
            self.focus_pane(self.active.name if self.active else "jfiles")

    def slot_vizinho(self, s, direcao):
        if s == 0:
            return self.last_slot if direcao == "down" else None
        if direcao == "up":
            return 0
        if direcao == "left" and s > 1:
            return s - 1
        if direcao == "right" and s < 3:
            return s + 1
        return None

    def mover_foco(self, direcao):
        atual = self.active.name if self.active else "jfiles"
        alvo = self.slot_vizinho(self.slot_de(atual), direcao)
        if alvo is None:
            return
        if self.maximized:  # sair do zoom para poder navegar
            self.maximized = None
            self.layout()
        self.focus_pane(self.slots[alvo])

    def mover(self, direcao):
        """Alt+Shift+direção: troca o painel focado de lugar com o vizinho (como o 'move' do sway)."""
        if self.maximized or not self.active:
            return
        s = self.slot_de(self.active.name)
        t = self.slot_vizinho(s, direcao)
        if t is None:
            return
        self.slots[s], self.slots[t] = self.slots[t], self.slots[s]
        if t > 0:
            self.last_slot = t
        self.layout()
        self.focus_pane(self.active.name)

    # ── redimensionamento (modo resize) ──
    def redimensionar(self, largura=0, altura=0):
        """+1 aumenta, -1 diminui (mesma semântica do 'resize grow/shrink' do sway)."""
        if self.maximized or not self.active:
            return
        s = self.slot_de(self.active.name)
        if altura:
            d = STEP * altura
            self.row_split += d if s == 0 else -d
            self.row_split = max(MIN_ROW, min(MAX_ROW, self.row_split))
        if largura and s > 0:
            d = STEP * largura
            i = s - 1
            j = i + 1 if i < 2 else i - 1     # o vizinho absorve a diferença
            if self.col_w[i] + d >= MIN_COL and self.col_w[j] - d >= MIN_COL:
                self.col_w[i] += d
                self.col_w[j] -= d
        self.layout()

    # ── visualizador (JSlides) ──
    def abrir_viewer(self, caminho, focar=True):
        if SlidesPane is None:
            return False
        if self.viewer is None:
            self.viewer = SlidesPane(self.frame, on_close=self.fechar_viewer, key_filter=self.desk.on_key)
        if not self.viewer_aberto:
            self.retorno = self.active.name if self.active else "jfiles"
        self.viewer_aberto = True
        for p in self.panes.values():
            p.set_visible(False)  # o que está por baixo não precisa desenhar
        self.viewer.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.viewer.lift()
        self.viewer.abrir(caminho)
        if focar:
            self.viewer.after(30, self.viewer.focus_canvas)
        return True

    def fechar_viewer(self):
        if self.viewer is not None:
            self.viewer.place_forget()
        self.viewer_aberto = False
        self.layout()
        self.focus_pane(self.retorno if self.retorno in self.panes else "jfiles")

    # ── encerramento ──
    def vivos(self):
        return [p.name for p in self.panes.values() if not p.dead and p.pty]

    def shutdown(self):
        for p in self.panes.values():
            p.shutdown()
        if self.viewer is not None:
            try:
                self.viewer.destroy()
            except tk.TclError:
                pass


class JDesk:
    def __init__(self, root):
        self.root = root
        root.title("JDesk")
        root.geometry("1400x820")
        root.minsize(640, 360)
        root.configure(bg=DEFAULT_BG)

        self.ipc = jipc.Servidor()   # antes dos workspaces: os panes recebem JDESK_SOCK/TOKEN
        self.ipc.iniciar()
        self._fechando = False
        self.modo_resize = False

        self.metrics = Metrics()
        self.metrics.start()
        self.bar = StatusBar(root, N_WS, self.switch)
        self.bar.pack(side=tk.TOP, fill=tk.X)
        self.area = tk.Frame(root, bg=BORDER_IDLE, bd=0, highlightthickness=0)
        self.area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.ws = [None] * N_WS
        self.cur = None
        self.pump = Pump(root, self.all_panes)
        self.bar.start(self.metrics)
        self.switch(0)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._poll_ipc()

    def all_panes(self):
        return [p for w in self.ws if w for p in w.panes.values()]

    # ── workspaces ────────────────────────────────────────────────────────
    def switch(self, i):
        if i == self.cur or not (0 <= i < N_WS):
            return
        self.sair_resize()
        if self.ws[i] is None:
            self.ws[i] = Workspace(self, i)  # só aqui os programas do workspace são iniciados
        if self.cur is not None:
            self.ws[self.cur].hide()
        self.cur = i
        w = self.ws[i]
        w.show()
        self.bar.set_workspaces(i, {k for k, x in enumerate(self.ws) if x})
        self.root.after(60, w.focus_current)

    # ── IPC (mensagens dos programas dos painéis) ─────────────────────────
    def _poll_ipc(self):
        """As threads do servidor só enfileiram; tudo que toca na interface roda aqui."""
        try:
            while True:
                msg, conn = self.ipc.fila.get_nowait()
                self.tratar_ipc(msg, conn)
        except queue.Empty:
            pass
        if not self._fechando:
            self.root.after(30, self._poll_ipc)

    def ws_da_msg(self, msg):
        try:
            i = int(msg.get("ws")) - 1
        except (TypeError, ValueError):
            return self.cur
        return i if 0 <= i < N_WS and self.ws[i] else self.cur

    def focar(self, i, nome):
        """Foca um pane do workspace i, mas só se ele for o que está na tela."""
        w = self.ws[i]
        if i != self.cur or not w or nome not in w.panes:
            return False
        if w.viewer_aberto:  # um pedido para um painel fecha o visualizador que cobria tudo
            w.fechar_viewer()
        if w.maximized and w.maximized != nome:  # o alvo precisa estar visível
            w.maximized = None
            w.layout()
        w.focus_pane(nome)
        return True

    def tratar_ipc(self, msg, conn):
        cmd, i = msg.get("cmd"), self.ws_da_msg(msg)
        ok, erro = False, f"comando desconhecido: {cmd}"
        try:
            if cmd == "open":
                path = msg.get("path")
                if not isinstance(path, str) or not path:
                    erro = "sem caminho"
                else:
                    ext = os.path.splitext(path)[1].lower()
                    alvo = msg.get("target") or ("viewer" if ext in VIEWER_EXT else "jcode")
                    if alvo == "viewer":  # o visualizador mora dentro do JDesk: sem socket
                        w = self.ws[i]
                        ok = bool(w and w.abrir_viewer(path, focar=msg.get("focus", True)))
                        erro = "" if ok else "visualizador indisponível (JSlides.py)"
                    else:
                        ok = self.ipc.entregar(str(i + 1), alvo, {"cmd": "open", "path": path})
                        erro = "" if ok else f"{alvo} não está conectado"
                        if ok and msg.get("focus", True):
                            self.focar(i, alvo)
            elif cmd == "focus":
                ok = self.focar(i, str(msg.get("target")))
                erro = "" if ok else "pane indisponível"
            elif cmd == "refresh":
                self.ipc.difundir("jfiles", {"cmd": "refresh", "path": msg.get("path")})
                ok, erro = True, ""
        except Exception as exc:  # um pedido ruim nunca derruba o JDesk
            erro = repr(exc)
        self.ipc.responder(conn, ok, erro)

    # ── modo resize ───────────────────────────────────────────────────────
    def entrar_resize(self):
        self.modo_resize = True
        self.bar.set_modo("RESIZE  h/l largura · j/k altura · Enter sai")

    def sair_resize(self):
        if self.modo_resize:
            self.modo_resize = False
            self.bar.set_modo("")

    def _tecla_resize(self, e):
        k = e.keysym.lower()
        if k in RESIZE:
            self.ws[self.cur].redimensionar(*RESIZE[k])
        elif k in ("return", "kp_enter", "escape"):
            self.sair_resize()
        return True  # enquanto o modo existe, nenhuma tecla vaza para o programa

    # ── teclado (chamado por cada painel antes de repassar a tecla) ───────
    def on_key(self, pane, e):
        ks = e.keysym
        acao = MIDIA.get(ks)
        if acao:  # teclas de mídia valem em qualquer painel e no visualizador
            acao()
            return True

        viewer = getattr(pane, "es_viewer", False)
        if self.modo_resize and not viewer:
            return self._tecla_resize(e)

        st = e.state
        if not (st & ALT_MASK) or (st & 0x4):  # sem Alt, ou AltGr (Ctrl+Alt): não é nosso
            return False
        shift = bool(st & 0x1)
        k = ks.lower()

        # ── globais (valem também com o visualizador em foco) ──
        if k.isdigit() and not shift:
            n = 10 if k == "0" else int(k)
            if 1 <= n <= N_WS:
                self.switch(n - 1)
                return True
        if k in ("equal", "plus"):  # Alt+= (ou Alt+Shift+=, que já é "plus")
            em_thread(adjust_volume, +1)
            return True
        if k == "minus":
            em_thread(adjust_volume, -1)
            return True
        if k == "m" and not shift:
            em_thread(toggle_mute)
            return True
        if k == "e" and shift:
            self.close()
            return True
        if viewer:
            return False

        # ── específicos de painel ──
        w = self.ws[self.cur]
        if k in DIRS:
            if shift:
                w.mover(DIRS[k])
            else:
                w.mover_foco(DIRS[k])
            return True
        if k in ("f", "z") and not shift:
            w.toggle_max(pane)
            return True
        if k == "r":
            if shift:
                pane.restart()
            else:
                self.entrar_resize()
            return True
        if k == "q" and shift:
            pane.encerrar()
            return True
        return False

    def on_title(self, pane, titulo):
        extra = f" · {titulo}" if titulo and titulo.lower() != pane.name else ""
        pane.set_header(f"{pane.name.upper()}{extra}")

    # ── encerramento ──────────────────────────────────────────────────────
    def close(self):
        vivos = [f"{n} (ws {w.index + 1})" for w in self.ws if w for n in w.vivos()]
        if vivos and not messagebox.askokcancel(
                "JDesk", "Fechar o JDesk?\nEstes programas serão encerrados:\n  " + ", ".join(vivos)):
            return
        self._fechando = True
        self.ipc.fechar()
        self.pump.stop()
        self.bar.stop()
        self.metrics.stop()
        for w in self.ws:
            if w:
                w.shutdown()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    JDesk(root)
    root.mainloop()


if __name__ == "__main__":
    main()
