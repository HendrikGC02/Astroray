# pkg243 — Raw relative band output and honest provenance

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** pkg125, pkg39, pkg54, pkg58

---

## Goal

**Before:** the existing relative raw band quantity is not preserved before any display transform and is not exposed with honest provenance; current raw-channel backend support is unverified. **After:** the existing relative raw band quantity is preserved BEFORE any display transform and exposed with honest provenance. This filing claims no calibrated SI units or GPU support and does not activate pkg133/Pillar 4.

---

## Context

This package serves Pillar 5 (Blender/DCC output) and Pillar 2 (spectral core). It depends on pkg125, pkg39, pkg54, and pkg58, which provide DONE band/multiwavelength coverage:

- pkg39 (multiwavelength render) — multi-band CPU rendering baseline.
- pkg54 (GPU multiwavelength integrator) — CUDA megakernel mirror.
- pkg58 (spectral profile UX) — band/profile user-facing controls.
- pkg125 (CPU path-tracer band awareness) — band-aware transport on the CPU
  path.

pkg133 (SRF/spectral sensors) owns SRF/instrument channels and is
Pillar-4-adjacent; pkg130 (light groups) and pkg134 (light path
expressions) own emission decomposition and LPEs. pkg133, pkg130, and
pkg134 are scope exclusions, not prerequisites; none are activated or
duplicated here. No Pillar 4 activation. Detailed architect review is
required before implementation; estimated effort is TBD at that review.

---

## Evidence

- `plugins/integrators/multiwavelength_path_tracer.cpp:127-137` — averages the
  4 spectral samples ("Simple mean of the 4 spectral samples") then
  `r.color = Vec3(L, L, L)` before XYZ/RGB conversion.
- `plugins/passes/colourmap_output.cpp:77` — reads the colour, applies
  Reinhard tone-mapping, then the named colourmap overwrites the colour.
- `blender_addon/__init__.py:1216-1226` — band setup; `:1255-1256` — colourmap
  opt-in for non-visible renders; `:1070` — no raw band pass exists.
- `src/io/exr_writer.h:1` — scoped to Cryptomatte, but already has named float
  channels and string headers that may be reusable.

---

## Reference

- Coverage specs: [pkg39](pkg39-multiwavelength-render.md),
  [pkg54](pkg54-gpu-multiwavelength-integrator.md),
  [pkg58](pkg58-spectral-profile-ux.md),
  [pkg125](pkg125-cpu-path-tracer-band-awareness.md).
- Excluded scopes: [pkg133](pkg133-srf-spectral-sensors.md),
  [pkg130](pkg130-light-groups-emission-decomposition.md),
  [pkg134](pkg134-light-path-expressions.md).

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Averages the 4 spectral samples at `:127-137` then `r.color = Vec3(L, L, L)` before XYZ/RGB conversion; the raw band quantity must be preserved before any display transform. |
| `plugins/passes/colourmap_output.cpp` | Reads the colour, applies Reinhard tone-mapping, then the named colourmap overwrites the colour at `:77`; the display path stays independent of the raw channel. |
| `blender_addon/__init__.py` | Band setup at `:1216-1226`; colourmap opt-in for non-visible renders at `:1255-1256`; no raw band pass exists at `:1070`. |
| `src/io/exr_writer.h` | Scoped to Cryptomatte at `:1`, but already has named float channels and string headers that may be reusable. |

### Key design decisions

Reuse existing pass, EXR, and band-render test machinery.

#### Phase 0 (mandatory)

Prove the existing average-vs-integral semantics, normalization, and backend
support; pin the honest schema. Then: a separate float raw-relative-band
channel; metadata for band bounds, quantity, normalization, build, backend,
seed, samples, plus explicitly-unavailable provenance; the display path stays
independent of the raw channel.

#### Phase 1

Implements the reviewed minimal pass/export boundary.

#### Phase 2

Checks round-trip and backend behavior.

---

## Acceptance criteria

All implementation gates are UNRUN.

- [ ] Flat-spectrum/exposure/bandwidth analytic checks pass WITHOUT an
      accidental average-to-integral switch.
- [ ] Raw float > 1.0 round-trips through the output path.
- [ ] Colourmap/denoise/display invariance: display transforms do not touch
      the raw channel.
- [ ] CPU/GPU actual support measured, or an explicit honest unsupported
      policy.
- [ ] Raw and display visuals saved and Astra-reviewed.
- [ ] Spectral ABI review for any native signature change; fresh native build
      identity if touched; caller/binding sweep; GPU lock; at most two isolated
      implementation worktrees; independent Claude sign-off.

---

## Non-goals

- No wavelength-sampling redesign.
- No calibrated radiance or photon counts.
- No telescope/GR/pkg51/pkg133 unpause.
- Risk: XYZ/RGB conversion can obscure the original scalar's meaning; existing
  band averages must not be mislabeled as integrals, calibrated radiance, or
  photon counts.
- Risk: metadata and unsupported-backend claims must match the actual output.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
