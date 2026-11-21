#!/usr/bin/env python3
"""JRun — lançador leve de aplicativos e comandos para o JWM (X11)."""
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

import jrcore

try:  # cores do tema (jtheme.py); sem ele ao lado vale o Tokyo Night embutido
    import jtheme
    _t = jtheme.T
    BG, PANEL, FG, BLUE = _t["bg"], _t["bg_hover"], _t["fg_bright"], _t["blue"]
    DIM, SELECT, MUTED = _t["dim"], _t["select"], _t["fg"]
except (ImportError, AttributeError, KeyError):
    BG, PANEL, FG, BLUE = "#1a1b26", "#24283b", "#c0caf5", "#7aa2f7"
    DIM, SELECT, MUTED = "#565f89", "#36415f", "#a9b1d6"


def monitor_sob_ponteiro(root):
    """(x, y, largura, altura) do monitor onde esta o mouse; None se nao der para saber."""
    try:
        px, py = root.winfo_pointerxy()
        saida = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=0.6).stdout
    except (OSError, subprocess.SubprocessError, tk.TclError):
        return None
    for linha in saida.splitlines():
        m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)", linha)
        if not m:
            continue
        w, h, x, y = (int(v) for v in m.groups())
        if x <= px < x + w and y <= py < y + h:
            return (x, y, w, h)
    return None


def launch_app(app):
    argv = list(app["argv"])
    if app["terminal"]:
        argv = jrcore.argv_terminal(argv)
        if argv is None:
            raise OSError("Este aplicativo precisa de um terminal, mas nenhum terminal conhecido foi encontrado.")
    cwd = app.get("cwd") if app.get("cwd") and os.path.isdir(app["cwd"]) else os.path.expanduser("~")
    subprocess.Popen(argv, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _lockfile():
    """Caminho do lockfile para impedir multiplas instancias."""
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "jrun.lock")


def _ja_rodando():
    """True se ja existe uma instancia do JRun viva (e mesmo do JRun). Foca ela se houver xdotool."""
    if not jrcore.instancia_viva(_lockfile()):
        return False
    if shutil.which("xdotool"):
        try:
            subprocess.run(["xdotool", "search", "--name", "JRun", "windowactivate"],
                           capture_output=True, timeout=1)
        except (OSError, subprocess.SubprocessError):
            pass
    return True


def _escrever_lock():
    try:
        with open(_lockfile(), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _apagar_lock():
    try:
        if open(_lockfile()).read().strip() == str(os.getpid()):   # só apaga a SUA trava
            os.unlink(_lockfile())
    except (OSError, ValueError):
        pass


def main():
    if _ja_rodando():
        return
    _escrever_lock()
    try:
        _main_ui()
    finally:
        _apagar_lock()


def _fonte(root):
    """Mesma fonte do resto do JDev (jtheme); sem ela, a monospace do Tk."""
    try:
        return jtheme.escolher_fonte(tkfont.families(root)) or "monospace"
    except Exception:
        return "monospace"


def _main_ui():
    root = tk.Tk()
    fam = _fonte(root)
    root.title("JRun")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 620, 440
    root.geometry(f"{width}x{height}")
    root.update_idletasks()
    # Centraliza no monitor onde esta o mouse (com varios monitores, a tela X inteira nao serve de base).
    mx, my, mw, mh = monitor_sob_ponteiro(root) or (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    x = mx + max(0, (mw - width) // 2)
    y = my + max(0, (mh - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=20, pady=(18, 12))

    tk.Label(
        header, text="JRun", bg=BG, fg=BLUE,
        font=(fam, 17, "bold")
    ).pack(side="left")

    tk.Label(
        header, text="  Aplicativos", bg=BG, fg=MUTED,
        font=(fam, 10)
    ).pack(side="left", pady=(5, 0))

    search = tk.Entry(
        root, bg=PANEL, fg=FG, insertbackground=FG,
        relief="flat", font=(fam, 12),
        highlightthickness=1, highlightbackground=DIM,
        highlightcolor=BLUE
    )
    search.pack(fill="x", padx=20, pady=(0, 12), ipady=9)

    list_frame = tk.Frame(
        root, bg=PANEL, highlightthickness=1,
        highlightbackground=DIM
    )
    list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    scrollbar = tk.Scrollbar(
        list_frame, relief="flat", troughcolor=PANEL,
        bg=DIM, activebackground=BLUE, bd=0
    )
    scrollbar.pack(side="right", fill="y")

    app_list = tk.Listbox(
        list_frame, bg=PANEL, fg=FG,
        selectbackground=SELECT, selectforeground="#ffffff",
        activestyle="none", relief="flat", borderwidth=0,
        highlightthickness=0, font=(fam, 11),
        yscrollcommand=scrollbar.set, exportselection=False
    )
    app_list.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    scrollbar.configure(command=app_list.yview)

    footer = tk.Frame(root, bg=BG)
    footer.pack(fill="x", padx=20, pady=(0, 15))

    status = tk.Label(
        footer, text="Carregando…", bg=BG, fg=DIM,
        font=(fam, 9), anchor="w"
    )
    status.pack(side="left", fill="x", expand=True)

    tk.Label(
        footer, text="Enter abrir · ↑↓ escolher · !cmd shell · =conta · Esc sair",
        bg=BG, fg=MUTED, font=(fam, 8)
    ).pack(side="right")

    uso = jrcore.uso_ler()
    all_apps = jrcore.cache_ler()          # abre na hora com o cache; a leitura de verdade roda em segundo plano
    shown_apps = []
    fila = queue.Queue()

    def carregar():
        try:
            fila.put(jrcore.ler_aplicativos())
        except Exception:                  # nunca deixa a thread morrer calada sem avisar a janela
            fila.put(None)

    threading.Thread(target=carregar, daemon=True).start()

    def verificar_carga():
        nonlocal all_apps
        try:
            novos = fila.get_nowait()
        except queue.Empty:
            root.after(80, verificar_carga)
            return
        if novos is not None:
            if novos != all_apps:
                all_apps = novos
                refresh_list()
            jrcore.cache_gravar(novos)
        elif not all_apps:
            status.configure(text="Não consegui ler os aplicativos (use Ctrl+Enter para comandos).")

    def refresh_list(_event=None):
        nonlocal shown_apps
        texto = search.get()
        shown_apps = jrcore.buscar(all_apps, texto, uso)
        app_list.delete(0, "end")
        for app in shown_apps:
            app_list.insert("end", "  " + app["name"])
        conta = jrcore.calcular(texto)
        if conta is not None:
            status.configure(text=f"{texto.strip()[1:].strip()} = {conta}", fg=BLUE)
        else:
            status.configure(text=(f"{len(shown_apps)} / {len(all_apps)} aplicativos" if all_apps else "Carregando…"),
                             fg=DIM)
        if shown_apps:
            app_list.selection_set(0)
            app_list.activate(0)
        return "break"

    def mover(delta):
        if not shown_apps:
            return "break"
        atual = app_list.curselection()
        i = max(0, min(len(shown_apps) - 1, (atual[0] if atual else 0) + delta))
        app_list.selection_clear(0, "end")
        app_list.selection_set(i)
        app_list.activate(i)
        app_list.see(i)
        return "break"

    def launch_selected(_event=None):
        selection = app_list.curselection()
        if not selection:
            return "break"
        app = shown_apps[selection[0]]
        try:
            launch_app(app)
            jrcore.uso_registrar(app["id"])
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("JRun", str(exc), parent=root)
            search.focus_set()
        return "break"

    def run_command(_event=None):
        argv = jrcore.argv_do_comando(search.get())
        if not argv:
            return "break"
        if argv[0] != "sh" and shutil.which(argv[0]) is None and not os.path.isabs(argv[0]):
            messagebox.showerror("JRun", f"Comando não encontrado: {argv[0]}", parent=root)
            search.focus_set()
            return "break"
        try:
            subprocess.Popen(argv, cwd=os.path.expanduser("~"), start_new_session=True,
                             stdin=subprocess.DEVNULL)
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("JRun", str(exc), parent=root)
            search.focus_set()
        return "break"

    def search_enter(_event=None):
        query = search.get().strip()
        if query[:1] in ("!", ">"):
            return run_command()
        if jrcore.calcular(query) is not None:
            return "break"
        if query and not shown_apps:
            return run_command()
        return launch_selected()

    app_list.bind("<Double-Button-1>", launch_selected)
    app_list.bind("<Return>", launch_selected)
    ultimo = [None]

    def ao_digitar(_event=None):           # setas também geram KeyRelease: só refaz a lista se o TEXTO mudou
        if search.get() != ultimo[0]:
            ultimo[0] = search.get()
            refresh_list()

    search.bind("<KeyRelease>", ao_digitar)
    search.bind("<Return>", search_enter)
    search.bind("<Control-Return>", run_command)
    search.bind("<Escape>", lambda _event: root.destroy())
    search.bind("<Down>", lambda _e: mover(1))
    search.bind("<Up>", lambda _e: mover(-1))
    search.bind("<Control-n>", lambda _e: mover(1))
    search.bind("<Control-p>", lambda _e: mover(-1))
    search.bind("<Next>", lambda _e: mover(8))
    search.bind("<Prior>", lambda _e: mover(-8))
    root.bind("<Control-a>", lambda _event: (search.select_range(0, "end"), "break"))
    root.bind("<Control-l>", lambda _event: (search.focus_set(), search.select_range(0, "end"), "break"))

    refresh_list()
    search.focus_set()
    root.after(80, verificar_carga)
    root.mainloop()


if __name__ == "__main__":
    main()
