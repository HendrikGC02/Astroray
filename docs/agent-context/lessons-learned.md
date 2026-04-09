# Lessons Learned
<!-- The agent updates this file when it discovers a pitfall, gotcha, or non-obvious solution. -->
<!-- Format: date | file/area | what went wrong | what fixed it -->

---

2026-03-15 | CMakeLists.txt / pybind11 | Module name conflict | Using `raytracer_py` as the module name caused confusion because it didn't match the expected Python import name. The fix was to use `astroray` as the PYBIND11_MODULE name and target name, making `import astroray` work cleanly without any renaming.

---

2026-03-15 | CMakeLists.txt / pybind11 | Python path setup | The Python module needs explicit path insertion (`sys.path.insert(0, 'build/Release')`) before importing. This is standard practice for local development builds that aren't installed via pip.

---

2026-03-15 | CMakeLists.txt / pybind11 | Target naming | Using `target_name("astroray")` in `pybind11_add_module()` creates both the compiled module and sets the Python import name. The target name should match the desired Python import name for consistency.

---

2026-03-15 | build system | CMake cache issues | After renaming targets, old build artifacts can cause issues. Always do a clean build (`rm -rf build/*` or delete the build folder) when changing target names significantly.

---

2026-03-15 | Python API | Feature detection | The module exposes `__version__` and `__features__` attributes which are useful for runtime feature detection and debugging. Always include these in the module for easier troubleshooting.

---

2026-03-15 | CMakeLists.txt | Build configuration mismatch | When building for Blender, the Python include paths must point to Blender's Python installation, not the system Python. Using `pybind11_add_module()` automatically handles the Python include paths from the pybind11 package, but the module must be built with the correct Python version that matches Blender's embedded Python.

---

2026-03-15 | CMakeLists.txt | Release vs Debug builds | The module name and import path can differ between Debug and Release builds. When switching between build configurations, ensure the build folder is cleaned or use separate build directories to avoid conflicts. The `bin/Release/` path is used for the Release build, but Debug builds may output to different locations.

---

2026-03-15 | Module organization | Consistent naming across files | When refactoring module names, update ALL references: CMakeLists.txt (target_name), module source file (PYBIND11_MODULE), and any Python imports (blender_addon/__init__.py, README.md). Missing even one reference will cause build failures or import errors.

---

2026-03-15 | Build system | Build artifacts in repository | Build artifacts (VCXProj, CMakeCache.txt, .tlog files, etc.) should NEVER be committed to the repository. Add them to .gitignore to keep the repository clean and avoid merge conflicts.

---

2026-03-15 | pybind11 | Module initialization order | The `PYBIND11_MODULE` function requires the module name to be a compile-time constant. Using macros or variables for the module name will cause compilation errors. Always use a literal string for the module name.

---



2026-03-15 | pybind11 | Array return shape for 3D data | Returning multi-dimensional numpy arrays from C++ requires explicit shape specification using `py::ssize_t shape[3]` for each dimension. Simply returning `py::array_t<float>` with a flat size calculation loses the dimensional structure. The fix is to declare the shape array and pass it to `py::array_t<float>(shape)`, then copy data using index arithmetic (e.g., `ptr[i*3]`, `ptr[i*3+1]`, `ptr[i*3+2]`) for the color channels. This pattern is essential for image buffers where (height, width, 3) layout is expected.


- [testing] Tests that use `return condition` instead of `assert condition`
  always pass silently. Always verify test files use assert statements.
  Run `grep -n "return True\|return False\|return result" tests/` to check.
- [rendering] PNG output requires gamma correction (pow(x, 1/2.2)) applied
  once at final pixel write. Without it, bright areas blow out to white.
- [rendering] Blocky brightness artifacts usually indicate shared/correlated
  RNG state between image regions — each pixel needs independent seeding.

---

2026-03-15 | tests/base_helpers.py | Wrong create_material call | create_cornell_box() was calling `astroray.create_material()` (module-level) instead of `renderer.create_material()` (instance method). The module has no top-level create_material function. Always call material creation on the renderer instance.

---

2026-03-15 | tests/conftest.py | tests/ directory not in sys.path | base_helpers.py (inside tests/) was not importable from test files because conftest.py only added the build dir and project root to sys.path, not the tests directory itself. Fix: add `TESTS_DIR = os.path.dirname(os.path.abspath(__file__))` and `sys.path.insert(0, TESTS_DIR)` in conftest.py.

---

2026-03-15 | tests/test_standalone_renderer.py | CLI flags not supported | The standalone binary (apps/main.cpp) only supports: --scene 1|2, --width, --height, --samples, --depth, --output, --help. It does NOT have --version, --test, --sphere, --triangle, --material, --look_from, --look_at, --vup, --vfov, --aperture, --focus_dist. Old tests used these unsupported flags and "passed" because the binary ignores unknown flags and exits 0, while producing wrong output.

---

2026-03-15 | tests/test_standalone_renderer.py | Convergence via MSE between two renders | Comparing MSE between two independent renders at the same SPP count is unreliable — a bright Cornell box light can create rare firefly pixels that make 64spp renders differ more than 4spp renders by chance. Use compare-to-reference style: render a high-SPP reference once, then assert that 64spp is closer to reference than 4spp.

---

2026-03-15 | rendering | Background sky is always present | The path tracer has a built-in sky gradient background (line 741 in raytracer.h): `Vec3(1)*(1-t) + Vec3(0.5,0.7,1)*t) * 0.2f`. After gamma correction, a sphere-in-open-sky scene produces mean brightness ~0.4. Do NOT write tests asserting "no light = dark image" — there is always ambient sky light. The Cornell box is *darker* than an open-sky scene because its walls occlude the background.

---

2026-03-15 | matplotlib | Non-interactive backend required in tests | Calling `matplotlib.use('Agg')` must happen before any other matplotlib imports (including pyplot) when running under pytest. Without it, matplotlib tries to connect to a display, which fails in headless environments. Set this at the top of base_helpers.py and any test file that uses matplotlib.

---

2026-03-15 | rendering | max_depth mismatch causes catastrophic fireflies | The standalone app defaulted to depth=50 while the Python test helper (base_helpers.render_image) uses max_depth=8. With a glass sphere in the scene, depth=50 creates runaway near-TIR refraction paths: throughput gets clamped to 10× per bounce, Russian Roulette survival stays at 95% for bright paths, so 50-bounce caustic paths dominate every pixel at low sample counts. Fix: set standalone default to depth=8 and add a per-sample luminance clamp (e.g. 20.0) in the render loop before accumulation. Always keep max_depth consistent between standalone and Python bindings.

---

2026-03-15 | rendering | Metal::eval() reflection sign bug | Metal::eval() used `wo - 2*(wo·n)*n` which equals `-wi` (negative of correct reflection). Deviation from sampled wi was always ~2, far above 0.1 threshold, so eval() always returned Vec3(0). The correct formula is `2*(wo·n)*n - wo`. sample() was already correct; only eval() was wrong.

---

2026-03-15 | rendering | Near-zero roughness GGX collapses numerically | For roughness < ~0.08, the +0.001f epsilon guard in the GGX D formula completely dominates the alpha term, making D/pdf ≈ 0. This renders near-mirror Metal and Disney BRDF materials completely black even though sample() generates the correct specular direction. Fix for Metal: raise the delta-path threshold from 0.01 to 0.08 so roughness < 0.08 uses the clean perfect-mirror path. Fix for DisneyBRDF: clamp the specular alpha to min 0.0064 (equiv. roughness 0.08) in both eval() and sample() so the GGX lobe remains numerically stable.

---

2026-03-15 | rendering | NEE double-cosine overexposes direct lighting | All material eval() functions return brdf * NdotL (cosine already included). The NEE branch of sampleDirect() was additionally multiplying by abs(wi·normal), causing a double-cosine: contribution scaled as NdotL² instead of NdotL. With a bright light (intensity 15) this caused systematic 2× overexposure, worst on specular surfaces. Fix: remove the redundant `* std::abs(wi.dot(rec.normal))` from the NEE accumulation line. The BSDF-sampling branch correctly omits this factor and serves as a reference for the expected convention.

---

2026-03-15 | rendering | Upside-down images in Python module | The render loop stored row y=0 at the bottom of the scene (v = y/(height-1) = 0 → lowerLeft). The Python module returned pixels in forward order so NumPy/matplotlib displayed the scene flipped. Fix: change the render loop to `v = 1 - y/(height-1)` so row 0 = top of scene. Also update standalone writePPM/writePNG to iterate y forward (0 to height-1) instead of the previous reverse-order compensating flip.

---

2026-03-15 | rendering | Metal::eval() dead backface guard causes overexposure | Metal::eval() clamped NdotL and NdotV to 0.001f BEFORE the `if (NdotL <= 0 || NdotV <= 0) return Vec3(0)` check, making the check permanently dead. Below-surface wi directions returned nonzero BRDF values (e.g. from sampleDirect's light sampling). This caused systematic overexposure with Metal materials, worst in standalone (mean=1.0). Fix: compute raw dot products first, guard against <=0, then use the raw (positive) values in formulas — no clamping needed for NdotL/NdotV since they're guaranteed positive.

---

2026-03-15 | rendering | Metal GGX pdf epsilon inconsistency | Metal::sample() computed pdf as `a2 * NdotH / (π * denom² * 4 * HdotV + 0.001)` while eval() computed D as `a2 / (π * denom² + 0.001)`. The two epsilon placements are inconsistent: the ratio f/pdf does not simplify cleanly to `F*G*HdotV/(NdotV*NdotH)`. Fix: compute D in sample() and pdf() using the same formula as eval(), then derive pdf = D * NdotH / (4 * HdotV). This ensures f/pdf is exactly the canonical GGX weight.

---

2026-03-15 | rendering | Metal::sample() uninitialized s.pdf | When the GGX reflected direction was below the surface, Metal::sample() set s.f=Vec3(0) but left s.pdf uninitialized (garbage float). If garbage > 0, pathTrace continued with 0 throughput (harmless), but relying on UB is dangerous and masked the above bugs. Fix: explicitly initialize s.f=Vec3(0) and s.pdf=0.0f before the direction check so a below-surface sample always returns a valid zero-contribution sample that terminates via the bs.pdf<=0 guard.

---

2026-03-15 | rendering | Progress callback called from inside OpenMP parallel region | renderer.render() calls the progress callback from inside `#pragma omp parallel for`. The original standalone code passed a lambda that called `std::cout << std::flush`, which is not thread-safe and produces garbled output and potential data races. The Python binding defaults to nullptr which avoids the issue entirely. Fix: pass nullptr for the progress callback in apps/main.cpp. Any non-null callback must be thread-safe (e.g. use an atomic counter updated outside the parallel region).

---

2026-03-15 | debugging | Isolate overexposure by rendering each material in isolation | When a fully-assembled scene is overexposed but individual materials work, test scenes with exactly one sphere type added at a time (walls+light only → add glass → add Disney → add Metal). This immediately identifies which material is responsible without source analysis. In this project, "Metal only → mean=1.0" while all others gave ~0.4 pinpointed Metal as the culprit in under one test run.

---

2026-04-09 | include/astroray/gr_integrator.h | MinGW GCC corrupts large structs passed by value | `integrateGeodesic()` originally took its initial state as `GeodesicState s` (64 bytes, 8 doubles). Under MinGW GCC 15.2 on Windows x64 the receiving function saw garbage in several fields — the call would crash before the first line of the function body executed. Standard MSVC works fine; this is a MinGW ABI quirk for structs > ~32 bytes. Fix: take the parameter as `const GeodesicState& s_init` and copy locally (`GeodesicState s = s_init;`). Apply this rule to ANY hot-path function on this toolchain that takes a struct larger than two doubles by value.

---

2026-04-09 | tests/base_helpers.py + build/ | Stale .pyd files shadow fresh build via sys.path order | `tests/base_helpers.py` does `sys.path.insert(0, build_dir)` and then `sys.path.insert(0, project_root)`, so the project root ends up FIRST in `sys.path`. Any `astroray.cp312-win_amd64.pyd` left at the project root (or in `tests/`, `Release/`, etc.) silently masks the freshly built `build/astroray.cp312-win_amd64.pyd`. Symptom: code changes appear to have no effect, bisects mislead because results are frozen in time. Fix: before each debugging session run `find . -name "astroray*.pyd"` and delete every match outside `build/`. Even better, fix `base_helpers.py` to put the build dir LAST so it stays authoritative.

---

2026-04-09 | CMakeLists.txt | -ffast-math defines __FINITE_MATH_ONLY__ which folds std::isfinite to true | With `-ffast-math` enabled, GCC defines `__FINITE_MATH_ONLY__=1`, and the libstdc++ headers replace `std::isfinite(x)` with `true` at preprocessor time. NaN/Inf guards in the GR integrator therefore did NOTHING — the very check meant to catch unrecoverable states was a no-op. Fix: add `-fno-finite-math-only` to compile options to keep `std::isfinite` semantically meaningful. As a belt-and-braces measure also provide a `gr_isfinite(double)` helper that does its own bit-pattern check (`((bits >> 52) & 0x7ff) != 0x7ff`) and use it in critical guards instead of `std::isfinite`.

---

2026-04-09 | debugging | Pytest captures stderr; OneDrive paths can't be opened with fopen | When debugging a multi-threaded crash inside an OpenMP render, `fprintf(stderr, ...)` is invisible because pytest captures stderr per-test and only prints it on failure (often after the process aborts). File logging is the only reliable channel. But: opening a log file under a OneDrive-synced path (e.g. project root) silently fails — `fopen` returns NULL with no useful error. Use `C:\Users\<user>\AppData\Local\Temp\` instead, which is a real local filesystem and is not under sync.

---

2026-04-09 | debugging | Step-count bisection lies when a stale binary is in sys.path | While hunting the GR integrator crash I bisected on `maxSteps` (500/1000/2000/4000/4500/4900) and got a "narrow window" where 4500 passed and 4900 crashed. The result was complete nonsense: every test was actually running against yesterday's stale `.pyd` at the project root, so changing `maxSteps` in source had zero effect on the running code, and the apparent threshold was pure noise from crash-time RNG. Lesson: when bisection results look weirdly narrow or implausibly correlated with an unrelated parameter, the FIRST hypothesis must be "am I running the binary I think I am?" — verify `import astroray; print(astroray.__file__)` before trusting any bisection.

---

2026-04-09 | include/raytracer.h | NEE BSDF-sample emissive check NULL-derefs on GR objects | `BlackHole::hit()` does NOT set `rec.material` (BlackHole has no Material — it's handled by the GR branch via virtual dispatch). When `sampleDirect()`'s BSDF-sample branch hits the BH influence sphere instead of the env map, it called `bRec.material->emitted(bRec)` and crashed with an access violation. Visible only when ALL of: (a) HDR env map loaded, (b) at least one non-GR object in the scene, (c) enough samples that BSDF sampling actually picks a direction toward the BH. Fix: guard the emissive check with `if (bRec.material) { ... }` so NEE just skips GR objects (correct behavior — they are handled by the GR branch in pathTrace, never as light sources). Any new Hittable that doesn't set `rec.material` must also be skipped here, OR the BVH shadow/light walks must filter `isGRObject()` explicitly.
