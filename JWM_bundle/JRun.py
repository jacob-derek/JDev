#!/usr/bin/env python3
"""JRun — executor simples de comandos para o JWM (X11)."""
import os
import shlex
import subprocess
import tkinter as tk
from tkinter import messagebox

BG = "#1a1b26"
FG = "#c0caf5"
BLUE = "#7aa2f7"
DIM = "#565f89"


def main():
    root = tk.Tk()
    root.title("JRun")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.geometry("620x92")
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - 620) // 2)
    y = max(0, (root.winfo_screenheight() - 92) // 3)
    root.geometry(f"620x92+{x}+{y}")

    tk.Label(root, text="JRUN  /  EXECUTAR COMANDO", anchor="w", bg=BG, fg=BLUE,
             font=("monospace", 10, "bold")).pack(fill="x", padx=14, pady=(10, 4))
    entry = tk.Entry(root, bg="#24283b", fg=FG, insertbackground=FG, relief="flat",
                     font=("monospace", 12), highlightthickness=1,
                     highlightbackground=DIM, highlightcolor=BLUE)
    entry.pack(fill="x", padx=14, pady=(0, 12), ipady=5)

    def run_command(_event=None):
        value = entry.get().strip()
        if not value:
            root.destroy()
            return "break"
        try:
            argv = shlex.split(value)
            if not argv:
                root.destroy()
                return "break"
            subprocess.Popen(argv, cwd=os.path.expanduser("~"), start_new_session=True,
                             stdin=subprocess.DEVNULL)
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("JRun", str(exc), parent=root)
            entry.focus_force()
        return "break"

    entry.bind("<Return>", run_command)
    entry.bind("<Escape>", lambda _e: root.destroy())
    root.bind("<Control-a>", lambda _e: (entry.select_range(0, "end"), "break"))
    entry.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
