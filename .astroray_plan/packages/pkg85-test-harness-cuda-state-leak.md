# pkg85 — Test-harness CUDA state leak (illegal memory access after test #369)

**Pillar:** 5
**Track:** A (RTX verifier)
**Status:** open — ready to implement
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

(To be filled on completion)
