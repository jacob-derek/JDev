"""Popups da JBar e lógica pura, sem dependências externas."""
from calendar import monthrange
from datetime import date


def grade_mes(ano, mes, hoje=None):
    """Retorna seis semanas (domingo a sábado), incluindo dias adjacentes."""
    hoje = hoje or date.today()
    primeiro, total = monthrange(ano, mes)
    inicio = (primeiro + 1) % 7  # Python: segunda=0; grade: domingo=0
    dia1 = date(ano, mes, 1)
    offset = (dia1.weekday() + 1) % 7
    n = 42
    from datetime import timedelta
    base = dia1 - timedelta(days=offset)
    return [[[(d := base + timedelta(days=i)).day, d.month == mes, d == hoje] for i in range(s, s + 7)] for s in range(0, n, 7)]


def mouse_para_percentual(x, largura, minimo=0, maximo=100):
    if largura <= 0:
        return minimo
    return round(max(minimo, min(maximo, (x / largura) * (maximo - minimo) + minimo)))


def limitar_popup(x, y, largura, altura, tela_w, tela_h, origem_y=None):
    """Prende popup à tela e tenta posicioná-lo acima da pílula."""
    x = max(0, min(int(x), max(0, tela_w - largura)))
    y = int(y if origem_y is None else origem_y - altura)
    y = max(0, min(y, max(0, tela_h - altura)))
    return x, y



import tkinter as tk
import subprocess
import shutil
import threading


try:
    from jtheme import BAR_BG, PILL_BG, PILL_HOVER, FG, DIM, FOCUS, CYAN, RED, DARK, ON_ACCENT, GAP, PILL_H, BAR_FONT
except ImportError:
    BAR_BG, PILL_BG, PILL_HOVER = "#13141c", "#1f2335", "#2a2f45"
    FG, DIM, FOCUS, CYAN, RED, DARK, ON_ACCENT = "#a9b1d6", "#565f89", "#b04a67", "#7dcfff", "#f7768e", "#16161e", "#fbe9ef"
    GAP, PILL_H, BAR_FONT = 8, 34, 12



class PopupBase(tk.Toplevel):
    """Popup sem moldura, com fechamento por clique externo e Escape."""
    def __init__(self, barra, pill, largura, altura):
        super().__init__(barra)
        self.barra, self.pill = barra, pill
        self.overrideredirect(True)
        self.configure(bg=BAR_BG)
        self.attributes("-topmost", True)
        self.withdraw()
        self.bind("<Escape>", lambda e: self.fechar())
        self.bind_all("<Button-1>", self._clique_global, add="+")
        self.bind_all("<Button-2>", self._clique_global, add="+")
        self.bind_all("<Button-3>", self._clique_global, add="+")
        self.bind_all("<Escape>", self._escape_global, add="+")
        self._mostrar(largura, altura)
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _mostrar(self, w, h):
        self.update_idletasks()
        px = self.barra.winfo_rootx() + self.pill[0]
        py = self.barra.winfo_rooty() + self.pill[1]
        x, y = limitar_popup(px, py - h, w, h, self.winfo_screenwidth(), self.winfo_screenheight(), py)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.lift()

    def _escape_global(self, e):
        self.fechar()
        return "break"


    def _clique_global(self, e):
        try:
            widget = e.widget
            dentro_popup = widget == self or str(widget).startswith(str(self))
            dentro_pilula = widget == self.barra
            if not dentro_popup and not dentro_pilula:
                self.fechar()
        except tk.TclError:
            self.fechar()

    def fechar(self):
        try:
            self.grab_release()
            self.unbind_all("<Button-1>")
            self.unbind_all("<Button-2>")
            self.unbind_all("<Button-3>")
            self.unbind_all("<Escape>")
            self.destroy()
        except tk.TclError:
            pass


class CalendarioPopup(PopupBase):
    MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
    DIAS = ("dom", "seg", "ter", "qua", "qui", "sex", "sáb")
    def __init__(self, barra, pill):
        self.ano, self.mes = date.today().year, date.today().month
        super().__init__(barra, pill, 252, 286)
        self._montar()
    def _botao(self, parent, text, command, **kw):
        b = tk.Button(parent, text=text, command=command, bg=PILL_BG, fg=FG, activebackground=PILL_HOVER, activeforeground=FG, bd=0, relief="flat", font=(self.barra.font.actual("family"), BAR_FONT), padx=6, **kw)
        b.pack(side=kw.pop("side", "left"))
        return b
    def _montar(self):
        for w in self.winfo_children(): w.destroy()
        head = tk.Frame(self, bg=BAR_BG); head.pack(fill="x", padx=8, pady=(8, 4))
        self._botao(head, "‹", lambda: self._mudar(-1))
        tk.Label(head, text=f"{self.MESES[self.mes-1].title()} {self.ano}", bg=BAR_BG, fg=FG, font=(self.barra.font.actual("family"), BAR_FONT, "bold")).pack(side="left", expand=True)
        self._botao(head, "›", lambda: self._mudar(1))
        grid = tk.Frame(self, bg=BAR_BG); grid.pack(padx=8)
        for i, d in enumerate(self.DIAS): tk.Label(grid, text=d, bg=BAR_BG, fg=DIM, width=4, font=(self.barra.font.actual("family"), BAR_FONT-1)).grid(row=0, column=i)
        hoje = date.today()
        semanas = grade_mes(self.ano, self.mes, hoje)
        for r, semana in enumerate(semanas, 1):
            for c, (dia, atual, eh_hoje) in enumerate(semana):
                bg = FOCUS if eh_hoje else PILL_BG
                fg = ON_ACCENT if eh_hoje else (FG if atual else DIM)
                tk.Label(grid, text=str(dia), bg=bg, fg=fg, width=3, padx=2, pady=3, font=(self.barra.font.actual("family"), BAR_FONT)).grid(row=r, column=c, padx=1, pady=1)
        rodape = tk.Frame(self, bg=BAR_BG); rodape.pack(fill="x", padx=8, pady=6)
        self._botao(rodape, "hoje", self._hoje)
    def _mudar(self, delta):
        self.mes += delta
        if self.mes < 1: self.mes, self.ano = 12, self.ano-1
        if self.mes > 12: self.mes, self.ano = 1, self.ano+1
        self._montar()
    def _hoje(self):
        self.ano, self.mes = date.today().year, date.today().month
        self._montar()

class VolumePopup(PopupBase):
    def __init__(self, barra, pill):
        super().__init__(barra, pill, 260, 220)
        self.volume = barra.dados.get("vol") or 0
        self.muted = bool(barra.dados.get("muted"))
        self._montar()
        self.after(80, self._listar_sinks)
    def _montar(self):
        tk.Label(self, text="Volume", bg=BAR_BG, fg=FG, font=(self.barra.font.actual("family"), BAR_FONT, "bold")).pack(pady=(10,5))
        self.canvas = tk.Canvas(self, width=220, height=24, bg=BAR_BG, highlightthickness=0)
        self.canvas.pack(padx=16)
        self.canvas.bind("<Button-1>", self._slider)
        self.canvas.bind("<B1-Motion>", self._slider)
        self._desenhar_slider()
        row = tk.Frame(self, bg=BAR_BG); row.pack(pady=5)
        tk.Button(row, text="Mudo" if not self.muted else "Ativar som", command=self._mudo, bg=PILL_BG, fg=FG, activebackground=PILL_HOVER, bd=0, padx=10).pack()
        self.lista = tk.Frame(self, bg=BAR_BG); self.lista.pack(fill="x", padx=8, pady=(2,8))
    def _desenhar_slider(self):
        self.canvas.delete("all")
        self.canvas.create_line(8, 12, 212, 12, fill=PILL_BG, width=6, capstyle="round")
        x = 8 + (self.volume/100)*204
        self.canvas.create_line(8, 12, x, 12, fill=CYAN, width=6, capstyle="round")
        self.canvas.create_oval(x-6, 6, x+6, 18, fill=FOCUS, outline="")
        self.canvas.create_text(220, 12, text=f"{self.volume}%", anchor="e", fill=FG, font=(self.barra.font.actual("family"), BAR_FONT-1))
    def _slider(self, e):
        self.volume = mouse_para_percentual(max(0, min(204, e.x-8)), 204)
        self._desenhar_slider()
        em_thread(self._set_volume, self.volume)
    def _set_volume(self, valor):
        if shutil.which("pactl"):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{valor}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, check=False)
        elif shutil.which("amixer"):
            subprocess.run(["amixer", "set", "Master", f"{valor}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, check=False)
    def _mudo(self):
        em_thread(toggle_mute)
        self.muted = not self.muted
        self._montar()
    def _listar_sinks(self):
        if not shutil.which("pactl"):
            tk.Label(self.lista, text="Saídas indisponíveis (pactl não encontrado)", bg=BAR_BG, fg=DIM, font=(self.barra.font.actual("family"), BAR_FONT-1)).pack()
            return
        try:
            res = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=1, check=False)
            sinks = [linha.split("	") for linha in res.stdout.splitlines() if linha.strip()]
            amigaveis = {}
            try:
                detalhes = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, timeout=1, check=False).stdout
                blocos = detalhes.split("Sink #")
                for b in blocos:
                    m = __import__("re").search(r"Name: (.+)\n.*?Description: (.+)", b, __import__("re").S)
                    if m: amigaveis[m.group(1).strip()] = m.group(2).strip()
            except Exception: pass
            for sink in sinks:
                if len(sink) < 2: continue
                nome = sink[1]
                rotulo = amigaveis.get(nome, nome)
                tk.Button(self.lista, text=rotulo, command=lambda n=nome: em_thread(self._trocar_sink, n), bg=PILL_BG, fg=FG, activebackground=PILL_HOVER, bd=0, anchor="w").pack(fill="x", pady=1)
            if not sinks: tk.Label(self.lista, text="Nenhuma saída encontrada", bg=BAR_BG, fg=DIM).pack()
        except Exception:
            tk.Label(self.lista, text="Não foi possível listar saídas", bg=BAR_BG, fg=DIM).pack()
    def _trocar_sink(self, nome):
        subprocess.run(["pactl", "set-default-sink", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, check=False)
