"""Halo shared constants, settings, and helpers. Imported by overlay/, mcp_server/, cli.py.

Keep this dependency-light (stdlib + ctypes only) so every process can import it cheaply.

User-tunable values live in config/settings.json (see load_settings()). The module-level
constants below are derived from it at import time and kept as the defaults/fallbacks, so
existing imports (OVERLAY_PORT, MAX_DIM, DEFAULT_RADIUS, ...) keep working.
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(_HERE, "config", "settings.json")

# Baked-in defaults. config/settings.json overrides any subset of these.
DEFAULTS = {
    "overlay": {"host": "127.0.0.1", "port": 7333},
    "draw": {"radius": 60, "color": "#FF2D2D", "ttl_ms": 8000, "ring_pen_width": 5},
    # Screenshot token budget: smaller max_dim + JPEG = far fewer tokens/bytes handed to the
    # agent, at some cost to how small a UI element the vision model can still resolve.
    "screenshot": {"max_dim": 1152, "format": "jpeg", "jpeg_quality": 72},
    # Global hotkeys (Windows). Modifiers: ctrl/alt/shift/win + one key. Empty string = off.
    "hotkeys": {"clear": "ctrl+alt+h", "toggle": "ctrl+alt+j", "quit": ""},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    """Return DEFAULTS deep-merged with config/settings.json (if present and valid)."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            user = json.load(f)
        return _deep_merge(DEFAULTS, user)
    except (OSError, ValueError, json.JSONDecodeError):
        return {k: dict(v) for k, v in DEFAULTS.items()}


SETTINGS = load_settings()

# --- IPC ---------------------------------------------------------------------
OVERLAY_HOST = SETTINGS["overlay"]["host"]
OVERLAY_PORT = int(SETTINGS["overlay"]["port"])
OVERLAY_BASE = f"http://{OVERLAY_HOST}:{OVERLAY_PORT}"

# --- Screenshot handshake ----------------------------------------------------
MAX_DIM = int(SETTINGS["screenshot"]["max_dim"])   # longest side handed to the agent
IMAGE_FORMAT = str(SETTINGS["screenshot"]["format"]).lower()   # "jpeg" or "png"
JPEG_QUALITY = int(SETTINGS["screenshot"]["jpeg_quality"])
# take_screenshot returns scale = displayed_longest_side / native_longest_side (<= 1.0).
# highlight(coord_space="image") coords are multiplied by 1/scale to reach physical pixels.

# --- Draw defaults (physical pixels) -----------------------------------------
DEFAULT_RADIUS = int(SETTINGS["draw"]["radius"])
DEFAULT_COLOR = str(SETTINGS["draw"]["color"])
DEFAULT_TTL_MS = int(SETTINGS["draw"]["ttl_ms"])
RING_PEN_WIDTH = int(SETTINGS["draw"]["ring_pen_width"])

# --- Hotkeys -----------------------------------------------------------------
HOTKEYS = dict(SETTINGS["hotkeys"])


def set_dpi_awareness() -> None:
    """Per-Monitor-v2 DPI awareness. Call BEFORE creating QApplication / capturing.

    Ensures we work in physical pixels so screenshot coords == overlay coords at any
    display scaling. See PLAN.md §3a — this is the #1 correctness requirement.
    """
    import ctypes
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 (Win10 1703+). Best fidelity.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Win 8.1+).
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # last-resort system-DPI aware
    except Exception:
        pass


# --- Windows hotkey parsing (used by the overlay's RegisterHotKey) -----------
# Virtual-key codes for a handful of common keys; letters/digits use ord(upper).
_VK = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "enter": 0x0D,
}
# MOD_ALT=1, MOD_CONTROL=2, MOD_SHIFT=4, MOD_WIN=8
_MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8, "super": 0x8}


def parse_hotkey(spec: str):
    """'ctrl+alt+h' -> (mod_mask, vk) for RegisterHotKey, or None if empty/invalid."""
    if not spec:
        return None
    mods = 0
    vk = None
    for part in spec.lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _VK:
            vk = _VK[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        else:
            return None
    if vk is None:
        return None
    return mods, vk
