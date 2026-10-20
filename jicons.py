"""
jicons - ícones usados pelo JFiles e pelo JShell, escolhidos conforme o terminal.

  JICONES=nerd    glifos Nerd Font (BMP, 1 célula): o JTerm sabe desenhá-los (é o padrão dentro dele)
  JICONES=emoji   emojis coloridos (📁 📄): bons em terminais modernos, mas fora do BMP, o que
                  o Tk (JTerm) pode não desenhar ou desenhar com a largura errada
  JICONES=ascii   [D] / [F]: para o console puro (TERM=linux), que não tem fonte de emoji

Sem JICONES definido: TERM=linux -> ascii; senão -> emoji. O JTerm define JICONES=nerd para os
programas que roda, a menos que você já tenha exportado outro valor (ex.: export JICONES=ascii).
"""
import os

_CONJUNTOS = {
    #          pasta        pasta aberta  arquivo      link
    "emoji": ("📁",        "📂",         "📄",        "🔗"),
    "nerd":  ("\uf07b",    "\uf07c",     "\uf15b",    "\uf0c1"),
    "ascii": ("[D]",       "[D]",        "[F]",       "->"),
}


def _modo() -> str:
    pedido = (os.environ.get("JICONES") or "").strip().lower()
    if pedido in _CONJUNTOS:
        return pedido
    return "ascii" if os.environ.get("TERM") == "linux" else "emoji"


MODO = _modo()
PASTA, PASTA_ABERTA, ARQUIVO, LINK = _CONJUNTOS[MODO]
