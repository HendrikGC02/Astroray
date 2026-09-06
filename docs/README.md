# Documentation Index

## Getting started

- [`../README.md`](../README.md) — project overview, gallery, quick build/test/usage
- [`QUICKSTART.md`](QUICKSTART.md) — full build instructions (Linux, Windows MSVC, Windows MinGW, Blender addon)
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — contributor workflow and expectations
- [Current project status](../.astroray_plan/docs/STATUS.md) — shipped work and remaining verification gaps
- [Rebuild and handoff record](../.astroray_plan/docs/rebuild-handoff-2026-09-06.md) — build evidence and limitations
- [Next-agent prompt](../.astroray_plan/docs/next-agent-prompt-pkg241-pkg240.md) — responsiveness/cancellation milestone and parallel CI work

## Architecture decisions

Completed designs documenting implemented subsystems:

- [`adr/CUDA_DESIGN.md`](adr/CUDA_DESIGN.md) — optional CUDA backend
- [`adr/GR_DESIGN.md`](adr/GR_DESIGN.md) — general-relativistic black hole rendering
- [`adr/HDRI_DESIGN.md`](adr/HDRI_DESIGN.md) — HDRI environment map with importance sampling

## Development

- [`DEVELOPMENT.md`](DEVELOPMENT.md) — build system details (Ninja/`build_cuda` canonical, legacy VS generator notes)
- [`../DEVELOPMENT.md`](../DEVELOPMENT.md) — one-command Blender addon dev loop (`scripts/dev_addon.ps1`)

## Blender integration

- [`blender_parity/`](blender_parity/) — Blender↔Astroray parity program docs (pkg119/pkg176/pkg178 mapping tables)

## Agent context / internals

Reference material for AI agents and new contributors:

- [`agent-context/renderer-internals.md`](agent-context/renderer-internals.md) — architecture, spectral pipeline, GPU wavefront backend, material conventions
- [`agent-context/lessons-learned.md`](agent-context/lessons-learned.md) — bugs encountered and root causes; read before touching rendering code

## Reports & showcase

- [`showcase/`](showcase/) — curated showcase renders
- [`reports/`](reports/) — historical feature-showcase reports
