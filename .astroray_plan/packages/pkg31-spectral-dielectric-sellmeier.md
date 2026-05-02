# pkg31 — Spectral Dielectric with Sellmeier Dispersion

**Pillar:** 2 follow-up  
**Track:** A  
**Status:** implemented
**Estimated effort:** 1–2 sessions (~6 h)  
**Depends on:** pkg30  
**Blocks:** pkg29

---

## Goal

**Before:** `DielectricPlugin` uses a single float `ior_` for all wavelengths.
`sampleSpectral()` inherits the default from pkg30, which delegates to
`sample()` — all wavelengths refract along the same direction.

**After:** `DielectricPlugin` overrides `sampleSpectral()` with Sellmeier-equation
IOR lookup. On refraction events, secondary wavelengths are terminated via
`lambdas.terminateSecondary()`, and the primary wavelength's IOR drives the
refracted direction. A `"dispersive"` ParamDict flag controls whether
dispersion is active (default: false for backward compat, true when
`"sellmeier"` coefficients are provided).

---

## Reference

- Sellmeier equation: `n²(λ) = 1 + B₁λ²/(λ²−C₁) + B₂λ²/(λ²−C₂) + B₃λ²/(λ²−C₃)`
- λ in micrometers.
- Common presets: BK7, fused silica, flint glass (SF11), diamond.
- PBRT-v4 `DielectricBxDF` for reference on `terminateSecondary()` usage.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/dielectric.cpp` | Add Sellmeier IOR function. Override `sampleSpectral()`: compute IOR for primary wavelength, refract using that IOR, call `lambdas.terminateSecondary()` on refraction, return `BSDFSampleSpectral` with per-λ throughput. Add `"dispersive"` bool and `"sellmeier_b"/"sellmeier_c"` Vec3 params to constructor. |

### Files to create

| File | Purpose |
|---|---|
| `data/spectra/glass_presets.json` | Named Sellmeier coefficient sets: `bk7`, `fused_silica`, `flint_sf11`, `diamond`. |

### Sellmeier IOR function

```cpp
static float sellmeierIOR(float lambda_nm, Vec3 B, Vec3 C) {
    float l2 = (lambda_nm * 1e-3f) * (lambda_nm * 1e-3f); // nm → μm
    float n2 = 1.0f + B.x*l2/(l2 - C.x) + B.y*l2/(l2 - C.y) + B.z*l2/(l2 - C.z);
    return std::sqrt(std::max(1.0f, n2));
}
```

### `sampleSpectral()` override (dispersive path)

On refraction (not TIR, not Fresnel-reflected):
1. Compute `ior = sellmeierIOR(lambdas[0], B_, C_)` for the primary wavelength.
2. Refract `wo` using this single IOR (same Snell's law as current code).
3. Call `lambdas.terminateSecondary()` — only the primary wavelength survives.
4. Return `BSDFSampleSpectral` with `f_spectral` set to `SampledSpectrum(eta*eta)` for
   the primary sample (secondaries zeroed by termination).

On reflection (TIR or Fresnel choice): no dispersion, all wavelengths survive.

### Backward compatibility

- Default `ior` param still works (`dispersive=false`, flat IOR).
- When `dispersive=false`, `sampleSpectral()` delegates to the base default
  (which calls `sample()` with flat IOR).
- Python: `r.add_sphere(..., material="dielectric", ior=1.5)` unchanged.
- Python dispersive: `r.add_sphere(..., material="dielectric", sellmeier_preset="bk7")`.

### Acceptance criteria

- [x] Non-dispersive glass scenes render identically to before pkg31.
- [x] A dispersive glass sphere under white light shows wavelength-dependent
      refraction angles (verified by rendering two renders: flat IOR vs Sellmeier,
      and checking pixel differences exist).
- [x] `terminateSecondary()` is called on dispersive refraction events.
- [x] All existing tests pass.
- [x] Preset loading works for at least `bk7`.

---

## Non-goals

- Do not implement the prism scene or prism validation test (that is pkg29).
- Do not modify the mirror plugin.
- Do not add CUDA-specific code.
