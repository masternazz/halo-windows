"""Halo overlay renderer (Milestone 1).

Run:  python -m overlay

A transparent, always-on-top, CLICK-THROUGH window sized to the primary monitor's
physical bounds. It listens on 127.0.0.1:OVERLAY_PORT for JSON draw commands and paints
antialiased rings / boxes / arrows with labels, expiring each by its ttl.

Design notes (see PLAN.md §5, §8):
  - DPI: call common.set_dpi_awareness() BEFORE QApplication so geometry is physical px.
  - Threading: the HTTP server runs on a daemon thread and MUST NOT touch Qt widgets. It
    emits a Qt Signal; the GUI thread applies the command. (PLAN.md §8.2)
  - Click-through: Qt.WindowTransparentForInput + WS_EX_TRANSPARENT|WS_EX_LAYERED on Windows.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Ensure the repo root is importable when launched as `python -m overlay` from anywhere.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# CRITICAL (PLAN.md §3a): Qt6 auto-scales the UI by the monitor's DPI, which makes QPainter
# and screen geometry work in *logical* pixels. mss captures *physical* pixels. To keep ONE
# coordinate space (physical) across capture and draw, disable Qt's high-DPI scaling so 1 Qt
# unit == 1 physical pixel. Must be set before QApplication is constructed.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

import common  # noqa: E402

# Per-Monitor-v2 DPI awareness (also before any Qt object exists).
common.set_dpi_awareness()

from PySide6.QtCore import (  # noqa: E402
    Qt, QObject, Signal, QTimer, QRectF, QPointF, QAbstractNativeEventFilter
)
from PySide6.QtGui import (  # noqa: E402
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QIcon, QPixmap, QPolygonF, QAction
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QSystemTrayIcon, QMenu
)


# --- annotation model --------------------------------------------------------

class Annotation:
    """A single on-screen mark in PHYSICAL pixels. Expires at `expiry` (monotonic seconds)."""

    __slots__ = ("shape", "x", "y", "radius", "w", "h", "dx", "dy",
                 "label", "color", "born", "expiry")

    def __init__(self, cmd: dict):
        self.shape = cmd.get("shape", "circle")
        self.x = float(cmd.get("x", 0))
        self.y = float(cmd.get("y", 0))
        self.radius = float(cmd.get("radius", common.DEFAULT_RADIUS))
        self.w = float(cmd.get("w", 0))
        self.h = float(cmd.get("h", 0))
        self.dx = float(cmd.get("dx", 0))
        self.dy = float(cmd.get("dy", 0))
        self.label = cmd.get("label") or ""
        self.color = cmd.get("color") or common.DEFAULT_COLOR
        ttl = float(cmd.get("ttl_ms", common.DEFAULT_TTL_MS))
        self.born = time.monotonic()
        self.expiry = self.born + ttl / 1000.0


# --- HTTP -> GUI bridge ------------------------------------------------------

class Bridge(QObject):
    """Marshals HTTP-thread commands onto the GUI thread via Qt signals."""
    draw = Signal(dict)
    clear = Signal()


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        # Silence the default stderr request logging.
        def log_message(self, *args):  # noqa: D401
            pass

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw or b"{}")
            except (json.JSONDecodeError, ValueError):
                return {}

        def _ok(self, payload: dict | None = None):
            body = json.dumps(payload or {"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._ok({"ok": True})
            else:
                self.send_error(404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/clear":
                bridge.clear.emit()
                self._ok()
                return
            if path in ("/circle", "/box", "/arrow"):
                cmd = self._json_body()
                cmd["shape"] = {"/circle": "circle", "/box": "box", "/arrow": "arrow"}[path]
                bridge.draw.emit(cmd)
                self._ok()
                return
            self.send_error(404)

    return Handler


def start_http(bridge: Bridge) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((common.OVERLAY_HOST, common.OVERLAY_PORT), make_handler(bridge))
    t = threading.Thread(target=server.serve_forever, name="halo-http", daemon=True)
    t.start()
    return server


# --- the overlay window ------------------------------------------------------

class Overlay(QWidget):
    def __init__(self, bridge: Bridge):
        super().__init__()
        self._marks: list[Annotation] = []

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Halo Overlay")

        # Cover the primary screen's physical bounds. With per-monitor-v2 awareness set,
        # Qt reports geometry in physical pixels on the primary monitor.
        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)

        bridge.draw.connect(self._on_draw)
        bridge.clear.connect(self._on_clear)

        # ~30fps sweep: expire old marks and repaint (pulse animation needs the repaint too).
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # -- command slots (GUI thread) --
    def _on_draw(self, cmd: dict):
        self._marks.append(Annotation(cmd))
        self.update()

    def _on_clear(self):
        self._marks.clear()
        self.update()

    def toggle_visible(self):
        """Show/hide the overlay without dropping the annotations (hotkey action)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.harden_click_through()

    def _tick(self):
        now = time.monotonic()
        before = len(self._marks)
        self._marks = [m for m in self._marks if m.expiry > now]
        # Repaint every tick while marks exist (pulse) or once when the last one expires.
        if self._marks or before:
            self.update()

    # -- Windows click-through hardening --
    def harden_click_through(self):
        if sys.platform != "win32":
            return
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x20
        WS_EX_LAYERED = 0x80000
        WS_EX_TOOLWINDOW = 0x80
        WS_EX_NOACTIVATE = 0x08000000
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE,
            cur | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        )

    # -- painting --
    def paintEvent(self, event):
        if not self._marks:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        now = time.monotonic()
        for m in self._marks:
            color = QColor(m.color)
            if not color.isValid():
                color = QColor(common.DEFAULT_COLOR)
            if m.shape == "box":
                self._draw_box(p, m, color)
            elif m.shape == "arrow":
                self._draw_arrow(p, m, color)
            else:
                self._draw_circle(p, m, color, now)
            if m.label:
                self._draw_label(p, m, color)
        p.end()

    def _draw_circle(self, p: QPainter, m: Annotation, color: QColor, now: float):
        # Gentle pulse: radius oscillates ~+/-8% over ~1.4s.
        import math
        phase = (now - m.born) / 1.4
        pulse = 1.0 + 0.08 * math.sin(phase * 2 * math.pi)
        r = m.radius * pulse
        pen = QPen(color, common.RING_PEN_WIDTH)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(m.x, m.y), r, r)
        # Faint inner glow ring for contrast on busy backgrounds.
        halo = QColor(color)
        halo.setAlpha(60)
        p.setPen(QPen(halo, common.RING_PEN_WIDTH + 6))
        p.drawEllipse(QPointF(m.x, m.y), r, r)

    def _draw_box(self, p: QPainter, m: Annotation, color: QColor):
        p.setPen(QPen(color, common.RING_PEN_WIDTH))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(m.x, m.y, m.w, m.h), 8, 8)

    def _draw_arrow(self, p: QPainter, m: Annotation, color: QColor):
        import math
        # Arrow points FROM (x+dx, y+dy) TO the target (x, y).
        tail = QPointF(m.x + m.dx, m.y + m.dy)
        tip = QPointF(m.x, m.y)
        p.setPen(QPen(color, common.RING_PEN_WIDTH, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(tail, tip)
        ang = math.atan2(tip.y() - tail.y(), tip.x() - tail.x())
        head = 18.0
        spread = math.radians(26)
        left = QPointF(tip.x() - head * math.cos(ang - spread),
                       tip.y() - head * math.sin(ang - spread))
        right = QPointF(tip.x() - head * math.cos(ang + spread),
                        tip.y() - head * math.sin(ang + spread))
        p.setBrush(QBrush(color))
        p.drawPolygon(QPolygonF([tip, left, right]))

    def _draw_label(self, p: QPainter, m: Annotation, color: QColor):
        font = QFont()
        font.setPointSizeF(11)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)
        pad_x, pad_y = 10, 6
        tw = fm.horizontalAdvance(m.label)
        th = fm.height()
        # Anchor the chip just above-right of the mark.
        if m.shape == "box":
            ax, ay = m.x, m.y - th - 2 * pad_y - 4
        elif m.shape == "arrow":
            ax, ay = m.x + m.dx, m.y + m.dy
        else:
            ax = m.x + m.radius * 0.7
            ay = m.y - m.radius - th - 2 * pad_y
        cw, ch = tw + 2 * pad_x, th + 2 * pad_y
        # Keep the chip fully on-screen: clamp into the window bounds so a label near any
        # edge slides back into view instead of being clipped off the screen.
        margin = 4
        ax = min(max(ax, margin), max(margin, self.width() - cw - margin))
        ay = min(max(ay, margin), max(margin, self.height() - ch - margin))
        chip = QRectF(ax, ay, cw, ch)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(chip, 6, 6)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.drawText(chip, Qt.AlignCenter, m.label)


# --- global hotkeys (Windows RegisterHotKey + native event filter) -----------

WM_HOTKEY = 0x0312
HOTKEY_IDS = {"clear": 1, "toggle": 2, "quit": 3}


class HotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY messages and fires the matching action on the GUI thread."""

    def __init__(self, actions: dict):
        super().__init__()
        self._actions = actions  # {hotkey_id: callable}
        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG), ("pt_y", wintypes.LONG),
            ]
        self._MSG = MSG
        self._ctypes = ctypes

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                msg = self._ctypes.cast(
                    int(message), self._ctypes.POINTER(self._MSG)).contents
                if msg.message == WM_HOTKEY:
                    action = self._actions.get(int(msg.wParam))
                    if action:
                        action()
        except Exception:
            pass
        return False, 0


def register_hotkeys(overlay: "Overlay", app) -> "HotkeyFilter | None":
    """Register configured global hotkeys. Returns the installed filter (or None)."""
    if sys.platform != "win32":
        return None
    import ctypes
    hwnd = int(overlay.winId())
    actions = {
        HOTKEY_IDS["clear"]: overlay._on_clear,
        HOTKEY_IDS["toggle"]: overlay.toggle_visible,
        HOTKEY_IDS["quit"]: app.quit,
    }
    filt = HotkeyFilter(actions)
    app.installNativeEventFilter(filt)
    any_ok = False
    for name, hid in HOTKEY_IDS.items():
        parsed = common.parse_hotkey(common.HOTKEYS.get(name, ""))
        if not parsed:
            continue
        mods, vk = parsed
        # 0x4000 = MOD_NOREPEAT so holding the key fires once.
        if ctypes.windll.user32.RegisterHotKey(hwnd, hid, mods | 0x4000, vk):
            any_ok = True
            sys.stderr.write(f"[halo-overlay] hotkey '{common.HOTKEYS[name]}' -> {name}\n")
        else:
            sys.stderr.write(
                f"[halo-overlay] could not register hotkey '{common.HOTKEYS[name]}' "
                f"for {name} (already in use?)\n")
    return filt if any_ok else filt


# --- tray --------------------------------------------------------------------

def make_tray_icon(color: str) -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(color), 4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(6, 6, 20, 20)
    p.end()
    return QIcon(pix)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    bridge = Bridge()
    overlay = Overlay(bridge)
    overlay.show()
    overlay.harden_click_through()

    # Global hotkeys (clear / toggle / quit) from config/settings.json.
    # Stash on app so Python doesn't GC the native event filter.
    app._halo_hotkey_filter = register_hotkeys(overlay, app)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(make_tray_icon(common.DEFAULT_COLOR))
        tray.setToolTip("Halo overlay — listening on :%d" % common.OVERLAY_PORT)
        menu = QMenu()
        act_clear = QAction("Clear annotations")
        act_clear.triggered.connect(bridge.clear.emit)
        act_quit = QAction("Quit Halo overlay")
        act_quit.triggered.connect(app.quit)
        menu.addAction(act_clear)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.show()

    try:
        server = start_http(bridge)
    except OSError as e:
        sys.stderr.write(f"Halo overlay: cannot bind {common.OVERLAY_BASE}: {e}\n")
        sys.stderr.write("Another overlay is probably already running.\n")
        return 1

    app.aboutToQuit.connect(lambda: server.shutdown())
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
