# pkg33 — OIDN FetchContent Integration

**Pillar:** 5  
**Track:** A  
**Status:** done  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** pkg06 (done)

---

## Goal

**Before:** `CMakeLists.txt` uses `find_package(OpenImageDenoise CONFIG QUIET)`
with `ASTRORAY_ENABLE_OIDN=ON` by default. Because OIDN is not installed on
the build machine, the find silently fails, `ASTRORAY_OIDN_ENABLED` is never
defined, and `plugins/passes/oidn_denoiser.cpp` compiles to a no-op. The user
never sees OIDN available.

**After:** When `ASTRORAY_ENABLE_OIDN=ON` (still the default), CMake first tries
`find_package`. If that fails, it falls back to `FetchContent` to download and
build OIDN from source (or a prebuilt binary release). The denoiser pass
compiles with `ASTRORAY_OIDN_ENABLED` and is available at runtime.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | After the existing `find_package(OpenImageDenoise CONFIG QUIET)` block, add a `FetchContent` fallback that fetches the OIDN 2.3 prebuilt binary package from GitHub releases (platform-detected: Windows x64). Set `OIDN_FOUND`, link target, and define `ASTRORAY_OIDN_ENABLED`. |

### FetchContent approach

OIDN binary packages are ~50 MB. Building from source requires ISPC and
oneTBB, which is complex. The pragmatic approach:

1. Download the prebuilt zip from `https://github.com/RenderKit/oidn/releases`.
2. Extract to `_deps/oidn-src/`.
3. Set `OpenImageDenoise_DIR` to the extracted `lib/cmake/OpenImageDenoise/`.
4. Re-run `find_package(OpenImageDenoise CONFIG REQUIRED)`.

This avoids building OIDN from source while still using its proper CMake
config.

### Acceptance criteria

- [x] `cmake --build . --config Release` succeeds with OIDN found.
- [x] `oidn_denoiser` appears in `pass_registry_names()` at runtime.
- [x] A test renders a noisy image, applies the OIDN pass, and verifies
      the output has lower variance than the input (30× at 4 spp).
- [x] Side-by-side PNG saved to `test_results/oidn_before_after.png`.
- [x] `ASTRORAY_ENABLE_OIDN=OFF` still works and skips OIDN entirely.
- [x] All existing tests pass.

### Implementation notes

- OIDN 2.4.1 was already installed at `C:/oidn`; added auto-detection for
  common Windows locations so `find_package` succeeds without any user flags.
- FetchContent fallback downloads OIDN 2.3.3 prebuilt zip on clean machines.
- `plugins/materials/disney.cpp` had duplicate function definitions from the
  rough-glass merge; fixed by removing the second copy.
- Blender addon `__init__.py` probes `addon_dir/oidn/` and `C:/oidn/bin`.
- `scripts/build_blender_addon.py` bundles OIDN DLLs into `dist/astroray/oidn/`.

---

## Non-goals

- Do not build OIDN from source.
- Do not support Linux/macOS in this package (Windows-only for now).
- Do not upgrade to OIDN 3.x (that's a future production polish task).
