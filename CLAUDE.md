# Halo

Windows on-screen guidance tool for AI agents: ask "what do I click?", get a **red circle on
your real screen** over the target. Ships as an **MCP server** → works with Claude Code AND Codex.

**Building it? Read [HANDOFF.md](HANDOFF.md), then [PLAN.md](PLAN.md).** PLAN.md is the complete,
self-contained spec (architecture, coordinate/DPI traps, MCP + HTTP contracts, milestones with
acceptance tests, dual-agent registration, and the open-source reference projects to mine).

Status: **M0–M4 built and working.** Overlay renderer + Halo MCP server done; the DPI /
downscale coordinate handshake is verified **exact at 200% scaling** on a 4K primary;
registered in both Claude Code (`claude mcp list` → halo ✓ Connected) and Codex. See PLAN.md §6
for the milestone table and §8.9–13 for the gotchas found while building. Remaining: global
hotkey (M5), demo GIF + PyInstaller build (M6). User-facing docs in [README.md](README.md).

**Two entry points, one overlay:** the MCP server (`mcp_server/`) is the cross-agent path
(Codex has no skills); `cli.py` + `skill/SKILL.md` is a Claude-Code skill path that drives the
same overlay over Bash with no MCP dependency. Both share `common.py` and the coordinate
handshake. The skill is installed at `~/.claude/skills/halo/`. Verified working end-to-end via
the CLI (accurate circles on real UI at 200% scaling).

Keep `CLAUDE.md` and `AGENTS.md` pointing at the same source (PLAN.md); don't duplicate spec here.
