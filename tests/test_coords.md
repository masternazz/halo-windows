# Coordinate / DPI fidelity checklist (Milestone 3, PLAN.md §3)

This is where these tools live or die. Verify the circle lands on the pixel you asked for,
at display scaling **≠ 100%**. This repo was verified **exact** on a 3840×2160 primary at
**200%** scaling with a 1280-px downscaled screenshot.

## The two spaces
- **physical pixels** — what mss captures and what the overlay draws in. One space, end to end.
- **image space** — the (possibly downscaled) screenshot the agent looks at. `take_screenshot`
  returns `scale = shown_longest / native_longest` (≤ 1.0). `highlight(coord_space="image")`
  multiplies coords by `1/scale` to get physical pixels. This is the mandatory handshake.

## A. Overlay-only, physical space (no agent, no downscale)
Draw three marks and screenshot the primary to check placement:
```bash
cd H:/vscode/halo
./.venv/Scripts/python.exe - <<'PY'
import urllib.request, json, mss
from PIL import Image
def post(p,o): urllib.request.urlopen(urllib.request.Request(
    "http://127.0.0.1:7333"+p, data=json.dumps(o).encode(),
    headers={"Content-Type":"application/json"}))
post("/clear", {})
post("/circle", {"x":1920,"y":1080,"radius":110,"label":"CENTER","ttl_ms":15000})
post("/circle", {"x":300,"y":300,"radius":80,"label":"TL","ttl_ms":15000})
post("/circle", {"x":3540,"y":1860,"radius":80,"label":"BR","ttl_ms":15000})
with mss.MSS() as s:
    m = next(x for x in s.monitors[1:] if x.get("is_primary"))
    g = s.grab(m); Image.frombytes("RGB", g.size, g.bgra, "raw", "BGRX").save("coords_A.png")
print("saved coords_A.png", m)
PY
```
Open `coords_A.png`: CENTER must be dead-center, TL near top-left, BR near bottom-right —
each ring centered on its requested physical pixel. (Adjust the numbers to your primary size.)

## B. Full handshake through the MCP server (downscaled screenshot)
Run the scripted client (spawns the server over stdio, exercises every tool):
```bash
./.venv/Scripts/python.exe tests/mcp_client_test.py
```
It calls `take_screenshot` (native 3840×2160 → shown 1280×720, scale 0.3333), then
`highlight` at the **image-space** center (640,360). Expect the server log:
```
highlight circle image=(640.0,360.0) -> physical=(1920,1080) scale=0.3333
```
and a red ring dead-center on the real screen. If the ring is off by a constant factor, the
DPI fix (`QT_ENABLE_HIGHDPI_SCALING=0`) or the primary-monitor selection is wrong.

## Pass criteria
- [ ] Overlay-only marks land on their exact physical pixels (Test A).
- [ ] The downscale handshake lands the ring within ~10 px of target (Test B).
- [ ] Both hold at 100% **and** a non-100% scaling (150% is the plan's bar; 200% verified here).
- [ ] `is_primary` monitor is captured/overlaid — not `mss.monitors[1]` blindly.
