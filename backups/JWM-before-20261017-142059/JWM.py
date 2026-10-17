#!/usr/bin/env python3
"""JWM — um window manager X11 minimalista para o ecossistema J.

- JDesk é tratado como desktop de fundo, sem decoração e sempre atrás.
- Janelas normais usam layout master/stack, com modo flutuante opcional.
- Alt fica reservado ao JDesk/JTerm; os atalhos globais usam Super (tecla Windows).

Este é um WM X11 real: não roda dentro de Sway/Wayland nem junto de outro WM.
"""
from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from Xlib import X, XK, display, error, protocol
except ImportError as exc:
    print("JWM precisa do pacote Python python-xlib.", file=sys.stderr)
    print("No Void, procure com: xbps-query -Rs python3-xlib", file=sys.stderr)
    print("Alternativa: python3 -m pip install --user python-xlib", file=sys.stderr)
    raise SystemExit(2) from exc

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = Path.home() / ".cache" / "jwm.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("JWM")

# Tokyo Night-inspired, deliberately simple: no shadows, no animations, no compositor.
COLOR_BG = "#1a1b26"
COLOR_BORDER = "#565f89"
COLOR_FOCUS = "#7aa2f7"
COLOR_FLOAT = "#e0af68"
BORDER = 3
GAP = 4
JDESK_BAR = 28  # deixa a barra do JDesk visível mesmo quando há apps por cima
MIN_W = 180
MIN_H = 100
DEFAULT_MASTER_RATIO = 0.56
RATIO_STEP = 0.04
WEIGHT_STEP = 0.12
MOVE_STEP = 24
RESIZE_STEP = 24


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
    geom: tuple[int, int, int, int] = (80, 80, 800, 600)


@dataclass
class Workspace:
    clients: list[int] = field(default_factory=list)
    master_ratio: float = DEFAULT_MASTER_RATIO


class JWM:
    """Small reparenting-free ICCCM/EWMH window manager for X11."""

    def __init__(self, jdesk: bool = True):
        self.dpy = display.Display()
        self.dpy.set_error_handler(self._xerror)
        self.screen = self.dpy.screen()
        self.root = self.screen.root
        self.width = self.screen.width_in_pixels
        self.height = self.screen.height_in_pixels
        self.clients: dict[int, Client] = {}
        self.workspaces = [Workspace() for _ in range(4)]
        self.current_ws = 0
        self.active: Optional[int] = None
        self.desktop_id: Optional[int] = None
        self.ignored_unmaps: dict[int, int] = {}
        self.running = True
        self.drag: Optional[dict] = None
        self.desktop_proc: Optional[subprocess.Popen] = None
        self.key_names: dict[int, str] = {}
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
        self.pix_bg = self._color(COLOR_BG)
        self._claim_root()
        self._setup_ewmh()
        self._grab_keys()
        self._refresh_size()
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

    def _grab_keys(self) -> None:
        # Alt é deliberadamente livre para os atalhos que JDesk/JTerm já usam.
        bindings = [
            ("Return", 0), ("d", 0), ("q", 0), ("q", X.ShiftMask),
            ("f", 0), ("space", 0), ("Tab", 0),
            ("1", 0), ("2", 0), ("3", 0), ("4", 0),
            ("1", X.ShiftMask), ("2", X.ShiftMask), ("3", X.ShiftMask), ("4", X.ShiftMask),
            ("h", 0), ("j", 0), ("k", 0), ("l", 0),
            ("Left", 0), ("Right", 0), ("Up", 0), ("Down", 0),
            ("h", X.ShiftMask), ("j", X.ShiftMask), ("k", X.ShiftMask), ("l", X.ShiftMask),
            ("Left", X.ShiftMask), ("Right", X.ShiftMask), ("Up", X.ShiftMask), ("Down", X.ShiftMask),
            ("Left", X.ControlMask), ("Right", X.ControlMask), ("Up", X.ControlMask), ("Down", X.ControlMask),
            ("Escape", X.ShiftMask),
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
                win.configure(x=0, y=0, width=self.width, height=self.height,
                              border_width=0, stack_mode=X.Below)
                win.change_property(self.a["_NET_WM_WINDOW_TYPE"], Xatom_atom(), 32,
                                    [self.a["_NET_WM_WINDOW_TYPE_DESKTOP"]])
                if not already_mapped:
                    win.map()
                self._lower_desktop()
                self.arrange()  # passa a reservar a faixa da JBar no topo
                log.info("JDesk reconhecido como desktop de fundo (0x%x)", wid)
                return

            trans = False
            try:
                trans = bool(win.get_wm_transient_for())
            except Exception:
                pass
            c = Client(window=win, wid=wid, title=title, wm_class=klass,
                       workspace=self.current_ws, floating=self._is_dialog(win, klass, title) or trans,
                       geom=self._geom(win))
            self.clients[wid] = c
            self.workspaces[self.current_ws].clients.append(wid)
            win.change_attributes(event_mask=(X.EnterWindowMask | X.FocusChangeMask | X.PropertyChangeMask))
            # Passive grabs allow Super+mouse actions without stealing normal clicks from Tk/apps.
            for button in (1, 3):
                for lock in self.lock_masks:
                    try:
                        win.grab_button(button, X.Mod4Mask | lock, False,
                                        X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask,
                                        X.GrabModeAsync, X.GrabModeAsync, X.NONE, X.NONE)
                    except error.BadAccess:
                        log.warning("Não foi possível reservar Super+botão %d em 0x%x", button, wid)
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
        ids = list(self.clients)
        try:
            self.root.change_property(self.a["_NET_CLIENT_LIST"], Xatom_window(), 32, ids)
            self.root.change_property(self.a["_NET_CLIENT_LIST_STACKING"], Xatom_window(), 32, ids)
        except Exception:
            pass

    def _visible_clients(self) -> list[Client]:
        return [self.clients[w] for w in self.workspaces[self.current_ws].clients if w in self.clients]

    def _tile_clients(self) -> list[Client]:
        return [c for c in self._visible_clients() if not c.floating and not c.fullscreen]

    def arrange(self) -> None:
        self._refresh_size()
        visible = self._visible_clients()
        tile = [c for c in visible if not c.floating and not c.fullscreen]
        full = next((c for c in visible if c.fullscreen), None)
        top = JDESK_BAR if self.desktop_id is not None else 0
        area_h = max(MIN_H, self.height - top)
        if full:
            self._place(full, 0, 0, self.width, self.height, border=0)
        elif tile:
            if len(tile) == 1:
                self._place(tile[0], 0, top, self.width, area_h)
            else:
                gap = GAP
                usable_w = max(2 * MIN_W, self.width - gap)
                master_w = int((usable_w) * self.workspaces[self.current_ws].master_ratio)
                master_w = min(usable_w - MIN_W, max(MIN_W, master_w))
                stack_w = usable_w - master_w
                self._place(tile[0], 0, top, master_w - gap, area_h)
                stack = tile[1:]
                total_weight = sum(max(0.1, c.weight) for c in stack)
                y = top
                remaining_h = area_h
                remaining_weight = total_weight
                for i, c in enumerate(stack):
                    if i == len(stack) - 1:
                        h = remaining_h
                    else:
                        h = int(remaining_h * max(0.1, c.weight) / max(0.1, remaining_weight))
                    h = max(MIN_H, min(remaining_h - MIN_H * (len(stack) - i - 1), h))
                    self._place(c, master_w + gap, y, stack_w - gap, h - gap)
                    y += h
                    remaining_h -= h
                    remaining_weight -= max(0.1, c.weight)
        for c in visible:
            if c.floating and not c.fullscreen:
                x, y, w, h = c.geom
                top = JDESK_BAR if self.desktop_id is not None else 0
                w, h = min(self.width, max(MIN_W, w)), min(self.height - top, max(MIN_H, h))
                x, y = max(0, min(x, self.width - w)), max(top, min(y, self.height - h))
                self._place(c, x, y, w, h)
        for c in visible:
            self._set_border(c)
        try:
            # Manter desktop abaixo de janelas; as flutuantes ficam acima das tiled.
            for c in visible:
                if c.floating:
                    c.window.configure(stack_mode=X.Above)
            if self.active in self.clients and self.clients[self.active].workspace == self.current_ws:
                self.clients[self.active].window.configure(stack_mode=X.Above)
        except error.BadWindow:
            pass
        self._lower_desktop()
        self._update_client_list()
        self.dpy.flush()

    def _place(self, c: Client, x: int, y: int, w: int, h: int, border: int = BORDER) -> None:
        w, h = max(MIN_W, int(w)), max(MIN_H, int(h))
        try:
            c.window.configure(x=int(x), y=int(y), width=w, height=h,
                               border_width=border, border_pixel=self.pix_focus if c.wid == self.active else self.pix_border)
            c.geom = (int(x), int(y), w, h)
        except error.BadWindow:
            pass

    def _set_border(self, c: Client) -> None:
        try:
            pixel = self.pix_focus if c.wid == self.active else (self.pix_float if c.floating else self.pix_border)
            c.window.configure(border_pixel=pixel)
        except error.BadWindow:
            pass

    def focus(self, wid: Optional[int]) -> None:
        if wid is None or wid not in self.clients:
            self.active = None
            try:
                self.root.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
            except Exception:
                pass
            return
        c = self.clients[wid]
        if c.workspace != self.current_ws:
            return
        self.active = wid
        try:
            c.window.map()
            c.window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
            c.window.configure(stack_mode=X.Above)
            self.root.change_property(self.a["_NET_ACTIVE_WINDOW"], Xatom_window(), 32, [wid])
        except error.BadWindow:
            self.remove(wid)
        self.arrange()

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
        # Em layout master/stack, ir para esquerda escolhe o master; direita escolhe o stack.
        tile = self._tile_clients()
        if cur in tile and len(tile) > 1:
            if direction in ("left", "h"):
                target = tile[0] if cur is not tile[0] else (tile[-1] if len(tile) > 1 else cur)
                self.focus(target.wid)
                return
            if direction in ("right", "l"):
                target = tile[1] if cur is tile[0] else (tile[0] if cur is tile[-1] else tile[tile.index(cur) + 1])
                self.focus(target.wid)
                return
            if direction in ("up", "k", "down", "j"):
                candidates = [c for c in visible if c is not cur]
                if candidates:
                    same_stack = [c for c in tile[1:] if c is not cur]
                    pool = same_stack if cur in tile[1:] and same_stack else candidates
                    i = pool.index(cur) if cur in pool else -1
                    if direction in ("up", "k"):
                        target = pool[(i - 1) % len(pool)] if pool else candidates[0]
                    else:
                        target = pool[(i + 1) % len(pool)] if pool else candidates[0]
                    self.focus(target.wid)
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
        ws = self.workspaces[self.current_ws]
        if self.active not in ws.clients:
            return
        i = ws.clients.index(self.active)
        delta = -1 if direction in ("left", "up", "h", "k") else 1
        j = max(0, min(len(ws.clients) - 1, i + delta))
        if i != j:
            ws.clients[i], ws.clients[j] = ws.clients[j], ws.clients[i]
            self.arrange()
            self.focus(self.active)

    def resize_tiling(self, direction: str) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        if c.floating:
            x, y, w, h = c.geom
            if direction == "left": w -= RESIZE_STEP
            elif direction == "right": w += RESIZE_STEP
            elif direction == "up": h -= RESIZE_STEP
            elif direction == "down": h += RESIZE_STEP
            c.geom = (x, y, max(MIN_W, w), max(MIN_H, h))
        else:
            ws = self.workspaces[self.current_ws]
            tile = self._tile_clients()
            if len(tile) < 2:
                return
            if direction == "left":
                ws.master_ratio = max(0.30, ws.master_ratio - RATIO_STEP)
            elif direction == "right":
                ws.master_ratio = min(0.78, ws.master_ratio + RATIO_STEP)
            elif direction in ("up", "down") and c in tile[1:]:
                idx = tile.index(c)
                neighbor = tile[idx - 1] if direction == "up" and idx > 1 else (
                    tile[idx + 1] if direction == "down" and idx < len(tile) - 1 else None)
                if neighbor:
                    step = WEIGHT_STEP if direction == "down" else -WEIGHT_STEP
                    c.weight = max(0.2, c.weight + step)
                    neighbor.weight = max(0.2, neighbor.weight - step)
        self.arrange()

    def toggle_float(self) -> None:
        if self.active not in self.clients:
            return
        c = self.clients[self.active]
        if not c.floating:
            # capture a comfortable rectangle centred around the current window
            c.geom = (max(20, self.width // 5), max(20, self.height // 6),
                      max(MIN_W, self.width * 3 // 5), max(MIN_H, self.height * 2 // 3))
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

    def _key(self, ev) -> None:
        state = ev.state
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
        top = JDESK_BAR if self.desktop_id is not None else 0
        c.geom = (max(0, min(x, self.width - w)), max(top, min(y, self.height - h)), w, h)
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
            top = JDESK_BAR if self.desktop_id is not None else 0
            c.geom = (max(0, min(x, self.width - sw)), max(top, min(y, self.height - sh)), sw, sh)
        else:
            c.geom = (sx, sy, max(MIN_W, sw + dx), max(MIN_H, sh + dy))
        self._place(c, *c.geom)

    def _button(self, ev) -> None:
        if self.desktop_id and ev.window.id == self.desktop_id:
            # JDesk continua abaixo dos outros; foco é necessário para os próprios atalhos Alt.
            try:
                self.dpy.set_input_focus(ev.window, X.RevertToPointerRoot, X.CurrentTime)
            except error.BadWindow:
                pass
            return
        if ev.window.id in self.clients:
            self.focus(ev.window.id)
            self._start_drag(ev)

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

    def _configure_request(self, ev) -> None:
        wid = ev.window.id
        if self.desktop_id and wid == self.desktop_id:
            try:
                ev.window.configure(x=0, y=0, width=self.width, height=self.height, border_width=0, stack_mode=X.Below)
            except error.BadWindow:
                self.desktop_id = None
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
        if c.floating:
            x, y, w, h = c.geom
            c.geom = (values.get("x", x), values.get("y", y),
                      max(MIN_W, values.get("width", w)), max(MIN_H, values.get("height", h)))
        self.arrange()

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
            wid = ev.window.id
            if wid in self.clients and self.clients[wid].workspace == self.current_ws:
                self.focus(wid)
            elif self.desktop_id and wid == self.desktop_id:
                try:
                    ev.window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
                except error.BadWindow:
                    pass
        elif ev.type == X.MotionNotify:
            self._motion(ev)
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
            self.arrange()

    def run(self) -> None:
        try:
            while self.running:
                while self.dpy.pending_events():
                    ev = self.dpy.next_event()
                    self._handle(ev)
                if not self.dpy.pending_events():
                    time.sleep(0.004)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        log.info("Encerrando JWM")
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
    parser.add_argument("--no-jdesk", action="store_true", help="não iniciar o JDesk automaticamente")
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
