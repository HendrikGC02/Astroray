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
- 2026-09-22: Codex Terra review defects applied (planning session).
- 2026-09-22: Astra turn-4 sign-off discrepancies closed (planning session).

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
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Averages the 4 spectral samples at `:127-137` then `r.color = Vec3(L, L, L)` before XYZ/RGB conversion. Write the pre-display scalar `Q_band` (defined in Phase 0) into a separate raw-plane slot at that point — before XYZ/RGB conversion, tone mapping, denoising, colourmaps, gamma, or clamping; the display `r.color` path is unchanged. |
| `plugins/passes/colourmap_output.cpp` | Reads the colour, applies Reinhard tone-mapping, then the named colourmap overwrites the colour at `:77`; the display path stays independent of the raw channel and never reads or writes the raw plane. |
| `blender_addon/__init__.py` | Band setup at `:1216-1226`; colourmap opt-in for non-visible renders at `:1255-1256`; no raw band pass exists at `:1070`. Expose the raw plane and its unit/convention metadata. |
| `src/io/exr_writer.h` | Scoped to Cryptomatte at `:1`, but already has named float channels and string headers that may be reusable. Add the raw-band export plane as named float channel(s) with unit and provenance string headers. |

### Key design decisions

Reuse existing pass, EXR, and band-render test machinery.

#### Phase 0 (mandatory)

Prove the existing average-vs-integral semantics, normalization, and backend
support; pin the honest schema and the exported estimator. The exported
estimator is the relative band scalar

$$Q_\mathrm{band} = \frac{1}{N}\sum_{i=1}^{N} L(\lambda_i),$$

where \(L(\lambda_i)\) is the per-wavelength radiance scalar accumulated for
the \(N\) uniform wavelength samples \(\lambda_i\) spanning the band interval
\([\lambda_\mathrm{lo}, \lambda_\mathrm{hi}]\) in nanometres. \(Q_\mathrm{band}\)
is a **relative scalar**: dimensionless in the current pipeline and carrying
physical radiance dimension only after the Phase 1 unit contract and the
Phase 2 normalisation bridge. The
band interval and \(N\) are recorded in metadata. Then: a separate float
raw-relative-band channel; metadata for band bounds, quantity, normalization,
build, backend, seed, samples, plus explicitly-unavailable provenance; the
display path stays independent of the raw channel.

#### Phase 1

Phase 1 is the prerequisite for every quantitative Stage 2 output
(stage-plan-2026-09-22.md Stage 1c); Phase 2 is the Stage 3 bridge.

Implements the reviewed minimal pass/export boundary. The raw plane is a
separate float framebuffer/export plane populated with the integrator's
scalar \(Q_\mathrm{band}\) at the moment it is computed (immediately after the
4-sample average), before XYZ/RGB conversion, tone mapping, denoising,
colourmap application, gamma, or clamping. The display colour path must never
read the raw plane, and the raw plane must never receive display-transformed
values.

Phase 1 also carries the unit and emission contracts that every quantitative
output depends on:

- Scene-length unit: one Blender unit = one metre, i.e. a conversion
  \(u_\mathrm{m/BU} = 1.0\) (metres per Blender unit); `scene_unit = "metre"`,
  declared and stored in provenance (frozen 2026-09-22, lead may adjust).
- Calibrated emissivity/source scale: the relative scalar is mapped to physical
  per-wavelength spectral radiance by
  \(I_{\lambda,\mathrm{SI}} = u_\mathrm{m/BU}\,C_j\,Q_\mathrm{band}\), where
  \(u_\mathrm{m/BU}\) is metres per Blender unit (m/BU), \(C_j\) is the
  calibrated emissivity constant (W m⁻³ sr⁻¹ nm⁻¹; default 1.0, frozen
  2026-09-22, lead may adjust) and \(Q_\mathrm{band}\) is the dimensionless
  relative scalar; \(I_{\lambda,\mathrm{SI}}\) is in W m⁻² sr⁻¹ nm⁻¹. This is
  the only dimensional conversion applied to the raw scalar.
- Emissivity-to-radiance: emission-only radiative transfer gives
  \(I = \int j\,ds\), where \(j\) is emissivity (radiance per unit length,
  W m⁻³ sr⁻¹ nm⁻¹) and \(I\) is radiance (Rybicki & Lightman, *Radiative
  Processes in Astrophysics*, 1979, §1.2). The path length \(ds\) is in scene
  units, converted to metres by \(u_\mathrm{m/BU}\), and the solid-angle
  convention (radiance per unit projected solid angle, steradian) is stated
  explicitly.

The analytic acceptance checks for these contracts live in Phase 1:

- A homogeneous slab of emissivity \(j\) and thickness \(L\) yields
  \(I = jL\) within 0.5 %.
- A known relative scalar \(Q_\mathrm{band}\) with declared \(u_\mathrm{m/BU}\)
  and \(C_j\) yields \(I_{\lambda,\mathrm{SI}} = u_\mathrm{m/BU}\,C_j\,
  Q_\mathrm{band}\) within 0.5 %.
- A unit round-trip test confirms `scene_unit` survives write/read unchanged.

#### Phase 2

Phase 2 is the Stage 3 bridge and keeps only the observer-pixel solid angle and
the physical radiance normalisation / detector conversion:

- Observer-pixel solid angle: pinhole convention
  \(\Omega_\mathrm{pix} = (w_\mathrm{pix}\,h_\mathrm{pix}) / f^2\)
  (small-angle approximation, steradian), with pixel size \(w_\mathrm{pix},
  h_\mathrm{pix}\) and focal length \(f\) in metres (scene units converted by
  \(u_\mathrm{m/BU}\); frozen 2026-09-22, lead may adjust).
- Physical radiance units and detector conversion: per-wavelength spectral
  radiance \(I_{\lambda,\mathrm{SI}}\) (W m⁻² sr⁻¹ nm⁻¹) comes from the Phase 1
  calibrated scale, and band-integrated radiance is
  \(I_\mathrm{band} = \Delta\lambda_\mathrm{nm}\,I_{\lambda,\mathrm{SI}}\)
  (W m⁻² sr⁻¹) with \(\Delta\lambda_\mathrm{nm} = \lambda_\mathrm{hi} -
  \lambda_\mathrm{lo}\) in nanometres. Where the output is intended as pixel
  irradiance, \(E_\mathrm{pix} = I_\mathrm{band}\,\Omega_\mathrm{pix}\)
  (W m⁻²); the exported plane is labelled as either radiance \(I_\mathrm{band}\)
  or pixel irradiance \(E_\mathrm{pix}\), never both.
- Per-output provenance (written alongside every exported plane): the
  normalization inputs and conversion formula below are mandatory, not implied
  by the display metadata:
  - metres-per-scene-unit \(u_\mathrm{m/BU}\);
  - emissivity calibration constant \(C_j\) with its units
    (W m⁻³ sr⁻¹ nm⁻¹);
  - wavelength estimator and PDF (uniform over \([\lambda_\mathrm{lo},
    \lambda_\mathrm{hi}]\), \(p(\lambda_i) = 1/N\), yielding
    \(Q_\mathrm{band} = \frac{1}{N}\sum_i L(\lambda_i)\));
  - band width \(\Delta\lambda_\mathrm{nm}\) and bounds
    \([\lambda_\mathrm{lo}, \lambda_\mathrm{hi}]\);
  - per-pixel \(\Omega_\mathrm{pix}\) (sr);
  - conversion formula identifier and version;
  - a flag stating whether the plane is band radiance \(I_\mathrm{band}\) or
    pixel irradiance \(E_\mathrm{pix}\).

---

## Acceptance criteria

All implementation gates are UNRUN.

- [ ] **(Phase 1)** Scene-length unit contract holds and round-trips: a unit
      round-trip test confirms `scene_unit = "metre"` (one Blender unit = one
      metre) is stored in and read back from provenance unchanged.
- [ ] **(Phase 1)** Emissivity-to-radiance analytic check passes: a homogeneous
      slab of emissivity \(j\) and thickness \(L\) yields
      \(I = \int j\,ds = jL\) within 0.5 %.
- [ ] **(Phase 1)** Calibrated-scale check passes: a known relative scalar
      \(Q_\mathrm{band}\) with declared \(u_\mathrm{m/BU}\) and \(C_j\) yields
      \(I_{\lambda,\mathrm{SI}} = u_\mathrm{m/BU}\,C_j\,Q_\mathrm{band}\) within
      0.5 %.
- [ ] **(Phase 1)** Flat-spectrum/exposure/bandwidth analytic checks pass
      WITHOUT an accidental average-to-integral switch, and confirm the
      exported estimator is \(Q_\mathrm{band} = \frac{1}{N}\sum_i L(\lambda_i)\).
- [ ] **(Phase 1)** Metadata assertions confirm the declared Phase 1 units and
      conventions (`scene_unit`, \(u_\mathrm{m/BU}\), \(C_j\) and units, band
      interval in nm, estimator/PDF) match the produced output.
- [ ] **(Phase 2)** Analytic fixtures prove each Phase 2 bridge component:
      observer-pixel solid angle \(\Omega_\mathrm{pix}\), the calibrated
      conversion \(I_{\lambda,\mathrm{SI}} = u_\mathrm{m/BU}\,C_j\,Q_\mathrm{band}\),
      and band integration \(I_\mathrm{band} = \Delta\lambda_\mathrm{nm}
      I_{\lambda,\mathrm{SI}}\) (and \(E_\mathrm{pix} = I_\mathrm{band}
      \Omega_\mathrm{pix}\) when irradiance is exported).
- [ ] **(Phase 2)** Per-output metadata assertions confirm every mandatory
      provenance field is present and matches the produced output:
      \(u_\mathrm{m/BU}\), \(C_j\) and units, wavelength estimator/PDF,
      \(\Delta\lambda_\mathrm{nm}\), per-pixel \(\Omega_\mathrm{pix}\),
      conversion formula/version, and the radiance-vs-irradiance plane flag.
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
- No detector, exposure, or photon-count calibration. The Phase 1 unit and
  emissivity contracts and the Phase 2 physical-radiance normalisation bridge
  (observer-pixel solid angle, radiance units) are required, not non-goals.
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
