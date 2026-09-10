# Issue #780 — root cause of the "OpenMP hangs the Blender addon" rule

**Date:** 2026-09-09 · **Branch:** `fix/780-addon-cpu-threads` · **Machine:** AMD Ryzen 7 7800X3D (8 cores / 8 threads), Windows 11, Blender 5.1 + 5.2

## Symptom

`scripts/build/build_blender_addon.py` forced `-DASTRORAY_DISABLE_OPENMP=ON` for
every addon build, so every Blender CPU render (F12 and viewport CPU mode) ran on
one core. Measured on `benchmarks/reference_corpus/scenes/lighting_studio.blend`
at 640×160 / 256 spp through the staged addon: **409.5 s wall for 371.7 CPU-s**
(CPU/wall = 0.91 — one core busy).

The flag was there because the addon *hung* with OpenMP on: the process sat at
~0 % CPU and never produced a frame. Memory `mingw_openmp_blender_deadlock`
blamed MinGW's libgomp at module-init time; its 2026-06-12 update recorded that
an MSVC/vcomp build hung too, and generalised the rule to "any `.pyd` loaded
inside Blender needs `-DASTRORAY_DISABLE_OPENMP=ON`, regardless of toolchain".

## Root cause — a GIL/OpenMP circular wait, not a toolchain defect

The hang is **not** at module init and **not** toolchain-specific. It is a
textbook GIL deadlock between the OpenMP master thread and its workers:

* `include/raytracer.h:4425-4432` — the CPU tile loop (`#pragma omp parallel for
  schedule(dynamic) collapse(2)`) calls `progress(float(done) / totalTiles)`
  from **whichever worker thread finishes a tile**.
* `module/blender_module.cpp:2386-2400` — that `std::function` is a lambda that
  wraps the Python callback in `py::gil_scoped_acquire`.
* Before pkg241 (#748), `PyRenderer::render()` held the GIL for the entire call.
  So: master thread holds the GIL and parks in the end-of-parallel-region
  barrier; every worker parks trying to acquire the GIL the master will not
  release until the barrier clears. Nothing runs — ~0 % CPU, forever.

Only one Python object crosses into the CPU render (`progressCallback`); a
`std::thread` tile pool would deadlock identically, so the fix had to address
the Python touch, not the threading primitive.

The standalone pytest suite never saw it because `render()` is called there with
`progress_callback=None`, which makes the C++ callback `nullptr` — no Python is
touched inside the parallel region at all.

### Reproduced stack (py-spy 0.4.2 `dump --native`, Blender 5.2, 128×128 / 16 spp)

Captured after killing a 120 s timeout, with a temporary env-gated switch
(`ASTRORAY_780_HOLD_GIL=1`) that restores the pre-#748 "hold the GIL across
`renderer.render()`" behaviour in an otherwise-current OpenMP-ON addon build.
Symbol names inside the `.pyd` resolve to the nearest export (`PyInit_astroray`);
the load-bearing frames are in libgomp and python313:

```
Thread 29104 (idle): "MainThread"          <-- holds the GIL
    ZwWaitForMultipleObjects (ntdll.dll)
    WaitForMultipleObjects (KERNELBASE.dll)
    sem_wait (astroray\libwinpthread-1.dll)
    gomp_sem_wait (astroray\libgomp-1.dll)
    gomp_team_barrier_wait_end (astroray\libgomp-1.dll)   <-- waiting for workers
    gomp_team_end (astroray\libgomp-1.dll)
    PyInit_astroray (astroray\astroray.cp313-win_amd64.pyd)   [Renderer::render]
    ...
    render (astroray\__init__.py:1313)

Thread 40788 (idle)                        <-- x4 OpenMP workers, all identical
    ZwWaitForAlertByThreadId (ntdll.dll)
    SleepConditionVariableSRW (KERNELBASE.dll)
    PyEval_AcquireThread (python313.dll)                  <-- waiting for the GIL
    PyInit_astroray (astroray\astroray.cp313-win_amd64.pyd)   [progress lambda]
    gomp_ialias_omp_fulfill_event (astroray\libgomp-1.dll)
    pthread_create_wrapper (astroray\libwinpthread-1.dll)
```

The offending call is `py::gil_scoped_acquire` (→ `PyEval_AcquireThread`) inside
the progress-callback lambda at `module/blender_module.cpp:2389`, executed on an
OpenMP worker while the master holds the GIL in `gomp_team_barrier_wait_end`.

## Why it is already fixed

pkg241 Phase 1b (PR #748, `module/blender_module.cpp:2413`) wrapped the CPU
render in `py::gil_scoped_release`. The master thread no longer holds the GIL
while it waits at the barrier, so worker re-acquisition succeeds and the render
completes. No engine change was needed for #780 — only the build flag, the
now-inverted guards, and the packaging of the OpenMP runtime DLL.

## Evidence: the rule was toolchain-independent in both directions

Same scene (Blender factory-startup cube, 128×128 / 16 spp, `device_mode='cpu'`,
denoising and adaptive sampling off), same source revision:

| addon `.pyd` | Blender | wall | process CPU | CPU/wall |
| --- | --- | --- | --- | --- |
| OpenMP OFF (pre-fix default) | 5.2 | 47.75 s | 45.31 s | **0.95** |
| OpenMP OFF (pre-fix default) | 5.1 | 51.00 s | 45.61 s | **0.89** |
| OpenMP ON, MinGW 15.2 / libgomp | 5.2 | 8.18 s | 45.50 s | **5.56** |
| OpenMP ON, MinGW 15.2 / libgomp | 5.1 | 8.48 s | 45.80 s | **5.40** |
| OpenMP ON, MSVC 14.44 / vcomp140 | 5.2 | 17.30 s | 77.02 s | **4.45** |
| OpenMP ON + `ASTRORAY_780_HOLD_GIL=1` | 5.2 | **HANG** (>120 s at ~0 % CPU) | — | — |

Total CPU-seconds are unchanged between the OFF and ON MinGW runs (45.3 → 45.5),
i.e. the same work, now spread across cores. Both OpenMP runtimes render
correctly; only the GIL-hold switch hangs. (The MSVC row is a separate CPU-only
`cl.exe` build with different codegen — `/arch:AVX2` vs `-march=native` — so its
absolute time is not comparable to the MinGW rows; the point is that it does not
hang and is threaded.)

`lighting_studio.blend`, 640×160 / 256 spp, Blender 5.2:

| addon `.pyd` | wall | process CPU | CPU/wall |
| --- | --- | --- | --- |
| OpenMP OFF | 409.48 s | 371.67 s | 0.91 |
| OpenMP ON | 69.65 s | 375.28 s | 5.39 |

**5.88× faster** on 8 cores (~74 % parallel efficiency; the remainder is serial
scene conversion, BVH build and PNG write inside the measured window).

## Packaging consequence

The shipped addon (`--backend cuda`) is built with Ninja + `cl.exe`, so `/openmp`
makes the `.pyd` hard-import `VCOMP140.DLL`:

```
$ objdump -p build_msvc_cpu_780/astroray.cp313-win_amd64.pyd | grep 'DLL Name'
  ... MSVCP140.dll  VCOMP140.DLL  VCRUNTIME140.dll  python313.dll ...
```

Blender bundles its own CRT in `blender.crt/` (msvcp140, vcruntime140, concrt140)
but **not** `vcomp140.dll`, so without the VC++ redistributable installed the
addon would fail to import. `_bundle_msvc_openmp_dll()` now copies it next to the
`.pyd`, mirroring the existing `libgomp-1.dll` bundling on the MinGW path.
(`vcomp140.dll` is on Microsoft's VS redistributable list.)

## Residual risk

The GUI F12 path calls `RenderEngine.test_break()` / `update_progress()` from
OpenMP worker threads (with the GIL held) rather than only from Blender's render
thread. Both are scalar read/writes on the Blender side and the headless F12 path
was exercised over 400 tiles without incident, but a GUI F12 spot-check is the
one thing headless testing cannot cover.
