## Project Structure

```
Astroray/
├── apps/                    # Standalone CLI entrypoint
├── blender_addon/           # Blender RenderEngine addon + shader_blending.py
├── docs/                    # Project docs, ADRs, agent context
├── plugins/                 # Plugin implementations compiled into both targets
├── include/                 # Header-only renderer core
│   ├── raytracer.h          # Core: Vec3, Ray, Materials, BVH, Camera, Renderer
│   ├── advanced_features.h  # DisneyBRDF, textures, transforms, volumes
│   └── astroray/            # GR physics, spectral pipeline, metric
├── module/                  # pybind11 Python bindings (blender_module.cpp)
├── scripts/                 # build_blender_addon.py and utilities
├── src/                     # C++ implementation units
├── tests/                   # pytest suite (227 collected tests as of 2026-04-28)
└── CMakeLists.txt
```

## Agent Operating Model

- `AGENTS.md` is the shared repo contract for Codex and other coding agents.
- `CLAUDE.md` remains Claude Code's behavioral guide. Do not delete or replace it.
- `.github/copilot-instructions.md` constrains GitHub Copilot coding agents.
- `.astroray_plan/docs/STATUS.md` is the current planning source of truth.
- `.astroray_plan/agents/codex.md` describes Codex's role in this repo.
- Keep agent-specific notes additive. If a rule belongs to all agents, put it here.

## Build & Test Commands

```bash
# Linux / macOS
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Windows (MinGW/MSYS2 or Ninja)
cmake -B build -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build build -j

# Windows (MSVC) — open a Developer Command Prompt first
cmake -B build -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build build --config Release -j

# Run all tests (from repo root)
pytest tests/ -v --tb=short

# Focused suites
pytest tests/test_python_bindings.py -v      # ~45 tests, Python API
pytest tests/test_material_properties.py -v  # material parameter tests
pytest tests/test_standalone_renderer.py -v  # standalone binary tests
pytest tests/test_spectral_*.py -v           # spectral pipeline tests

# Standalone binary CLI (supported flags only)
./build/bin/raytracer --scene 1|2 --width N --height N --samples N --depth N --output file.png --help
```

> **Windows note:** On MSVC the module lands in `build/Release/astroray.cp*-win_amd64.pyd`.
> Copy it to `build/` before running tests, or `conftest.py` won't find it.

## Domain Context

C++ path tracer with physically-based rendering. Key concepts:
Vec3, Ray, Material, Hittable, BVH, Monte Carlo estimation (NOT ML).
Python module (`astroray`) via pybind11. Module is at `build/astroray.cpython-*.so` (Linux) or `build/astroray.cp*-win_amd64.pyd` (Windows).

Pillars 1 and 2 are complete: plugin architecture and the spectral core are
now the baseline. The active next-stage queue is Pillar 3 (light transport),
with Pillar 4 astrophysics and Pillar 5 production polish queued/ongoing.

## Test Structure

- `tests/conftest.py` — pytest path setup (adds build/, tests/, project root)
- `tests/base_helpers.py` — shared helpers: `create_renderer()`, `setup_camera()`, `render_image()`, `create_cornell_box()`, `assert_valid_image()`
- `tests/test_python_bindings.py` — main suite covering materials, Cornell box, Blender feature parity, GR black hole, AOVs, pixel filters, seed determinism
- `tests/test_material_properties.py` — material parameter validation
- `tests/test_standalone_renderer.py` — C++ binary (correct CLI flags only)
- `tests/test_spectral_*.py` and `tests/test_spectrum.py` — spectral pipeline, spectral materials/textures/env maps
- `tests/test_*_plugins.py` — registry/plugin contract coverage

All tests write images/charts to `test_results/` (gitignored).

## Rendering Notes

- `Material::eval(rec, wo, wi)` returns **brdf × NdotL** (cosine INCLUDED). Do NOT multiply by NdotL again.
- `sampleDirect()` returns the combined NEE+MIS estimate. Do NOT multiply by NdotL in the caller.
- Gamma correction (1/2.2) is applied ONCE inside `Renderer::render()`. Do not apply it in test code.
- The firefly clamp is `luminance > 20.0f` in the per-sample accumulation.
- Emissive light from direct hits is only added when `wasSpecular=true` or `bounce==0` to avoid double-counting NEE.
- `BSDFSample` has NO default initialization of `pdf` or `isDelta`. Always set every field.
- Y is up (matches Blender). GR integrator uses `double`; all other rendering math uses `float`.

## Important Files

- `include/raytracer.h` — core data structures; do not refactor casually
- `include/advanced_features.h` — textures, transforms, Disney BRDF, mesh support
- `include/astroray/` — GR subsystem (metric, integrator, accretion disk, spectral)
- `plugins/` — material, texture, shape, integrator, and pass plugins
- `blender_addon/shader_blending.py` — must be packaged with the addon (see `scripts/build_blender_addon.py`)

## Current Known Rendering/Test Gaps

- Standalone black-hole smoke can pass with a fully black output; it currently
  verifies crash-freedom more than visible GR correctness.
- GR shadow tests are xfailed after the spectral path-tracer flip until GR
  dispatch is ported into the current integrator path.
- Some older "RGB vs spectral" wording is stale because `path_tracer` is now
  spectral-first and the legacy RGB path was deleted in pkg14.

## Issue Tracking

Issues are tracked on GitHub: https://github.com/HendrikGC02/Astroray/issues

```bash
# List open issues
gh issue list

# Create an issue
gh issue create --title "feat: ..." --body "..."

# Close an issue with a comment
gh issue close <number> --comment "Implemented in PR #..."
```

## Session Completion

1. Run tests — ensure no regressions
2. Stage and commit changes
3. Update issue status (`gh issue close`)
4. Push: `git push`
