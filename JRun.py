#!/usr/bin/env python3
"""JRun — lançador leve de aplicativos e comandos para o JWM (X11)."""
import os
import re
import shlex
import shutil
import subprocess
import configparser
import tkinter as tk
from tkinter import messagebox

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
        saida = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=2).stdout
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


def application_dirs():
    """Retorna diretórios XDG de arquivos .desktop, sem duplicatas."""
    dirs = [
        os.path.expanduser("~/.local/share/applications"),
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/usr/local/share/applications",
        "/usr/share/applications",
        os.path.expanduser("~/.nix-profile/share/applications"),
    ]
    for base in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        dirs.append(os.path.join(base, "applications"))
    result, seen = [], set()
    for path in dirs:
        path = os.path.abspath(os.path.expanduser(path))
        if path not in seen and os.path.isdir(path):
            result.append(path)
            seen.add(path)
    return result


def read_applications():
    """Lê lançadores .desktop e devolve uma lista de aplicativos executáveis."""
    apps = {}
    for directory in application_dirs():
        for current, subdirs, files in os.walk(directory):
            subdirs[:] = [d for d in subdirs if d not in (".", "locale")]
            for filename in files:
                if not filename.endswith(".desktop"):
                    continue
                path = os.path.join(current, filename)
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.optionxform = str
                try:
                    parser.read(path, encoding="utf-8")
                    section = parser["Desktop Entry"]
                    if section.get("Type", "Application") != "Application":
                        continue
                    if section.get("Hidden", "false").lower() == "true":
                        continue
                    if section.get("NoDisplay", "false").lower() == "true":
                        continue
                    name = section.get("Name", "").strip()
                    command = section.get("Exec", "").strip()
                    if not name or not command:
                        continue
                    # Remover marcadores de campo do padrão .desktop (%U, %f, etc.).
                    try:
                        argv = shlex.split(command)
                    except ValueError:
                        continue
                    argv = [arg for arg in argv if not (
                        arg.startswith("%") and len(arg) == 2
                    )]
                    if not argv:
                        continue
                    # Filtrar apps cujo executavel principal nao existe no PATH nem no disco.
                    exec0 = argv[0]
                    if not (os.path.isabs(exec0) or shutil.which(exec0)):
                        continue
                    app = {
                        "name": name,
                        "exec": command,
                        "argv": argv,
                        "comment": section.get("Comment", "").strip(),
                        "categories": section.get("Categories", "").replace(";", " · ").strip(" ·"),
                        "path": path,
                        "terminal": section.get("Terminal", "false").lower() == "true",
                    }
                    # Primeiro diretório XDG tem prioridade para o mesmo nome de arquivo.
                    apps.setdefault(filename, app)
                except (OSError, KeyError, configparser.Error):
                    continue
    return sorted(apps.values(), key=lambda app: app["name"].casefold())


def launch_app(app):
    argv = list(app["argv"])
    # Algumas entradas usam variáveis de ambiente ou executáveis sem caminho absoluto.
    if app["terminal"]:
        terminal = next((shutil.which(x) for x in ("x-terminal-emulator", "xterm", "urxvt", "kitty", "alacritty", "foot") if shutil.which(x)), None)
        if terminal:
            argv = [terminal, "-e", *argv]
        else:
            raise OSError("Este aplicativo precisa de um terminal, mas nenhum terminal conhecido foi encontrado.")
    subprocess.Popen(argv, cwd=os.path.expanduser("~"), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _lockfile():
    """Caminho do lockfile para impedir multiplas instancias."""
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "jrun.lock")


def _ja_rodando():
    """True se ja existe uma instancia do JRun viva. Foca ela pelo WM_NAME se possivel."""
    lock = _lockfile()
    try:
        pid = int(open(lock).read().strip())
        os.kill(pid, 0)   # 0 = so checar; levanta OSError se nao existe
        # Tenta trazer a janela existente para a frente via xdotool (opcional)
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "search", "--name", "JRun", "windowactivate"],
                           capture_output=True, timeout=1)
        return True
    except (OSError, ValueError, FileNotFoundError):
        return False


def _escrever_lock():
    try:
        with open(_lockfile(), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _apagar_lock():
    try:
        os.unlink(_lockfile())
    except OSError:
        pass


def main():
    if _ja_rodando():
        return
    _escrever_lock()
    try:
        _main_ui()
    finally:
        _apagar_lock()


def _familia():
    """Fonte do tema (a mesma do JTerm e da JBar); sem jtheme, a monospace do sistema."""
    try:
        from tkinter import font as tkfont
        import jtheme
        return jtheme.escolher_fonte(set(tkfont.families())) or "monospace"
    except (ImportError, AttributeError, tk.TclError):
        return "monospace"


def _main_ui():
    root = tk.Tk()
    fam = _familia()
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
        footer, text="Enter abrir · Ctrl+Enter comando · Esc sair",
        bg=BG, fg=MUTED, font=(fam, 8)
    ).pack(side="right")

    all_apps = read_applications()
    shown_apps = []

    def refresh_list(_event=None):
        nonlocal shown_apps
        query = search.get().strip().casefold()
        shown_apps = [
            app for app in all_apps
            if query in app["name"].casefold()
            or query in app["comment"].casefold()
            or query in app["categories"].casefold()
            or query in app["exec"].casefold()
        ]
        app_list.delete(0, "end")
        for app in shown_apps:
            app_list.insert("end", "  " + app["name"])
        status.configure(text=f"{len(shown_apps)} / {len(all_apps)} aplicativos")
        if shown_apps:
            app_list.selection_set(0)
            app_list.activate(0)
        return "break"

    def launch_selected(_event=None):
        selection = app_list.curselection()
        if not selection:
            return "break"
        app = shown_apps[selection[0]]
        try:
            launch_app(app)
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("JRun", str(exc), parent=root)
            search.focus_set()
        return "break"

    def run_command(_event=None):
        value = search.get().strip()
        if not value:
            return "break"
        try:
            argv = shlex.split(value)
            if not argv:
                return "break"
            if shutil.which(argv[0]) is None and not os.path.isabs(argv[0]):
                messagebox.showerror("JRun", f"Comando não encontrado: {argv[0]}", parent=root)
                search.focus_set()
                return "break"
            subprocess.Popen(
                argv, cwd=os.path.expanduser("~"), start_new_session=True,
                stdin=subprocess.DEVNULL
            )
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("JRun", str(exc), parent=root)
            search.focus_set()
        return "break"

    def search_enter(_event=None):
        query = search.get().strip()
        if query and not shown_apps:
            return run_command()
        return launch_selected()

    app_list.bind("<Double-Button-1>", launch_selected)
    app_list.bind("<Return>", launch_selected)
    app_list.bind("<<ListboxSelect>>", lambda _event: None)
    search.bind("<KeyRelease>", refresh_list)
    search.bind("<Return>", search_enter)
    search.bind("<Control-Return>", run_command)
    search.bind("<Escape>", lambda _event: root.destroy())
    root.bind("<Control-a>", lambda _event: (search.select_range(0, "end"), "break"))
    root.bind("<Control-l>", lambda _event: (search.focus_set(), search.select_range(0, "end"), "break"))

    refresh_list()
    search.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
