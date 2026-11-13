#!/usr/bin/env python3
"""JWM — um window manager X11 minimalista para o ecossistema J.

- JDesk é tratado como desktop de fundo, sem decoração e sempre atrás.
- Janelas normais usam mosaico em árvore (divisões h/v, estilo Sway), com modo flutuante opcional.
- Alt fica reservado ao JDesk/JTerm; os atalhos globais usam Super (tecla Windows).

Este é um WM X11 real: não roda dentro de Sway/Wayland nem junto de outro WM.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from Xlib import X, XK, display, error, protocol
    from Xlib.protocol import event as xevent
    try:
        from Xlib.ext import randr as _randr
    except ImportError:
        _randr = None
except ImportError as exc:
    print("JWM precisa do pacote Python python-xlib.", file=sys.stderr)
    print("No Void, procure com: xbps-query -Rs python3-xlib", file=sys.stderr)
    print("Alternativa: python3 -m pip install --user python-xlib", file=sys.stderr)
    raise SystemExit(2) from exc

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
from jtile import Arvore, vizinho  # noqa: E402  (mosaico em árvore)
try:  # paleta compartilhada (opcional): sem o jtheme.py ao lado vale o Tokyo Night embutido
    import jtheme as _T  # noqa: E402
except ImportError:
    from types import SimpleNamespace as _NS
    _T = _NS(PANE_BG="#1a1b26", BORDER="#56566e", FOCUS="#b04a67", FLOAT="#e0af68", MODE="#9ece6a",
             GAP=8, BAR_H=36)
LOG_PATH = Path.home() / ".cache" / "jwm.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("JWM")

# Paleta e medidas vêm do jtheme (a mesma da JBar, do JTerm e do JDesk).
# Tokyo Night-inspired, simples: sem sombras nem animações aqui; isso é com o picom.
COLOR_BG = _T.PANE_BG
COLOR_BORDER = _T.BORDER
COLOR_FOCUS = _T.FOCUS
COLOR_FLOAT = _T.FLOAT
COLOR_MODE = _T.MODE     # borda da janela ativa enquanto o modo resize está ligado
BORDER = 2

GAP = _T.GAP         # espaço entre janelas em mosaico
OUTER = _T.GAP       # espaço entre o mosaico e a borda do monitor
PORTRAIT_ROWS = True  # monitor em pé (altura > largura): janelas empilhadas em linhas, não lado a lado
JDESK_BAR = _T.BAR_H  # faixa da barra do JDesk, no RODAPÉ do monitor primário (Super+Shift+B esconde)
STATE_PATH = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jwm-state.json"
MIN_W = 180
MIN_H = 100
DEFAULT_MASTER_RATIO = 0.80
RATIO_STEP = 0.04
WEIGHT_STEP = 0.12
MOVE_STEP = 10
RESIZE_STEP = 20
HOTPLUG_POLL = 2.0   # s entre checagens de monitores ligados/desligados
LAYOUT_SCRIPT = APP_DIR / "jwm-layout"
# Padrão: foco por teclado/clique, nunca só por passar o ponteiro.
# Para reativar o comportamento antigo: JWM_FOCUS_FOLLOWS_MOUSE=1.
FOCUS_FOLLOWS_MOUSE = os.environ.get("JWM_FOCUS_FOLLOWS_MOUSE", "0").strip().lower() in {"1", "yes", "true", "on"}


@dataclass
class Client:
    window: object
    wid: int
    title: str = ""
    wm_class: str = ""
    workspace: int = 0
    floating: bool = False
    fullscreen: bool = False
    was_floating: bool = False
    mapped_by_wm: bool = False
    weight: float = 1.0
    monitor: int = 0
    geom: tuple[int, int, int, int] = (80, 80, 800, 600)
    applied_geom: Optional[tuple[int, int, int, int, int]] = None
    applied_border: Optional[int] = None


@dataclass
class Workspace:
    clients: list[int] = field(default_factory=list)
    master_ratio: float = DEFAULT_MASTER_RATIO   # (legado; o mosaico em árvore guarda a proporção em cada divisão)
    trees: dict = field(default_factory=dict)    # monitor -> Arvore
    next_orient: Optional[str] = None            # "h"/"v": como a PRÓXIMA janela divide (Super+B / Super+V)


class JWM:
    """Small reparenting-free ICCCM/EWMH window manager for X11."""

    def __init__(self, jdesk: bool = True):
        self.dpy = display.Display()
        self.dpy.set_error_handler(self._xerror)
        self.screen = self.dpy.screen()
        self.root = self.screen.root
        self.width = self.screen.width_in_pixels
        self.height = self.screen.height_in_pixels
        self.monitors: list[tuple[int, int, int, int]] = [(0, 0, self.width, self.height)]
        self.active_monitor = 0
        self.desk_monitor = 0   # índice do monitor primário: onde mora o JDesk
        self._outputs_sig: Optional[tuple] = None
        self._pending_sig: Optional[tuple] = None
        self._monitor_sig: Optional[tuple] = None
        self._randr_enabled = False
        self._stack_order_cache: Optional[tuple[int, ...]] = None
        self._stacking_dirty = True
        self._deferred_events = []
        self._layout_proc: Optional[subprocess.Popen] = None
        self.clients: dict[int, Client] = {}
        self.workspaces = [Workspace() for _ in range(4)]
        self.current_ws = 0
        self.active: Optional[int] = None
        self.mru: list[int] = []  # ids por recência de foco (a mais recente por último)
        self.desktop_id: Optional[int] = None
        self.ignored_unmaps: dict[int, int] = {}
        self.running = True
        self.drag: Optional[dict] = None
        self.desktop_proc: Optional[subprocess.Popen] = None
        self.key_names: dict[int, str] = {}
        self.mode: Optional[str] = None   # None | "resize"
        self.bar_visible = True           # faixa da JBar reservada no rodapé?
        self._state_json = ""
        self._client_list_cache: Optional[tuple[int, ...]] = None
        self.start_jdesk = jdesk
        self.lock_masks = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)
        self.a = {name: self.dpy.intern_atom(name) for name in (
            "WM_PROTOCOLS", "WM_DELETE_WINDOW", "WM_STATE", "WM_NAME", "WM_CLASS",
            "UTF8_STRING", "_NET_SUPPORTED", "_NET_SUPPORTING_WM_CHECK", "_NET_WM_NAME",
            "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DIALOG",
            "_NET_WM_WINDOW_TYPE_UTILITY", "_NET_WM_WINDOW_TYPE_SPLASH", "_NET_WM_WINDOW_TYPE_DOCK",
            "_NET_WM_STATE", "_NET_WM_STATE_FULLSCREEN", "_NET_ACTIVE_WINDOW", "_NET_CLIENT_LIST",
            "_NET_CLIENT_LIST_STACKING", "_NET_NUMBER_OF_DESKTOPS", "_NET_CURRENT_DESKTOP",
            "_NET_WM_DESKTOP", "_NET_DESKTOP_NAMES", "_NET_WORKAREA", "_NET_CLOSE_WINDOW",
            "_NET_WM_PID", "_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL", "UTF8_STRING",
        )}
        self.pix_focus = self._color(COLOR_FOCUS)
        self.pix_border = self._color(COLOR_BORDER)
        self.pix_float = self._color(COLOR_FLOAT)
        self.pix_mode = self._color(COLOR_MODE)
        self.pix_bg = self._color(COLOR_BG)
        self._claim_root()
        self._setup_ewmh()
        self._grab_keys()
        self._refresh_size()
        self._refresh_monitors()
        self._outputs_sig = self._connected_signature()
        self._monitor_sig = self._display_signature()
        self._setup_randr_events()
        self._scan_existing_windows()
        if self.start_jdesk:
            self._start_desktop()
        log.info("JWM iniciado em %dx%d; log: %s", self.width, self.height, LOG_PATH)

    def _xerror(self, exc, request) -> None:
        # Clientes GUI podem destruir suas janelas entre um evento e o próximo.
        # BadWindow/BadDrawable nessa corrida é normal; não deve encerrar o WM.
        if isinstance(exc, (error.BadWindow, error.BadDrawable)):
            return
        log.warning("Erro de protocolo X11 (%s), request=%s", exc, getattr(request, "_request", request))

    def _color(self, color: str) -> int:
        try:
            return self.screen.default_colormap.alloc_named_color(color).pixel
        except Exception:
            return self.screen.black_pixel

    def _claim_root(self) -> None:
        try:
            self.root.change_attributes(
                event_mask=(X.SubstructureRedirectMask | X.SubstructureNotifyMask |
                            X.PropertyChangeMask | X.KeyPressMask | X.StructureNotifyMask)
            )
            self.dpy.sync()
        except error.BadAccess as exc:
            print("JWM: outro window manager já controla este display X11.", file=sys.stderr)
            print("Saia do Sway/Cinnamon/outro WM ou teste numa sessão Xorg/Xephyr separada.", file=sys.stderr)
            raise SystemExit(1) from exc

    def _setup_ewmh(self) -> None:
        self.wm_check = self.root.create_window(0, 0, 1, 1, 0, X.CopyFromParent, X.InputOutput)
        utf8 = self.a["UTF8_STRING"]
        self.wm_check.change_property(self.a["_NET_WM_NAME"], utf8, 8, b"JWM")
        self.root.change_property(self.a["_NET_SUPPORTING_WM_CHECK"], Xatom_window(), 32, [self.wm_check.id])
        self.wm_check.change_property(self.a["_NET_SUPPORTING_WM_CHECK"], Xatom_window(), 32, [self.wm_check.id])
        supported = [
            "_NET_SUPPORTING_WM_CHECK", "_NET_WM_NAME", "_NET_WM_STATE",
            "_NET_WM_STATE_FULLSCREEN", "_NET_ACTIVE_WINDOW", "_NET_CLIENT_LIST",
            "_NET_CLIENT_LIST_STACKING", "_NET_NUMBER_OF_DESKTOPS", "_NET_CURRENT_DESKTOP",
            "_NET_WM_DESKTOP", "_NET_DESKTOP_NAMES", "_NET_WORKAREA", "_NET_CLOSE_WINDOW",
        ]
        self.root.change_property(self.a["_NET_SUPPORTED"], Xatom_atom(), 32,
                                  [self.a[name] for name in supported])
        self.root.change_property(self.a["_NET_NUMBER_OF_DESKTOPS"], Xatom_cardinal(), 32, [4])
        self.root.change_property(self.a["_NET_CURRENT_DESKTOP"], Xatom_cardinal(), 32, [0])
        self.root.change_property(self.a["_NET_DESKTOP_NAMES"], utf8, 8, b"J|WEB|CODE|MISC\0")
        self.root.change_property(self.a["_NET_WORKAREA"], Xatom_cardinal(), 32,
                                  [0, 0, self.width, self.height] * 4)
        self._update_client_list()

    def _start_desktop(self) -> None:
        script = APP_DIR / "JDesk.py"
        if not script.is_file():
            log.warning("JDesk.py não encontrado em %s; JWM será iniciado sem desktop J.", APP_DIR)
            return
        try:
            self.desktop_proc = subprocess.Popen(
                [sys.executable, str(script)], cwd=str(APP_DIR),
                stdin=subprocess.DEVNULL, stdout=open(LOG_PATH, "a"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log.info("JDesk iniciado (PID %s)", self.desktop_proc.pid)
        except OSError:
            log.exception("Não foi possível iniciar o JDesk")

    def _refresh_size(self) -> None:
        try:
            info = self.root.get_geometry()
            self.width, self.height = max(1, info.width), max(1, info.height)
        except Exception:
            pass

    def _setup_randr_events(self) -> None:
        """Prefere eventos RandR a consultas frequentes ao xrandr."""
        if _randr is None:
            return
        try:
            if not self.dpy.has_extension("RANDR"):
                return
            self.dpy.xrandr_query_version()
            mask = (_randr.RRScreenChangeNotifyMask | _randr.RRCrtcChangeNotifyMask |
                    _randr.RROutputChangeNotifyMask)
            self.root.xrandr_select_input(mask)
            self.dpy.flush()
            self._randr_enabled = True
            log.info("Eventos RandR habilitados para detectar alterações de monitores")
        except Exception:
            self._randr_enabled = False
            log.warning("Não foi possível habilitar eventos RandR; usando polling de segurança", exc_info=True)

    def _read_output_state(self) -> Optional[tuple[tuple[str, Optional[str]], ...]]:
        """Retorna (saída, modo+posição) para cada saída conectada."""
        try:
            result = subprocess.run(["xrandr", "--query"], capture_output=True, text=True,
                                    timeout=1.5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        outputs = re.findall(
            r"^(\S+) connected(?: primary)?(?:\s+(\d+x\d+[+-]\d+[+-]\d+))?",
            result.stdout, re.M,
        )
        return tuple(sorted(outputs))

    def _display_signature(self) -> Optional[tuple]:
        return self._read_output_state()

    def _refresh_monitors(self) -> None:
        """Lê os retângulos físicos do xrandr; fallback para o desktop X11 inteiro.

        O monitor "primário" do xrandr é onde o JDesk fica; sem primário, o mais à esquerda."""
        found: list[tuple[int, int, int, int]] = []
        primary: Optional[tuple[int, int, int, int]] = None
        try:
            result = subprocess.run(
                ["xrandr", "--query"], capture_output=True, text=True,
                timeout=1.5, check=False,
            )
            if result.returncode == 0:
                pattern = re.compile(
                    r"^\s*(\S+)\s+connected(\s+primary)?\s+"
                    r"(\d+)x(\d+)([+-]\d+)([+-]\d+)"
                )
                for line in result.stdout.splitlines():
                    match = pattern.match(line)
                    if not match:
                        continue
                    _, prim, width, height, x, y = match.groups()
                    rect = (int(x), int(y), int(width), int(height))
                    if rect not in found:
                        found.append(rect)
                    if prim:
                        primary = rect
        except (OSError, subprocess.SubprocessError):
            log.debug("Não foi possível consultar os monitores com xrandr", exc_info=True)
        if not found:
            found = [(0, 0, self.width, self.height)]
        self.monitors = sorted(found, key=lambda r: (r[0], r[1]))
        self.desk_monitor = self.monitors.index(primary) if primary in self.monitors else 0
        self.active_monitor = max(0, min(self.active_monitor, len(self.monitors) - 1))
        for c in self.clients.values():
            x, y, w, h = c.geom
            c.monitor = self._monitor_for_point(x + w // 2, y + h // 2)

    def _connected_signature(self) -> Optional[tuple]:
        """Somente nomes das saídas conectadas; modo/posição não significa hotplug."""
        state = self._read_output_state()
        return tuple(name for name, _geometry in state) if state is not None else None

    def _place_desktop(self) -> None:
        """JDesk sempre cobre o monitor primário (e só ele)."""
        if not self.desktop_id:
            return
        try:
            mx, my, mw, mh = self._monitor_rect(self.desk_monitor)
            self.dpy.create_resource_object("window", self.desktop_id).configure(
                x=mx, y=my, width=mw, height=mh, border_width=0, stack_mode=X.Below)
        except error.BadWindow:
            self.desktop_id = None

    def _poll_outputs(self) -> None:
        """Reage a hotplug com jwm-layout; mudanças de modo/posição só reorganizam janelas."""
        proc = self._layout_proc
        if proc is not None:
            if proc.poll() is None:
                return
            self._layout_proc = None
            self._outputs_sig = self._connected_signature()
            self._monitor_sig = self._display_signature()
            self._pending_sig = None
            self._after_layout()
            return

        state = self._read_output_state()
        if state is None:
            return
        connected = tuple(name for name, _geometry in state)
        if self._monitor_sig != state:
            self._monitor_sig = state
            # Resolução/posição mudou, mas as saídas continuam as mesmas:
            # não execute jwm-layout, pois ele poderia desfazer a escolha manual.
            if self._outputs_sig == connected:
                log.info("Modo/posição dos monitores mudou; atualizando geometria sem reaplicar jwm-layout")
                self._after_layout()
                return

        if self._outputs_sig is None:
            self._after_layout()
            return
        if connected == self._outputs_sig:
            self._pending_sig = None
            return
        if not LAYOUT_SCRIPT.is_file():
            log.warning("Saídas conectadas mudaram, mas %s não existe; atualizando geometria", LAYOUT_SCRIPT)
            self._after_layout()
            return
        if connected != self._pending_sig:  # duas leituras iguais evitam oscilações no hotplug
            self._pending_sig = connected
            return

        log.info("Conexões de monitores mudaram: %s -> %s; executando jwm-layout",
                 self._outputs_sig, connected)
        try:
            self._layout_proc = subprocess.Popen(
                ["sh", str(LAYOUT_SCRIPT)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            log.exception("Não foi possível executar %s", LAYOUT_SCRIPT)
            self._outputs_sig = connected
            self._pending_sig = None

    def _after_layout(self) -> None:
        self._refresh_size()
        self._refresh_monitors()
        self._place_desktop()
        self.arrange()
        self._outputs_sig = self._connected_signature()
        self._monitor_sig = self._display_signature()
        self._pending_sig = None

    def _monitor_rect(self, index: Optional[int] = None) -> tuple[int, int, int, int]:
        if not self.monitors:
            return (0, 0, self.width, self.height)
        if index is None:
            index = self.active_monitor
        index = max(0, min(int(index), len(self.monitors) - 1))
        return self.monitors[index]

    def _bar_bottom(self, monitor_index: int) -> int:
        """Altura reservada no RODAPÉ pela barra do JDesk; só existe no monitor primário e some com Super+Shift+B."""
        if self.bar_visible and self.desktop_id is not None and monitor_index == self.desk_monitor:
            return JDESK_BAR
        return 0

    def _write_state(self) -> None:
        """Publica o estado do WM para a JBar (que só lê). Escrita atômica e só quando algo muda."""
        c = self.clients.get(self.active) if self.active is not None else None
        ws = self.workspaces[self.current_ws]
        dados = {"pid": os.getpid(), "bar": self.bar_visible, "mode": self.mode, "split": ws.next_orient,
                 "title": (c.title if c else "") or "", "ws": self.current_ws + 1}
        texto = json.dumps(dados, ensure_ascii=False)
        if texto == self._state_json:
            return
        self._state_json = texto
        try:
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(texto, encoding="utf-8")
            os.replace(tmp, STATE_PATH)
        except OSError:
            pass

    def _desktop_box(self) -> tuple[int, int, int, int]:
        """Retângulo que envolve todos os monitores: (x1, y1, x2, y2)."""
        ms = self.monitors or [(0, 0, self.width, self.height)]
        return (min(m[0] for m in ms), min(m[1] for m in ms),
                max(m[0] + m[2] for m in ms), max(m[1] + m[3] for m in ms))

    def _monitor_for_point(self, x: int, y: int) -> int:
        for i, (mx, my, mw, mh) in enumerate(self.monitors):
            if mx <= x < mx + mw and my <= y < my + mh:
                return i
        # Pontos fora de todos os outputs vão para o centro físico mais próximo.
        return min(
            range(len(self.monitors)),
            key=lambda i: (x - (self.monitors[i][0] + self.monitors[i][2] / 2)) ** 2
                           + (y - (self.monitors[i][1] + self.monitors[i][3] / 2)) ** 2,
        ) if self.monitors else 0

    def _monitor_under_pointer(self) -> int:
        try:
            pointer = self.root.query_pointer()
            return self._monitor_for_point(int(pointer.root_x), int(pointer.root_y))
        except Exception:
            return self.active_monitor

    def _grab_keys(self) -> None:
        # Alt é deliberadamente livre para os atalhos que JDesk/JTerm já usam.
        bindings = [
            ("Return", 0), ("d", 0), ("e", 0), ("q", 0), ("q", X.ShiftMask),
            ("f", 0), ("space", 0), ("Tab", 0),
            ("1", 0), ("2", 0), ("3", 0), ("4", 0),
            ("1", X.ShiftMask), ("2", X.ShiftMask), ("3", X.ShiftMask), ("4", X.ShiftMask),
            ("h", 0), ("j", 0), ("k", 0), ("l", 0),
            ("Left", 0), ("Right", 0), ("Up", 0), ("Down", 0),
            ("h", X.ShiftMask), ("j", X.ShiftMask), ("k", X.ShiftMask), ("l", X.ShiftMask),
            ("Left", X.ShiftMask), ("Right", X.ShiftMask), ("Up", X.ShiftMask), ("Down", X.ShiftMask),
            ("Left", X.ControlMask), ("Right", X.ControlMask), ("Up", X.ControlMask), ("Down", X.ControlMask),
            ("Escape", X.ShiftMask),
            ("b", 0), ("v", 0), ("t", 0), ("r", 0), ("b", X.ShiftMask),
        ]
        for keysym_name, extra in bindings:
            code = self.dpy.keysym_to_keycode(XK.string_to_keysym(keysym_name))
            if not code:
                continue
            self.key_names[code] = keysym_name
            for lock in self.lock_masks:
                try:
                    self.root.grab_key(code, X.Mod4Mask | extra | lock, False,
                                       X.GrabModeAsync, X.GrabModeAsync)
                except error.BadAccess:
                    log.warning("Atalho ocupado: Super+%s", keysym_name)
        self.dpy.sync()

    def _scan_existing_windows(self) -> None:
        try:
            for win in self.root.query_tree().children:
                if win.id == self.wm_check.id:
                    continue
                attrs = win.get_attributes()
                if attrs.map_state != X.IsUnmapped and not attrs.override_redirect:
                    self.manage(win, already_mapped=True)
        except Exception:
            log.exception("Falha ao examinar janelas que já existiam")

    def _title(self, win) -> str:
        for atom in (self.a["_NET_WM_NAME"], self.a["WM_NAME"]):
            try:
                prop = win.get_full_property(atom, X.AnyPropertyType)
                if prop and prop.value is not None:
                    value = prop.value
                    if isinstance(value, bytes):
                        return value.decode("utf-8", "replace")
                    if hasattr(value, "tobytes"):
                        return value.tobytes().decode("utf-8", "replace").rstrip("\0")
                    return str(value)
            except Exception:
                pass
        return ""

    def _class(self, win) -> str:
        try:
            parts = win.get_wm_class() or ()
            return " ".join(x.decode(errors="replace") if isinstance(x, bytes) else str(x) for x in parts).lower()
        except Exception:
            return ""

    def _window_types(self, win) -> list[int]:
        try:
            p = win.get_full_property(self.a["_NET_WM_WINDOW_TYPE"], X.AnyPropertyType)
            return list(p.value) if p else []
        except Exception:
            return []

    def _is_desktop(self, win, title: str, klass: str) -> bool:
        return (title.strip().lower() == "jdesk" or
                "jdesk" in klass or
                self.a["_NET_WM_WINDOW_TYPE_DESKTOP"] in self._window_types(win))

    def _is_dialog(self, win, klass: str, title: str) -> bool:
        types = self._window_types(win)
        if any(self.a[t] in types for t in ("_NET_WM_WINDOW_TYPE_DIALOG", "_NET_WM_WINDOW_TYPE_UTILITY",
                                            "_NET_WM_WINDOW_TYPE_SPLASH")):
            return True
        if any(s in klass for s in ("jrun", "gtk-file-chooser", "calendar", "dialog")):
            return True
        try:
            if win.get_wm_transient_for():
                return True
        except Exception:
            pass
        return title.strip().lower() in {"jrun", "run command", "executar comando"}

    def _geom(self, win) -> tuple[int, int, int, int]:
        try:
            g = win.get_geometry()
            xy = self.root.translate_coords(win, 0, 0)
            return int(xy.x), int(xy.y), max(MIN_W, int(g.width)), max(MIN_H, int(g.height))
        except Exception:
            return (60, 60, max(MIN_W, self.width // 2), max(MIN_H, self.height // 2))

    def manage(self, win, already_mapped: bool = False) -> None:
        wid = win.id
        if wid in self.clients:
            if not already_mapped:
                win.map()
            return
        try:
            attrs = win.get_attributes()
            if attrs.override_redirect:
                return
            title = self._title(win)
            klass = self._class(win)
            if self._is_desktop(win, title, klass):
                self.desktop_id = wid
                win.change_attributes(event_mask=X.EnterWindowMask | X.PropertyChangeMask)
                self._grab_window_buttons(win, wid)
                # JDesk fica restrito ao monitor primário (HDMI quando ligado).
                self._place_desktop()
                win.change_property(self.a["_NET_WM_WINDOW_TYPE"], Xatom_atom(), 32,
                                    [self.a["_NET_WM_WINDOW_TYPE_DESKTOP"]])
                if not already_mapped:
                    win.map()
                self._lower_desktop()
                self.arrange()  # passa a reservar a faixa da JBar no rodapé
                log.info("JDesk reconhecido como desktop de fundo (0x%x)", wid)
                return

            trans = False
            try:
                trans = bool(win.get_wm_transient_for())
            except Exception:
                pass
            geom = self._geom(win)
            monitor = self._monitor_under_pointer()
            try:
                parent = win.get_wm_transient_for()
                if parent and parent.id in self.clients:
                    monitor = self.clients[parent.id].monitor
            except Exception:
                pass
            c = Client(window=win, wid=wid, title=title, wm_class=klass,
                       workspace=self.current_ws,
                       floating=self._is_dialog(win, klass, title) or trans,
                       monitor=monitor, geom=geom)
            if c.floating:
                mx, my, mw, mh = self._monitor_rect(c.monitor)
                gx, gy, gw, gh = c.geom
                bot = self._bar_bottom(c.monitor)
                if gx + gw <= mx or gx >= mx + mw or gy + gh <= my or gy >= my + mh - bot:
                    gx, gy = mx + (mw - min(gw, mw)) // 2, my + (mh - bot - min(gh, mh - bot)) // 2
                c.geom = (gx, gy, min(gw, mw), min(gh, max(MIN_H, mh - bot)))
            self.clients[wid] = c
            self.workspaces[self.current_ws].clients.append(wid)
            win.change_attributes(event_mask=(X.EnterWindowMask | X.FocusChangeMask | X.PropertyChangeMask))
            self._grab_window_buttons(win, wid)
            win.change_attributes(border_pixel=self.pix_border)
            win.configure(border_width=BORDER)
            win.change_property(self.a["_NET_WM_DESKTOP"], Xatom_cardinal(), 32, [self.current_ws])
            win.change_property(self.a["WM_STATE"], self.a["WM_STATE"], 32, [1, X.NONE])
            if not already_mapped and self.current_ws == c.workspace:
                win.map()
            elif c.workspace != self.current_ws:
                self._unmap_by_wm(c)
            self._update_client_list()
            self.arrange()
            if c.workspace == self.current_ws:
                self.focus(c.wid)
            log.info("Gerenciada: %s (0x%x)%s", c.title or c.wm_class or "sem título", wid,
                     " [flutuante]" if c.floating else "")
        except error.BadWindow:
            return
        except Exception:
            log.exception("Falha ao gerenciar janela 0x%x", wid)

    def _grab_window_buttons(self, win, wid: int) -> None:
        """Implementa foco por clique sem perder o clique original do aplicativo.

        O ponteiro fica síncrono no ButtonPress. Clique normal é repassado com
        ReplayPointer; Super+botão inicia arraste e libera os eventos de movimento.
        """
        for button in (1, 3):
            try:
                win.grab_button(
                    button, X.AnyModifier, False,
                    X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask,
                    X.GrabModeSync, X.GrabModeAsync, X.NONE, X.NONE,
                )
            except error.BadAccess:
                log.warning("Não foi possível reservar botão %d em 0x%x", button, wid)

    def _unmap_by_wm(self, c: Client) -> None:
        try:
            self.ignored_unmaps[c.wid] = self.ignored_unmaps.get(c.wid, 0) + 1
            c.window.unmap()
        except error.BadWindow:
            pass

    def _lower_desktop(self) -> None:
        if self.desktop_id:
            try:
                self.dpy.create_resource_object("window", self.desktop_id).configure(stack_mode=X.Below)
            except error.BadWindow:
                self.desktop_id = None

    def _update_client_list(self) -> None:
        """Atualiza listas EWMH; stacking segue a ordem real da árvore X (baixo -> cima)."""
        ids = tuple(self.clients)
        if ids != self._client_list_cache:
            try:
                self.root.change_property(self.a["_NET_CLIENT_LIST"], Xatom_window(), 32, list(ids))
                self._client_list_cache = ids
                self._stacking_dirty = True
            except error.BadWindow:
                return
            except Exception:
                log.debug("Não foi possível atualizar _NET_CLIENT_LIST", exc_info=True)

        if not self._stacking_dirty:
            return
        try:
            children = self.root.query_tree().children  # XQueryTree: ordem bottom-to-top
            child_order = {child.id: index for index, child in enumerate(children)}
            stacking = sorted((wid for wid in self.clients if wid in child_order),
                              key=child_order.__getitem__)
            self.root.change_property(self.a["_NET_CLIENT_LIST_STACKING"], Xatom_window(), 32, stacking)
            self._stacking_dirty = False
        except error.BadWindow:
            pass
        except Exception:
            log.debug("Não foi possível atualizar _NET_CLIENT_LIST_STACKING", exc_info=True)

    def _visible_clients(self) -> list[Client]:
        return [self.clients[w] for w in self.workspaces[self.current_ws].clients if w in self.clients]

    def _tile_clients(self, monitor: Optional[int] = None) -> list[Client]:
        if monitor is None:
            monitor = self.clients[self.active].monitor if self.active in self.clients else self.active_monitor
        return [c for c in self._visible_clients()
                if c.monitor == monitor and not c.floating and not c.fullscreen]

    def _sync_tree(self, monitor: int, ids: list[int], area: tuple[int, int, int, int]) -> Arvore:
        """Deixa a árvore deste monitor/workspace com exatamente as janelas `ids`.
        Quem saiu (fechou, virou flutuante, mudou de workspace/monitor) é removido e o espaço volta
        para o vizinho; quem chegou divide a janela focada, no lado maior (ou como Super+B/V pediu)."""
        ws = self.workspaces[self.current_ws]
        tree = ws.trees.setdefault(monitor, Arvore())
        wanted = set(ids)
        for wid in [w for w in tree.ids() if w not in wanted]:
            tree.remover(wid)
        for wid in ids:
            if wid in tree:
                continue
            tree.layout(*area, GAP, MIN_W, MIN_H)               # atualiza os retângulos antes de dividir
            alvo = self.active if self.active in tree else None
            orient = ws.next_orient
            ws.next_orient = None
            if orient is None:
                r = tree.folhas[alvo].rect if alvo in tree.folhas else area
                orient = "h" if r[2] >= r[3] else "v"
            tree.inserir(wid, alvo, orient)
        return tree

    def arrange(self) -> None:
        self._refresh_size()
        visible = self._visible_clients()

        # Cada monitor tem seu próprio layout. O JDesk fica apenas no monitor 0
        # (HDMI à esquerda); janelas comuns são organizadas no monitor onde abriram.
        for monitor_index, (mx, my, mw, mh) in enumerate(self.monitors or [(0, 0, self.width, self.height)]):
            group = [c for c in visible if c.monitor == monitor_index]
            tile = [c for c in group if not c.floating]          # inclui a tela cheia: mantém o lugar na árvore
            full = next((c for c in group if c.fullscreen), None)
            bot = self._bar_bottom(monitor_index)
            area_y = my
            area_h = max(MIN_H, mh - bot)
            ax, ay = mx + OUTER, area_y + OUTER
            aw, ah = max(MIN_W, mw - 2 * OUTER), max(MIN_H, area_h - 2 * OUTER)
            tree = self._sync_tree(monitor_index, [c.wid for c in tile], (ax, ay, aw, ah))
            if full:
                self._place(full, mx, my, mw, mh, border=0)
            elif tile:
                for wid, (rx, ry, rw, rh) in tree.layout(ax, ay, aw, ah, GAP, MIN_W, MIN_H).items():
                    self._place(self.clients[wid], rx, ry, rw, rh)

        # Janelas flutuantes podem ocupar qualquer ponto do desktop, inclusive a emenda entre os
        # monitores. Só garantimos que fiquem inteiras dentro da caixa que une os monitores, que
        # não cubram a barra do JDesk e que o centro delas caia sobre algum monitor (sem "vazio").
        bx1, by1, bx2, by2 = self._desktop_box()
        m0x, m0y, m0w, m0h = self._monitor_rect(self.desk_monitor)
        for c in visible:
            if c.fullscreen or not c.floating:
                continue
            x, y, w, h = c.geom
            w = min(bx2 - bx1, max(MIN_W, w))
            h = min(by2 - by1, max(MIN_H, h))
            x = max(bx1, min(x, bx2 - w))
            toca_jdesk = self.desktop_id is not None and x < m0x + m0w and x + w > m0x
            y = max(by1, min(y, by2 - h))
            bot0 = self._bar_bottom(self.desk_monitor)
            if toca_jdesk and bot0:                    # não deixa a flutuante cobrir a faixa da barra
                barra_y = m0y + m0h - bot0
                if y < m0y + m0h and y + h > barra_y:
                    y = max(by1, barra_y - h)
            cx, cy = x + w // 2, y + h // 2
            mx, my, mw, mh = self._monitor_rect(self._monitor_for_point(cx, cy))
            if not (mx <= cx < mx + mw and my <= cy < my + mh):  # centro no vazio entre monitores
                y += min(max(cy, my), my + mh - 1) - cy
                x += min(max(cx, mx), mx + mw - 1) - cx
            c.geom = (x, y, w, h)
            c.monitor = self._monitor_for_point(x + w // 2, y + h // 2)
            self._place(c, *c.geom)

        for c in visible:
            self._set_border(c)

        # Camadas, de baixo para cima: mosaico < fullscreen < flutuantes.
        # Só reenvia requests quando a ordem desejada realmente muda.
        ordem = {wid: i for i, wid in enumerate(self.mru)}
        stack_clients = ([c for c in visible if not c.floating and not c.fullscreen] +
                         [c for c in visible if c.fullscreen] +
                         sorted((c for c in visible if c.floating),
                                key=lambda c: ordem.get(c.wid, -1)))
        stack_order = tuple(c.wid for c in stack_clients)
        if stack_order != self._stack_order_cache:
            try:
                for c in stack_clients:
                    c.window.configure(stack_mode=X.Above)
                self._stack_order_cache = stack_order
                self._stacking_dirty = True
            except error.BadWindow:
                self._stack_order_cache = None
        self._lower_desktop()
        self._update_client_list()
        self.dpy.flush()

    def _place(self, c: Client, x: int, y: int, w: int, h: int, border: int = BORDER) -> None:
        """(x, y, w, h) é o retângulo EXTERNO da janela, borda incluída.

        No X11 width/height são o tamanho interno e a borda é somada por fora; sem descontar
        2*border aqui, toda janela passaria da área que recebeu (alguns pixels à direita/embaixo)."""
        w, h = max(MIN_W, int(w)), max(MIN_H, int(h))
        target = (int(x), int(y), w, h, int(border))
        if c.applied_geom == target:
            c.geom = target[:4]
            return
        iw, ih = max(1, w - 2 * border), max(1, h - 2 * border)
        try:
            # Evita configure() redundante: arraste e eventos de foco podem chamar
            # arrange() muitas vezes com a mesma geometria.
            c.window.configure(x=target[0], y=target[1], width=iw, height=ih,
                               border_width=target[4])
            c.applied_geom = target
            c.geom = target[:4]
            self._set_border(c)
        except error.BadWindow:
            pass

    # _set_border
    def _set_border(self, c: Client) -> None:
        pixel = self.pix_focus if c.wid == self.active else (self.pix_float if c.floating else self.pix_border)
        if self.mode and c.wid == self.active:
            pixel = self.pix_mode
        if c.applied_border == pixel:
            return
        try:
            c.window.change_attributes(border_pixel=pixel)
            c.applied_border = pixel
        except error.BadWindow:
            pass


    def focus(self, wid: Optional[int]) -> None:
        old_wid = self.active
        old = self.clients.get(old_wid) if old_wid is not None else None

        if wid is None or wid not in self.clients:
            self.active = None
            if old is not None:
                self._set_border(old)
            try:
                self.root.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
                self.root.change_property(self.a["_NET_ACTIVE_WINDOW"], Xatom_window(), 32, [X.NONE])
                self.dpy.flush()
            except Exception:
                pass
            return

        c = self.clients[wid]
        if c.workspace != self.current_ws:
            return

        # A janela pode continuar marcada como ativa internamente enquanto o foco X11
        # foi transferido para o JDesk (desktop). Ao clicar nela de novo, restaure o
        # foco real mesmo que o ID já seja self.active.
        if wid == old_wid:
            try:
                c.window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
                self.root.change_property(self.a["_NET_ACTIVE_WINDOW"], Xatom_window(), 32, [wid])
                self.dpy.flush()
            except error.BadWindow:
                self.remove(wid)
            return

        self.active = wid
        self.active_monitor = c.monitor
        if wid in self.mru:
            self.mru.remove(wid)
        self.mru.append(wid)

        try:
            c.window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
            # Só janelas flutuantes precisam subir ao receber foco. Uma janela em mosaico
            # elevada aqui poderia ficar por cima de um diálogo flutuante.
            if c.floating:
                c.window.configure(stack_mode=X.Above)
                self._stack_order_cache = None
                self._stacking_dirty = True
                self._update_client_list()
            self.root.change_property(self.a["_NET_ACTIVE_WINDOW"], Xatom_window(), 32, [wid])
            if old is not None:
                self._set_border(old)
            self._set_border(c)
            self.dpy.flush()
        except error.BadWindow:
            self.remove(wid)

    def focus_step(self, step: int = 1) -> None:
        ws = self.workspaces[self.current_ws]
        ids = [w for w in ws.clients if w in self.clients]
        if not ids:
            self.focus(None)
            return
        try:
            i = ids.index(self.active) if self.active in ids else -1
        except ValueError:
            i = -1
        self.focus(ids[(i + step) % len(ids)])

    def focus_direction(self, direction: str) -> None:
        visible = self._visible_clients()
        if not visible:
            return
        if self.active not in self.clients:
            self.focus(visible[0].wid)
            return
        cur = self.clients[self.active]
        visible = [c for c in visible if c.monitor == cur.monitor]
        direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(direction, direction)
        tile = self._tile_clients(cur.monitor)
        if cur in tile:
            alvo = vizinho({c.wid: c.geom for c in tile}, cur.wid, direction)
            if alvo is not None:
                self.focus(alvo)
                return
        x, y, w, h = cur.geom
        cx, cy = x + w / 2, y + h / 2
        eligible = []
        for c in visible:
            if c is cur:
                continue
            xx, yy, ww, hh = c.geom
            tx, ty = xx + ww / 2, yy + hh / 2
            if direction in ("left", "h") and tx < cx:
                dist = cx - tx + abs(cy - ty) * 0.4
            elif direction in ("right", "l") and tx > cx:
                dist = tx - cx + abs(cy - ty) * 0.4
            elif direction in ("up", "k") and ty < cy:
                dist = cy - ty + abs(cx - tx) * 0.4
            elif direction in ("down", "j") and ty > cy:
                dist = ty - cy + abs(cx - tx) * 0.4
            else:
                continue
            eligible.append((dist, c))
        if eligible:
            self.focus(min(eligible, key=lambda pair: pair[0])[1].wid)
        else:
            self.focus_step(1)

    def reorder(self, direction: str) -> None:
        """Super+Shift+setas/hjkl: troca a janela de lugar com a vizinha nessa direção."""
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(direction, direction)
        tile = self._tile_clients(c.monitor)
        tree = self.workspaces[self.current_ws].trees.get(c.monitor)
        if c not in tile or tree is None:
            return
        alvo = vizinho({t.wid: t.geom for t in tile}, c.wid, direction)
        if alvo is None:
            return
        tree.trocar(c.wid, alvo)
        self.arrange()
        self.focus(c.wid)

    def resize_tiling(self, direction: str) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        if mask & (X.CWSibling | X.CWStackMode):
            self._stack_order_cache = None
            self._stacking_dirty = True
        if c.floating:
            x, y, w, h = c.geom
            if direction == "left": w -= RESIZE_STEP
            elif direction == "right": w += RESIZE_STEP
            elif direction == "up": h -= RESIZE_STEP
            elif direction == "down": h += RESIZE_STEP
            c.geom = (x, y, max(MIN_W, w), max(MIN_H, h))
        else:
            tree = self.workspaces[self.current_ws].trees.get(c.monitor)
            if tree is None or len(tree) < 2:
                return
            direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(direction, direction)
            if not tree.redimensionar(c.wid, direction, RESIZE_STEP, GAP):
                return
        self.arrange()

    def toggle_float(self) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        if not c.floating:
            # Retângulo confortável centralizado no monitor da janela ativa.
            mx, my, mw, mh = self._monitor_rect(c.monitor)
            bot = self._bar_bottom(c.monitor)
            w, h = min(mw, max(MIN_W, mw * 3 // 5)), min(mh - bot, max(MIN_H, mh * 2 // 3))
            c.geom = (mx + (mw - w) // 2, my + (mh - bot - h) // 2, w, h)
            c.floating = True
        else:
            c.floating = False
        self.arrange()
        self.focus(c.wid)

    def toggle_fullscreen(self) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        c.fullscreen = not c.fullscreen
        try:
            states = self._property_values(c.window, self.a["_NET_WM_STATE"])
            fs = self.a["_NET_WM_STATE_FULLSCREEN"]
            states = [atom for atom in states if atom != fs]
            if c.fullscreen:
                states.append(fs)
            c.window.change_property(self.a["_NET_WM_STATE"], Xatom_atom(), 32, states)
        except Exception:
            pass
        self.arrange()

    def switch_workspace(self, idx: int) -> None:
        idx = max(0, min(3, idx))
        if idx == self.current_ws:
            return
        self._enter_mode(None)
        old = self.workspaces[self.current_ws]
        for wid in list(old.clients):
            c = self.clients.get(wid)
            if c:
                self._unmap_by_wm(c)
        self.current_ws = idx
        self.root.change_property(self.a["_NET_CURRENT_DESKTOP"], Xatom_cardinal(), 32, [idx])
        ws = self.workspaces[idx]
        for wid in ws.clients:
            c = self.clients.get(wid)
            if c:
                try:
                    c.window.map()
                    c.window.configure(border_width=BORDER)
                except error.BadWindow:
                    pass
        self.active = None
        self.arrange()
        self.focus(ws.clients[-1] if ws.clients else None)

    def send_to_workspace(self, idx: int) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        old_ws = c.workspace
        if old_ws == idx:
            return
        if c.wid in self.workspaces[old_ws].clients:
            self.workspaces[old_ws].clients.remove(c.wid)
        c.workspace = idx
        self.workspaces[idx].clients.append(c.wid)
        c.window.change_property(self.a["_NET_WM_DESKTOP"], Xatom_cardinal(), 32, [idx])
        if old_ws == self.current_ws:
            self._unmap_by_wm(c)
            self.active = None
            self.arrange()
        if idx == self.current_ws:
            c.window.map()
            self.arrange()
            self.focus(c.wid)

    def launch(self, argv: list[str]) -> None:
        try:
            subprocess.Popen(argv, cwd=str(Path.home()), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=open(LOG_PATH, "a"), stderr=subprocess.STDOUT)
        except OSError as exc:
            log.error("Falha ao executar %r: %s", argv, exc)

    def launch_terminal(self) -> None:
        jterm = APP_DIR / "JTerm.py"
        if jterm.is_file():
            self.launch([sys.executable, str(jterm)])
            return
        for name in ("foot", "kitty", "alacritty", "xterm", "uxterm"):
            found = shutil.which(name)
            if found:
                self.launch([found])
                return
        self.launch_runner()

    def launch_file_manager(self) -> None:
        """Abre a pasta pessoal no gerenciador instalado, com fallback via xdg-open."""
        for name in ("thunar", "pcmanfm", "pcmanfm-qt", "spacefm", "xfe", "nemo", "dolphin", "nautilus"):
            executable = shutil.which(name)
            if executable:
                self.launch([executable, str(Path.home())])
                return
        xdg_open = shutil.which("xdg-open")
        if xdg_open:
            self.launch([xdg_open, str(Path.home())])
        else:
            log.error("Nenhum gerenciador de arquivos encontrado; instale Thunar/PCManFM ou xdg-utils")

    def launch_runner(self) -> None:
        runner = APP_DIR / "JRun.py"
        if runner.is_file():
            self.launch([sys.executable, str(runner)])
        else:
            log.error("JRun.py não encontrado em %s", APP_DIR)

    def close_active(self) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        try:
            protocols = c.window.get_wm_protocols() or []
            if self.a["WM_DELETE_WINDOW"] in protocols:
                ev = protocol.event.ClientMessage(
                    window=c.window, client_type=self.a["WM_PROTOCOLS"],
                    data=(32, [self.a["WM_DELETE_WINDOW"], X.CurrentTime, 0, 0, 0]),
                )
                c.window.send_event(ev, event_mask=0, propagate=False)
            else:
                c.window.kill_client()
        except error.BadWindow:
            self.remove(c.wid)

    def remove(self, wid: int) -> None:
        c = self.clients.pop(wid, None)
        if not c:
            return
        for ws in self.workspaces:
            if wid in ws.clients:
                ws.clients.remove(wid)
        self.ignored_unmaps.pop(wid, None)
        if wid in self.mru:
            self.mru.remove(wid)
        if self.active == wid:
            self.active = None
        self._update_client_list()
        self.arrange()
        if self.active is None:
            self.focus_step(1)

    def _property_values(self, win, atom) -> list[int]:
        try:
            prop = win.get_full_property(atom, X.AnyPropertyType)
            return list(prop.value) if prop else []
        except Exception:
            return []

    def _enter_mode(self, nome: Optional[str]) -> None:
        """Modo \"resize\" (como o do sway): captura o teclado; hjkl/setas redimensionam, Enter/Esc saem."""
        if nome == self.mode:
            return
        try:
            if nome:
                self.root.grab_keyboard(True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
            else:
                self.dpy.ungrab_keyboard(X.CurrentTime)
        except Exception:
            log.warning("não consegui %s o teclado", "capturar" if nome else "soltar")
            return
        self.mode = nome
        log.info("modo: %s", nome or "normal")
        if self.active in self.clients:
            self._set_border(self.clients[self.active])
        self.dpy.flush()

    def _key_resize(self, ev) -> None:
        k = self.key_names.get(ev.detail, "").lower()
        if k in ("return", "escape"):
            self._enter_mode(None)
            return
        direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(k, k)
        if direction in ("left", "right", "up", "down"):
            self.resize_tiling(direction)

    def _key(self, ev) -> None:
        state = ev.state
        if self.mode == "resize":
            self._key_resize(ev)
            return
        if not (state & X.Mod4Mask):
            return
        shift = bool(state & X.ShiftMask)
        ctrl = bool(state & X.ControlMask)
        # Xlib não converte todos os keysyms especiais (Left/Right/space) em texto;
        # usamos os keycodes registrados na hora de instalar os atalhos.
        k = self.key_names.get(ev.detail, "").lower()
        if k in ("return", "kp_enter") and not shift and not ctrl:
            self.launch_terminal()
        elif k == "d" and not shift:
            self.launch_runner()
        elif k == "e" and not shift and not ctrl:
            self.launch_file_manager()
        elif k == "q" and shift:
            self.running = False
        elif k == "q" and not shift:
            self.close_active()
        elif k == "f" and not shift:
            self.toggle_fullscreen()
        elif k == "space" and not shift:
            self.toggle_float()
        elif k == "tab" and not shift:
            self.focus_step(1)
        elif k == "b" and shift and not ctrl:
            self.bar_visible = not self.bar_visible
            self.arrange()
        elif k in ("b", "v") and not shift and not ctrl:
            self.workspaces[self.current_ws].next_orient = "h" if k == "b" else "v"
        elif k == "t" and not shift and not ctrl:
            c = self.clients.get(self.active)
            tree = self.workspaces[self.current_ws].trees.get(c.monitor) if c else None
            if tree is not None and tree.alternar_divisao(c.wid):
                self.arrange()
        elif k == "r" and not shift and not ctrl:
            self._enter_mode("resize")
        elif k == "escape" and shift:
            self.running = False
        elif k in ("1", "2", "3", "4"):
            idx = int(k) - 1
            if shift:
                self.send_to_workspace(idx)
            else:
                self.switch_workspace(idx)
        elif ctrl and k in ("left", "right", "up", "down"):
            self.resize_tiling(k)
        elif shift and k in ("h", "j", "k", "l", "left", "right", "up", "down"):
            direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(k, k)
            if self.active in self.clients and self.clients[self.active].floating:
                self.resize_tiling(direction)
            else:
                self.reorder(direction)
        elif k in ("left", "right", "up", "down", "h", "j", "k", "l"):
            direction = {"h": "left", "j": "down", "k": "up", "l": "right"}.get(k, k)
            if self.active in self.clients and self.clients[self.active].floating and k in ("left", "right", "up", "down"):
                self.move_floating(direction)
            else:
                self.focus_direction(direction)

    def move_floating(self, direction: str) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        if not c.floating:
            return
        x, y, w, h = c.geom
        if direction == "left": x -= MOVE_STEP
        elif direction == "right": x += MOVE_STEP
        elif direction == "up": y -= MOVE_STEP
        elif direction == "down": y += MOVE_STEP
        c.geom = (max(0, min(x, self.width - w)), max(0, min(y, self.height - h)), w, h)
        c.monitor = self._monitor_for_point(c.geom[0] + w // 2, c.geom[1] + h // 2)
        self.active_monitor = c.monitor
        self.arrange()

    def _start_drag(self, ev) -> None:
        wid = ev.window.id
        if wid == self.desktop_id:
            return
        c = self.clients.get(wid)
        if not c or not (ev.state & X.Mod4Mask):
            return
        button = ev.detail
        if button not in (1, 3):
            return
        self.focus(wid)
        if not c.floating:
            x, y, w, h = c.geom
            c.floating = True
            c.geom = (x, y, w, h)
            self.arrange()
        # O passive grab (Super+botão) já captura os eventos de movimento/liberação.
        c.geom = self._geom(c.window)
        self.drag = {"wid": wid, "button": button, "root_x": ev.root_x, "root_y": ev.root_y,
                     "geom": c.geom}
        self.dpy.flush()

    def _motion(self, ev) -> None:
        if not self.drag:
            return
        c = self.clients.get(self.drag["wid"])
        if not c:
            return
        sx, sy, sw, sh = self.drag["geom"]
        dx, dy = ev.root_x - self.drag["root_x"], ev.root_y - self.drag["root_y"]
        if self.drag["button"] == 1:
            x, y = sx + dx, sy + dy
            c.geom = (max(0, min(x, self.width - sw)), max(0, min(y, self.height - sh)), sw, sh)
            c.monitor = self._monitor_for_point(c.geom[0] + sw // 2, c.geom[1] + sh // 2)
            self.active_monitor = c.monitor
        else:
            c.geom = (sx, sy, max(MIN_W, sw + dx), max(MIN_H, sh + dy))
        self._place(c, *c.geom)

    def _button(self, ev) -> None:
        wid = ev.window.id
        if self.desktop_id and wid == self.desktop_id:
            # Só um clique no desktop pode transferir o foco para o JDesk; passar o mouse
            # por ele não rouba o teclado das aplicações.
            try:
                self.dpy.set_input_focus(ev.window, X.RevertToPointerRoot, X.CurrentTime)
            except error.BadWindow:
                pass
            self.dpy.allow_events(X.ReplayPointer, X.CurrentTime)
            return

        if wid not in self.clients:
            self.dpy.allow_events(X.ReplayPointer, X.CurrentTime)
            return

        self.focus(wid)
        if (ev.state & X.Mod4Mask) and ev.detail in (1, 3):
            self._start_drag(ev)
            # A passive grab já está ativa; liberta os eventos seguintes para mover/redimensionar.
            self.dpy.allow_events(X.AsyncPointer, X.CurrentTime)
        else:
            # Reenvia o mesmo clique ao aplicativo (botões, seleção de texto e menus continuam a funcionar).
            self.dpy.allow_events(X.ReplayPointer, X.CurrentTime)

    def _client_message(self, ev) -> None:
        typ = ev.client_type
        data = list(ev.data) if not isinstance(ev.data, tuple) else list(ev.data[1])
        wid = ev.window.id
        if typ == self.a["_NET_ACTIVE_WINDOW"]:
            if wid in self.clients:
                self.focus(wid)
        elif typ == self.a["_NET_CLOSE_WINDOW"]:
            if wid in self.clients:
                self.focus(wid)
                self.close_active()
        elif typ == self.a["_NET_WM_STATE"] and wid in self.clients:
            c = self.clients[wid]
            # action 0=remove, 1=add, 2=toggle; handle fullscreen atom in either slot
            action = data[0] if data else 0
            atoms = data[1:3]
            if self.a["_NET_WM_STATE_FULLSCREEN"] in atoms:
                want = (action == 1) or (action == 2 and not c.fullscreen)
                c.fullscreen = want
                self.arrange()

    def _send_configure_notify(self, c: Client) -> None:
        """Informa ao cliente a geometria efetiva quando o WM controla o layout (ICCCM)."""
        x, y, outer_w, outer_h = c.geom
        border = c.applied_geom[4] if c.applied_geom else BORDER
        event = xevent.ConfigureNotify(
            event=c.window, window=c.window, above_sibling=X.NONE,
            x=int(x), y=int(y), width=max(1, int(outer_w - 2 * border)),
            height=max(1, int(outer_h - 2 * border)), border_width=int(border),
            override=False,
        )
        try:
            c.window.send_event(event, event_mask=X.StructureNotifyMask, propagate=False)
        except error.BadWindow:
            pass

    def _configure_request(self, ev) -> None:
        wid = ev.window.id
        if self.desktop_id and wid == self.desktop_id:
            self._place_desktop()
            return
        c = self.clients.get(wid)
        mask = ev.value_mask
        values = {}
        for bit, name in ((X.CWX, "x"), (X.CWY, "y"), (X.CWWidth, "width"),
                          (X.CWHeight, "height"), (X.CWBorderWidth, "border_width"),
                          (X.CWSibling, "sibling"), (X.CWStackMode, "stack_mode")):
            if mask & bit:
                values[name] = getattr(ev, name)
        if c is None:
            try:
                ev.window.configure(**values)
            except error.BadWindow:
                pass
            return
        if mask & (X.CWSibling | X.CWStackMode):
            self._stack_order_cache = None
            self._stacking_dirty = True
        if c.floating:
            x, y, w, h = c.geom
            c.geom = (values.get("x", x), values.get("y", y),
                      max(MIN_W, values.get("width", w)), max(MIN_H, values.get("height", h)))
            c.monitor = self._monitor_for_point(c.geom[0] + c.geom[2] // 2,
                                                c.geom[1] + c.geom[3] // 2)
        self.arrange()
        if wid in self.clients:
            self._send_configure_notify(self.clients[wid])

    def _handle(self, ev) -> None:
        if ev.type == X.MapRequest:
            self.manage(ev.window)
        elif ev.type == X.ConfigureRequest:
            self._configure_request(ev)
        elif ev.type == X.DestroyNotify:
            self.remove(ev.window.id)
        elif ev.type == X.UnmapNotify:
            wid = ev.window.id
            count = self.ignored_unmaps.get(wid, 0)
            if count:
                if count <= 1:
                    self.ignored_unmaps.pop(wid, None)
                else:
                    self.ignored_unmaps[wid] = count - 1
            elif wid in self.clients:
                self.remove(wid)
        elif ev.type == X.KeyPress:
            self._key(ev)
        elif ev.type == X.ButtonPress:
            self._button(ev)
        elif ev.type == X.EnterNotify:
            if (FOCUS_FOLLOWS_MOUSE and ev.mode == X.NotifyNormal
                    and ev.detail not in (X.NotifyInferior, X.NotifyVirtual, X.NotifyNonlinearVirtual)):
                wid = ev.window.id
                if wid in self.clients and self.clients[wid].workspace == self.current_ws:
                    self.focus(wid)
            # O JDesk não recebe foco ao mero movimento do ponteiro; use clique ou atalho.
        elif ev.type == X.MotionNotify:
            # Descarta movimentos intermediários já enfileirados; preserva eventos
            # não relacionados em fila para serem tratados na ordem original.
            latest = ev
            while self.dpy.pending_events():
                queued = self.dpy.next_event()
                if queued.type == X.MotionNotify:
                    latest = queued
                else:
                    self._deferred_events.append(queued)
                    break
            self._motion(latest)
        elif ev.type == X.ButtonRelease:
            if self.drag:
                self.drag = None
                try:
                    self.dpy.ungrab_pointer(X.CurrentTime)
                except Exception:
                    pass
                self.arrange()
        elif ev.type == X.PropertyNotify:
            wid = ev.window.id
            if wid in self.clients and ev.atom in (self.a["WM_NAME"], self.a["_NET_WM_NAME"], self.a["WM_CLASS"]):
                c = self.clients[wid]
                c.title, c.wm_class = self._title(c.window), self._class(c.window)
        elif ev.type == X.ClientMessage:
            self._client_message(ev)
        elif ev.type == X.ConfigureNotify and ev.window.id == self.root.id:
            self._refresh_size()
            self._poll_outputs()
        elif _randr is not None and ev.type in (
                self.dpy.extension_event.ScreenChangeNotify,
                self.dpy.extension_event.CrtcChangeNotify,
                self.dpy.extension_event.OutputChangeNotify):
            self._refresh_size()
            try:
                self._poll_outputs()
            except Exception:
                log.exception("Erro ao processar evento RandR")

    def run(self) -> None:
        """Dorme em select() até chegar evento do X (ou até a próxima checagem de monitores):
        o WM parado não gasta CPU, e um erro num evento não derruba a sessão."""
        fd = self.dpy.fileno()
        poll_interval = 30.0 if self._randr_enabled else HOTPLUG_POLL
        next_poll = time.monotonic() + poll_interval
        try:
            while self.running:
                while self._deferred_events or self.dpy.pending_events():
                    try:
                        ev = self._deferred_events.pop(0) if self._deferred_events else self.dpy.next_event()
                        self._handle(ev)
                    except Exception:
                        log.exception("Erro ao tratar evento do X11 (ignorado)")
                    if not self.running:
                        break
                if not self.running:
                    break
                if self._pending_sig is not None:
                    next_poll = min(next_poll, time.monotonic() + 0.4)
                # Durante arraste, envia as últimas alterações de geometria antes de
                # dormir novamente em select(); evita depender de outro evento X11
                # para descarregar o buffer de requisições.
                if self.drag:
                    self.dpy.flush()
                self._write_state()
                now = time.monotonic()
                if now >= next_poll:
                    try:
                        self._poll_outputs()
                    except Exception:
                        log.exception("Erro ao checar monitores (ignorado)")
                    next_poll = time.monotonic() + (0.3 if self._layout_proc else poll_interval)
                    continue
                select.select([fd], [], [], max(0.01, next_poll - now))
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        log.info("Encerrando JWM")
        try:
            STATE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if self.drag:
                self.dpy.ungrab_pointer(X.CurrentTime)
            for c in list(self.clients.values()):
                try:
                    c.window.configure(border_width=0)
                except error.BadWindow:
                    pass
            if self.desktop_id:
                try:
                    self.dpy.create_resource_object("window", self.desktop_id).configure(border_width=0)
                except Exception:
                    pass
            # Fechar JDesk de forma normal; o X server também encerra os clientes ao sair da sessão.
            if self.desktop_proc and self.desktop_proc.poll() is None:
                self.desktop_proc.terminate()
                try:
                    self.desktop_proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    self.desktop_proc.kill()
            try:
                self.root.change_property(self.a["_NET_ACTIVE_WINDOW"], Xatom_window(), 32, [X.NONE])
                self.root.delete_property(self.a["_NET_SUPPORTING_WM_CHECK"])
            except Exception:
                pass
            self.dpy.sync()
            self.dpy.close()
        except Exception:
            log.exception("Erro durante encerramento")


def Xatom_atom():
    from Xlib import Xatom
    return Xatom.ATOM


def Xatom_window():
    from Xlib import Xatom
    return Xatom.WINDOW


def Xatom_cardinal():
    from Xlib import Xatom
    return Xatom.CARDINAL


def main() -> int:
    parser = argparse.ArgumentParser(description="JWM: window manager X11 do ecossistema J")

    parser.add_argument("--no-jdesk", "--no-ui", dest="no_jdesk", action="store_true",
                        help="não iniciar o JDesk (sem JBar): só o WM, sistema liso")

    args = parser.parse_args()
    try:
        JWM(jdesk=not args.no_jdesk).run()
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        log.exception("JWM terminou com erro; veja %s", LOG_PATH)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
