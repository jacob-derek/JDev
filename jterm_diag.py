#!/usr/bin/env python3
"""
jterm_diag - diagnóstico de renderização do JTerm (emojis, altura de linha, zoom).

    python3 jterm_diag.py            # precisa de um display (rode dentro do JWM/X)

Mostra a versão do Tk, a fonte escolhida e, para vários caracteres, o quanto o Tk os mede
e quão alta fica uma linha que os contém. Cole a saída inteira quando pedir ajuda.
"""
import subprocess
import tkinter as tk
from tkinter import font

from JTerm import pick_family

AMOSTRAS = [
    ("ASCII", "0"),
    ("caixa ─│┌", "─│┌"),
    ("nerd pasta", "\uf07b"),
    ("pasta 📁", "📁"),
    ("arquivo 📄", "📄"),
    ("check ✓", "✓"),
    ("check ✅", "✅"),
    ("estrela ⭐", "⭐"),
    ("python 🐍", "🐍"),
]


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"(falhou: {exc})"


def main():
    root = tk.Tk()
    root.withdraw()
    print(f"Tk {tk.TkVersion}  patchlevel {root.tk.call('info', 'patchlevel')}  "
          f"windowing {root.tk.call('tk', 'windowingsystem')}")
    n = root.tk.call("string", "length", "\U0001F4C1")
    print(f"Tcl conta o emoji 📁 como {n} caractere(s): "
          + ("OK (suporta fora do BMP)" if str(n) == "1" else "PROBLEMA: Tcl sem suporte a emoji (TCL_UTF_MAX=3)"))
    familia = pick_family()
    print(f"Fonte do terminal: {familia}")
    print(f"fc-match monospace : {sh(['fc-match', 'monospace'])}")
    print(f"fc-match emoji     : {sh(['fc-match', 'emoji'])}")
    emoji_fontes = sh(["sh", "-c", "fc-list | grep -i emoji | head -3"])
    print(f"fontes de emoji    : {emoji_fontes or 'NENHUMA instalada'}")
    print()

    for tamanho in (10, 12, 14, 16):
        f = font.Font(family=familia, size=tamanho)
        cw, lh = f.measure("0"), f.metrics("linespace")
        t = tk.Text(root, font=f, wrap="none", width=40, height=3, bd=0, highlightthickness=0, padx=0, pady=0)
        t.pack()
        print(f"── tamanho {tamanho}: célula {cw}px, linespace {lh}px")
        print(f"   {'amostra':<14}{'largura':>9}{'= células':>11}{'altura linha':>14}{'vs linespace':>14}")
        for nome, txt in AMOSTRAS:
            t.delete("1.0", "end")
            t.insert("1.0", txt)
            root.update_idletasks()
            info = t.dlineinfo("1.0")
            alt = info[3] if info else -1
            larg = f.measure(txt)
            n = max(1, len(txt))
            print(f"   {nome:<14}{larg:>8}px{larg / (cw * n):>10.2f}x{alt:>12}px{alt - lh:>+12}px")
        t.destroy()
    print("\nLeitura: 'altura linha' maior que 'linespace' = o Tk aumentou a linha (fonte de fallback);")
    print("'células' perto de 2.00 para emoji = alinhamento certo; muito maior/menor = colunas desalinhadas.")
    root.destroy()


if __name__ == "__main__":
    main()
