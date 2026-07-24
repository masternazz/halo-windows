"""Generate docs/demo.gif — a self-contained animation of the Halo 'what do I click?' flow.

This reproduces the overlay's actual visual language (red ring + faint glow, pulsing radius,
white-on-red label chip) over a neutral mock UI, so the README can show what Halo does without
leaking a real (private) screen. Run:  python docs/make_demo.py

No dependency on a running overlay — pure Pillow. Colors/sizes mirror common.py + overlay.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo.gif")

W, H = 900, 560
RED = (255, 45, 45)          # common.DEFAULT_COLOR #FF2D2D
BG_TOP, BG_BOT = (24, 26, 32), (15, 16, 20)
CARD = (32, 34, 41)
CARD_EDGE = (52, 55, 64)
TEXT = (223, 226, 233)
MUTED = (140, 146, 158)
ROW_HL = (42, 45, 54)


def _font(size, bold=False):
    names = (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for n in names:
        p = os.path.join(r"C:\Windows\Fonts", n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_TITLE = _font(26, bold=True)
F_ROW = _font(20)
F_ROWB = _font(20, bold=True)
F_CHIP = _font(19, bold=True)
F_Q = _font(20)


def base_scene() -> Image.Image:
    """The static mock UI: a 'Preferences' card with rows, plus a question bubble."""
    img = Image.new("RGB", (W, H), BG_BOT)
    d = ImageDraw.Draw(img)
    # vertical gradient background
    for y in range(H):
        t = y / H
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)

    # window card
    cx, cy, cw, ch = 150, 96, 600, 320
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=16, fill=CARD, outline=CARD_EDGE, width=1)
    # title bar dots
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([cx + 20 + i * 22, cy + 20, cx + 32 + i * 22, cy + 32], fill=col)
    d.text((cx + 24, cy + 46), "Preferences", font=F_TITLE, fill=TEXT)

    rows = [("Account", False), ("Appearance", False),
            ("Enable dark mode", True), ("Notifications", False)]
    ry = cy + 100
    global TARGET
    for name, hl in rows:
        rx0, rx1 = cx + 20, cx + cw - 20
        if hl:
            d.rounded_rectangle([rx0, ry - 6, rx1, ry + 40], radius=10, fill=ROW_HL)
            # a toggle on the right — this is the click target
            tgl_x, tgl_y = cx + cw - 96, ry + 4
            d.rounded_rectangle([tgl_x, tgl_y, tgl_x + 56, tgl_y + 28], radius=14,
                                fill=(60, 63, 72))
            d.ellipse([tgl_x + 3, tgl_y + 3, tgl_x + 25, tgl_y + 25], fill=(200, 204, 212))
            TARGET = (tgl_x + 28, tgl_y + 14)  # center of the toggle
            d.text((rx0 + 16, ry + 6), name, font=F_ROWB, fill=TEXT)
        else:
            d.text((rx0 + 16, ry + 6), name, font=F_ROW, fill=MUTED)
        ry += 54

    # question bubble (the 'ask') bottom-left
    q = "how do I turn on dark mode?"
    bx, by = 150, H - 96
    tw = d.textlength(q, font=F_Q)
    d.rounded_rectangle([bx, by, bx + tw + 76, by + 48], radius=24, fill=(45, 48, 58))
    d.ellipse([bx + 14, by + 12, bx + 38, by + 36], outline=RED, width=3)  # mic glyph-ish
    d.line([bx + 26, by + 30, bx + 26, by + 40], fill=RED, width=3)
    d.text((bx + 52, by + 12), q, font=F_Q, fill=TEXT)
    return img


TARGET = (W // 2, H // 2)


def draw_ring(img: Image.Image, center, radius, alpha=255, label=None):
    """Mirror the overlay: faint wide glow ring + bold ring + white-on-red label chip."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cxp, cyp = center
    # glow
    d.ellipse([cxp - radius, cyp - radius, cxp + radius, cyp + radius],
              outline=(255, 45, 45, int(0.24 * alpha)), width=11)
    # bold ring
    d.ellipse([cxp - radius, cyp - radius, cxp + radius, cyp + radius],
              outline=(255, 45, 45, alpha), width=5)
    if label:
        f = F_CHIP
        tw = d.textlength(label, font=f)
        pad_x, pad_y = 12, 7
        chw, chh = tw + 2 * pad_x, 19 + 2 * pad_y
        ax = cxp + radius * 0.7
        ay = cyp - radius - chh - 4
        ax = min(max(ax, 4), W - chw - 4)
        ay = min(max(ay, 4), H - chh - 4)
        d.rounded_rectangle([ax, ay, ax + chw, ay + chh], radius=8,
                            fill=(255, 45, 45, alpha))
        d.text((ax + pad_x, ay + pad_y - 1), label, font=f, fill=(255, 255, 255, alpha))
    img.alpha_composite(layer)


def main():
    scene = base_scene().convert("RGBA")
    frames = []
    # 1) hold the plain UI + question briefly
    for _ in range(6):
        frames.append(scene.copy())
    # 2) ring fades in, then pulses over the toggle (mirrors overlay pulse ~+/-8%)
    base_r = 46
    fade_in = 5
    total = 34
    for i in range(total):
        f = scene.copy()
        alpha = 255 if i >= fade_in else int(255 * (i + 1) / (fade_in + 1))
        pulse = 1.0 + 0.08 * math.sin(i / 6.0 * math.pi)
        draw_ring(f, TARGET, base_r * pulse, alpha=alpha, label="Click here")
        frames.append(f)

    rgb = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    durations = [700] + [70] * 5 + [70] * total  # linger on first frame
    rgb[0].save(OUT, save_all=True, append_images=rgb[1:], duration=durations,
                loop=0, optimize=True, disposal=2)
    print("wrote", OUT, os.path.getsize(OUT), "bytes,", len(frames), "frames")


if __name__ == "__main__":
    main()
