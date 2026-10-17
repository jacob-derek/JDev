#!/usr/bin/env python3
"""
JDesk - ambiente de terminal com vários painéis (Fases 1-3).

  [ workspaces |      hora      | vol · ram · net · cpu ]
  [                    JFILES                    ]
  [ JSHELL ]       [ JCODE ]       [ JCLASS ]

Cada workspace (1-4) tem seus próprios 4 painéis e proporções; é criado só na
primeira vez que você entra nele (os programas só sobem ali).

Cada painel é um PtyPane (JTerm.py) com seu próprio pty, rodando um programa do
ecossistema J. Tudo é controlado pelo teclado com Alt (o resto vai direto ao
programa do painel focado):

    Alt+1..4                        troca de workspace (ou clique na barra)
    Alt+h/j/k/l ou Alt+setas        move o foco (esq/baixo/cima/dir)
    Alt+Shift+h/j/k/l ou +setas     redimensiona o painel focado:
                                      ↑ / k / → / l  = cresce     ↓ / j / ← / h = diminui
    Alt+z                           maximiza / restaura o painel focado
    Alt+r                           reinicia o painel se o processo já terminou
    Alt+Shift+R                     reinicia o painel mesmo com o processo vivo
    Alt+= / Alt+-                   volume do sistema +5% / -5%   (Alt+m = mudo)
    Alt+Shift+Q                     fecha o JDesk
    Enter (painel finalizado)       reinicia o painel

Dentro de cada painel valem os atalhos do JTerm (Ctrl+Shift+C/V, Shift+PgUp,
Ctrl+roda para zoom da fonte DAQUELE painel, etc.).

Dependências: pip install pyte psutil   (+ pywinpty, pycaw no Windows)
              psutil é opcional (sem ele a barra mostra "--" nas métricas)
"""
import os
import queue
import sys
import tkinter as tk
from tkinter import messagebox

import jipc
from JBar import Metrics, StatusBar, adjust_volume, em_thread, toggle_mute
from JTerm import (ALT_MASK, BASE_DIR, BORDER_IDLE, DEFAULT_BG, Pump, PtyPane,
                   enable_dpi_awareness)

BOTTOM = ["jshell", "jcode", "jclass"]
ORDER = ["jfiles", *BOTTOM]
N_WS = 4

MIN_ROW, MAX_ROW = 0.20, 0.80
MIN_COL = 0.12
STEP = 0.04

# Extensões que pertencem a um visualizador (JSlides, Fase 4). Enquanto ele não existir,
# o "open" falha e o programa de origem cai no comportamento antigo (ex.: zathura/xdg-open).
VIEWER_EXT = {".pptx", ".ppt", ".odp", ".pdf"}

def achar(nome):
    """Procura o script em JDev/ e em JDev/<Nome>/ (ex.: JDev/JClass/JClass.py)."""
    stem = os.path.splitext(nome)[0]
    candidatos = [
        os.path.join(BASE_DIR, nome),
        os.path.join(BASE_DIR, stem, nome),
    ]
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return candidatos[0]  # inexistente: o painel mostra o erro e permite reiniciar


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
    """Um conjunto de 4 painéis com layout próprio (criado sob demanda)."""

    def __init__(self, desk, index):
        self.desk = desk
        self.index = index
        self.frame = tk.Frame(desk.area, bg=BORDER_IDLE, bd=0, highlightthickness=0)
        self.row_split = 0.60                  # fração da altura ocupada pelo JFiles
        self.col_w = [0.30, 0.40, 0.30]        # larguras da linha inferior
        self.maximized = None
        self.active = None
        self.last_bottom = "jshell"

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
        self.layout()

    def hide(self):
        self.frame.place_forget()
        for p in self.panes.values():
            p.set_visible(False)  # segue rodando, só não desenha

    def rects(self):
        h = self.row_split
        r = {"jfiles": (0.0, 0.0, 1.0, h)}
        x = 0.0
        for nome, w in zip(BOTTOM, self.col_w):
            r[nome] = (x, h, w, 1.0 - h)
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
        if pane.name in BOTTOM:
            self.last_bottom = pane.name

    def focus_pane(self, nome):
        pane = self.panes[nome]
        self.set_active(pane)
        pane.focus_text()

    def focus_current(self):
        self.focus_pane(self.active.name if self.active else "jfiles")

    def vizinho(self, atual, direcao):
        if atual == "jfiles":
            return self.last_bottom if direcao == "down" else None
        i = BOTTOM.index(atual)
        if direcao == "up":
            return "jfiles"
        if direcao == "left" and i > 0:
            return BOTTOM[i - 1]
        if direcao == "right" and i < len(BOTTOM) - 1:
            return BOTTOM[i + 1]
        return None

    def mover_foco(self, direcao):
        atual = self.active.name if self.active else "jfiles"
        alvo = self.vizinho(atual, direcao)
        if not alvo:
            return
        if self.maximized:  # sair do zoom para poder navegar
            self.maximized = None
            self.layout()
        self.focus_pane(alvo)

    # ── redimensionamento ──
    def redimensionar(self, direcao):
        if self.maximized or not self.active:
            return
        nome = self.active.name
        if direcao in ("up", "down"):
            d = STEP if direcao == "up" else -STEP          # ↑ = cresce
            self.row_split += d if nome == "jfiles" else -d
            self.row_split = max(MIN_ROW, min(MAX_ROW, self.row_split))
        elif nome != "jfiles":
            d = STEP if direcao == "right" else -STEP       # → = cresce
            i = BOTTOM.index(nome)
            j = i + 1 if i < len(BOTTOM) - 1 else i - 1     # o vizinho absorve a diferença
            if self.col_w[i] + d >= MIN_COL and self.col_w[j] - d >= MIN_COL:
                self.col_w[i] += d
                self.col_w[j] -= d
        self.layout()

    # ── encerramento ──
    def vivos(self):
        return [p.name for p in self.panes.values() if not p.dead and p.pty]

    def shutdown(self):
        for p in self.panes.values():
            p.shutdown()


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

    # ── teclado (chamado por cada PtyPane antes de repassar a tecla) ──────
    def on_key(self, pane, e):
        st = e.state
        if not (st & ALT_MASK) or (st & 0x4):  # sem Alt, ou AltGr (Ctrl+Alt): não é nosso
            return False
        shift = bool(st & 0x1)
        ks = e.keysym
        k = ks.lower()
        w = self.ws[self.cur]
        dirs = {"left": "left", "h": "left", "right": "right", "l": "right",
                "up": "up", "k": "up", "down": "down", "j": "down"}

        if k.isdigit() and not shift and 1 <= int(k) <= N_WS:
            self.switch(int(k) - 1)
            return True
        if k in dirs:
            if shift:
                w.redimensionar(dirs[k])
            else:
                w.mover_foco(dirs[k])
            return True
        if k == "z" and not shift:
            w.toggle_max(pane)
            return True
        if k == "r":
            if shift or pane.dead:
                pane.restart()
                return True
            return False  # painel vivo: Alt+r segue para o programa
        if k in ("equal", "plus"):  # Alt+= (ou Alt+Shift+=, que já é "plus")
            em_thread(adjust_volume, +1)
            return True
        if k == "minus":
            em_thread(adjust_volume, -1)
            return True
        if k == "m" and not shift:
            em_thread(toggle_mute)
            return True
        if k == "q" and shift:
            self.close()
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
