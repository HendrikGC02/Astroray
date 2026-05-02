# pkg29 — Spectral Dielectric Prism Validation

**Pillar:** 2 / 5 follow-up  
**Track:** A  
**Status:** implemented
**Estimated effort:** 2-3 sessions (~9 h)
**Depends on:** pkg30, pkg31

---

## Goal

**Before:** the spectral path tracer transports spectral radiance, but glass
and transparent objects still sample directions through the RGB-era
`Material::sample()` API. A prism cannot spread white light into a rainbow
because all wavelengths refract along the same direction.

**After:** dielectric/glass sampling is wavelength-aware. A glass-prism scene
under white illumination renders visible angular color separation, and a test
asserts non-zero red/green/blue spread or verifies the saved render is not
monochrome.

---

## Context

This is not part of Pillar 3 light transport. It is the missing spectral
material work needed for the prism/rainbow acceptance goal that was deferred
from pkg11/pkg13. NRC and ReSTIR can improve sampling, but neither can create
chromatic dispersion without wavelength-dependent refraction.

---

## Reference

- `.astroray_plan/docs/spectral-core.md` dispersion note
- `.astroray_plan/packages/pkg11-spectral-path-tracer.md` deferred prism item
- `.astroray_plan/packages/pkg13-spectral-materials.md` dielectric deferral
- Current implementation: `plugins/materials/dielectric.cpp`

---

## Specification

### Files created

| File | Purpose |
|---|---|
| `tests/test_spectral_prism.py` | Prism dispersion validation, initially small and deterministic. |
| `tests/scenes/prism_reference.py` | Shared scene builder for a triangular glass prism, narrow white light, and screen/catcher. |

### Files modified

| File | What changes |
|---|---|
| `.astroray_plan/docs/STATUS.md` | Mark pkg29 and its prerequisites implemented. |
| `.astroray_plan/packages/pkg29-spectral-dielectric-prism.md` | Completion record. |

### Acceptance criteria

- [x] Transparent/glass objects render through the spectral path tracer without
      the current incorrect same-direction-per-wavelength behavior.
- [x] A prism scene produces visible color separation in a saved render.
- [x] A deterministic test verifies non-zero wavelength/color exit spread.
- [x] Existing spectral material tests still pass.
- [x] The default non-dispersive glass path remains compatible with existing
      scenes and Python material creation.

---

## Non-goals

- Do not make NRC responsible for prism dispersion.
- Do not require CUDA.
- Do not attempt caustic-perfect convergence; the first test can be low
  resolution and structural.

---

## Completion Notes

pkg30 and pkg31 supplied the required spectral BSDF hook and Sellmeier
dielectric sampling. pkg29 adds the prism validation layer: a closed triangular
BK7 prism, structured target plane, saved render outputs, and a deterministic
red/blue centroid-spread check against flat-IOR glass.

Generated visual artifacts:

- `test_results/pkg29_flat_prism.png`
- `test_results/pkg29_bk7_prism.png`
- `test_results/pkg29_dispersive_prism.png`
