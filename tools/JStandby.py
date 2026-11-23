#!/usr/bin/env python3
"""JStandby — painel de descanso leve para o TTY.

    python3 tools/JStandby.py

Usa a logo e as informações do Fastfetch, se instalado. q ou Esc sai.
"""
from __future__ import annotations

import curses
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def ler_os() -> tuple[str, str]:
    dados: dict[str, str] = {}
    try:
        for linha in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            chave, sep, valor = linha.partition("=")
            if sep:
                dados[chave] = valor.strip().strip('"')
    except OSError:
        pass
    return dados.get("PRETTY_NAME", "Linux"), dados.get("ID", "linux")


def fastfetch() -> tuple[list[str], list[tuple[str, str]], int]:
    """Busca a logo em texto e um conjunto pequeno de módulos do Fastfetch."""
    nome, distro_id = ler_os()
    exe = shutil.which("fastfetch")
    logo: list[str] = []
    specs: list[tuple[str, str]] = [("SISTEMA", nome), ("KERNEL", platform.release())]
    cores = os.cpu_count() or 1
    if not exe:
        return logo, specs, cores

    try:
        r = subprocess.run(
            [exe, "--logo", "auto", "--structure", "none", "--pipe"],
            capture_output=True, text=True, timeout=4,
        )
        logo = [ANSI.sub("", linha).rstrip() for linha in r.stdout.splitlines()]
        logo = [linha for linha in logo if linha.strip()]
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        r = subprocess.run(
            [exe, "--logo", "none", "--structure", "OS:Kernel:Host:CPU:Memory:Uptime", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        itens = json.loads(r.stdout)
        valores: dict[str, object] = {}
        for item in itens:
            if isinstance(item, dict) and isinstance(item.get("result"), dict):
                valores[item.get("type", "")] = item["result"]
        sistema = valores.get("OS", {})
        kernel = valores.get("Kernel", {})
        host = valores.get("Host", {})
        cpu = valores.get("CPU", {})
        mem = valores.get("Memory", {})
        uptime = valores.get("Uptime", {})
        if isinstance(sistema, dict):
            nome = str(sistema.get("prettyName") or sistema.get("name") or nome)
        specs = [("SISTEMA", nome)]
        if isinstance(host, dict) and host.get("name"):
            specs.append(("MÁQUINA", str(host["name"])))
        if isinstance(cpu, dict):
            cpu_nome = str(cpu.get("cpu") or "CPU")
            cores_data = cpu.get("cores")
            if isinstance(cores_data, dict):
                cores = int(cores_data.get("logical") or cores)
            specs.append(("CPU", f"{cpu_nome} · {cores} threads"))
        if isinstance(mem, dict) and mem.get("total"):
            total = int(mem["total"])
            usado = int(mem.get("used", 0))
            specs.append(("MEMÓRIA", f"{usado / 2**30:.1f} / {total / 2**30:.1f} GiB"))
        if isinstance(kernel, dict) and kernel.get("release"):
            specs.append(("KERNEL", str(kernel["release"])))
        if isinstance(uptime, dict) and uptime.get("uptime"):
            mins = int(uptime["uptime"]) // 60
            specs.append(("ATIVO HÁ", f"{mins // 60}h {mins % 60:02d}m"))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        pass

    # Logo em branco é comum em terminais sem dados de logo no Fastfetch.
    if not logo:
        logo = [f"{nome}", f"{distro_id.upper()} · Linux"]
    return logo, specs, max(1, min(cores, 64))


def _put(tela, y: int, x: int, texto: str, attr: int = 0) -> None:
    h, w = tela.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    texto = texto[:max(0, w - x - 1)]
    try:
        tela.addstr(y, max(0, x), texto, attr)
    except curses.error:
        pass


def executar(tela, logo: list[str], specs: list[tuple[str, str]], cores: int) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    tela.nodelay(True)
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, -1)
        curses.init_pair(3, curses.COLOR_BLUE, -1)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
        curses.init_pair(5, curses.COLOR_YELLOW, -1)
    except curses.error:
        pass
    dim, muted, accent = (curses.color_pair(i) for i in (1, 2, 3))
    started = time.monotonic()
    next_frame = 0.0
    frame = 0
    while True:
        key = tela.getch()
        if key in (ord("q"), ord("Q"), 27):
            break
        now = time.monotonic()
        if now < next_frame:
            time.sleep(min(0.1, next_frame - now))
            continue
        next_frame = now + 0.6
        frame += 1
        h, w = tela.getmaxyx()
        tela.erase()
        title = "J D E V   /   STANDBY"
        _put(tela, 1, max(0, (w - len(title)) // 2), title, dim | curses.A_BOLD)
        _put(tela, 2, max(0, (w - 24) // 2), "────────────────────────", accent)

        left_w = max((len(s) for s in logo), default=0)
        panel_w = max((len(k) + len(v) + 5 for k, v in specs), default=24)
        gap = 5
        total_w = left_w + (gap if logo else 0) + panel_w
        x0 = max(1, (w - total_w) // 2)
        content_h = max(len(logo), len(specs) * 2 + 1)
        y0 = max(4, (h - content_h) // 2)

        if w >= min(70, total_w + 2):
            for i, line in enumerate(logo):
                _put(tela, y0 + i, x0, line, dim)
            sx = x0 + left_w + gap
            _put(tela, y0, sx, "SISTEMA", accent | curses.A_BOLD)
            _put(tela, y0 + 1, sx, "────────────────────────────────", dim)
            for i, (label, value) in enumerate(specs):
                row = y0 + 3 + i * 2
                _put(tela, row, sx, label, dim)
                _put(tela, row + 1, sx, value, muted)
        else:
            # Layout estreito para TTYs pequenos: identidade e dados em coluna.
            _put(tela, 4, 2, specs[0][1] if specs else "Linux", accent | curses.A_BOLD)
            row = 6
            for label, value in specs[1:]:
                _put(tela, row, 2, f"{label:<10} {value}", muted)
                row += 1

        # Indicador calmo percorre os threads lógicos, uma posição por quadro.
        bar_w = min(cores, max(8, min(w - 8, 28)))
        pos = frame % bar_w
        bar = "·" * bar_w
        bar = bar[:pos] + "◆" + bar[pos + 1:]
        foot_y = max(0, h - 3)
        _put(tela, foot_y, max(0, (w - bar_w) // 2), bar, dim)
        elapsed = int(now - started)
        pulse = ("◦", "○", "◦", "·")[(frame // 2) % 4]
        footer = f"{pulse}  repouso  ·  sessão {elapsed // 60:02d}:{elapsed % 60:02d}  ·  q sair"
        _put(tela, h - 1, max(0, (w - len(footer)) // 2), footer, dim)
        tela.refresh()


def main() -> int:
    logo, specs, cores = fastfetch()
    try:
        curses.wrapper(executar, logo, specs, cores)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
