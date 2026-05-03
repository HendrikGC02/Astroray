# pkg35 — Spectral GPU Material Kernels

**Pillar:** 2/5 bridge
**Track:** A
**Status:** done
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg14, pkg34

---

## Goal

**Before:** The CPU path tracer is spectral-first, while the CUDA material
layer is still mostly RGB-shaped. GPU renders are fast, but they cannot
faithfully represent spectral-only features such as Sellmeier dispersion
or narrowband emitters.

**After:** The CUDA material path carries sampled wavelengths through
core BSDF and emitter evaluation for the standard material set:
Lambertian, metal, dielectric/glass, diffuse light/emissive, and Disney.
CPU/GPU reference renders agree within tolerance for non-dispersive
materials, and spectral GPU limitations are explicit.

---

## Context

Astroray's visual-quality target is spectral fidelity with modern GPU
performance. The current renderer has both pieces, but not fully in the
same backend. This package closes that gap for the core material set
before more astrophysical spectral emitters arrive.

---

## Reference

- `include/astroray/spectrum.h`
- `include/astroray/gpu_materials.h`
- `include/astroray/gpu_types.h`
- `src/gpu/path_trace_kernel.cu`
- `plugins/materials/dielectric.cpp`
- `plugins/materials/line_emitter.cpp`
- `plugins/materials/blackbody.cpp`

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | Add sampled-wavelength payloads or compact spectral material params needed by CUDA kernels. |
| `include/astroray/gpu_materials.h` | Add spectral eval/sample/emission variants for core materials. |
| `src/gpu/path_trace_kernel.cu` | Accumulate sampled spectra/XYZ consistently with CPU spectral path tracer. |
| `src/gpu/scene_upload.cu` | Upload spectral params such as Sellmeier coefficients and emitter spectra where supported. |
| `tests/` | Add CPU/GPU spectral parity tests for the core set. |

---

## Acceptance criteria

- [x] CPU and GPU contact-sheet renders match within documented
      tolerances for core non-dispersive materials.
- [x] GPU dielectric can represent at least flat IOR and the capability
      system reports whether Sellmeier dispersion is supported.
- [x] Narrowband/blackbody emitters have either spectral GPU support or
      explicit CPU-only capability metadata.

---

## Completion Notes

- Added compact CUDA `GSampledWavelengths` / `GSampledSpectrum` payloads and
  spectral material dispatch helpers for core RGB-derived GPU materials.
- The CUDA path now samples wavelengths per path and carries spectral BSDF and
  emission payloads alongside the existing linear-RGB framebuffer path.
- Added `gpu_spectral` capability metadata in C++/Python and contact-sheet CSV
  output.
- Flat-IOR dielectric/glass reports spectral GPU support. Sellmeier dispersion
  remains explicit CPU-only because GPU refraction still needs
  wavelength-dependent direction splitting/termination.
- Narrowband line/laser and blackbody emitters remain explicit CPU-only until
  dedicated spectral emitter parameter upload is implemented.
- Validation: focused CUDA build succeeded; `tests/test_spectral_gpu_materials.py`,
  `tests/test_material_backend_capabilities.py`, and the legacy CPU/GPU render
  parity test passed against `build_tcnn/Release`.

---

## Non-goals

- Do not implement arbitrary material graphs; pkg36 owns shared closure
  composition.
- Do not require all Pillar 4 volumetric emission plugins to be GPU-ready
  in this package.
