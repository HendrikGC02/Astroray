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