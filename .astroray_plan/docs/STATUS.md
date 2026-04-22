# Astroray Status

**Last updated:** 2026-04-22 (pkg06 complete)

This is the source-of-truth for "where are we?" Updated by the overseer
at the start of each week, and by the project owner when a significant
event happens (pillar transition, major failure, scope change).

If you are reading this to start a coding session: check **Pillar
status** for what's active, then check **This week** for what you
personally should pick up.

---

## Pillar status

| # | Name | Status | % | Next milestone | Blocked on |
|---|---|---|---|---|---|
| 1 | Plugin architecture | **Done** | 100% | — | — |
| 2 | Spectral core | **Ready to start** | 0% | Spectral types (pkg10) | ~~Pillar 1~~ |
| 3 | Light transport | Queued | 0% | — | Pillars 1, 2 |
| 4 | Astrophysics platform | Queued | 0% | Kerr | Pillars 1, 2 |
| 5 | Production polish | Ongoing | — | OpenEXR output | — |

**Pillar 1 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg01 | Registry skeleton | done |
| pkg02 | Migrate Lambertian | done |
| pkg03 | Migrate remaining materials | done |
| pkg04 | Migrate textures + shapes | done |
| pkg05 | Integrator interface | done |
| pkg06 | Pass registry | done |

---

## This week

**Week of:** 2026-04-21

### Track A (Claude Code)

- Package in flight: none (pkg06 done — Pillar 1 complete)
- Next session goal: Begin Pillar 2 — spectral types (pkg10)

### Track B (Copilot cloud)

- Assigned issues: —
- In review: —
- Queue depth: —

### Track C (Cline prototype)

- Active: no
- Current exploration: none

### Track D (Ralph loop)

- Last run: —
- Queue depth: —

---

## Recently merged (this week)

| Date | PR | Track | Pillar | Description |
|---|---|---|---|---|
| 2026-04-22 | feat/pkg06-pass-registry | A | 1 | Pass registry; OIDN + 3 AOV plugins; Framebuffer API; add_pass/clear_passes bindings; 169 tests passing. **Pillar 1 complete.** |
| 2026-04-22 | feat/pkg05-integrator-interface | A | 1 | Integrator base class, PathTracer + AO plugins, Blender UI selector; 165 tests passing |
| 2026-04-21 | feat/pkg04-migrate-textures-shapes | A | 1 | Migrate 9 textures + 5 shapes to plugin files; 161 tests passing |
| 2026-04-21 | feat/pkg03-migrate-remaining-materials | A | 1 | Migrate remaining materials to plugin files |

---

## Active packages

| Package | Track | Status | Blocker |
|---|---|---|---|
| pkg10-spectral-types | A | queued | — |

---

## Known issues

- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-04-22** — pkg06 merged: Pass registry closes Pillar 1. `Pass` abstract base + `Framebuffer` named-buffer API in `include/astroray/pass.h` / `raytracer.h`. Five plugins in `plugins/passes/` (OIDN denoiser, depth/normal/albedo AOV). `add_pass`/`clear_passes` Python bindings. `pass_registry_names()` module function. Blender `use_denoising` property wired to `add_pass("oidn_denoiser")`. Inline OIDN code removed from `blender_module.cpp`. Test suite: 169 passed, 1 skipped.
- **2026-04-22** — pkg05 merged: `Integrator` abstract base class in `include/astroray/integrator.h`; PathTracer and AmbientOcclusion plugins in `plugins/integrators/`; `SampleResult` + `Renderer::traceFull()` for AOV preservation; `set_integrator` Python binding + `integrator_registry_names()`; Blender `integrator_type` EnumProperty wired into render. Test suite: 165 passed, 1 skipped.
- **2026-04-21** — pkg04 merged: 9 texture plugin files + 5 shape plugin files. `Sphere`/`Triangle` bodies moved to `include/astroray/shapes.h`. Python bindings `sample_texture()`, `texture_registry_names()`, `shape_registry_names()` added. Test suite: 161 passed, 1 skipped.
- **2026-04-21** — pkg03 merged: all remaining material types (Metal, Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided) migrated to plugin files.
- **Earlier** — pkg01/02 merged: registry skeleton and Lambertian plugin established the pattern.
