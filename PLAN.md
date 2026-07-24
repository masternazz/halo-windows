# Halo — Build Plan

> **Halo** is a Windows on-screen guidance tool for AI coding agents. You ask your agent
> *"what do I click?"*, it takes a screenshot, figures out the pixel, and a **big red circle
> appears on your real screen** over the thing to click — with a label. Works with **both
> Claude Code and Codex** because it ships as a standard **MCP server**.
>
> This file is the complete, self-contained spec. A fresh agent with zero prior context can
> build the whole thing from this doc. Read it top to bottom before writing code.

---

## 0. Why this exists / prior art

The exact UX is proven on macOS by **Clicky** (`github.com/farzaa/clicky`) and
**Screen Annotations** (`screenannotations.com`). Both are **macOS-only**. Microsoft's
"Click To Do" needs Copilot+ NPU hardware. **Nothing off-the-shelf does this on Windows +
Claude Code / Codex.** Halo fills that gap.

Clicky's core trick, which we copy: the agent embeds a coordinate in its response
(`[POINT:x,y]`); a transparent always-on-top overlay parses it and draws the indicator.
We generalize it into MCP tools so any MCP client can drive it.

**Target user:** Nazeem — Windows 11, VS Code + Claude Code + Codex, Python-comfortable.
This is also a **portfolio project** (masternazz.com), so treat code quality and the README
as first-class.

---

## 1. Architecture (two processes + the agent)

```
┌─────────────┐   MCP (stdio)   ┌──────────────────┐   HTTP 127.0.0.1:7333   ┌────────────────┐
│ Agent       │◄───────────────►│ Halo MCP server  │────────────────────────►│ Overlay        │
│ (Claude/    │  take_screenshot│ (python, stdio)  │  POST /circle /clear    │ renderer       │
│  Codex)     │  highlight/clear│                  │                         │ (PySide6, GUI, │
└─────────────┘                 └──────────────────┘                         │  always-on-top)│
                                        │  captures screen via mss           └────────────────┘
                                        └──── returns PNG + scale to agent          draws red circle
```

**Why two processes?** An MCP server is spawned per agent session over stdio and dies with it.
A GUI overlay must **persist** and own a Qt event loop. So we split:

- **Overlay renderer** — a long-lived, standalone GUI process. Transparent, click-through,
  always-on-top, covers the screen. Listens on `127.0.0.1:7333` for JSON draw commands. This
  is the only process that touches the screen visually.
- **Halo MCP server** — a thin stdio bridge the agent talks to. Captures screenshots (via
  `mss`) and forwards highlight commands to the overlay over localhost HTTP. If the overlay
  isn't running, it auto-launches it.

Decoupling via localhost HTTP means the transport is language-agnostic and trivially testable
with `curl` — you can build and verify the overlay with zero agent/MCP involved.

---

## 2. Tech stack (decided — don't re-litigate without reason)

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | User knows it; fast to build; good libs |
| Overlay GUI | **PySide6** (LGPL) | First-class transparent + click-through + topmost on Windows |
| Screen capture | **mss** + **Pillow** | Fast, returns **physical** pixels, multi-monitor aware |
| MCP server | **`mcp` Python SDK** (`from mcp.server.fastmcp import FastMCP`) | Official, both clients support stdio |
| MCP ↔ overlay IPC | **localhost HTTP + JSON** (`127.0.0.1:7333`) | Simple, curl-testable, decoupled |
| Overlay HTTP listener | stdlib `http.server` on a daemon thread | No extra dep; push commands into Qt via a signal |
| Packaging (later) | **PyInstaller** one-file for the overlay | So it can run without a dev env |

Single shared `halo/common.py` holds constants (port, default radius/color/ttl, DPI helpers).

---

## 3. THE hard part: coordinate fidelity (read this twice)

Everything else is plumbing. **This is where these tools live or die.** Three traps:

### 3a. DPI scaling
Windows scales UI (100% / 125% / 150%…). "Logical" pixels ≠ "physical" pixels. If the
screenshot is in physical px but the overlay draws in logical px, the circle lands in the wrong
place at any scaling ≠ 100%.
- **Fix:** make BOTH processes **Per-Monitor-v2 DPI aware**, and work exclusively in
  **physical pixels**. `mss` already returns physical px. For the overlay, set DPI awareness
  before the QApplication is created:
  ```python
  import ctypes
  ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
  ```
  and position/size the window using physical geometry. **Acceptance: test at 100% AND 150%.**

### 3b. Screenshot downscaling (token budget)
Full-res PNGs are huge and burn the agent's tokens. We downscale the image we hand the agent
(e.g. longest side → 1280). But then the coordinates the agent reads are in **downscaled image
space**, not physical space.
- **Fix — the coordinate handshake (mandatory):** `take_screenshot` returns the image AND the
  `scale` used and the native `width`/`height`. `highlight(x, y)` accepts coords in the SAME
  space the agent saw (`coord_space="image"` default) and the **server multiplies by 1/scale**
  to get physical px before sending to the overlay. This removes an entire class of "circle is
  off by a bit" bugs. Document the contract in the tool docstrings so the agent uses it right.

### 3c. Multi-monitor
- **v1: primary display only.** Capture and overlay the primary monitor. Document as a known
  limitation. v2 adds monitor selection (mss enumerates monitors; overlay needs one window per
  monitor or a virtual-desktop-spanning window).

### 3d. Accuracy aid (optional, high value)
Vision models estimate pixels imperfectly. Two cheap boosters, add in Milestone 3 if needed:
- Draw a faint labeled coordinate grid onto the screenshot before sending (computer-use trick).
- Support a `highlight` follow-up: agent circles, user says "a bit left", agent nudges.

---

## 4. MCP tool contracts (implement exactly these)

All tools live in the Halo MCP server. Keep names/prefixes stable — both agents and the README
depend on them.

```
take_screenshot(window_title?: str) -> { image: <png>, width: int, height: int, scale: float }
    Capture the primary display (or a window by partial title match, v2).
    Downscale so longest side <= MAX_DIM (default 1280); `scale` = displayed/native (<=1.0).
    width/height are NATIVE physical dims. Returns the image content for the agent to view.

highlight(x: float, y: float, label?: str, shape?: "circle"|"box"|"arrow",
          radius?: int, color?: str, ttl_ms?: int, coord_space?: "image"|"physical") -> {ok}
    Draw an indicator. coord_space defaults to "image" (space of the last take_screenshot);
    server converts image->physical via the stored scale. "physical" bypasses conversion.
    Defaults: shape=circle, radius=60 (physical px), color="#FF2D2D", ttl_ms=8000.
    Multiple calls stack until clear() or ttl expiry.

clear() -> {ok}
    Remove all on-screen annotations immediately.

ping_overlay() -> {running: bool}     # health/util; auto-launch overlay if dead
```

Overlay HTTP API (what the MCP server POSTs to — also your curl test surface):
```
POST /circle   {x, y, radius, label, color, ttl_ms}      -> 200 {ok:true}
POST /box      {x, y, w, h, label, color, ttl_ms}        -> 200
POST /arrow    {x, y, dx, dy, label, color, ttl_ms}      -> 200   (v2)
POST /clear    {}                                         -> 200
GET  /health                                             -> 200 {ok:true}
```
All coordinates crossing this boundary are **physical pixels**. The MCP server does the
image→physical conversion; the overlay is dumb and just draws where told.

---

## 5. Overlay renderer spec (Milestone 1 — the foundation)

A `QWidget` window with these flags/attributes:
```python
flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
         | Qt.WindowTransparentForInput)          # click-through
setAttribute(Qt.WA_TranslucentBackground)
setAttribute(Qt.WA_ShowWithoutActivating)
```
Plus, on Windows, harden click-through with the extended styles (some setups need this even
with `WindowTransparentForInput`):
```python
WS_EX_TRANSPARENT = 0x20; WS_EX_LAYERED = 0x80000; WS_EX_TOOLWINDOW = 0x80
# GetWindowLongW/SetWindowLongW GWL_EXSTYLE |= those
```
- Geometry = full primary-monitor physical bounds (top-left 0,0 in single-monitor).
- `paintEvent` draws the current list of annotations with `QPainter` (antialiased): a bold
  ring (pen width ~5, `color`), optional pulsing radius, and the `label` in a small rounded
  chip beside it.
- A daemon-thread `http.server` receives POSTs, parses JSON, and hands the command to the Qt
  thread via a `Signal` (never touch widgets from the HTTP thread). Each annotation has an
  expiry; a `QTimer` (~30fps) removes expired ones and triggers repaint.
- Runs standalone: `python -m overlay`. A tray icon (QSystemTrayIcon) with "Clear" and "Quit".

**Definition of done (M1):** with the overlay running,
`curl -X POST 127.0.0.1:7333/circle -d '{"x":960,"y":540,"radius":70,"label":"HERE","ttl_ms":6000}'`
draws a red labeled ring dead-center on a 1920×1080 primary display, clicks pass through to
whatever's under it, and it auto-clears after 6s. Verified at 100% and 150% scaling.

---

## 6. Milestones (build order — each independently testable)

| # | Milestone | Definition of done | Status |
|---|---|---|---|
| **M0** | Repo skeleton, venv, deps, `common.py` constants | `pip install -r requirements.txt` clean; `python -m overlay` opens a transparent topmost window | ✅ |
| **M1** | **Overlay renderer** (circle + clear + health, HTTP listener, click-through, TTL, tray) | The curl test in §5 passes at 100% & 150% | ✅ (verified at **200%**) |
| **M2** | **Halo MCP server** (`take_screenshot`, `highlight`, `clear`, `ping_overlay`; mss capture; forwards to overlay; auto-launch overlay if dead) | Run server standalone with the MCP inspector / a scripted client: screenshot returns PNG+scale; highlight draws via overlay | ✅ |
| **M3** | **Coordinate fidelity** (DPI per-monitor v2 both sides; image→physical scale handshake; verify accuracy) | Circle lands within ~10px of target at 100% & 150%, from a downscaled screenshot | ✅ (exact at **200%**, 3840×2160→1280 downscale) |
| **M4** | **Dual-agent integration** (register in Claude Code + Codex; end-to-end "what do I click") | From BOTH Claude Code and Codex: ask → screenshot → correct red circle on screen | ✅ registered (`claude mcp list` → halo ✓ Connected; Codex block added). End-to-end needs a fresh agent session to load the tools. |
| **M5** | **UX polish** (box + arrow shapes, multi-highlight, pulse animation, optional global hotkey to trigger a guidance turn, better labels) | Shapes/animation work; hotkey optional | ✅ box/arrow/circle + pulse + multi-highlight; on-screen label clamping; **global hotkeys** (clear/toggle) via RegisterHotKey; JPEG token optimization; all settings in `config/settings.json` |
| **M6** | **Portfolio** (README + demo GIF, masternazz.com writeup, PyInstaller build of overlay) | `README.md` with GIF; one-file overlay exe runs without a dev env | ✅ README + `docs/demo.gif` (self-contained, reproducible via `docs/make_demo.py`); `build.py` → `dist/halo-overlay.exe` (windowed one-file), verified serving + drawing with no Python env |

Ship M1–M4 first; that's the working product. M5/M6 are polish + resume value.

---

## 7. Dual-agent registration (M4 — the "works with both" part)

Halo is one stdio MCP server; register the same server in each client.

**Claude Code:**
```bash
claude mcp add -s user -t stdio halo -- python -m mcp_server
# (run from the repo root, or use an absolute path to the module / a venv python)
```
or in `~/.claude.json` under `mcpServers`:
```json
"halo": { "type": "stdio", "command": "C:/path/to/venv/Scripts/python.exe", "args": ["-m", "mcp_server"], "cwd": "H:/vscode/halo" }
```

**Codex** — `~/.codex/config.toml`:
```toml
[mcp_servers.halo]
command = "C:/path/to/venv/Scripts/python.exe"
args = ["-m", "mcp_server"]
cwd = "H:/vscode/halo"
```

After registering, restart/reload the client so it loads the tools (Claude Code: reload the
VS Code window or start a new chat; Codex: new session). Templates live in `config/`.

---

## 8. Known gotchas (don't rediscover these the hard way)

1. **DPI** — the #1 source of "circle is in the wrong spot". Per-Monitor-v2 on both processes,
   physical pixels everywhere. Test at 150%.
2. **Never touch Qt widgets from the HTTP thread.** Marshal via a `Signal` to the GUI thread.
3. **Overlay must exist before highlight works.** MCP server checks `/health`; if dead,
   `subprocess.Popen` the overlay (detached) and wait for health before proceeding.
4. **Exclusive-fullscreen apps/games** can draw over the topmost overlay. Document: use
   borderless-windowed. Fine for our use case (installers, web UIs, dialogs).
5. **Codex vs Claude config formats differ** (TOML `[mcp_servers.x]` vs JSON `mcpServers`).
   Ship both templates.
6. **Downscale handshake** — if you skip the `scale` round-trip, every highlight from a resized
   screenshot is off. It's not optional.
7. **Antivirus / SmartScreen** may flag a PyInstaller one-file exe (M6). Sign it or document.
8. **Multi-monitor is v1-out-of-scope.** Say so; don't half-build it.

### Gotchas found while building (append-only log)
9. **Qt6 auto-scales by DPI → it draws in *logical* pixels, not physical.** This is the real
   form the §3a trap takes with PySide6. `SetProcessDpiAwareness` alone is NOT enough: Qt still
   applies its own high-DPI scaling, so on a 200%-scaled 4K display a circle requested at
   physical (1920,1080) rendered at the screen edge (logical 1920,1080). **Fix:** set
   `QT_ENABLE_HIGHDPI_SCALING=0` (and `QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough`) in the
   environment *before* `QApplication` is created, so 1 Qt unit == 1 physical pixel and Qt's
   space matches mss. Done in `overlay/__main__.py`. Verified exact at 200% scaling.
10. **`mss.monitors[1]` is NOT always the primary display.** On a multi-monitor setup it can be
    a secondary (this dev box: `monitors[1]` was a 1920×1080 at left=-1920, while the real
    primary was a 3840×2160 4K at (0,0)). Always pick the monitor with `is_primary: True`;
    `monitors[0]` is the union of all displays. Both `overlay` and `mcp_server` do this now.
11. **DPI awareness API:** prefer `user32.SetProcessDpiAwarenessContext(-4)` (Per-Monitor-**v2**,
    Win10 1703+) over `shcore.SetProcessDpiAwareness(2)` (v1). `common.set_dpi_awareness()`
    tries v2 first, then falls back. Must run before QApplication *and* before mss capture.
12. **Overlay lifetime on Windows.** The overlay is auto-launched detached
    (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`) and, in
    isolation, survives its launcher exiting. But the MCP **stdio client** tears down its whole
    child process tree at session end, which takes the overlay with it. That's fine — the
    overlay only needs to live for the duration of a session, and it persists across every
    highlight call within one. `ping_overlay`/`highlight` re-launch it next session if needed.
    For a truly always-on overlay, start it once manually (`python -m overlay`) or as a
    Windows startup task; the server detects the running instance via `/health` and reuses it.
13. **FastMCP `take_screenshot` return shape:** return a `list` of `[Image(data=png,
    format="png"), json_metadata_str]`. FastMCP maps the `Image` to an ImageContent block and
    the string to a TextContent block, so the agent gets both the picture and width/height/scale.
14. **`-m mcp_server` needs cwd = repo; the VS Code extension launches from the WORKSPACE ROOT.**
    This was the real "MCP server isn't working" cause: registered as `args:["-m","mcp_server"]`,
    it connected from a shell `cd`'d into `halo/` but **crashed instantly** under the extension
    (cwd = `H:/vscode`) with `No module named mcp_server`, so the tools never loaded — while
    `claude mcp list` still showed ✓ Connected because the CLI ran from the repo. **Fix:** point
    `args` at the **absolute** `mcp_server/__main__.py` path (cwd-independent; `__main__.py`
    inserts the repo root on `sys.path` itself for `import common`). Set `cwd` too, belt-and-
    suspenders. Also note `claude mcp add-json` dropped the `cwd` field on this machine —
    verify the persisted entry with `claude mcp get halo`.
15. **Screenshot token budget:** default to **JPEG** (`quality≈72`) at `max_dim≈1152`, not PNG.
    On a 4K capture this cut the payload ~4.4× (323 KB PNG → 73 KB JPEG) and trims image tokens;
    both are tunable in `config/settings.json`. Raise them only if the model can't resolve small
    UI. Metadata JSON is emitted compact (`separators=(",",":")`).
16. **Labels must clamp on-screen.** A label chip anchored past a screen edge gets clipped;
    clamp the chip rect into the window bounds in `paintEvent` so edge/corner marks stay legible.
17. **Global hotkeys with no extra deps:** `user32.RegisterHotKey` + a `QAbstractNativeEventFilter`
    that watches `WM_HOTKEY (0x0312)` — no `keyboard`/`pynput` dependency. Add `MOD_NOREPEAT`
    (0x4000). Keep a Python reference to the filter (stash on the app) or it gets GC'd. Configured
    in `config/settings.json` → `hotkeys` (default `ctrl+alt+h`=clear, `ctrl+alt+j`=toggle).
18. **PyInstaller `--windowed` sets `sys.stderr`/`sys.stdout` to `None`.** A raw
    `sys.stderr.write(...)` then throws `AttributeError` and silently kills startup (the process
    lingers but never binds the port — maddening with no console). Route all diagnostics through
    a guarded `_elog()` that no-ops when stderr is None and also appends to
    `%TEMP%/halo-overlay.log` so windowed builds stay debuggable. Also: a one-file exe's **first**
    launch unpacks ~48 MB to temp (+ AV scan), so allow ~5–20 s before health on the very first run.
19. **Frozen settings path:** in a PyInstaller build `common.__file__` points inside `_MEIPASS`.
    `load_settings()` checks `settings.json`/`config/settings.json` **next to the .exe** first
    (so the packaged build is configurable without rebuilding), then the bundled `_MEIPASS` copy,
    then the dev repo path. Bundle the default via `--add-data "config/settings.json;config"`.
20. **Demo GIF without leaking a real screen:** the honest real-overlay captures contained private
    content (Discord DMs), unfit for a public README. `docs/make_demo.py` renders a neutral mock UI
    and reproduces the overlay's exact ring/glow/pulse/label styling in Pillow — reproducible, safe,
    and it tells the "ask → circle appears" story in one loop.

---

## 9. Repo layout

```
halo/
  PLAN.md              <- this file (source of truth)
  HANDOFF.md           <- read-me-first for the fresh agent building it
  README.md            <- user-facing (write in M6)
  CLAUDE.md / AGENTS.md<- point both agents at PLAN.md
  requirements.txt
  common.py            <- shared constants + DPI helpers
  cli.py               <- no-MCP entry point (screenshot/highlight/clear/ping) for the skill
  overlay/
    __main__.py        <- python -m overlay  (renderer + HTTP listener + tray)
  mcp_server/
    __main__.py        <- python -m mcp_server (FastMCP; tools; mss capture; overlay bridge)
  skill/
    SKILL.md           <- Claude Code skill (drives cli.py; install to ~/.claude/skills/halo/)
  config/
    claude.mcp.json    <- registration template
    codex.config.toml  <- registration template
  tests/
    test_overlay_curl.md   <- manual curl checks (§5)
    test_coords.md         <- DPI/scale verification checklist (§3)
  docs/
    demo.gif           <- M6
```

---

## 10. First actions for the building agent

1. Read this whole file. Then `HANDOFF.md`.
2. M0: create venv, `requirements.txt` (`PySide6 mss pillow mcp`), `common.py`.
3. M1: build `overlay/__main__.py`; verify with the curl test in §5 **at 150% scaling** before
   moving on. Do not proceed until the circle lands correctly.
4. M2→M4 in order. Keep each milestone's acceptance test green.
5. Update this PLAN.md's milestone table with ✅ as you complete each, and log real gotchas you
   hit into §8 so the next person benefits.

**Guiding principle:** the overlay + coordinate fidelity (M1+M3) are 80% of the value and 80%
of the risk. Spend your care there. The MCP glue is easy.

---

## 11. Reference implementations to mine (don't build blind)

We are NOT starting from scratch — study these first and port their proven ideas.

| Project | License / source | What to take from it | Caveat |
|---|---|---|---|
| **Clicky** — `github.com/farzaa/clicky` | Open source (Swift) | The core pattern: agent emits `[POINT:x,y]` coords, a transparent always-on-top overlay parses + points. Read how it does the coordinate handshake, multi-monitor mapping, and the topmost transparent panel. | macOS/Swift — port the **ideas**, not the code. `ScreenCaptureKit` has no Windows analog (we use `mss`). |
| **Overlay AI Assistant** — `devpost.com/software/overlay-ai-assistant` (find its GitHub) | Open source (**PyQt5**) | **Most directly reusable.** Same GUI toolkit family as our PySide6. Its transparent, always-on-top, click-through overlay window code is close to copy-adaptable. Also see how it wires screenshot → multimodal model → highlight. | Uses Gemini, standalone (not MCP). We keep the overlay, swap the brain for MCP tools. |
| **Screen Annotations** — `screenannotations.com` | Closed (Mac App Store) | UX + MCP tool-surface inspiration only (shape library, board/scene model). | No source. Study behavior, don't copy. |
| **PointerFocus / presentation highlighters** | Commercial | Visual design of the ring/pulse (what reads well on screen). | Cosmetic reference only. |

**Recommended approach:** start M1 by adapting Overlay AI Assistant's Qt transparent-overlay
window (closest match), and adopt Clicky's `[POINT:x,y]`-style coordinate contract (which we've
already generalized into the `highlight` tool in §4). This can cut M1 substantially.
Before copying any code, check each project's license and keep attribution where required.
