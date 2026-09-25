import tkinter as tk
from tkinter import ttk


TODO = [
    (
        "JCode",
        [
            "Linha + coluna na status bar",
            "Ctrl+F — procurar",
            "Ctrl+G — ir para linha",
            "Melhorar AST / Outline",
            "Abas no JCode",
            "Autocomplete de símbolos / variáveis",
            "Executar código pelo JCode",
            "Auto-fechamento de parênteses",
            "Testar highlight de C, C++, Rust, HTML, CSS, JS, PHP etc.",
        ],
    ),
    (
        "JShell",
        [
            "Autocomplete de arquivos e pastas",
            "history",
            "system",
            "Help organizado",
            "Abas / terminal secundário",
        ],
    ),
    (
        "JFiles",
        [
            "Renomear",
            "Copiar / mover",
            "Informações do arquivo",
            "Busca",
            "Preview",
            "Escolher: abrir no JCode ou executar",
        ],
    ),
    (
        "JDev — futuro",
        [
            "Integração maior entre JShell, JFiles e JCode",
            "Sistema de projetos",
            "Configuração / tema compartilhado",
        ],
    ),
]


class JDevTodo:
    def __init__(self, root):
        self.root = root
        self.root.title("JDev — To-Do")
        self.root.geometry("460x650")
        self.root.minsize(380, 450)

        # Mantém a janela sempre acima das outras.
        self.root.attributes("-topmost", True)

        # Paleta inspirada no visual atual do JDev.
        self.bg = "#282828"
        self.fg = "#ebdbb2"
        self.muted = "#a89984"
        self.accent = "#fe8019"
        self.card = "#3c3836"

        self.root.configure(bg=self.bg)

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")

        self.style.configure(
            "JDev.TCheckbutton",
            background=self.card,
            foreground=self.fg,
            font=("DejaVu Sans", 10),
            padding=(5, 4),
        )

        self.style.map(
            "JDev.TCheckbutton",
            background=[("active", self.card)],
            foreground=[("active", self.fg)],
        )

        self.style.configure(
            "JDev.Vertical.TScrollbar",
            background=self.card,
            troughcolor=self.bg,
            bordercolor=self.bg,
            arrowcolor=self.fg,
        )

        self.checks = []

        self.criar_interface()

    def criar_interface(self):
        # Cabeçalho
        header = tk.Frame(self.root, bg=self.bg)
        header.pack(fill="x", padx=16, pady=(14, 5))

        tk.Label(
            header,
            text="JDev",
            bg=self.bg,
            fg=self.accent,
            font=("DejaVu Sans", 18, "bold"),
        ).pack(side="left")

        tk.Label(
            header,
            text="  TO-DO",
            bg=self.bg,
            fg=self.fg,
            font=("DejaVu Sans", 13),
        ).pack(side="left", pady=(4, 0))

        self.count_var = tk.StringVar(value="0 concluídas")

        tk.Label(
            header,
            textvariable=self.count_var,
            bg=self.bg,
            fg=self.muted,
            font=("DejaVu Sans", 9),
        ).pack(side="right", pady=(6, 0))

        # Linha divisória
        tk.Frame(self.root, bg=self.card, height=1).pack(
            fill="x", padx=16, pady=(0, 6)
        )

        # Área rolável
        container = tk.Frame(self.root, bg=self.bg)
        container.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.canvas = tk.Canvas(
            container,
            bg=self.bg,
            highlightthickness=0,
            bd=0,
        )

        self.scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.canvas.yview,
            style="JDev.Vertical.TScrollbar",
        )

        self.content = tk.Frame(self.canvas, bg=self.bg)

        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.content.bind("<Configure>", self.atualizar_scroll)
        self.canvas.bind("<Configure>", self.atualizar_largura)

        self.criar_tarefas()

        # Rodapé
        footer = tk.Frame(self.root, bg=self.bg)
        footer.pack(fill="x", padx=16, pady=(0, 12))

        tk.Label(
            footer,
            text="Clique nas tarefas para marcar",
            bg=self.bg,
            fg=self.muted,
            font=("DejaVu Sans", 8),
        ).pack(side="left")

        tk.Button(
            footer,
            text="Limpar",
            command=self.limpar_tarefas,
            bg=self.card,
            fg=self.fg,
            activebackground=self.accent,
            activeforeground=self.bg,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="right")

        # Mouse wheel
        self.canvas.bind_all("<MouseWheel>", self.mousewheel)

        # Linux costuma usar Button-4/Button-5 para scroll em alguns
        # ambientes X11.
        self.canvas.bind_all("<Button-4>", self.scroll_up)
        self.canvas.bind_all("<Button-5>", self.scroll_down)

    def criar_tarefas(self):
        for categoria, tarefas in TODO:
            card = tk.Frame(
                self.content,
                bg=self.card,
                highlightthickness=0,
            )
            card.pack(fill="x", padx=3, pady=(6, 4))

            tk.Label(
                card,
                text=categoria,
                bg=self.card,
                fg=self.accent,
                font=("DejaVu Sans", 11, "bold"),
                anchor="w",
            ).pack(fill="x", padx=12, pady=(9, 5))

            for tarefa in tarefas:
                var = tk.BooleanVar(value=False)

                check = ttk.Checkbutton(
                    card,
                    text=tarefa,
                    variable=var,
                    command=self.atualizar_estado,
                    style="JDev.TCheckbutton",
                )
                check.pack(fill="x", padx=8, pady=1)

                self.checks.append((var, check))

            tk.Frame(card, bg=self.card, height=7).pack()

    def atualizar_estado(self):
        concluidas = 0

        for var, check in self.checks:
            if var.get():
                concluidas += 1
                check.configure(foreground=self.muted)
            else:
                check.configure(foreground=self.fg)

        self.count_var.set(
            f"{concluidas}/{len(self.checks)} concluídas"
        )

    def limpar_tarefas(self):
        for var, check in self.checks:
            var.set(False)
            check.configure(foreground=self.fg)

        self.atualizar_estado()

    def atualizar_scroll(self, event=None):
        self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        )

    def atualizar_largura(self, event):
        self.canvas.itemconfigure(
            self.window_id,
            width=event.width,
        )

    def mousewheel(self, event):
        self.canvas.yview_scroll(
            int(-event.delta / 120),
            "units",
        )

    def scroll_up(self, event):
        self.canvas.yview_scroll(-1, "units")

    def scroll_down(self, event):
        self.canvas.yview_scroll(1, "units")


def main():
    root = tk.Tk()
    JDevTodo(root)
    root.mainloop()


if __name__ == "__main__":
    main()
