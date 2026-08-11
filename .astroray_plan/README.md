# Astroray Development Plan

**Self-contained.** Everything you (or any AI agent) needs to push Astroray
toward being the best open-source physically-based astrophysical rendering
engine is in this folder. Drop it into the repo root as `.astroray_plan/`.

## Start here

1. **[`docs/ROADMAP.md`](docs/ROADMAP.md)** — master roadmap. Agent tracks,
   five pillars, 12-week view. Read first.
2. **[`docs/STATUS.md`](docs/STATUS.md)** — current state. Updated weekly.
3. **[`docs/NEXT_STAGE_REPORT.md`](docs/NEXT_STAGE_REPORT.md)** — current
   orientation report and recommended next work.
4. Pick a package from **[`packages/`](packages/)** and go.

## Structure

```
.astroray_plan/
├── README.md                      ← this file
├── docs/                          ← design documentation
│   ├── ROADMAP.md                ← start here
│   ├── STATUS.md                 ← current state
│   ├── NEXT_STAGE_REPORT.md      ← orientation + next-stage report
│   ├── local-agent-integration.md← local model integration plan
│   ├── plugin-architecture.md    ← Pillar 1 design
│   ├── spectral-core.md          ← Pillar 2 design
│   ├── light-transport.md        ← Pillar 3 design
│   ├── astrophysics.md           ← Pillar 4 design
│   ├── production.md             ← Pillar 5 design
│   └── external-references.md    ← libraries, data, papers
├── agents/                        ← per-agent handbooks
│   └── claude-code.md            ← track A (Claude Code)
├── packages/                      ← work packages (one per PR/session)
│   ├── TEMPLATE.md
│   └── pkg01…pkg182 live here; see docs/STATUS.md for current state
├── tracker/                       ← orchestrator ledger/state
└── logs/                          ← orchestrator tick logs
```

## The agent setup (2026-08)

| Role | Agent | Notes |
|---|---|---|
| Core implementation + judgment | Claude Code (local): `architect`, `package-implementer`, `hardware-verifier`, `pr-reviewer`, `roadmap-orchestrator` | See `.claude/agents/` and `.claude/skills/` |
| Bounded grunt work | Open-weight models via the `delegate` skill (opencode) | Evidence-verified, never trusted (CLAUDE.md §5 cost routing) |
| Retired | Codex (2026-07), Copilot-cloud / Cline / Ralph multi-track scheme (2026-04 era) | Handbooks archived in `docs/archive/agents-multitrack-2026-04/` |

Dispatch flow: the roadmap-orchestrator ticks dispatch ready packages from
`packages/` to implementers, dual-gates PRs (CI + serialized local RTX
hardware verification), and auto-merges when clean.
