# Astroray — Iterative Test, Validate & Fix Loop

## Objective
Iteratively run the test suite, inspect PNG outputs for visual correctness,
write new tests where coverage is missing, and fix problems in the source code
until all tests pass and all rendered outputs look correct.

## Test Command
```
python -m pytest tests/ -x -q --tb=short
```

## Build Command
Run this after ANY change to C++ source files or CMakeLists.txt:
```
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release -j8
```
The built module must be importable before running tests. Verify with:
```
python -c "import astroray; print('module OK')"
```
If the import fails, the build did not complete correctly — do not proceed to tests.

### Cross-Platform Build Notes
- **Linux/macOS**: The build outputs to `build/` with `.so` or `.dylib` extension
- **Windows**: The build outputs to `build/Release/` with `.pyd` extension
- Use `cmake --build` instead of `make` for cross-platform compatibility
- On Windows, use `--config Release` flag with CMake generator
- After building, ensure the build directory is in `sys.path` before importing `astroray`

## Module Path
The pybind11 module is built to `build/` and found via `tests/conftest.py`.
Do NOT hardcode Windows paths. Do NOT hardcode `raytracer_blender` — the module
is named `astroray`.

## Rules

### On fixing tests
- NEVER modify existing test assertions to make them pass — fix the source code
- If a test is genuinely testing wrong behaviour, add `# REVIEW: possibly wrong`
  and `@pytest.mark.skip(reason="needs human review")` — do not delete it
- Fix one failing test at a time, run the full suite after each fix

### On writing new tests
- Write new tests when you find untested behaviour or rendering features
- New tests go in `tests/` following the naming pattern `test_<feature>.py`
- Every new test that renders must save output to `tests/output/<test_name>.png`
- New tests must be self-contained — no hardcoded paths, no Blender required

### On PNG output validation
- After each render, open the PNG and check it visually makes sense:
  - Is it non-black? (black image = renderer failed silently)
  - Does brightness/colour match what the scene should produce?
  - Are there obvious artefacts (NaN pixels show as white or black speckles)?
- Use pixel statistics for automated checks:
```python
  from PIL import Image
  import numpy as np
  img = np.array(Image.open("tests/output/result.png"))
  assert img.mean() > 5,    "image is too dark — renderer may have failed"
  assert img.mean() < 250,  "image is overexposed"
  assert not np.isnan(img).any(), "NaN pixels detected"
```
- Save reference images to `tests/references/` when a render is confirmed correct
- Do NOT commit `tests/output/` — only `tests/references/`

### On rebuilding
- Rebuild after any change to `src/`, `include/`, or `CMakeLists.txt`
- Do NOT rebuild for changes to Python test files or `blender_addon/`
- After rebuilding, always re-run the full suite to catch regressions

## Project Structure
- `src/`              C++ renderer source
- `include/`          Headers — `raytracer.h` (core), `advanced_features.h` (transforms)
- `blender_addon/`    Python Blender integration (not needed for headless tests)
- `build/`            CMake build output — module is here
- `tests/`            Pytest test files
- `tests/output/`     Rendered PNG outputs (gitignored)
- `tests/references/` Known-good reference images (committed to git)
- `docs/agent-context/` Reference docs for the agent

## Reference Files
Read these before making any changes:
- `docs/agent-context/lessons-learned.md` — prior pitfalls (if it exists)
- `docs/agent-context/blender-addon-patterns.md` — Blender API notes (if it exists)
- `include/raytracer.h` — core data structures
- `include/advanced_features.h` — transform and mesh classes
- `CMakeLists.txt` — build configuration
- `tests/conftest.py` — module path setup

## Task Breakdown
Use Beads to track tasks. Suggested starting workflow:
1. Build the project and confirm `import astroray` works
2. Run full test suite — record every failure with `bd create`
3. Fix failures in order: import errors → build errors → rendering errors → assertions
4. After each fix: rebuild if needed, run suite, confirm no regressions
5. For each passing test that renders: inspect the PNG output
6. Write new tests for any rendering feature not yet covered
7. Confirm `tests/references/` has a reference image for each visual test

## Definition of Done
- `python -m pytest tests/ -q` exits 0
- All rendered PNGs in `tests/output/` are visually correct (non-black, no artefacts)
- `tests/references/` contains at least one reference image per rendering feature
- No regressions — all previously passing tests still pass
- All fixes committed with messages referencing the Beads task ID