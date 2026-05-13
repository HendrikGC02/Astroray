---
name: rebuild-pyd
description: Rebuild the astroray Python extension cleanly, clearing every stale .pyd shadow copy that can mask a fresh build. Use when tests behave as if code changes had no effect, or after switching between Blender/standalone/CUDA build variants.
disable-model-invocation: true
---

# rebuild-pyd

Astroray ships its Python module (`astroray.pyd` / `astroray.cp312-win_amd64.pyd`) into several directories for IDE/Jupyter/Blender convenience. `tests/base_helpers.py` inserts the project root into `sys.path` *after* `build/`, so the project-root copy wins. A stale `.pyd` outside `build/` will silently shadow a fresh build and produce frozen-in-time test output.

This skill does the canonical clean rebuild for one of three variants. The user picks the variant; nothing here assumes.

## Variants

| Variant     | Preset / script                              | OpenMP   | CUDA  | Loaded by               |
|-------------|----------------------------------------------|----------|-------|-------------------------|
| `standalone`| `cmake --preset windows-cpu-vs` + build      | ON       | OFF   | pytest, CLI raytracer   |
| `cuda`      | `cmake --preset windows-cuda-vs` + build     | ON       | ON    | pytest with GPU         |
| `blender`   | `python scripts/build/build_blender_addon.py`| **OFF**  | OFF   | Blender's MSVC Python   |

**Hard rule**: the `blender` variant MUST build with `-DASTRORAY_DISABLE_OPENMP=ON`. MinGW `libgomp-1.dll` deadlocks silently inside Blender's MSVC-built host Python. The `build_blender_addon.py` path already sets this; do not override it. (See `memory/mingw_openmp_blender_deadlock.md`.)

## Procedure

1. **Locate every shadow.** From repo root:
   ```powershell
   Get-ChildItem -Recurse -Filter astroray*.pyd | Select-Object FullName, Length, LastWriteTime
   ```
   Expected legitimate locations:
   - `build/astroray.cp312-win_amd64.pyd` (standalone preset binaryDir is `build/`)
   - `build_cuda/astroray.cp312-win_amd64.pyd`
   - `build_tcnn/astroray.cp312-win_amd64.pyd`
   - the Blender addon's `Release/` staging copy

   Anything at any of these paths is a shadow and must go:
   - `./astroray.pyd`
   - `./astroray.cp312-win_amd64.pyd`
   - `./tests/astroray*.pyd`
   - `./Release/astroray*.pyd` (only if not the Blender staging dir — check `blender_addon/Release/` is the legit one)

2. **Delete shadows.** Show the list to the user before deleting. Then `Remove-Item` each. Never delete from `build/`, `build_cuda/`, `build_tcnn/`, or `blender_addon/Release/`.

3. **Rebuild the chosen variant:**
   - `standalone`: `cmake --preset windows-cpu-vs` then `cmake --build --preset windows-cpu-vs-release`
   - `cuda`: `cmake --preset windows-cuda-vs` then `cmake --build --preset windows-cuda-vs-release`
   - `blender`: `python scripts/build/build_blender_addon.py` — do not pass extra CMake flags; the script owns `ASTRORAY_DISABLE_OPENMP=ON` and `PYBIND11_FINDPYTHON=ON`.

4. **Verify the fresh artifact.** Re-run the `Get-ChildItem` from step 1 and confirm the timestamp on the expected output (e.g. `build/astroray.cp312-win_amd64.pyd`) is newer than 60 seconds ago. If any shadow reappeared (e.g. a post-build copy step you forgot about), surface that path rather than silently moving on.

5. **For `standalone`/`cuda`, smoke-test:** `python -c "import sys; sys.path.insert(0, 'build'); import astroray; print(astroray.__file__)"`. The printed path must be inside `build/` (or `build_cuda/`). If it points to the project root, step 2 missed a shadow.

## Anti-patterns

- Running `cmake --build` without first clearing shadows: the build will succeed and tests will still load the old binary.
- Using `find . -name '*.pyd' -delete` blindly: that nukes the Blender addon staging copy too.
- Re-enabling OpenMP "just to test" in the Blender variant: it will hang at module init with no log past `Read blend:`.

## When to invoke

Type `/rebuild-pyd` (model invocation is disabled — this only runs on explicit user request) when:
- A test fix "isn't working" and the failure output looks identical to before the edit.
- You just switched Python versions or pybind11 settings.
- You're about to ship a Blender addon build and need to be sure no OpenMP-linked `.pyd` leaked through.
