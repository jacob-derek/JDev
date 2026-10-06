import os
import sys
import re
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import font, scrolledtext

# Mapeamento de códigos ANSI básicos para a paleta Tokyo Night
ANSI_COLOR_MAP = {
    '30': '#15161e', '31': '#f7768e', '32': '#9ece6a', '33': '#e0af68',
    '34': '#7aa2f7', '35': '#bb9af7', '36': '#7dcfff', '37': '#a9b1d6',
    '90': '#565f89', '91': '#f7768e', '92': '#9ece6a', '93': '#e0af68',
    '94': '#7aa2f7', '95': '#bb9af7', '96': '#7dcfff', '97': '#c0caf5'
}

class JShellTTYWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("JShell - Window Terminal")
        self.root.geometry("850x550")
        self.root.configure(bg="#1a1b26")

        self.custom_font = font.Font(family="Consolas", size=11)
        self.queue = queue.Queue()

        # Widget de texto estilizado
        self.text_area = scrolledtext.ScrolledText(
            root,
            bg="#1a1b26",
            fg="#a9b1d6",
            insertbackground="#7dcfff",
            selectbackground="#33467c",
            font=self.custom_font,
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=12,
            wrap=tk.WORD
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Configurar tags de cores
        for code, hex_color in ANSI_COLOR_MAP.items():
            self.text_area.tag_configure(f"ansi_{code}", foreground=hex_color)
        self.text_area.tag_configure("ansi_bold", font=(self.custom_font.actual('family'), 11, 'bold'))

        # Iniciar processo do JShell
        caminho_jshell = os.path.join(os.path.dirname(__file__), "JShell.py")
        
        # PYTHONUNBUFFERED=1 garante que o Python envie os prints imediatamente
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"

        self.process = subprocess.Popen(
            [sys.executable, "-u", caminho_jshell],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        # Configuração das marcas do cursor/entrada
        self.mark_input = "input_start"
        self.text_area.mark_set(self.mark_input, "1.0")
        self.text_area.mark_gravity(self.mark_input, tk.LEFT)

        # Eventos do teclado
        self.text_area.bind("<Return>", self.ao_pressionar_enter)
        self.text_area.bind("<BackSpace>", self.ao_pressionar_backspace)
        self.text_area.bind("<Key>", self.ao_digitar_tecla)

        # Thread de leitura contínua
        self.thread_leitura = threading.Thread(target=self.ler_saida, daemon=True)
        self.thread_leitura.start()

        self.root.after(30, self.processar_saida)

    def ler_saida(self):
        """Lê os caracteres do JShell assim que eles são gerados."""
        while True:
            try:
                char = self.process.stdout.read(1)
                if not char:
                    break
                self.queue.put(char)
            except Exception:
                break

    def processar_saida(self):
        """Aplica os códigos ANSI e imprime o buffer do JShell na GUI."""
        buffer = ""
        while not self.queue.empty():
            buffer += self.queue.get_nowait()

        if buffer:
            self.inserir_texto_com_ansi(buffer)

        self.root.after(30, self.processar_saida)

    def inserir_texto_com_ansi(self, texto):
        """Filtra e interpreta sequências de cores ANSI no widget."""
        # Expressão regular para capturar comandos ANSI de cor
        partes = re.split(r'(\x1b\[[0-9;]*m)', texto)
        tags_atuais = []

        for parte in partes:
            if parte.startswith('\x1b['):
                codigos = parte[2:-1].split(';')
                for c in codigos:
                    if c == '0' or c == '':
                        tags_atuais.clear()
                    elif c == '1':
                        tags_atuais.append("ansi_bold")
                    elif c in ANSI_COLOR_MAP:
                        tags_atuais.append(f"ansi_{c}")
            else:
                if parte:
                    if tags_atuais:
                        self.text_area.insert(tk.END, parte, tuple(tags_atuais))
                    else:
                        self.text_area.insert(tk.END, parte)

        self.text_area.see(tk.END)
        # Atualiza o ponto de limite para a nova entrada do usuário
        self.text_area.mark_set(self.mark_input, tk.END)

    def ao_digitar_tecla(self, event):
        """Impede que o usuário digite/modifique linhas antigas acima do prompt."""
        if self.text_area.compare("insert", "<", self.mark_input):
            self.text_area.mark_set("insert", tk.END)

    def ao_pressionar_backspace(self, event):
        """Impede apagar o texto do prompt impresso pelo JShell."""
        if self.text_area.compare("insert", "<=", self.mark_input):
            return "break"  # Cancela a ação do Backspace

    def ao_pressionar_enter(self, event):
        """Captura o comando inserido e envia para o stdin do JShell."""
        comando = self.text_area.get(self.mark_input, "end-1c")
        
        # Escreve o comando no stdin do processo filho
        if self.process.poll() is None:
            self.process.stdin.write(comando + "\n")
            self.process.stdin.flush()

        return None

if __name__ == "__main__":
    root = tk.Tk()
    app = JShellTTYWindow(root)
    root.mainloop()