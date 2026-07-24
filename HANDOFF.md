# Halo — Handoff (read me first)

You are a fresh Claude Code (or Codex) instance being asked to **build Halo**. You have no
prior context. Everything you need is in this repo.

## What you're building (one sentence)
A Windows MCP server + transparent overlay so that when a user asks their AI agent "what do I
click?", a **big red circle appears on their real screen** over the right UI element — working
with both Claude Code and Codex.

## Do this in order
1. **Read [PLAN.md](PLAN.md) fully.** It is the complete spec: architecture (§1), stack (§2),
   the coordinate/DPI traps that make-or-break it (§3), exact MCP + HTTP contracts (§4–5),
   milestones with acceptance tests (§6), dual-agent registration (§7), gotchas (§8), and
   reference projects to mine (§11).
2. **Build in milestone order M0→M4** (that's the working product; M5–M6 are polish).
3. **Gate on the acceptance tests.** Especially: do not leave M1 until the §5 curl test draws
   a correctly-placed red circle **at 150% display scaling**, not just 100%.
4. **Mine the references first** (§11) — Overlay AI Assistant (PyQt5) and Clicky are open
   source; adapt their overlay/coordinate patterns instead of starting cold.
5. As you finish each milestone, tick §6's table and append any real gotchas to §8.

## Context you won't find in the repo
- **User:** Nazeem — Windows 11, VS Code, runs **both** Claude Code and Codex, Python-comfortable.
- **This is a portfolio project** for masternazz.com — README quality and a demo GIF matter (M6).
- The user's other Claude Code session is busy with unrelated job-prep work; **this session owns
  Halo end-to-end.** Don't wait on the other session.
- Workspace convention (from `H:\vscode\CLAUDE.md`): each project is its own folder; keep a
  `CLAUDE.md` and `AGENTS.md` in sync (both currently point at PLAN.md).

## First command
```bash
cd H:/vscode/halo
python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt
python -m overlay    # should open a transparent, always-on-top window (M0 check)
```
Then start Milestone 1.
