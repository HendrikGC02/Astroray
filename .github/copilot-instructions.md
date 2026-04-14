# Astroray — Copilot Instructions

## Project overview
Astroray is a C++17 physically-based path tracer with pybind11 Python bindings for Blender integration. The long-term goal is full Cycles feature parity so that any standard Blender scene renders correctly in Astroray.

## Architecture
- `include/raytracer.h` — Core renderer: Vec3, Ray, HitRecord, all materials, BVH, Camera, LightList, Renderer. Header-only.
- `include/advanced_features.h` — DisneyBRDF, textures, transforms, subsurface, volumes. Header-only.
- `include/astroray/` — GPU types, GR physics, spectral pipeline.
- `module/blender_module.cpp` — pybind11 bindings exposing the `astroray` Python module.
- `blender_addon/__init__.py` — Blender RenderEngine addon, scene/material/light conversion.
- `apps/main.cpp` — Standalone CLI binary.
- `tests/` — pytest suite; `base_helpers.py` has shared renderer setup utilities.

## Build commands
```bash
# Linux
cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)
# Windows (MSVC)
cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && cmake --build . --config Release
# Tests
pytest tests/ -v --tb=short
```

## Cycles reference source code
The Blender/Cycles source is at https://projects.blender.org/blender/blender. Key paths:
- `intern/cycles/kernel/closure/` — All BSDF implementations (bsdf_microfacet.h, bsdf_diffuse.h, bsdf_sheen.h, bsdf_hair.h, etc.)
- `intern/cycles/kernel/light/` — Light sampling, area lights, environment
- `intern/cycles/kernel/integrator/` — Path tracing loop, shadow rays, volume integration
- `intern/cycles/kernel/svm/` — Shader VM nodes (texture, math, color, mapping, normal_map, bump, etc.)
- `intern/cycles/scene/` — Scene, shader, mesh, object, camera, light, image, background
- `intern/cycles/blender/` — Blender export: blender_shader.cpp, blender_mesh.cpp, blender_object.cpp, blender_camera.cpp
- `source/blender/nodes/shader/nodes/` — Individual shader node definitions

When implementing a feature, always look at the Cycles source for the correct formulas and edge case handling. Cite the specific Cycles file and function in your PR description.

## Rendering conventions (CRITICAL — violating these causes bugs)
- `Material::eval(rec, wo, wi)` returns **brdf × NdotL** (cosine INCLUDED). Do NOT multiply by NdotL again.
- `sampleDirect()` returns the combined NEE+MIS estimate. Do NOT multiply by NdotL in the caller.
- Gamma correction (pow 1/2.2) is applied ONCE inside `Renderer::render()`.
- The firefly clamp is `luminance > 20.0f` in the per-sample accumulation.
- Emissive light from direct hits is only added when `wasSpecular=true` or `bounce==0` to avoid double-counting NEE.
- `BSDFSample` has NO default initialization of `pdf` or `isDelta`. Always set every field.

## Code style
- C++17, no `using namespace std;` in headers.
- Use `std::shared_ptr` and `std::make_shared`, no raw `new`/`delete`.
- Use `float` for rendering math, `double` only for GR geodesic integration.
- Use `M_PI` for pi, `std::clamp`, `std::max`, `std::min`.
- Match the existing code patterns: header-only classes, `eval()/sample()/pdf()` material interface.

## Testing
- Every new feature must include at least one test in `tests/test_python_bindings.py`.
- Tests use `assert` (not `return True/False`).
- Use helpers from `base_helpers.py`: `create_renderer()`, `setup_camera()`, `render_image()`, `save_image()`, `create_cornell_box()`, `assert_valid_image()`.
- Test images are saved to `test_results/` (gitignored).
- Standard test resolution: 200×150, SAMPLES_FAST=16.

## PR conventions
- One feature per PR. Keep PRs under 500 lines of diff when possible.
- Title format: `feat: <description>` or `fix: <description>`.
- Reference the Cycles source file/function used in the PR description.
- Include a rendered test image in the PR description if the change affects visual output.
- Run `pytest tests/ -v` and paste the result summary.
