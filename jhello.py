#!/usr/bin/env python3
"""jhello - o JDev te recebe: balão de boas-vindas no login e um aviso discreto quando um app do JDev abre.

Fala com o JToast pelo D-Bus (qualquer servidor de notificação serve). Roda em segundo plano:
    python3 jhello.py            fica de olho nos apps (jwm-session chama)
    python3 jhello.py --teste    só manda o "bem-vindo" e sai
    JHELLO=0   desliga tudo     JHELLO_APPS=0   só o bem-vindo     JDEV_NOME=Jacob   como te chamar
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
import time

PRONTO = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "jdev", "pronto")

# script -> (nome bonito, mensagem). Só apps que VOCÊ abre; JBar/JDesk/JToast/JWM ficam de fora.
APPS = {
    "JTerm.py": ("JTerm", "terminal na mão"),
    "JCode.py": ("JCode", "bora codar"),
    "JShell.py": ("JShell", "painéis prontos"),
    "JFiles.py": ("JFiles", "pastas à vista"),
    "JRun.py": ("JRun", ""),
    "JAnalyzer.py": ("JAnalyzer", "partidas na mesa"),
}
CALMOS = ("JRun",)          # abrem toda hora: nem avisam
FRASES = ("o dia é seu", "café e código", "a gatinha já está dormindo", "tudo no lugar", "bora fuçar")


def saudacao(hora: int, nome: str = "") -> str:
    base = "Bom dia" if 5 <= hora < 12 else "Boa tarde" if 12 <= hora < 18 else "Boa noite"
    return f"{base}, {nome}" if nome else base


def app_do_cmdline(partes: list[str]):
    """Nome do script JDev numa linha de comando (python3 /x/JCode.py ...), ou None."""
    for p in partes[:4]:
        base = os.path.basename(p)
        if base in APPS:
            return base
    return None


def apps_rodando() -> dict[int, str]:
    achados = {}
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return achados
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                partes = f.read().decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        app = app_do_cmdline(partes)
        if app:
            achados[int(pid)] = app
    return achados


def novos(antes: dict[int, str], agora: dict[int, str]) -> list[str]:
    """Apps com pid novo, sem repetir o mesmo app duas vezes na mesma rodada."""
    vistos, saida = set(), []
    for pid, app in agora.items():
        if pid not in antes and app not in vistos:
            vistos.add(app)
            saida.append(app)
    return saida


def notificar(resumo: str, corpo: str = "", timeout_ms: int = 3500) -> bool:
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        end = DBusAddress("/org/freedesktop/Notifications", bus_name="org.freedesktop.Notifications",
                          interface="org.freedesktop.Notifications")
        with open_dbus_connection(bus="SESSION") as conn:
            msg = new_method_call(end, "Notify", "susssasa{sv}i",
                                  ("JDev", 0, "", resumo, corpo, [], {}, timeout_ms))
            conn.send_and_get_reply(msg, timeout=2)
        return True
    except Exception:       # sem jeepney/barramento: tenta o notify-send, senão desiste em silêncio
        try:
            subprocess.run(["notify-send", "-a", "JDev", "-t", str(timeout_ms), resumo, corpo],
                           timeout=2, check=False)
            return True
        except (OSError, subprocess.SubprocessError):
            return False


def esperar_pronto(limite: float = 14.0) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim and not os.path.exists(PRONTO):
        time.sleep(0.2)
    time.sleep(3.0)         # deixa o fade dos passarinhos acabar antes do balão


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if os.environ.get("JHELLO", "1") == "0":
        return 0
    nome = os.environ.get("JDEV_NOME", "").strip()
    if "--teste" not in argv:
        esperar_pronto()
    notificar(saudacao(time.localtime().tm_hour, nome), random.choice(FRASES), 5000)
    if "--teste" in argv or os.environ.get("JHELLO_APPS", "1") == "0":
        return 0
    conhecidos = apps_rodando()
    ultimo = {}
    while True:
        time.sleep(1.5)
        agora = apps_rodando()
        for app in novos(conhecidos, agora):
            nome_app, msg = APPS[app]
            if nome_app in CALMOS or time.monotonic() - ultimo.get(app, -99) < 8:
                continue
            ultimo[app] = time.monotonic()
            notificar(f"{nome_app} aberto", msg, 2200)
        conhecidos = agora


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
