# pkg54d — GPU Profile Lookup Python Binding

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** ~half a day
**Depends on:** pkg54a

---

## Why

Liveness verification on real renders is confounded by scene physics;
e.g. pkg54a's UV ratio test caps at ~1.7× image-wide in the parity
scene (see pkg54a Lessons), and NIR is dead by D65 construction.
A direct device-side reflectance lookup removes both confounders.

---

## Goal

**Before:** pkg54a profile dispatch on the GPU is exercised only
indirectly, via the multiwavelength parity tests. Those tests need (i)
a light source with spectral content in the band of interest and
(ii) a profile that differs from zero in that band. The baked D65 SPD
in `data/spectra/illuminant_d65.inc` is zero past 780 nm, so
`test_nir_band_cpu_gpu_ssim_with_profiles` cannot probe NIR liveness —
profiles get no light to reflect, and CPU/GPU agree on the dim 700-780 nm
overlap whether profile dispatch is live or dead.

**After:** A `astroray._gpu_profile_lookup(name, lambda)` Python binding
launches a one-thread CUDA kernel that returns the device-side
`gpu_profile_reflectance()` value for the named profile at `lambda`.
This gives a true unit-test gate for pkg54a that does not depend on
light-source spectrum, scene geometry, or Monte Carlo noise.

---

## Context

The current pkg54a verification path is end-to-end (multiwavelength
render → SSIM). It catches catastrophic dispatch failures via parity
mismatch with the CPU integrator, but it cannot distinguish
"profile dispatch live but band unilluminated" from
"profile dispatch dead but band unilluminated" — both produce the same
near-black output. The pkg54a Lessons section now documents the D65
zero-past-780-nm caveat; this package replaces the workaround (the
UV-band liveness assertion in `test_uv_band_cpu_gpu_ssim_with_profiles`)
with a direct, scene-free unit gate.

---

## Reference

- pkg54a constant-memory profile table:
  [src/gpu/multiwavelength_kernel.cu](src/gpu/multiwavelength_kernel.cu)
  `g_profileTable` + `gpu_profile_reflectance()`.
- pkg54a host upload:
  [src/gpu/scene_upload.cu](src/gpu/scene_upload.cu) (resamples
  per-material profiles onto the GPU grid and uploads).
- CPU equivalent already exposed:
  `astroray.spectral_profile_reflectance(name, lambda)`.

---

## Specification

### Files to create / modify

| File | What changes |
|---|---|
| `src/gpu/multiwavelength_kernel.cu` | Add `__global__ void gpu_profile_lookup_kernel(int idx, float lambda, float* d_out)` plus a host-callable `float launchProfileLookup(int profileIndex, float lambda)` wrapper. |
| `src/gpu/cuda_renderer.cu` | Expose `CUDARenderer::profileLookup(int idx, float lam)` that calls into the launcher. |
| `module/blender_module.cpp` | Add `_gpu_profile_lookup(name, lambda)` Python binding: resolve `name → profileIndex` via the existing `SpectralProfileDatabase`, ensure `uploadProfileTable()` has run with that index slotted, then call into the renderer hook. |
| `tests/test_gpu_profile_lookup.py` | New test: for each loaded profile, sweep the GPU grid (`G_PROFILE_LAMBDA_MIN` step `G_PROFILE_LAMBDA_STEP`) and assert equality with `astroray.spectral_profile_reflectance` within 1e-6. |

### Key design decisions

1. **One-thread kernel, not a buffer copy.** The point is to exercise
   the same `gpu_profile_reflectance()` device function the megakernel
   uses, including constant-memory addressing. A direct
   `cudaMemcpyFromSymbol` would skip that path.
2. **Reuse the existing upload pipeline** — do not introduce a
   second profile-table store. The binding requires that a scene with
   the queried profile has been uploaded (or it triggers a minimal
   upload of just that profile slot for testing).
3. **Underscore-prefixed name** (`_gpu_profile_lookup`) to flag it as an
   internal/test-only binding, not a public API.

---

## Acceptance criteria

- [ ] `astroray._gpu_profile_lookup(name, lambda)` returns the same
  value as `astroray.spectral_profile_reflectance(name, lambda)` at
  every grid point (`G_PROFILE_LAMBDA_MIN`, `+ step`, …,
  `G_PROFILE_LAMBDA_MIN + (G_PROFILE_SAMPLES-1)*step`) for every
  loaded profile, within ε = 1e-6.
- [ ] Test runs in <1 s on a CUDA-capable box.
- [ ] Skipped (not failed) when no CUDA GPU is available.

---

## Non-goals

- No public-facing API change. This is a test hook.
- No change to `gpu_profile_reflectance()` itself.
- No host/device interpolation parity beyond what pkg54a already
  guarantees — this just locks in a direct test for it.

---

## Progress

- [ ] Add `gpu_profile_lookup_kernel` + `launchProfileLookup`.
- [ ] Wire `CUDARenderer::profileLookup` and Python binding.
- [ ] Add `tests/test_gpu_profile_lookup.py`.
- [ ] Document the binding in pkg54a Lessons (replace the UV-band
  workaround note once the unit gate is live).

---

## Lessons

*(Fill in after the package is done.)*
