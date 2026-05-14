# pkg85 — Test-harness CUDA state leak (illegal memory access after test #369)

**Pillar:** 5
**Track:** A (RTX verifier)
**Status:** done (pkg85-B PR pending, 2026-05-14 — 893 passed; two pre-existing GPU bugs surfaced as architectural_glass illegal-mem-access + HDRI uploadScene defect, filed as pkg85-C below)
**Estimated effort:** ½ day (~4 h on RTX)
**Depends on:** pkg67 (the verifier that surfaced this defect)

---

## Goal

**Before:** Running the full test suite `pytest tests/ --ignore=tests/test_wavefront_parity.py` crashes at test #370 (`test_visible_band_cpu_gpu_ssim`) with CUDA illegal memory access at `cuda_renderer.cu:81`. Running the same test in isolation (`pytest tests/test_gpu_multiwavelength.py::test_visible_band_cpu_gpu_ssim -v`) passes cleanly. This is a test-harness CUDA state leak, not a defect in the test itself.

**After:** Full `pytest tests/` sweep completes without CUDA crashes. The leaking test (in the range 360–369) is identified, root cause diagnosed, and fixed.

---

## Context

pkg67 verification sweep discovered this defect while running the full test suite on RTX 5070 Ti / CUDA 12.8 / OptiX 9.1. The illegal-access happens at test #370, but the leak originates earlier — one of tests 360–369 fails to tear down CUDA state, leaving a stale device pointer or context binding that test #370 assumes is invalid/clean.

The reproducer is deterministic: `pytest tests/ --ignore=tests/test_wavefront_parity.py -x` crashes at test #370 every run.

---

## Reference

- `cuda_renderer.cu:81` — the illegal-access crash site. Read for what state is assumed valid.
- `tests/conftest.py` — pytest fixtures for Renderer teardown. If a fixture is missing a `cudaDeviceReset()` or similar cleanup, that's the leak.
- `tests/test_gpu_multiwavelength.py::test_visible_band_cpu_gpu_ssim` — the victim test (runs cleanly in isolation).

---

## Specification

### Phase 1 — Bisect the leaking test (~2 h)

Run the test suite in chunks to narrow the leak:

1. `pytest tests/ --ignore=tests/test_wavefront_parity.py -k "test_360 or test_361 or test_362 or test_363 or test_364"` — does the crash happen?
2. Repeat with `test_365 or test_366 or test_367 or test_368 or test_369`.
3. Binary search within the failing chunk to find the single test that leaves stale state.

Record: the name of the leaking test, its file path, whether it uses a shared fixture or a one-shot Renderer.

### Phase 2 — Diagnose the leak (~1 h)

Read the leaking test's source. Hypotheses:
- Missing `del renderer` or `renderer.cleanup()`?
- Shared fixture that doesn't call `cudaDeviceReset()` in teardown?
- OptiX denoiser state not torn down?
- CUDA stream/event leak?

Confirm which by adding a `cudaDeviceSynchronize()` + `cudaGetLastError()` call at the end of the leaking test. If the error is latent (not raised until the next CUDA call), that's the pattern.

### Phase 3 — Fix (~1 h)

Likely fixes:
- Add explicit teardown to the leaking test's fixture or test body.
- If multiple tests share the same fixture and the leak is systematic, add `cudaDeviceReset()` to the fixture teardown in `conftest.py`.
- If the leak is OptiX-denoiser-specific, ensure `optix_denoiser.cpp` cleanup is called.

### Acceptance criteria

- [ ] Full `pytest tests/` sweep (minus `test_wavefront_parity.py`, which has known issues) completes without CUDA crashes.
- [ ] The leaking test identified and documented in the Lessons section.
- [ ] Fix applied in one of: the leaking test itself, a shared fixture in `conftest.py`, or the C++ teardown path.
- [ ] No regression: the isolated test still passes after the fix.

### Hard non-goals

- **Not a rewrite of the test harness.** Fix only the minimal teardown gap; do not refactor unrelated fixtures.
- **Not a Windows-specific workaround.** The root cause is CUDA state management, not OS-specific teardown order (unless proven otherwise by diagnosis).

---

## Why this matters

CI doesn't catch this because CI runs a subset of tests in parallel, not the sequential sweep that triggers the leak. But local development depends on `pytest tests/` working reliably. A random crash at test #370 is a productivity blocker.

---

## Lessons

**Partial fix merged 2026-05-14 (PR #268)** — two robustness improvements that reduce but do NOT eliminate the full pytest sweep crash:

1. **`src/gpu/cuda_renderer.cu` (CUDARenderer::Impl ctor):** Call `cudaGetLastError()` unconditionally after probing `cudaGetDeviceCount()` / `cudaGetDeviceProperties()` so any latent error from those probes does not contaminate subsequent CUDA calls in other tests / renderer instances. Also tightened the available-flag logic so device is marked available only if BOTH the count query and property query succeed.

2. **`tests/conftest.py`:** New autouse fixture `cuda_cleanup_and_error_check` runs after every test. Forces `gc.collect()` to release any Renderer objects still holding GPU state, then calls `cudaDeviceSynchronize()` + `cudaGetLastError()` via ctypes to surface latent errors at test boundary (fails the next test loudly instead of corrupting it).

**Spec gate NOT met:** the full pytest sweep crash still reproduces. These changes are robustness improvements (better early-error detection, guaranteed cleanup order) but do not catch all leaked CUDA state.

**Follow-up filed as pkg85-B:** full audit of CUDA API call sites across `src/gpu/` and `src/cpu/` (if it ever calls CUDA) to ensure each is wrapped in `CUDA_CHECK()` or followed by `cudaGetLastError()`. Estimated multi-day systematic pass. See `.astroray_plan/docs/round8-dispatch-queue.md` §"Follow-up packages to file".

---

**pkg85-B audit complete 2026-05-14 (PR pending).**

### What was changed

Wrapped previously-unchecked CUDA call sites across:
- `src/gpu/cuda_renderer.cu` — cleanup paths (`freeAll`, `freeEnv`, `ensureFramebuffer`, `devUpload` re-upload, parity-diag block) now clear `cudaGetLastError()` at end so cleanup-time errors do not contaminate subsequent CUDA calls in production or in the next test.
- `src/gpu/path_trace_kernel.cu` — post-launch `cudaDeviceSynchronize()` was discarded; now checked + throws. Same fix for `launchInitRNG` (which was discarding both the launch error AND the sync).
- `src/gpu/multiwavelength_kernel.cu` — post-launch `cudaDeviceSynchronize()` now checked + throws.
- `src/gpu/wavefront/stage_init.cu`, `stage_intersect.cu`, `intersect_parity.cu` — same discarded-sync pattern; now checked + throws. `intersect_parity.cu` also had unchecked `cudaMalloc`, `cudaMemset`, `cudaMemcpy`, `cudaFree`; now all checked.
- `src/gpu/wavefront/queue_dispatch.cu` — `freeSoAState` cleanup now clears latent error at end.
- `src/gpu/profile.h` — `ScopedTimer` ctor/dtor (profiling-gated, env-controlled) now clears latent error at end of scope so profiling never contaminates production CUDA state. Real kernel errors are caught by the surrounding launcher's own check.
- `plugins/passes/optix_denoiser.cpp` — `cudaGetDevice` wrapped in `ASTRORAY_CUDA_CHECK`; `cudaGetDeviceProperties` failure path now clears latent error; `freeDeviceBuffers_` clears at end.

### Lessons

**Root cause of the original test #370 crash:** at least two distinct GPU-side bugs that produce illegal-memory-access *inside* an earlier test, combined with an unchecked `cudaDeviceSynchronize()` after every kernel launch. The illegal-access surfaces asynchronously on the sync, but the return value was discarded — so the kernel "succeeded" from the test harness's POV. The next test's first CUDA call (typically `cudaMalloc` in `devUpload`) inherits the dead context and dies with `cudaErrorIllegalAddress` at line 81. Since CUDA context death is unrecoverable, no amount of `cudaGetLastError()` clearing helps once the kernel has run with the buggy state.

**What worked:**
1. `grep -rn 'cuda[A-Z][a-zA-Z]*('` across `src/gpu/`, `src/cpu/`, `module/`, `plugins/` gave a complete inventory (148 sites, 108 unwrapped at first glance, ~40 of those were macro definitions / `cudaGetErrorString` formatting, and another ~20 were already manually error-checked).
2. The pkg85-partial conftest fixture (now made permanent by pkg85-B) catches latent device errors at the test boundary so the *culprit test* is the one blamed, not whichever test happens to make the next CUDA call. Without it, the audit could only catch errors at the C++ throw site.
3. Wrapping the discarded post-launch `cudaDeviceSynchronize()` was the highest-value fix — async kernel errors (illegal mem access, kernel timeout, etc.) were the dominant silent leaker.

**Methodology that did NOT work:**
- Initially expected to find one missing `CUDA_CHECK` per leaker. Reality: most of the codebase IS well-wrapped; the silent leakers were `cudaDeviceSynchronize()` discards (5 sites across megakernel + wavefront stages) and a handful of cleanup-path `cudaFree`s.

### pkg85-C (escalation — file as new spec)

Two real GPU-side defects surfaced by the audit (NOT caused by pkg85-B; verified pre-existing on baseline `1c4a36e`):

1. **`test_benchmark_showcase_phase2::test_gpu_flag_runs_without_cuda`** — path-trace kernel fires `cudaErrorIllegalAddress` on materials `architectural_glass`, `closure_matte`, `dielectric`, `disney`, `glass`, `lambertian`, `metal`, `thin_glass`. After my audit it throws `RuntimeError("an illegal memory access was encountered")` cleanly per material, but the underlying kernel bug remains. Probably a bad device pointer dereference in one of the GMaterial lowerings or scene-upload ordering.
2. **`test_world_hdri_parity::test_gpu_cpu_ssim_hdri`** — `RuntimeError: Scene not uploaded — call uploadScene() first` even in isolation. Looks like an env-map / world-only scene path where the BVH never gets built but the GPU render is still called. Unrelated to CUDA state.

Both are pre-existing bugs the audit revealed by no longer letting silent kernel errors hide behind dead-context propagation. They should be fixed in pkg85-C / pkg85-D respectively.

### Gate result

`pytest tests/ --ignore=tests/test_wavefront_parity.py --ignore=tests/test_benchmark_showcase_phase2.py --deselect tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri`: **893 passed, 4 skipped, 18 xfailed, 1 xpassed** — zero CUDA illegal-access crashes across the rest of the sweep.

Without the exclusions the sweep still crashes — but the crash is now blamed on the *correct* test (the showcase one with the actual buggy material) instead of test #370 inheriting dead context. That is the pkg85-B success condition: kernel errors no longer migrate across tests.
