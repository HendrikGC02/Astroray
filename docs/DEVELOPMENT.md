# Development setup (Windows)

How to stand up a full Astroray development environment on a Windows machine
with an NVIDIA GPU. Written for the project's two known machines — the
workstation (RTX 5070 Ti) and a travel laptop (RTX 3000 Ada Generation,
sm_89, 8 GB) — but applies to any Turing/Ampere/Ada-or-newer card
(sm_75 / sm_86 / sm_89).
[QUICKSTART.md](QUICKSTART.md) covers the short version; this page covers the
full developer workflow and the Windows footguns.

## Prerequisites

| Component | Version | Notes |
|---|---|---|
| Visual Studio 2022 Build Tools | MSVC v143 (14.4x) | C++ workload. The VS CMake generator finds it itself — no `vcvars` needed for `configure_and_build.bat`. |
| CUDA Toolkit | 12.6+ (12.8 workstation, 13.2 laptop) | `nvcc` on PATH or default install path. Targets `sm_75;86;89` (see "GPU architectures"). With several toolkits installed, the CMake VS integration picks the **newest** — not the one on PATH. |
| CMake | 3.24+ | VS generator used for the canonical build. |
| Python | 3.13 x64 | Must match Blender 5.2's bundled Python minor version for addon work. `winget install Python.Python.3.13`. `pip install -r requirements.txt`. |
| Blender | 5.1 | Only for addon work / cross-engine benchmarks. Auto-detected at the default install path, or set `BLENDER_EXE`. |
| OptiX SDK | 8.x / 9.x (optional) | OptiX denoiser. Auto-detected from `C:\ProgramData\NVIDIA Corporation\OptiX SDK 9.x.x\` or `OPTIX_INSTALL_DIR`. Without it, the denoiser falls back to OIDN. |
| OIDN | 2.4+ (optional install) | CMake finds a local install (e.g. `C:\oidn`, `C:\Program Files\Intel\OpenImageDenoise`) and otherwise **fetches the v2.4.1 prebuilt automatically** during configure — a fresh machine needs nothing. |

## The two-build story (important)

Astroray on Windows is always built **twice**, into two separate build dirs:

1. **Test/dev build — `build_cuda/` (OpenMP ON).**

   ```bat
   scripts\build\build_cuda.bat
   ```

   **Ninja** generator (single-config), CUDA 12.8 (`CUDA_PATH` env
   preferred, 12.8 fallback), `-DASTRORAY_CUDA_ARCHS=native` (sm_120 AOT
   on the workstation), sccache auto-used if on PATH. CUDA + OIDN + OptiX
   auto-detect. Artifacts land at the **build root** (Ninja has no
   `Release/` subdir): `build_cuda/astroray.cp313-win_amd64.pyd` (+
   `astroray_test_helpers`). This is the build pytest and all
   benchmark/diagnostic scripts use.
   Optional extras: `-DASTRORAY_TINY_CUDA_NN=ON` adds the neural-cache
   backend + `tcnn_smoke` / `nrc_smoke_render` harnesses.
   *(Legacy: `configure_and_build.bat` at the repo root used the VS 2022
   multi-config generator with artifacts under `build_cuda/Release/` —
   superseded 2026-08-06; kept only for reference.)*

2. **Blender addon build — `build_blender_addon_*/` (OpenMP OFF, forced).**

   ```bat
   python scripts/build/build_blender_addon.py --backend cuda   REM or tcnn / cpu
   ```

   The script always passes `-DASTRORAY_DISABLE_OPENMP=ON`: **OpenMP
   deadlocks inside Blender 5.2 on Windows with BOTH MinGW libgomp and MSVC
   vcomp** (diagnosed in PR #471). It stages `dist/astroray/` (addon +
   `.pyd` + CUDA runtime DLLs + OIDN DLLs) and zips
   `dist/astroray-<version>.zip` for `Install from Disk...`.

   **Never load the OpenMP test build's `.pyd` into Blender.** The two build
   dirs exist precisely so the artifacts cannot be confused.

## GPU architectures / second-machine portability

`CMakeLists.txt` defaults `CMAKE_CUDA_ARCHITECTURES` to `"75;86;89"` —
Turing, Ampere (RTX 3000 = sm_86), Ada — for distributable/CI builds;
Blackwell cards (RTX 5070 Ti = sm_120) then run the `compute_89` PTX via
JIT. **Local dev builds override this**: `scripts/build/build_cuda.bat` and
`build_cuda_worktree.bat` pass `-DASTRORAY_CUDA_ARCHS=native` (AOT sm_120,
~3× less device compile work; a *build-time* win — distinct from the
separate pkg155 runtime finding about sm_120 AOT documented below). The
tiny-cuda-nn targets keep the fixed list (`TCNN_CUDA_ARCHITECTURES`, floor
`TCNN_MIN_GPU_ARCH=75`).

## Running tests

```bat
REM recommended: split runner — CPU tests parallel via xdist, GPU tests serial
REM (PR #545; ~18% faster and avoids concurrent-CUDA false crashes)
python scripts/test/run_split.py
```

```bat
REM classic single-pass runner (still valid; resolves DLL dirs, temp dirs, .pyd path)
python scripts/dev/run_tests.py --build-dir build_cuda -- tests -q --tb=short
```

Rules that save hours:

- **Never run two CUDA-heavy test/verify processes concurrently** — it
  produces false-positive illegal-access crashes.
- **Seed 0 is a sentinel** for `std::random_device` (non-deterministic), not
  a pin (`raytracer.h`, `setSeed`). Use any non-zero seed in tests.
- **Perf ratios are thermally robust; absolute timings are not.** After
  hours of GPU benchmarking the card throttles — re-run timing gates on a
  cool GPU before believing a regression.
- A `.pyd` import picks up the **first** `astroray` on `sys.path` — check
  `astroray.__file__` points at `build_cuda/` (root; `build_cuda/Release/`
  only for legacy multi-config builds) and that the file is newer than
  `git log -1 --format=%cd HEAD` before trusting any GPU result.

### Perf gates calibrated to the workstation (RTX 5070 Ti)

| Gate | Type | On a slower GPU |
|---|---|---|
| `tests/wavefront_diff/test_pkg55_perf_gate.py` | wavefront/megakernel **ratio** (hard floor 1.30×, 1.5× target xfail) | Ratio-based — expected to hold approximately on any sm_75+ card. |
| `tests/test_pkg64_gpu_phase{2,3}_no_regression.py` empty-hook walltime | absolute walltime vs pinned baseline | Calibrated to this machine; flaky under suite load even here. Re-run in isolation; on another machine re-pin the baseline or deselect (`-k "not empty_hook_walltime"`). |
| `tests/wavefront_diff/test_pkg55_gpu_wavefront_image.py` etc. | per-channel mean-ratio vs CPU oracle | Machine-independent. |
| `tests/test_pkg86_light_tree.py` upload ≤ 10 ms | absolute, huge headroom (measured 0.09–0.5 ms) | Should pass anywhere. |
| `benchmarks/viewport_parity/` numbers (p99 0.84× Cycles) | informational benchmark, not a gate | Workstation-specific. |

## Windows footguns

- **CUDA 13 moved its runtime DLLs**: from CUDA 13.0, `nvrtc64_*.dll`,
  `cudart64_*.dll`, `cublas64_*.dll` etc. live in `bin\x64\`, not `bin\`.
  `tests/runtime_setup.py` and the addon bundler probe both layouts; any
  hand-rolled PATH/`os.add_dll_directory` setup must include `bin\x64` or
  imports fail with "DLL load failed" despite a healthy build.
- **OneDrive syncs `build_cuda/` between machines**: a CMake cache and
  `.obj` files built on the other machine are invalid here (different
  username/toolkit paths). On arriving at a new machine, delete
  `build_cuda/` and configure fresh before trusting any build output.
- **OneDrive locks**: the repo lives under OneDrive on the workstation. Sync
  can hold `.git` objects and directories open — deletion fails with
  "Permission denied"/"used by another process". Retry, or pause OneDrive
  sync for heavy git surgery (worktree removal, branch cleanup). This is
  also why `tests/runtime_setup.py` keeps pytest temp dirs inside the repo.
- **Stale `.pyd` shadowing**: multiple `astroray.pyd` copies can exist
  (`build/`, `build_tcnn/`, `dist/astroray/`, Blender's installed
  extension). Harnesses honour `ASTRORAY_PYD_DIR` / `ASTRORAY_BUILD_DIR` to
  disambiguate; when in doubt print `astroray.__file__`.
- **Signature changes need a clean rebuild**: MSVC/CMake sometimes links
  stale `.obj` files against new headers. If a function signature changed
  and behaviour looks impossible, delete the affected `.obj`s or rebuild
  clean before debugging further.
- **`.ps1` hook files must be ASCII or UTF-8-with-BOM** — PowerShell reads
  BOM-less files as cp1252; an em-dash in a comment becomes a parse error
  and the hook silently stops running.
- **MinGW (only if you build with it)**: pass structs > 32 bytes as
  `const T&` across TU boundaries (by-value corrupts), and `.pyd`s for
  Blender additionally need the OpenMP-off rule above.

## Blender addon on a second machine

1. Build + install: `python scripts/build/build_blender_addon.py --backend cuda --install`
   (or copy `dist/astroray-<version>.zip` and install via
   `Edit > Preferences > Get Extensions > Install from Disk...`).
   The staged addon bundles the CUDA runtime DLLs (cublas/cudart/nvrtc) and
   OIDN — the target machine only needs an NVIDIA driver, not the toolkit.
2. On Python 3.13, DLL resolution is strict: the addon (and all headless
   harness scripts) call `os.add_dll_directory()` for the `.pyd` dir and the
   CUDA runtime — if you wire up a custom loader, replicate that.
3. Headless smoke check (no GUI needed):

   ```bat
   "<blender>" --background --factory-startup --python scripts/verify_pkg115_textures_blender.py -- --engine CUSTOM_RAYTRACER --out test_results/pkg115_visual
   ```

4. Env overrides honoured by the verify/benchmark harnesses:
   `BLENDER_EXE` (Blender path), `ASTRORAY_PYD_DIR` (addon-visible `.pyd`),
   `ASTRORAY_BUILD_DIR` (test-build dir), `ASTRORAY_ROOT` (repo root for
   in-Blender scripts), `CUDA_PATH` (CUDA runtime bin for DLL loading).

## Standalone renderer

```bat
build_cuda\bin\Release\raytracer.exe --scene 1 --width 800 --height 600 ^
    --samples 128 --depth 8 --device gpu --output cornell.png
```

`--device auto|gpu|cpu`, `--integrator <name>` (e.g.
`wavefront_path_tracer`), `--integrator-param key=value`, `--envmap <hdr>`.
The exe needs the OIDN and CUDA runtime DLLs on PATH when run outside the
test harness (e.g. `set PATH=C:\oidn\bin;%CUDA_PATH%\bin;%PATH%`).
