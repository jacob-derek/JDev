#!/usr/bin/env python3
"""K-Move — controle global do ponteiro pelo teclado no X11.

Inativo: observa a sequência ← → ← → sem consumir as teclas.
Ativo: captura o teclado e controla o ponteiro.

Requer python3-xlib, XTEST e RECORD no servidor X.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from Xlib import X, XK, display
from Xlib.ext import record, xtest
from Xlib.protocol import rq


SEQUENCE = ("left", "right", "left", "right")
SEQUENCE_TIMEOUT_MS = 1000
STEP = 18
FAST_STEP = 65
NORMAL_SCROLL_TICKS = 3
FAST_SCROLL_TICKS = 9
SCROLL_UP = 4
SCROLL_DOWN = 5

active = threading.Event()
stopping = threading.Event()
mode_lock = threading.Lock()
mode_thread: threading.Thread | None = None
record_display = None
record_context = None


def notify(title: str, message: str, sound: str | None = None) -> None:
    """Notificação visual e um tom curto opcional, sem depender do JWM."""
    if subprocess.call(["sh", "-c", "command -v notify-send >/dev/null 2>&1"]) == 0:
        try:
            subprocess.Popen(
                ["notify-send", "-a", "K-Move", "-t", "1400", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
    if sound:
        play_tone(sound)


def make_tone(path: Path, frequency: int) -> None:
    rate = 22050
    duration = 0.12
    amplitude = 6500
    frames = bytearray()
    for i in range(int(rate * duration)):
        fade = min(1.0, i / 250, (rate * duration - i) / 500)
        sample = int(amplitude * fade * math.sin(2 * math.pi * frequency * i / rate))
        frames.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


def play_tone(kind: str) -> None:
    player = shutil_which("paplay")
    if not player:
        return
    path = Path(tempfile.gettempdir()) / f"kmove-{os.getuid()}-{kind}.wav"
    try:
        if not path.exists():
            make_tone(path, 880 if kind == "on" else 440)
        subprocess.Popen(
            [player, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, wave.Error):
        pass


def shutil_which(command: str) -> str | None:
    # Evita uma dependência extra além da biblioteca padrão.
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def keycode(dpy: display.Display, keysym: int) -> int:
    return dpy.keysym_to_keycode(keysym)


def keycodes(dpy: display.Display) -> dict[str, int]:
    return {
        "left": keycode(dpy, XK.XK_Left),
        "right": keycode(dpy, XK.XK_Right),
        "up": keycode(dpy, XK.XK_Up),
        "down": keycode(dpy, XK.XK_Down),
        "a": keycode(dpy, XK.XK_a),
        "d": keycode(dpy, XK.XK_d),
        "s": keycode(dpy, XK.XK_s),
        "l": keycode(dpy, XK.XK_l),
        "escape": keycode(dpy, XK.XK_Escape),
        "page_up": keycode(dpy, XK.XK_Page_Up),
        "page_down": keycode(dpy, XK.XK_Page_Down),
        "q": keycode(dpy, XK.XK_q),
    }


def fake_click(dpy: display.Display, button: int) -> None:
    xtest.fake_input(dpy, X.ButtonPress, button)
    xtest.fake_input(dpy, X.ButtonRelease, button)
    dpy.flush()


def scroll(dpy: display.Display, button: int, ticks: int) -> None:
    for _ in range(ticks):
        xtest.fake_input(dpy, X.ButtonPress, button)
        xtest.fake_input(dpy, X.ButtonRelease, button)
    dpy.flush()


def focus_window_under_pointer(dpy: display.Display, root) -> bool:
    """Eleva e foca a janela superior que contém o ponteiro."""
    pointer = root.query_pointer()
    window = pointer.child
    if window is None or window.id == X.NONE:
        return False

    try:
        while True:
            tree = window.query_tree()
            parent = tree.parent
            if parent is None or parent.id == root.id:
                break
            window = parent
        window.configure(stack_mode=X.Above)
        window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
        dpy.flush()
        return True
    except Exception:
        return False


def run_mouse_mode() -> None:
    """Captura o teclado enquanto o modo mouse estiver ligado."""
    dpy = None
    selection_mode = False
    sequence_progress = 0
    last_sequence_time = 0

    try:
        dpy = display.Display()
        root = dpy.screen().root
        width = dpy.screen().width_in_pixels
        height = dpy.screen().height_in_pixels
        keys = keycodes(dpy)

        status = root.grab_keyboard(
            owner_events=False,
            pointer_mode=X.GrabModeAsync,
            keyboard_mode=X.GrabModeAsync,
            time=X.CurrentTime,
        )
        if status != X.GrabSuccess:
            notify("K-Move", "Não foi possível capturar o teclado.", "off")
            return

        pointer = root.query_pointer()
        x, y = pointer.root_x, pointer.root_y
        notify("K-Move", "Modo mouse ativado", "on")

        while not stopping.is_set():
            event = dpy.next_event()
            if event.type != X.KeyPress:
                continue

            code = event.detail
            state = event.state
            ctrl = bool(state & X.ControlMask)
            shift = bool(state & X.ShiftMask)

            # A mesma sequência usada para ativar também desativa o modo.
            arrow_name = next(
                (name for name in ("left", "right", "up", "down")
                 if code == keys[name]),
                None,
            )
            if arrow_name:
                now = int(time.monotonic() * 1000)
                if now - last_sequence_time > SEQUENCE_TIMEOUT_MS:
                    sequence_progress = 0
                last_sequence_time = now
                if arrow_name == SEQUENCE[sequence_progress]:
                    sequence_progress += 1
                else:
                    sequence_progress = 1 if arrow_name == SEQUENCE[0] else 0
                if sequence_progress == len(SEQUENCE):
                    break
            elif code != keys["escape"]:
                sequence_progress = 0

            if code == keys["escape"] or (ctrl and code == keys["q"]):
                if code == keys["escape"] and selection_mode:
                    selection_mode = False
                    notify("K-Move", "Modo seleção cancelado")
                    continue
                if ctrl and code == keys["q"]:
                    stopping.set()   # Ctrl+Q encerra o processo inteiro
                break
                continue

            if ctrl and code == keys["l"]:
                selection_mode = True
                notify("K-Move", "Seleção: mova até a janela e pressione A")
                continue

            if selection_mode and code == keys["a"]:
                selected = focus_window_under_pointer(dpy, root)
                selection_mode = False
                notify(
                    "K-Move",
                    "Janela selecionada" if selected else "Nenhuma janela sob o ponteiro",
                )
                continue

            if ctrl and code in (keys["page_up"], keys["page_down"]):
                button = SCROLL_UP if code == keys["page_up"] else SCROLL_DOWN
                scroll(dpy, button, FAST_SCROLL_TICKS if shift else NORMAL_SCROLL_TICKS)
                continue

            if code == keys["a"]:
                fake_click(dpy, 1)
            elif code == keys["d"]:
                fake_click(dpy, 3)
            elif code == keys["s"]:
                fake_click(dpy, 2)
            elif code in (keys["left"], keys["right"], keys["up"], keys["down"]):
                step = FAST_STEP if shift else STEP
                if code == keys["left"]:
                    x -= step
                elif code == keys["right"]:
                    x += step
                elif code == keys["up"]:
                    y -= step
                else:
                    y += step
                x = max(0, min(width - 1, x))
                y = max(0, min(height - 1, y))
                root.warp_pointer(x, y)
                dpy.flush()

    except Exception as exc:
        if not stopping.is_set():
            notify("K-Move", f"Erro no modo mouse: {exc}")
    finally:
        if dpy is not None:
            try:
                dpy.ungrab_keyboard(X.CurrentTime)
                dpy.flush()
                dpy.close()
            except Exception:
                pass
        active.clear()
        if not stopping.is_set():
            notify("K-Move", "Modo mouse desativado", "off")


def start_mouse_mode() -> None:
    global mode_thread
    with mode_lock:
        if active.is_set() or stopping.is_set():
            return
        active.set()
        mode_thread = threading.Thread(target=run_mouse_mode, daemon=True)
        mode_thread.start()


def record_callback(reply) -> None:
    """Observa KeyPress globalmente sem consumir eventos das aplicações."""
    if reply.category != record.FromServer or reply.client_swapped or active.is_set():
        return
    data = reply.data
    if not data:
        return

    global _sequence_progress, _last_sequence_time
    while data and not active.is_set():
        try:
            event, data = rq.EventField(None).parse_binary_value(
                data, record_display.display, None, None
            )
        except Exception:
            return

        if event.type != X.KeyPress:
            continue

        code = event.detail
        now = int(time.monotonic() * 1000)
        if now - _last_sequence_time > SEQUENCE_TIMEOUT_MS:
            _sequence_progress = 0
        _last_sequence_time = now

        if code == _activation_keys["left"]:
            name = "left"
        elif code == _activation_keys["right"]:
            name = "right"
        else:
            _sequence_progress = 0
            continue

        if name == SEQUENCE[_sequence_progress]:
            _sequence_progress += 1
        else:
            _sequence_progress = 1 if name == SEQUENCE[0] else 0

        if _sequence_progress == len(SEQUENCE):
            _sequence_progress = 0
            start_mouse_mode()


_sequence_progress = 0
_last_sequence_time = 0
_activation_keys: dict[str, int] = {}


def stop_handler(_signum, _frame) -> None:
    stopping.set()
    if record_display is not None and record_context is not None:
        try:
            record_display.record_disable_context(record_context)
            record_display.flush()
        except Exception:
            pass
    # Envia SIGUSR1 para desbloquear record_enable_context no thread do RECORD.
    # No Linux, qualquer sinal interrompe a syscall de leitura do socket X.
    try:
        os.kill(os.getpid(), signal.SIGUSR1)
    except OSError:
        pass


def _noop(_signum, _frame) -> None:
    """Recebe SIGUSR1 sem fazer nada: só serve para desbloquear o socket."""
    pass


def main() -> int:
    global record_display, record_context, _activation_keys

    try:
        record_display = display.Display()
        control_display = display.Display()
    except Exception as exc:
        print(f"K-Move: não foi possível conectar ao X11: {exc}", file=sys.stderr)
        return 1

    if not record_display.has_extension("RECORD"):
        print("K-Move: o servidor X não oferece a extensão RECORD.", file=sys.stderr)
        return 1
    if not control_display.has_extension("XTEST"):
        print("K-Move: o servidor X não oferece a extensão XTEST.", file=sys.stderr)
        return 1

    _activation_keys = keycodes(record_display)
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGUSR1, _noop)   # usado internamente para desbloquear o RECORD

    record_context = record_display.record_create_context(
        0,
        [record.AllClients],
        [{
            "core_requests": (0, 0),
            "core_replies": (0, 0),
            "ext_requests": (0, 0, 0, 0),
            "ext_replies": (0, 0, 0, 0),
            "delivered_events": (X.KeyPress, X.KeyPress),
            "device_events": (0, 0),
            "errors": (0, 0),
            "client_started": False,
            "client_died": False,
        }],
    )

    print("K-Move aguardando: ← → ← → para ativar/desativar.")
    print("Ctrl+C ou SIGTERM encerra o processo.")

    def _record_loop() -> None:
        try:
            record_display.record_enable_context(record_context, record_callback)
        except Exception as exc:
            if not stopping.is_set():
                print(f"K-Move: erro no observador global: {exc}", file=sys.stderr)
        finally:
            stopping.set()   # garante que main() acorda mesmo se _record_loop sair antes

    record_thread = threading.Thread(target=_record_loop, daemon=True, name="kmove-record")
    record_thread.start()

    try:
        stopping.wait()   # dorme aqui; Ctrl+C levanta KeyboardInterrupt
    except KeyboardInterrupt:
        stopping.set()
        try:
            record_display.record_disable_context(record_context)
            record_display.flush()
        except Exception:
            pass

    if active.is_set() and mode_thread is not None:
        mode_thread.join(timeout=1.5)
    record_thread.join(timeout=2.0)
    try:
        record_display.record_free_context(record_context)
        record_display.close()
        control_display.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
