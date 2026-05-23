# pkg64-gpu-sellmeier-upload — GPU Sellmeier dispersion material support

**Pillar:** 1
**Track:** A
**Status:** open
**Estimated effort:** 1–1.5 weeks
**Depends on:** pkg64-gpu Phase 2 (PR #348) + Phase 3 (PR #350) — both merged. The CPU Sellmeier path tracer is the reference.
**Reference research:** Sellmeier 1871 dispersion equation (public domain); Cycles `intern/cycles/kernel/svm/closure_principled.h` wavelength-dependent IOR (Apache-2.0); PBRT-v4 `pbrt::DispersiveBSDF` (Apache-2.0).

---

## Why this package exists

pkg64-gpu Phase 3 (PR #350) shipped the GPU caustics toggle + three acceptance tests (prism receiver-energy, GPU↔CPU SSIM parity, no-regression). On the 2026-05-23 post-merge HW sweep, **three of those tests failed with the same error**:

```
RuntimeError: Material cannot be uploaded to GPU: Sellmeier dispersion
requires wavelength-dependent GPU refraction and remains CPU-only.
```

The blocker is `Material::uploadToGPU()` (or equivalent in `scene_upload.cu`) raising on any material that returns true from `isWavelengthDependent()` / `isSellmeier()`. The GPU material struct (`GMaterial` in `include/astroray/gpu_types.h`) carries a fixed `ior` scalar; it has no wavelength-indexed refraction path.

This package adds the wavelength-dependent refraction path on the GPU side so pkg64-gpu Phase 3's hardware gates can actually run on the prism scene.

---

## Goal

**Before:** GPU `GMaterial` has scalar `ior` + scalar `transmission`. `Material::uploadToGPU()` refuses to upload Sellmeier materials. pkg64-gpu Phase 3's GPU acceptance gates (prism receiver-energy ≥1.10×, PSNR floor delta ≥−0.5 dB, GPU↔CPU SSIM ≥0.97) cannot run.

**After:**

- `GMaterial` carries Sellmeier coefficients (B1, B2, B3, C1, C2, C3) or a packed dispersion descriptor.
- A device-callable `gpu_sellmeier_ior(coeffs, lambda_nm)` evaluates `n(λ)` per-wavelength in the closed-form Sellmeier equation.
- The GPU dielectric / glass closure paths read per-wavelength `ior` from the sampled spectral lambdas rather than the scalar.
- `scene_upload.cu` accepts and packs Sellmeier materials.
- The three deferred Phase 3 gate tests run end-to-end on RTX and pass at their pinned thresholds.

---

## Specification

### 1. `GMaterial` layout (`include/astroray/gpu_types.h`)

Add a packed `GDispersion` sub-struct (or 6 floats inline if MinGW alignment plays nicely — memory `mingw_large_struct_byval` says struct >32B passes by `const T&`; check the resulting size and pass-by-ref where needed):

```cpp
struct GDispersion {
    float b1, b2, b3;  // Sellmeier B coefficients
    float c1, c2, c3;  // Sellmeier C coefficients (μm²)
};

struct GMaterial {
    // ... existing fields ...
    GDispersion dispersion;       // populated when type == DIELECTRIC_DISPERSIVE
    bool        isDispersive;      // fast-path predicate
};
```

Cite the Sellmeier 1871 form in the comment:
`n²(λ) = 1 + B1·λ²/(λ²−C1) + B2·λ²/(λ²−C2) + B3·λ²/(λ²−C3)` with λ in μm.

### 2. Device-callable IOR evaluator

`include/astroray/gpu_dispersion.cuh` (new file):

```cpp
__device__ inline float gpu_sellmeier_ior(const GDispersion& d, float lambda_nm) {
    float lam_um = lambda_nm * 1e-3f;
    float l2 = lam_um * lam_um;
    float n2 = 1.0f
             + (d.b1 * l2) / (l2 - d.c1)
             + (d.b2 * l2) / (l2 - d.c2)
             + (d.b3 * l2) / (l2 - d.c3);
    return sqrtf(n2);
}
```

Cite Cycles `closure_principled.h` wavelength-dependent IOR — the exact same Sellmeier closed form is used there.

### 3. Update GPU dielectric BSDF

In `include/astroray/gpu_materials.h` / `gpu_bsdf.h` — wherever Fresnel + Snell are evaluated for dielectric / glass / dispersive closures — branch on `mat.isDispersive`:

```cpp
float ior = mat.isDispersive
    ? gpu_sellmeier_ior(mat.dispersion, wavelengths.lambda[hero])
    : mat.ior;
// ... Snell + Fresnel using `ior` instead of `mat.ior` ...
```

Hero-channel-only is fine for Session 1; full per-wavelength multi-IOR refraction (one ray per sampled lambda) is a Session 2 enhancement.

### 4. `scene_upload.cu` upload path

In the material-pack code that currently rejects Sellmeier:
- Detect `Material::isDispersive()` and populate `GMaterial::dispersion + .isDispersive=true`.
- Stop raising the upload RuntimeError; instead set the dispersive flag.

### 5. Tests

- `tests/test_gpu_sellmeier_ior.py` — unit test of the device evaluator at the standard BK7 lambdas (587.6 / 486.1 / 656.3 nm) matches Schott's tabulated n with rel-err ≤ 1e-4. Cite Schott BK7 datasheet.
- The three pkg64-gpu Phase 3 tests should now succeed on the first RTX run (`test_pkg64_gpu_cpu_parity_ssim`, `test_pkg64_gpu_phase3_prism_receiver_energy`, `test_pkg64_gpu_phase3_prism_psnr_floor`). The baselines they capture pin the hardware numbers in the spec Lessons.

---

## Acceptance criteria

- [ ] `gpu_sellmeier_ior` device function exists and unit-tests against Schott BK7 within 1e-4 rel-err.
- [ ] `scene_upload.cu` accepts Sellmeier materials without raising.
- [ ] pkg64-gpu Phase 3 prism receiver-energy gate runs on RTX and passes at ≥ 1.10×.
- [ ] pkg64-gpu Phase 3 PSNR floor gate runs and passes at ≥ −0.5 dB.
- [ ] pkg64-gpu Phase 3 GPU↔CPU SSIM parity gate runs and passes at ≥ 0.97.
- [ ] No regression on existing GPU dielectric tests (the scalar-IOR fast path must remain bit-identical).

---

## Non-goals

- Full per-wavelength refraction (4 separate rays per spectral sample). Defer to a Session 2 add-on; hero-channel-only is good enough to close the Phase 3 acceptance gates.
- Adding Cauchy or Conrady alternative dispersion forms. Sellmeier covers BK7 + the common Schott catalog scenes.
- Mesh-attached per-material dispersion overrides via the Blender addon. The pkg89 dedicated-materials path is the place; treat it as a future pkg.

---

## References

- Sellmeier 1871 — Annalen der Physik 219(11):272-282 (public domain via age).
- Cycles `intern/cycles/kernel/svm/closure_principled.h` wavelength-dependent IOR (Apache-2.0).
- PBRT-v4 `src/pbrt/bxdfs.h` `DielectricBxDF` (Apache-2.0).
- Schott BK7 optical glass datasheet (n at standard lambdas — for the unit test).
- pkg64-gpu Phase 3 PR #350: shipped the toggle + tests that need this to actually run.
- 2026-05-23 final HW sweep report (`.astroray_plan/docs/sweep-final-2026-05-23.md` if present, else the standup).
