# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

---

### Pillar 1 — Plugin architecture COMPLETE (pkg01–pkg06)

All materials, shapes, textures, integrators, and post-process passes are now
plugin-registered. The core render loop has zero hardcoded knowledge of any
specific material, integrator, or post-process effect. New implementations
drop in as single files.

- **pkg06** — Pass registry closes Pillar 1. `Pass` abstract base class in
  `include/astroray/pass.h`; `Framebuffer` named-buffer API in `raytracer.h`.
  Five pass plugins in `plugins/passes/`: OIDN denoiser, depth AOV, normal AOV,
  albedo AOV (and the `.gitkeep` placeholder). `Renderer` gains `addPass()` /
  `clearPasses()` and a post-render pass loop. Python bindings: `add_pass(name)`,
  `clear_passes()`, `pass_registry_names()`. Blender addon: `use_denoising`
  checkbox wires to `add_pass("oidn_denoiser")`. Inline OIDN code removed from
  `blender_module.cpp` — no hardcoded denoiser remains in the render loop.
  Test suite: 169 passed, 1 skipped.

- **pkg05** — `Integrator` abstract base class in `include/astroray/integrator.h`.
  `PathTracer` and `AmbientOcclusion` plugins in `plugins/integrators/`.
  `SampleResult` struct and `Renderer::traceFull()` for AOV preservation across
  the integrator boundary. `set_integrator(name)` Python binding and
  `integrator_registry_names()` module function. Blender addon: `integrator_type`
  `EnumProperty` backed by the live registry. Test suite: 165 passed, 1 skipped.

- **pkg04** — Migrated nine texture classes (Checker, Noise, Gradient, Voronoi,
  Brick, Musgrave, Magic, Wave, Image) and five shape classes (Sphere, Triangle,
  Mesh, ConstantMedium, BlackHole) to plugin files under `plugins/textures/` and
  `plugins/shapes/`. Shape class bodies moved to `include/astroray/shapes.h`.
  Python bindings: `sample_texture()`, `texture_registry_names()`,
  `shape_registry_names()`. Test suite: 161 passed, 1 skipped.

- **pkg03** — Migrated all remaining material types to plugin files: Metal,
  Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic,
  OrenNayar, TwoSided.

- **pkg02** — Migrated Lambertian material to a plugin file, establishing the
  pattern for all subsequent Track A plugin migrations.

- **pkg01** — Added `Registry<T>` template, `ParamDict`, and `ASTRORAY_REGISTER_*`
  macros. Created `plugins/` directory tree and the CMake OBJECT library that
  preserves static initialisers from registration macros across linker
  dead-stripping.

---

### Other

- Refreshed core documentation (`README.md`, `docs/README.md`,
  `docs/QUICKSTART.md`, `CONTRIBUTING.md`, `docs/agent-context/renderer-internals.md`)
  to reflect the plugin architecture and current API.
- Added a visual gallery section to `README.md` with the GR black hole
  showcase as the hero image.
- Removed the `notebooks/` directory from the repository.
