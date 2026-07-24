"""Scripted MCP client: spawn the Halo server over stdio and exercise every tool.

This is the Milestone 2 acceptance test (PLAN.md §6) and the handshake half of the
Milestone 3 check (see tests/test_coords.md, Test B).

    cd H:\\vscode\\halo
    .\\.venv\\Scripts\\python.exe tests\\mcp_client_test.py

Expects the venv at .venv and (optionally) an already-running overlay; if the overlay is
down, ping_overlay auto-launches it.
"""
import asyncio
import base64
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
SERVER = os.path.join(REPO, "mcp_server", "__main__.py")


async def main():
    # Mirror the production registration: absolute script path (cwd-independent). Launch from a
    # parent dir on purpose so a regression back to `-m mcp_server` would fail this test.
    params = StdioServerParameters(command=PY, args=[SERVER], cwd=os.path.dirname(REPO))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            assert {"take_screenshot", "highlight", "clear", "ping_overlay"} <= {
                t.name for t in tools.tools
            }

            # 1) ping — auto-launches the overlay if it's dead
            r = await session.call_tool("ping_overlay", {})
            print("ping_overlay:", r.content[-1].text)

            # 2) screenshot — returns image + metadata json
            r = await session.call_tool("take_screenshot", {})
            img_parts = [c for c in r.content if getattr(c, "type", "") == "image"]
            txt_parts = [c for c in r.content if getattr(c, "type", "") == "text"]
            meta = json.loads(txt_parts[-1].text)
            print("take_screenshot meta:", meta)
            if img_parts:
                b = base64.b64decode(img_parts[0].data)
                print("  image bytes:", len(b), "mime:", img_parts[0].mimeType)

            # 3) highlight in IMAGE space — center of the downscaled image
            cx, cy = meta["shown_width"] / 2, meta["shown_height"] / 2
            r = await session.call_tool("highlight", {
                "x": cx, "y": cy, "label": "MCP CENTER", "radius": 110, "ttl_ms": 9000,
            })
            print(f"highlight image-center ({cx:.0f},{cy:.0f}) ->", r.content[-1].text)

            # 4) a box in image space near the top-left
            r = await session.call_tool("highlight", {
                "x": meta["shown_width"] * 0.1, "y": meta["shown_height"] * 0.1,
                "shape": "box", "w": 220, "h": 120, "label": "MCP BOX", "ttl_ms": 9000,
            })
            print("highlight box ->", r.content[-1].text)

            print("RESULT: OK")


if __name__ == "__main__":
    asyncio.run(main())
