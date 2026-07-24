"""Halo MCP server (Milestone 2).

Run:  python -m mcp_server        (stdio MCP server for Claude Code / Codex)

A thin stdio bridge the agent talks to. It:
  - captures the primary display via mss (physical pixels),
  - downscales the image handed to the agent (token budget) and returns the `scale`,
  - converts agent-space coords back to physical pixels (the §3b handshake),
  - forwards draw/clear commands to the long-lived overlay over localhost HTTP,
  - auto-launches the overlay if it isn't already running.

IMPORTANT: this process speaks the MCP protocol on stdout. Never print to stdout — all
diagnostics go to stderr.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# Make the repo root importable when launched as `python -m mcp_server` from any cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common  # noqa: E402

# Screen capture must also be Per-Monitor-v2 aware so mss returns true physical pixels
# and the geometry we reason about matches the overlay's. (PLAN.md §3a)
common.set_dpi_awareness()

import mss  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from mcp.server.fastmcp import FastMCP, Image  # noqa: E402


def log(*a):
    print("[halo-mcp]", *a, file=sys.stderr, flush=True)


mcp = FastMCP("halo")

# --- handshake state ---------------------------------------------------------
# The scale used by the most recent take_screenshot, so highlight() can convert
# image-space coordinates back to physical pixels. (PLAN.md §3b)
_last = {"scale": 1.0, "width": 0, "height": 0, "origin_x": 0, "origin_y": 0}


# --- overlay bridge ----------------------------------------------------------

def _overlay_get_health(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(common.OVERLAY_BASE + "/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _overlay_post(path: str, payload: dict, timeout: float = 3.0) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        common.OVERLAY_BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw or b"{}")
    except (json.JSONDecodeError, ValueError):
        return {"ok": r.status == 200}


def _launch_overlay() -> None:
    """Start the overlay as a detached background process (no console window)."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Prefer pythonw.exe (no console) next to the current interpreter.
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    log("launching overlay:", exe, "-m overlay")
    args = [exe, "-m", "overlay"]
    base = dict(cwd=repo, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so it outlives this MCP session.
        # CREATE_BREAKAWAY_FROM_JOB escapes the terminal/VS Code Job Object, which would
        # otherwise kill the overlay when the MCP server process exits. Not every job
        # permits breakaway, so fall back without it. (learned M2)
        DETACHED, NEW_GROUP, BREAKAWAY = 0x00000008, 0x00000200, 0x01000000
        try:
            subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP | BREAKAWAY, **base)
            return
        except OSError as e:
            log("breakaway launch failed, retrying without breakaway:", e)
            subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP, **base)
            return
    subprocess.Popen(args, **base)


def _ensure_overlay(wait_s: float = 8.0) -> bool:
    """Return True if the overlay is up, launching + waiting for it if needed."""
    if _overlay_get_health():
        return True
    _launch_overlay()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if _overlay_get_health():
            return True
        time.sleep(0.25)
    return False


# --- capture -----------------------------------------------------------------

def _primary_monitor(sct: "mss.base.MSSBase") -> dict:
    """The OS primary monitor in physical pixels. mss.monitors[1] is NOT always primary
    on multi-display setups, so prefer the one flagged is_primary. (learned M1)"""
    for m in sct.monitors[1:]:
        if m.get("is_primary"):
            return m
    return sct.monitors[1]


# --- MCP tools ---------------------------------------------------------------

@mcp.tool()
def take_screenshot(window_title: str | None = None) -> list:
    """Capture the PRIMARY display and return it for you to look at.

    Returns the PNG image plus, as text, the native physical `width`/`height` and the
    `scale` used to downscale it. You do NOT need to do coordinate math yourself: when you
    later call `highlight(x, y)`, pass the pixel you see in THIS image (coord_space="image",
    the default) and the server converts it back to physical screen pixels automatically.

    window_title is accepted for forward-compat but ignored in v1 (primary display only).
    """
    with mss.MSS() as sct:
        mon = _primary_monitor(sct)
        shot = sct.grab(mon)
        img = PILImage.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    native_w, native_h = img.size
    longest = max(native_w, native_h)
    scale = 1.0
    if longest > common.MAX_DIM:
        scale = common.MAX_DIM / float(longest)
        disp = (max(1, round(native_w * scale)), max(1, round(native_h * scale)))
        # BOX (area-average) is ~4x faster than LANCZOS for downscaling with equal or better
        # legibility — no ringing on text. ~45ms saved per 4K screenshot. (measured)
        img = img.resize(disp, PILImage.BOX)

    _last.update({
        "scale": scale, "width": native_w, "height": native_h,
        "origin_x": int(mon.get("left", 0)), "origin_y": int(mon.get("top", 0)),
    })

    # Encode as JPEG by default (much smaller → far fewer tokens/bytes than PNG). Falls back
    # to PNG if configured. See config/settings.json -> screenshot.
    buf = io.BytesIO()
    if common.IMAGE_FORMAT == "png":
        img.save(buf, format="PNG", optimize=True)
        fmt = "png"
    else:
        img.save(buf, format="JPEG", quality=common.JPEG_QUALITY, optimize=True)
        fmt = "jpeg"
    data = buf.getvalue()
    log(f"screenshot native={native_w}x{native_h} scale={scale:.4f} shown={img.size} "
        f"fmt={fmt} bytes={len(data)}")

    meta = {"width": native_w, "height": native_h, "scale": round(scale, 6),
            "shown_width": img.size[0], "shown_height": img.size[1]}
    return [
        Image(data=data, format=fmt),
        json.dumps(meta, separators=(",", ":")),
    ]


@mcp.tool()
def highlight(
    x: float,
    y: float,
    label: str | None = None,
    shape: str = "circle",
    radius: int = common.DEFAULT_RADIUS,
    color: str = common.DEFAULT_COLOR,
    ttl_ms: int = common.DEFAULT_TTL_MS,
    coord_space: str = "image",
    w: float = 0.0,
    h: float = 0.0,
    dx: float = 0.0,
    dy: float = 0.0,
) -> dict:
    """Draw a big red indicator on the user's real screen over a UI element.

    x, y: the target point. By default these are in "image" space — the pixel coordinates as
    they appear in the most recent take_screenshot image. The server multiplies by 1/scale to
    reach physical screen pixels (the mandatory §3b handshake). Pass coord_space="physical" to
    give raw screen pixels instead.

    shape: "circle" (default), "box" (needs w,h), or "arrow" (needs dx,dy — the tail offset;
    the arrow points from x+dx,y+dy to x,y). radius/color/ttl_ms are physical-pixel/# values.
    Multiple highlights stack until clear() or their ttl_ms elapses.
    """
    if not _ensure_overlay():
        return {"ok": False, "error": "overlay not reachable (failed to launch)"}

    space = (coord_space or "image").lower()
    if space == "image":
        s = _last["scale"] or 1.0
        px = x / s
        py = y / s
        # Box dims and arrow tail are in the same space as the point.
        pw, ph = w / s, h / s
        pdx, pdy = dx / s, dy / s
    else:
        px, py, pw, ph, pdx, pdy = x, y, w, h, dx, dy

    payload = {
        "x": px, "y": py, "label": label or "",
        "color": color, "ttl_ms": ttl_ms,
    }
    shape = (shape or "circle").lower()
    if shape == "box":
        payload.update({"w": pw, "h": ph})
        path = "/box"
    elif shape == "arrow":
        payload.update({"dx": pdx, "dy": pdy})
        path = "/arrow"
    else:
        payload["radius"] = radius
        path = "/circle"

    try:
        res = _overlay_post(path, payload)
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": f"overlay POST failed: {e}"}
    log(f"highlight {shape} image=({x},{y}) -> physical=({px:.0f},{py:.0f}) scale={_last['scale']:.4f}")
    return {"ok": bool(res.get("ok", True)), "physical": {"x": round(px), "y": round(py)}}


@mcp.tool()
def clear() -> dict:
    """Remove ALL Halo annotations from the screen immediately."""
    if not _overlay_get_health():
        return {"ok": True, "note": "overlay not running; nothing to clear"}
    try:
        res = _overlay_post("/clear", {})
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": bool(res.get("ok", True))}


@mcp.tool()
def ping_overlay() -> dict:
    """Check whether the overlay renderer is running; launch it if not. Returns {running}."""
    running = _ensure_overlay()
    return {"running": running}


if __name__ == "__main__":
    log("starting Halo MCP server (stdio)")
    # Pre-warm the overlay in the background so it's up (~1s cold start) by the time the user
    # asks their first "what do I click?" — hides the launch latency behind the agent's own
    # thinking, making the first highlight feel instant. No-op if already running.
    threading.Thread(target=_ensure_overlay, name="halo-prewarm", daemon=True).start()
    mcp.run(transport="stdio")
