## Project Structure

```
Astroray/
├── apps/                    # Standalone CLI entrypoint
├── blender_addon/           # Blender RenderEngine addon + shader_blending.py
├── docs/                    # Project docs, ADRs, agent context
├── include/                 # Header-only renderer core
│   ├── raytracer.h          # Core: Vec3, Ray, Materials, BVH, Camera, Renderer
│   ├── advanced_features.h  # DisneyBRDF, textures, transforms, volumes
│   └── astroray/            # GR physics, spectral pipeline, metric
├── module/                  # pybind11 Python bindings (blender_module.cpp)
├── scripts/                 # build_blender_addon.py and utilities
├── src/                     # C++ implementation units
├── tests/                   # pytest suite (66 tests)
└── CMakeLists.txt
```

## Build & Test Commands

```bash
# Linux / macOS
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Windows (MSVC) — open a Developer Command Prompt first
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DASTRORAY_ENABLE_CUDA=OFF
cmake --build . --config Release -j

# Run all tests (from repo root)
pytest tests/ -v --tb=short

# Focused suites
pytest tests/test_python_bindings.py -v      # ~45 tests, Python API
pytest tests/test_material_properties.py -v  # material parameter tests
pytest tests/test_standalone_renderer.py -v  # standalone binary tests

# Standalone binary CLI (supported flags only):
./build/bin/raytracer --scene 1|2 --width N --height N --samples N --depth N --output file.png --help
```

> **Windows note:** On MSVC the module lands in `build/Release/astroray.cp*-win_amd64.pyd`.
> Copy it to `build/` before running tests, or `conftest.py` won't find it.

## Domain Context

C++ path tracer with physically-based rendering. Key concepts:
Vec3, Ray, Material, Hittable, BVH, Monte Carlo estimation (NOT ML).
Python module (`astroray`) via pybind11. Module is at `build/astroray.cpython-*.so` (Linux) or `build/astroray.cp*-win_amd64.pyd` (Windows).

## Test Structure

- `tests/conftest.py` — pytest path setup (adds build/, tests/, project root)
- `tests/base_helpers.py` — shared helpers: `create_renderer()`, `setup_camera()`, `render_image()`, `create_cornell_box()`, `assert_valid_image()`
- `tests/test_python_bindings.py` — main suite covering all materials, Cornell box, Disney BRDF, convergence, GR black hole, pixel filters, seed determinism
- `tests/test_material_properties.py` — material parameter validation
- `tests/test_standalone_renderer.py` — C++ binary (correct CLI flags only)

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
- `blender_addon/shader_blending.py` — must be packaged with the addon (see `scripts/build_blender_addon.py`)

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
