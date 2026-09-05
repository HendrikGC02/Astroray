# Astroray Codex setup

This is the repository-scoped layer for Codex CLI, desktop, and IDE. It leaves
the global Codex model and provider settings untouched.

- `config.toml` enables up to three concurrent Codex subagents and translates
  the existing optional Blender MCP server to Codex configuration.
- `hooks/` provides session context and enforces the important source-artifact,
  stale-PYD, and diagnostic-commit guards.
- `agents/` contains focused roles without fixed model names.
- `.agents/skills/` makes the project index and shared workflow bridge
  discoverable to Codex.

## Start a Codex task

Trust this repository in Codex, then review and trust the hooks using `/hooks`.
Start a fresh task and use `/mcp` (or `codex mcp list`) to check `blender`. The
server is optional and connects to the existing `localhost:9876` bridge when
Blender is running.

Run `scripts/dev/check_blender_mcp.ps1` to distinguish a missing `uvx`, a
closed Blender bridge port, and a Codex configuration problem. It is read-only;
the normal 60-second Codex startup window accommodates a cold `uvx` launch.

The planning sequence is deliberately explicit:

1. Read `.astroray_plan/docs/STATUS.md` for the latest factual state.
2. Read `.astroray_plan/docs/NEXT_STAGE_REPORT.md` for the current handoff,
   deployment context, and next work.
3. Read the `Current sequencing` section of `.astroray_plan/docs/ROADMAP.md`
   for owner priority and pause directives.
4. Confirm a package's own `Status:` and dependencies, then check git/GitHub
   state before dispatching it.

Use `$astroray-index` to route through the SQLite index and
`$astroray-workflows` for existing project workflows. To use an inexpensive
external model, spawn `astroray-opencode-delegator`; it dynamically reads the
existing tier policy and returns evidence for Codex to review.

Use `$astroray-architect-round` for an architect-first autonomous delivery
round. It selects only an eligible package, maintains visual evidence for visual
work, and keeps valuable tangents as scoped follow-ups rather than hidden scope
creep.

Git and GitHub remain on the authenticated local `git` and `gh` path. Do not
add a cloud connector unless a task needs data or actions these existing tools
cannot provide; connector authentication is a user action.
