## Project Structure
src/          C++ ray tracer source
include/      Header files (raytracer.h, advanced_features.h)
blender_addon/ Python Blender integration module
CMakeLists.txt Build configuration

## Build & Test Commands
```bash
# Build (from project root)
mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j8

# Run all tests
pytest tests/ -v

# Python bindings only (21 tests, ~15s)
pytest tests/test_python_bindings.py -v

# Standalone binary only (7 tests, ~5s)
pytest tests/test_standalone_renderer.py -v

# Standalone binary CLI (only supported flags):
./build/bin/raytracer --scene 1|2 --width N --height N --samples N --depth N --output file.png --help
```

## Domain Context
C++ ray tracer with physically-based rendering. Key concepts:
Vec3, Ray, Material, Hittable, BVH, MoE (not ML — Monte Carlo estimation).
Python module (`astroray`) via pybind11. Module is at `build/astroray.cpython-*.so`.

## Test Structure
- `tests/conftest.py`           — pytest path setup (adds build/, tests/, project root)
- `tests/base_helpers.py`       — shared helpers: create_renderer, setup_camera, render_image, create_cornell_box, assert_valid_image, etc.
- `tests/test_python_bindings.py` — 21 tests covering all materials, Cornell box, convergence, Disney BRDF grid, performance benchmark, quality analysis, AOV buffers
- `tests/test_standalone_renderer.py` — 7 tests for the C++ binary (correct CLI flags only)

All tests save images/charts to `test_results/` (gitignored).

## Rendering Notes
- The path tracer has a built-in sky gradient background at 0.2 scale; open scenes are never fully dark.
- Cornell box scenes are *darker* than open-sky scenes because walls occlude the background.
- Gamma correction (1/2.2) is applied inside the renderer; do not apply it again in test code.
- Standalone binary CLI only supports: `--scene`, `--width`, `--height`, `--samples`, `--depth`, `--output`, `--help`.

## Important Files
include/raytracer.h       - Core data structures, do not refactor casually
include/advanced_features.h - Transform classes and mesh support
CMakeLists.txt            - Controls both standalone and Blender build targets

## Issue Tracking with bd (beads)

Use `bd` for all project issue tracking.
Quick start and full workflow docs:
- `docs/QUICKSTART.md`
- `docs/BEADS_WORKFLOW.md`

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
