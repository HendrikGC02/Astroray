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
