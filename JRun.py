#!/usr/bin/env python3
"""JRun — lançador leve de aplicativos e comandos para o JWM (X11)."""
import os
import shlex
import shutil
import subprocess
import configparser
import tkinter as tk
from tkinter import messagebox

BG = "#1a1b26"
PANEL = "#24283b"
FG = "#c0caf5"
BLUE = "#7aa2f7"
DIM = "#565f89"
SELECT = "#36415f"
MUTED = "#a9b1d6"


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


def main():
    root = tk.Tk()
    root.title("JRun")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 620, 440
    root.geometry(f"{width}x{height}")
    root.update_idletasks()
    # Centraliza horizontal e verticalmente na tela X11.
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=20, pady=(18, 12))

    tk.Label(
        header, text="JRun", bg=BG, fg=BLUE,
        font=("monospace", 17, "bold")
    ).pack(side="left")

    tk.Label(
        header, text="  Aplicativos", bg=BG, fg=MUTED,
        font=("monospace", 10)
    ).pack(side="left", pady=(5, 0))

    search = tk.Entry(
        root, bg=PANEL, fg=FG, insertbackground=FG,
        relief="flat", font=("monospace", 12),
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
        highlightthickness=0, font=("monospace", 11),
        yscrollcommand=scrollbar.set, exportselection=False
    )
    app_list.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    scrollbar.configure(command=app_list.yview)

    footer = tk.Frame(root, bg=BG)
    footer.pack(fill="x", padx=20, pady=(0, 15))

    status = tk.Label(
        footer, text="Carregando…", bg=BG, fg=DIM,
        font=("monospace", 9), anchor="w"
    )
    status.pack(side="left", fill="x", expand=True)

    tk.Label(
        footer, text="Enter abrir · Ctrl+Enter comando · Esc sair",
        bg=BG, fg=MUTED, font=("monospace", 8)
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
