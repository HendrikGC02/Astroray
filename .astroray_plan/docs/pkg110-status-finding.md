# pkg110 status + finding — BSDF-driven photon bounce (2026-05-30)

**Status: WORK IN PROGRESS, NOT merged.** Preserved on branch
`pkg110-bsdf-photon-bounce`. pkg109 (the kd-tree foundation) is merged; pkg110
builds on it. The general photon loop is implemented and **validated on a glass
sphere**, but the **prism rainbow `hue_spread` gate does not yet reproduce** under
the general loop, so it is not shippable as-is.

## What landed (validated)

- `plugins/integrators/light_tracer_caustic.cpp`: the hard-coded 2-face prism
  refraction is replaced by a **general BVH + `Material::sampleSpectral` photon
  loop** — at each transmissive surface the dielectric chooses reflect/refract by
  Fresnel and handles TIR, multi-bounce, and Sellmeier dispersion at the hero
  wavelength (`terminateSecondary`), so a photon traverses ANY glass shape. A
  general caster-bounds scan (`isCausticCaster()` + `boundingBox()`) replaces the
  triangle-only `gatherTriangleCasters`, so non-triangle casters (spheres, meshes)
  work. Deposits only on L S+ D paths (passed ≥1 caster) → no direct-light
  double-count.
- `benchmarks/reference_bank/scenes/glass-sphere-caustic/scene.py`: a primitive
  glass **sphere** (a non-triangle caster the old 2-face code could not handle) +
  collimated sun + floor. **VALIDATED:** 596k photons stored, a focused
  "burning-glass" caustic — peak luminance **0.79** vs floor median **0.016**
  (~48× concentration). This proves the general loop refracts enter→exit correctly
  through a solid (geometric normals + the dielectric's own enter/exit detection).
- `benchmarks/reference_bank/scenes/prism-bk7-collimated/scene.py`: converted from
  the old **non-solid 2-quad** prism to a **closed SOLID** triangular prism (8
  triangles, auto-oriented outward normals). Required because the general loop
  relies on consistent outward normals; the 2-quad hack only worked with the old
  explicit 2-face path (with the 2-quad geometry the general loop deposits ~23k
  scattered photons and the band collapses, hue 0.000).

## The blocker — prism hue_spread not reproduced

| geometry / loop | photons stored | hue_spread (gate 0.7) | bright_coverage (gate 0.5) |
|---|---|---|---|
| 2-quad + explicit 2-face (pkg109, on main) | (many) | **0.750** PASS | 0.615 PASS |
| 2-quad + general loop | 23k | 0.000 FAIL | — |
| solid prism + general loop, 3M photons | 130k | 0.603 FAIL | 0.766 PASS |
| solid prism + general loop, 9M photons | 391k | 0.523 FAIL | 0.744 PASS |

The band is continuous (coverage passes) and is in the right place, but the
`hue_spread` (red→violet diversity above a fixed 0.1 luminance threshold) is
0.52–0.60, below the 0.70 gate, and is **non-monotonic in photon count** (more
photons made it worse). The dispersion physics is identical (hero-λ Sellmeier in
`sampleSpectral`), so this is NOT a dispersion regression — it is that the general
loop's **deposited floor spectrum differs** from the explicit deterministic 2-face
deposit:

1. **Stochastic Fresnel vs weighted deposit.** The explicit path deposited
   `cmf(λ)·Fresnel_T` for every aperture-hit (deterministic). The general loop
   reflects-or-refracts by Fresnel *probability* and deposits unit-ish throughput —
   a different per-wavelength brightness distribution on the floor.
2. **Radiance η² in a power-transport loop.** `dielectric::refractSpectral` returns
   `f = tint·η²` (the radiance compression factor). For photon (power) transport
   this is the Veach non-symmetry; it cancels for an air→glass→air path but is
   formally wrong for power and perturbs intermediate weighting.
3. **Multi-face solid scatter.** Aperture photons that hit the bottom/end-cap
   faces refract off-band and are wasted, lowering useful band density.
4. **Auto-scale × fixed threshold.** `hue_spread` counts hues above a fixed 0.1
   luminance; the 95th-pct→boost auto-scale + a sparser band push mid-band
   wavelengths under threshold, shrinking the measured spread.

## Recommended next steps (next session)

- **Strip the radiance η² for power transport** in the photon loop (use the BSDF
  value without the `etaScale`, à la PBRT importance transport / `TransportMode`),
  so per-bounce throughput is energy-correct for photons.
- **Consider a Fresnel-weighted (non-stochastic) deposit** for the dedicated
  forward tracer — deposit `throughput·(1−Fresnel_R)` and always refract — to match
  the explicit path's deterministic spectrum density and reduce variance.
- **Restrict the emission aperture** to the slant faces (or accept the waste with a
  higher photon budget) so fewer photons scatter off the bottom/caps.
- **Re-tune `caustic_boost`** so the band peak comfortably clears the metric's 0.1
  luminance threshold across all wavelengths, then re-confirm hue_spread ≥ 0.7.
- **Finalize the glass-sphere acceptance gate** (a concentration-ratio test, e.g.
  ROI peak/median ≥ N) — the sphere already produces ~48× concentration; just needs
  a committed scene + pytest with a stable threshold.
- Owner decision: whether the prism gate's `hue_spread` ROI/threshold should be
  re-derived for the solid-prism scene, since the deposited spectrum legitimately
  differs from the explicit path.

## Key reusable finding

The general BSDF photon loop is **correct for solid glass** (sphere validated) but
is **incompatible with non-solid surface hacks** (the 2-quad "prism"): general
refraction needs a closed solid with consistent outward normals. A reproduction
gate built on a *spectral-spread metric over a deterministic special-case deposit*
(the prism `hue_spread`) is sensitive to the deposit-weighting details and does not
transfer for free to a stochastic general loop — reproducing the **physics** (the
band) is easy; reproducing the **exact metric value** needs deposit-weighting parity.
