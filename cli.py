"""Halo CLI — the skill / no-MCP entry point.

Same capability as the MCP tools, but driven by plain command-line calls so it works from any
agent that can run a shell (Claude Code skills, Codex, a human). It talks to the same overlay
renderer over localhost HTTP and uses the same image->physical coordinate handshake.

Usage:
    python cli.py screenshot [--out PATH]        capture primary display (downscaled), save PNG,
                                                 print {path,width,height,scale,shown_*}
    python cli.py highlight X Y [opts]           draw a mark; X,Y are in the LAST screenshot's
                                                 image space unless --physical is given
        opts: --label TEXT --shape circle|box|arrow --radius N --color #RRGGBB --ttl MS
              --w N --h N  (box)   --dx N --dy N  (arrow)   --physical
    python cli.py clear                          remove all marks
    python cli.py ping                           ensure overlay is running; print {running}

The scale from the most recent `screenshot` is stored next to the image so `highlight` can
convert image coordinates back to physical pixels automatically (the coordinate handshake).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

common.set_dpi_awareness()

STATE_PATH = os.path.join(tempfile.gettempdir(), "halo_state.json")
_EXT = "png" if common.IMAGE_FORMAT == "png" else "jpg"
DEFAULT_SHOT = os.path.join(tempfile.gettempdir(), f"halo_screenshot.{_EXT}")


# --- overlay bridge (mirrors mcp_server) ------------------------------------

def _health(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(common.OVERLAY_BASE + "/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _post(path: str, payload: dict, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(
        common.OVERLAY_BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw or b"{}")
    except (json.JSONDecodeError, ValueError):
        return {"ok": r.status == 200}


def _launch_overlay() -> None:
    repo = os.path.dirname(os.path.abspath(__file__))
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    args = [exe, "-m", "overlay"]
    base = dict(cwd=repo, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32":
        DETACHED, NEW_GROUP, BREAKAWAY = 0x00000008, 0x00000200, 0x01000000
        try:
            subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP | BREAKAWAY, **base)
            return
        except OSError:
            subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP, **base)
            return
    subprocess.Popen(args, **base)


def _ensure_overlay(wait_s: float = 8.0) -> bool:
    if _health():
        return True
    _launch_overlay()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if _health():
            return True
        time.sleep(0.25)
    return False


# --- capture -----------------------------------------------------------------

def _primary(sct) -> dict:
    for m in sct.monitors[1:]:
        if m.get("is_primary"):
            return m
    return sct.monitors[1]


def cmd_screenshot(args) -> int:
    import mss
    from PIL import Image
    with mss.MSS() as sct:
        mon = _primary(sct)
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    native_w, native_h = img.size
    longest = max(native_w, native_h)
    scale = 1.0
    if longest > common.MAX_DIM:
        scale = common.MAX_DIM / float(longest)
        img = img.resize((max(1, round(native_w * scale)), max(1, round(native_h * scale))),
                         Image.LANCZOS)
    out = args.out or DEFAULT_SHOT
    # JPEG by default keeps the file (and the tokens when the agent Reads it) small.
    if common.IMAGE_FORMAT == "png" or out.lower().endswith(".png"):
        img.save(out, format="PNG", optimize=True)
    else:
        img.save(out, format="JPEG", quality=common.JPEG_QUALITY, optimize=True)
    state = {"scale": scale, "width": native_w, "height": native_h,
             "origin_x": int(mon.get("left", 0)), "origin_y": int(mon.get("top", 0)),
             "path": out, "shown_width": img.size[0], "shown_height": img.size[1]}
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)
    print(json.dumps({k: state[k] for k in
                      ("path", "width", "height", "scale", "shown_width", "shown_height")}))
    return 0


def _load_scale() -> float:
    try:
        with open(STATE_PATH) as f:
            return float(json.load(f).get("scale", 1.0)) or 1.0
    except (OSError, ValueError, json.JSONDecodeError):
        return 1.0


def cmd_highlight(args) -> int:
    if not _ensure_overlay():
        print(json.dumps({"ok": False, "error": "overlay not reachable"}))
        return 1
    s = 1.0 if args.physical else _load_scale()
    px, py = args.x / s, args.y / s
    payload = {"x": px, "y": py, "label": args.label or "",
               "color": args.color, "ttl_ms": args.ttl}
    shape = (args.shape or "circle").lower()
    if shape == "box":
        payload.update({"w": args.w / s, "h": args.h / s})
        path = "/box"
    elif shape == "arrow":
        payload.update({"dx": args.dx / s, "dy": args.dy / s})
        path = "/arrow"
    else:
        payload["radius"] = args.radius
        path = "/circle"
    try:
        res = _post(path, payload)
    except (urllib.error.URLError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": bool(res.get("ok", True)),
                      "physical": {"x": round(px), "y": round(py)}, "scale": s}))
    return 0


def cmd_clear(args) -> int:
    if not _health():
        print(json.dumps({"ok": True, "note": "overlay not running"}))
        return 0
    try:
        _post("/clear", {})
    except (urllib.error.URLError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


def cmd_ping(args) -> int:
    print(json.dumps({"running": _ensure_overlay()}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="halo", description="Halo on-screen guidance CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("screenshot", help="capture primary display (downscaled)")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_screenshot)

    h = sub.add_parser("highlight", help="draw a mark")
    h.add_argument("x", type=float)
    h.add_argument("y", type=float)
    h.add_argument("--label", default=None)
    h.add_argument("--shape", default="circle", choices=["circle", "box", "arrow"])
    h.add_argument("--radius", type=int, default=common.DEFAULT_RADIUS)
    h.add_argument("--color", default=common.DEFAULT_COLOR)
    h.add_argument("--ttl", type=int, default=common.DEFAULT_TTL_MS)
    h.add_argument("--w", type=float, default=0.0)
    h.add_argument("--h", type=float, default=0.0)
    h.add_argument("--dx", type=float, default=0.0)
    h.add_argument("--dy", type=float, default=0.0)
    h.add_argument("--physical", action="store_true",
                   help="treat X,Y as physical screen pixels (skip the handshake)")
    h.set_defaults(func=cmd_highlight)

    c = sub.add_parser("clear", help="remove all marks")
    c.set_defaults(func=cmd_clear)

    pg = sub.add_parser("ping", help="ensure the overlay is running")
    pg.set_defaults(func=cmd_ping)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
