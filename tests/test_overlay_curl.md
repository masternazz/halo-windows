# Overlay HTTP checks (Milestone 1, PLAN.md §5)

Manual smoke tests for the overlay renderer. Start it first:

```powershell
cd H:\vscode\halo
.\.venv\Scripts\pythonw.exe -m overlay      # background, no console
# (or .\.venv\Scripts\python.exe -m overlay to see stderr)
```

The HTTP listener is on `127.0.0.1:7333`. All coordinates are **physical pixels**.

> Note: Windows PowerShell's `curl` is an alias for `Invoke-WebRequest` with different args.
> Use `curl.exe` (the real one, bundled with Win10+) or the `Invoke-RestMethod` forms below.

## Health
```powershell
Invoke-RestMethod http://127.0.0.1:7333/health          # -> @{ok=True}
```

## Circle (the §5 acceptance test — center of a 1920×1080 primary)
```powershell
$b = '{"x":960,"y":540,"radius":70,"label":"HERE","ttl_ms":6000}'
Invoke-RestMethod http://127.0.0.1:7333/circle -Method Post -Body $b -ContentType application/json
```
Expect: a red labeled ring appears dead-center, clicks pass through to whatever is under it,
and it auto-clears after 6 s.

On a 4K (3840×2160) primary the center is `{"x":1920,"y":1080}`.

## Box
```powershell
$b = '{"x":300,"y":300,"w":400,"h":250,"label":"BOX","ttl_ms":8000}'
Invoke-RestMethod http://127.0.0.1:7333/box -Method Post -Body $b -ContentType application/json
```

## Arrow (points FROM x+dx,y+dy TO x,y)
```powershell
$b = '{"x":1000,"y":600,"dx":-180,"dy":-120,"label":"THIS","ttl_ms":8000}'
Invoke-RestMethod http://127.0.0.1:7333/arrow -Method Post -Body $b -ContentType application/json
```

## Clear everything
```powershell
Invoke-RestMethod http://127.0.0.1:7333/clear -Method Post -Body '{}' -ContentType application/json
```

## curl.exe equivalents (bash / cmd)
```bash
curl.exe -s http://127.0.0.1:7333/health
curl.exe -s -X POST http://127.0.0.1:7333/circle -H "Content-Type: application/json" \
     -d '{"x":960,"y":540,"radius":70,"label":"HERE","ttl_ms":6000}'
curl.exe -s -X POST http://127.0.0.1:7333/clear  -H "Content-Type: application/json" -d '{}'
```

## Pass criteria
- [ ] `/health` returns `{ok:true}`.
- [ ] `/circle` draws a red labeled ring at the requested physical pixel.
- [ ] Clicks pass through the overlay to the window beneath it (type into an editor under it).
- [ ] The ring disappears on its own after `ttl_ms`.
- [ ] `/clear` removes all marks immediately.
- [ ] Tray icon menu offers **Clear annotations** and **Quit Halo overlay**.
- [ ] Verified at **100%** and **150%** display scaling (this repo was verified exact at 200%).
