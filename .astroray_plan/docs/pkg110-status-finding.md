# pkg110 status + finding — BSDF-driven photon bounce (2026-05-30)

> **RESOLVED — shipped via HYBRID auto-select (PR #397, owner-chosen).** The
> integrator routes flat prisms (caster triangles → exactly 2 planar faces) to the
> explicit 2-face refraction (clean rainbow, gate unchanged) and any other caster
> (curved/solid: sphere/lens/mesh) to the general deterministic BVH refraction loop
> (glass sphere focuses a caustic). **Key catch:** the owner first chose "re-derive
> the gate", but executing it exposed that a low-K general loop on a SOLID prism
> PASSES both numeric gates (hue 0.72, cov 0.80) while rendering salt-and-pepper
> NOISE — caught only by a VISUAL check, after which the owner switched to the
> hybrid. **Lesson: always visually verify caustic/dispersion renders; hue_spread +
> bright_coverage can both pass on dense chromatic noise.** The history below is the
> investigation that led here.


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

## Update 2026-05-30 — deterministic loop tried; root cause confirmed

The latest WIP (branch **`pkg110-photon-bounce`**, supersedes the stochastic
`pkg110-bsdf-photon-bounce`) replaces `sampleSpectral` with a **deterministic**
loop: Snell refraction (`iorAt(λ)`, enter/exit from the sign of the geometric
normal) + Schlick-Fresnel-weighted throughput + TIR-reflect; always-refract (no
stochastic reflection), so the deposit is dense and noise-free. Results:

| loop × prism geometry | photons | hue_spread (0.70) | bright_coverage (0.50) |
|---|---|---|---|
| deterministic × 2-quad prism | **0** | 0.000 | 0.000 |
| deterministic × solid prism (9M) | 487k | **0.475** | 0.741 |
| (for reference) stochastic × solid prism | 130–391k | 0.52–0.60 | 0.74–0.77 |

- **Glass sphere (deterministic): peak luminance 0.673, ~41× concentration, a
  focused spot (<0.02 % of pixels > 0.3).** Gate `tests/test_glass_sphere_caustic.py`
  PASSES. The deterministic refraction is **proven correct** (sphere focuses).
- **2-quad prism still gives 0 deposits** with the general loop (the old explicit
  code's `nearestCaster` deposited only clean 2-refraction photons; `bvh->hit`
  through 2 thin coplanar quads doesn't reconstruct that path). Needs a closed solid.
- **Solid prism + deterministic still gives hue 0.475** — and density does NOT help
  (more photons made the stochastic version *worse*). **Confirmed root cause: the
  prism gate relies on the PURITY of the exactly-2-slant-face path.** A general loop
  on a closed solid also captures bottom/end-cap-scattered photons that land in the
  ROI and desaturate it. There is no deposit-weighting tweak that recovers 0.75 while
  staying general.

**Conclusion — needs an OWNER DECISION, not a tuning fix.** The general loop is the
right design and is validated for focusing casters (the sphere). The prism rainbow
`hue_spread ≥ 0.70` regression conflicts with generalization. Options for the owner:
1. **Re-derive the prism gate for the general loop** — measure the solid-prism band
   with the general loop, pick an ROI on the actual band, and set a hue threshold
   that the general (impure) deposit can meet (with `bright_coverage` still guarding
   continuity). The thresholds change because the *scene/algorithm* legitimately
   changed, not to fit a number.
2. **Keep a special-case flat-caster path** — detect coplanar/flat casters (a prism)
   and use the explicit 2-slant-face deposit for them, general loop for the rest.
   Pragmatic but reintroduces a special case the spec wanted gone.
3. **Accept the sphere/focusing-caster gate as pkg110's acceptance** and move the
   prism to a separate "flat-caster dispersion" gate, since a flat prism is a
   non-focusing special case (the original pkg106 rationale).

Recommended: option 1 (re-derive) + option 3 framing. The shippable core today is
the deterministic general loop + the glass-sphere caustic gate (both on
`pkg110-photon-bounce`).

### Rebase caveat (float-param landed after this branch)

`pkg110-photon-bounce` was cut before PR #396 (integrator float-param). main now
reads `caustic_boost` via `ParamDict::getNumber` (int OR float). When this branch
rebases onto main:
- Resolve the `plugins/integrators/light_tracer_caustic.cpp` constructor conflict
  in favour of main's `boost_(p.getNumber("caustic_boost", 1.0f))`.
- The glass-sphere scene sets `caustic_boost = 14` via the **int** route; under
  `getNumber` that reads as `14.0` (10× too bright; the old int×0.1 hack is gone).
  Change it to `r.set_integrator_param_float("caustic_boost", 1.4)` and re-confirm
  `tests/test_glass_sphere_caustic.py` (calibrated at boost 1.4 → peak 0.673).
