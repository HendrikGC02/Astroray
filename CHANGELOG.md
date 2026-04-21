# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Plugin architecture (Pillar 1) — pkg01–04 complete

- **pkg04** — Migrated nine texture classes (Checker, Noise, Gradient, Voronoi, Brick, Musgrave, Magic, Wave, Image) and five shape classes (Sphere, Triangle, Mesh, ConstantMedium, BlackHole) to plugin files under `plugins/textures/` and `plugins/shapes/`. Shape class bodies moved to `include/astroray/shapes.h`. Python bindings extended with `sample_texture()`, `texture_registry_names()`, and `shape_registry_names()`.
- **pkg03** — Migrated all remaining material types to plugin files (Metal, Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided).
- **pkg02** — Migrated Lambertian material to plugin, established plugin pattern for Track A.
- **pkg01** — Added `Registry<T>`, `ParamDict`, and `ASTRORAY_REGISTER_*` macros; created `plugins/` directory tree and CMake OBJECT library.

### Other
- Refreshed core documentation (`README.md`, `docs/README.md`, `docs/QUICKSTART.md`, `CONTRIBUTING.md`) with current build/test/usage guidance.
- Added a visual gallery section to `README.md` using rendered test outputs.
- Removed the `notebooks/` directory from the repository.
