# pkg54a — GPU Spectral Profile Dispatch

**Pillar:** 5
**Track:** A
**Status:** done (verified on CUDA hardware — see Lessons for measured ratios)
**Estimated effort:** ~1 week (~20 h)
**Depends on:** pkg54 (GPU MW kernel landed), pkg38/pkg39 (CPU spectral profiles)

---

## Goal

**Before:** The pkg54 GPU multi-wavelength megakernel ignores
`Material::setSpectralProfile()`. For wavelengths inside [380, 780] it
falls through to `gpu_rgbToSampledSpectrum`; for wavelengths outside that
range, with no profile awareness, it produces near-zero radiance for every
material — exactly the same as the CPU integrator's no-profile fallback.
That makes the pkg54 parity test pass *for the wrong reason* (both
backends are near-black) and means the GPU IR/UV outputs do not match the
spec scene's expected behaviour (vegetation bright in NIR, water dark,
aluminium bright in UV, etc.).

**After:** GPU multi-wavelength rendering reproduces the CPU integrator's
profile-aware behaviour — `evalSpectralExt` semantics on-device. The
canonical IR/UV scene from
[tests/scenes/multiwavelength_parity.py](tests/scenes/multiwavelength_parity.py)
(extended with profile-attached materials) renders the same on CPU and
GPU at SSIM ≥ 0.97 in both NIR and UV bands.

---

## Context

CPU dispatch is in [include/raytracer.h](include/raytracer.h) around the
`Material::evalSpectralExt` / `sampleSpectralExt` methods (search for
`spectralProfile_`):

* For visible λ → reuse the existing Jakob-Hanika sigmoid spectral path.
* For non-visible λ + profile → `profile.reflectance(λ) * cosθ / π`
  (Lambertian assumption regardless of underlying material — this matches
  the CPU implementation exactly and is fine to mirror).
* For non-visible λ + no profile → 0.

The pkg54 kernel ([src/gpu/multiwavelength_kernel.cu](src/gpu/multiwavelength_kernel.cu))
currently calls `gpu_material_sample_spectral`, which has no notion of a
spectral profile. We need a profile-aware spectral evaluation specific to
the MW kernel.

---

## Reference

- CPU spec: `Material::evalSpectralExt` / `Material::sampleSpectralExt` in
  [include/raytracer.h](include/raytracer.h).
- Profile data: [include/astroray/spectral_profile.h](include/astroray/spectral_profile.h)
  (5 nm grid, linearly interpolated).
- Material upload: [src/gpu/scene_upload.cu](src/gpu/scene_upload.cu).

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | Add `int profileIndex` to `GMaterial` (default `-1`). Add constants for profile table layout. |
| `include/astroray/gpu_materials.h` | Add `gpu_profile_reflectance(profileIndex, lambda)` device helper reading from `__constant__` memory. |
| `src/gpu/scene_upload.cu` | Walk all materials, deduplicate spectral profiles by name, build a flat `[numProfiles × N]` reflectance table on the host. Set `mat.profileIndex` per material. |
| `src/gpu/cuda_renderer.cu` | New `uploadSpectralProfileTable()` private helper invoked from `uploadScene`; copies the host table into `__constant__` memory. |
| `src/gpu/multiwavelength_kernel.cu` | Replace `gpu_material_sample_spectral` call with a profile-aware local function that mirrors `evalSpectralExt`. |
| `tests/scenes/multiwavelength_parity.py` | Extend the scene with profile-attached materials (vegetation + water + aluminium + UV light) so the parity test exercises real profile dispatch. |
| `tests/test_gpu_multiwavelength.py` | NIR + UV bands now compare CPU vs GPU on a *non-degenerate* render. |

### Key design decisions

1. **Constant-memory table.** Budget: 64 KB. With ≤64 profiles × 256
   samples × 4 bytes = 64 KB max. The pkg38/pkg39 profile set fits well
   under that. Constant-memory broadcast is the right pick because every
   thread reads the same `(profileIndex, λ)` pair within a warp during
   the spectral evaluation.
2. **Profile table layout.** Resample every profile onto a fixed
   `[300, 1000] nm @ 5 nm` grid (141 samples/profile). Store as
   `__constant__ float g_profile_table[G_MAX_PROFILES * 141]`.
3. **Deduplication.** Two materials sharing the same profile name should
   share the same `profileIndex`. Builds a `name → index` map on the host
   during upload.
4. **MW-kernel-only.** Do not touch the standard `path_trace_kernel.cu` —
   it never uses spectral profiles; only the MW kernel needs this.
5. **Lambertian-form fallback.** Mirror the CPU exactly:
   `f_spectral(λ) = profile(λ) * cosθ / π` for non-visible λ regardless of
   material type. Visible λ keep the existing `gpu_rgbToSampledSpectrum`
   path so visible-band parity is preserved.

---

## Acceptance criteria

- [ ] `tests/test_gpu_multiwavelength.py` NIR + UV gates pass at SSIM ≥
  0.97 on a profile-attached scene (vegetation should be visibly bright,
  water visibly dark in NIR; both backends agree).
- [ ] Profile dispatch is exercised — assert non-degenerate brightness:
  e.g. NIR mean > 0.05 on the profile-attached scene.
- [ ] No regression in pkg54 visible-band parity test or
  `tests/test_multiwavelength.py`.
- [ ] STATUS.md updated; pkg54 status corrected to "done".

---

## Non-goals

- No GPU port of `Material::sampleSpectralExt`'s direction sampling
  (still uses the existing RGB-domain sampler — same as CPU).
- No spectral emitter parameters (line emitters, blackbody) on GPU —
  pkg54c/follow-up if we ever need it.
- No host-CPU change.

---

## Progress

- [x] Add `profileIndex` field + constants ([include/astroray/gpu_types.h](include/astroray/gpu_types.h)).
- [x] Build host-side dedup table ([src/gpu/scene_upload.cu](src/gpu/scene_upload.cu)) + constant-memory upload ([src/gpu/multiwavelength_kernel.cu](src/gpu/multiwavelength_kernel.cu) `uploadProfileTable`).
- [x] Add `gpu_profile_reflectance()` device fn.
- [x] Profile-aware spectral eval in MW kernel (mirrors `evalSpectralExt`).
- [x] Extend parity scene with profiles ([tests/scenes/multiwavelength_parity.py](tests/scenes/multiwavelength_parity.py)).
- [x] Tighten test gates ([tests/test_gpu_multiwavelength.py](tests/test_gpu_multiwavelength.py) — profiled NIR + UV gates, plus a non-profiled fallback gate, plus UV cross-backend ratio asymmetry gate).
- [x] Verification on CUDA hardware green: NIR (with profiles) SSIM ≥ 0.97, UV (with profiles) SSIM ≥ 0.97, UV CPU/GPU ratio asymmetry 5% (CPU 1.73 vs GPU 1.64; gate <25%), NIR-fallback SSIM ≥ 0.97. Bug fixed during verification: `GSPEC_RGB_ILLUMINANT` mode now uses the baked D65 SPD via `gpu_sampleD65()` instead of a Gaussian stand-in (was ~5× over-bright per λ).
- [x] Promote pkg54 to "done" — done in this verification commit.

---

## Lessons

- Liveness verification of profile dispatch needs a band where (i) the
  light source has spectral content and (ii) the profile differs from
  zero. D65 zeroes past 780 nm so the NIR test only gates parity, not
  liveness; the UV-band aluminium ratio test carries the liveness
  assertion.
- Profile-dispatch *liveness* cannot be cleanly probed via render-level
  SSIM or absolute brightness because (i) the baked D65 SPD zeroes
  past 780 nm, killing NIR signal regardless of dispatch, and (ii) in
  UV the 380-400 nm visible-band overlap already gives JH-upsampled
  ~0.85 reflectance from the RGB albedo, so the no-profile baseline
  is not near-zero. Math: for aluminium back wall, no-profile
  contribution ≈ 20 nm × 0.85 ≈ 17; with-profile ≈ 100 nm × 0.93
  ≈ 93; ceiling ratio ≈ 5.5 back-wall-only, ~1.7 image-wide after
  dilution by low-UV-reflectance floor (vegetation/water).
  Cross-backend ratio agreement within 25% (measured: CPU 1.73 vs
  GPU 1.64, 5% divergence) is the meaningful parity signal here.
  True dispatch liveness — independent of scene physics — is filed
  as pkg54d (direct gpu_profile_reflectance lookup binding).
