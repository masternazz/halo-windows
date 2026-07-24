---
name: halo
description: Show the user WHERE to click on their real Windows screen by drawing a big red circle (or box/arrow) over the right UI element. Use whenever the user asks "what do I click?", "where is the X button?", "show me on screen", "point to it", "highlight it", or otherwise wants a specific on-screen element indicated visually. Also handles "clear the circle" / "remove the highlight".
---

# Halo — on-screen click guidance

Halo draws a labeled indicator on the user's **real screen** over a UI element. It works by
capturing the primary display, letting you (the agent) look at the image and pick the pixel,
then drawing a ring there. A long-lived transparent overlay process does the drawing; it
auto-launches on first use.

**Everything runs through one CLI. Use the venv python and absolute path:**

```
PY=H:/vscode/halo/.venv/Scripts/python.exe
CLI=H:/vscode/halo/cli.py
```

## The loop: screenshot → look → highlight

1. **Capture** the screen:
   ```bash
   H:/vscode/halo/.venv/Scripts/python.exe H:/vscode/halo/cli.py screenshot
   ```
   It prints JSON like `{"path": "...halo_screenshot.png", "width":3840, "height":2160,
   "scale":0.333, "shown_width":1280, "shown_height":720}`.

2. **Look** at the image with the Read tool, using the `path` from step 1. Find the element the
   user asked about and note its pixel coordinates **in that image** (image is `shown_width` ×
   `shown_height`).

3. **Highlight** it — pass the image-space pixel; the CLI converts to physical screen pixels
   automatically (it remembers the scale from the last screenshot):
   ```bash
   H:/vscode/halo/.venv/Scripts/python.exe H:/vscode/halo/cli.py highlight <X> <Y> --label "Click here"
   ```

4. Tell the user what you circled. If they say "a bit left / lower / that's wrong", just call
   `highlight` again with adjusted coordinates (optionally `clear` first).

## Commands

| Command | Purpose |
|---|---|
| `... cli.py screenshot [--out PATH]` | Capture primary display (downscaled). Prints path + scale. |
| `... cli.py highlight X Y [opts]` | Draw a mark. X,Y are in the last screenshot's image space. |
| `... cli.py clear` | Remove all marks. |
| `... cli.py ping` | Ensure the overlay is running. |

`highlight` options: `--label TEXT`, `--shape circle|box|arrow`, `--radius N` (physical px,
default 60), `--color #RRGGBB` (default red), `--ttl MS` (default 8000, auto-fade),
`--w N --h N` (box size), `--dx N --dy N` (arrow tail offset — arrow points from X+dx,Y+dy to
X,Y), `--physical` (treat X,Y as raw screen pixels, skipping the image→physical conversion).

## Notes
- Coordinates you pass to `highlight` are in **image space by default** — the same pixels you
  see in the screenshot you Read. Don't pre-multiply by anything; the CLI handles the scale.
- Multiple highlights stack until `clear` or their `--ttl` elapses.
- v1 covers the **primary display only**.
- This is the same capability as the Halo MCP server (for Codex); the skill is the Claude Code
  path and doesn't depend on MCP being connected. Repo + full spec: `H:/vscode/halo` (PLAN.md).
