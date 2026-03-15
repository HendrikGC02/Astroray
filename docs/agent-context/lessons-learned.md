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
