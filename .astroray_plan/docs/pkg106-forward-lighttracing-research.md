# pkg106 — Forward light-tracing for prism rainbow caustics (2026-05-29)

## Summary

pkg106's goal was a clean rainbow caustic from a triangulated equilateral glass
prism (acceptance: `hue_spread >= 0.7` in the rainbow ROI, a continuous band, not
salt-and-pepper chromatic noise). The plan of record was camera-side SMS/MNEE.
That was implemented and unit-tested, but it does **not** produce a clean band on
a flat prism. The rainbow now ships via a **forward light-tracer**
(`plugins/integrators/light_tracer_caustic.cpp`), which gives a smooth continuous
spectrum. This note records both the MNEE work (kept — it is correct and useful
for focusing casters) and why forward tracing is the right tool for a prism.

## Papers

- Arvo, "Backward Ray Tracing", SIGGRAPH 1986 Developments in Ray Tracing course
  notes. Forward light-particle transport for caustics (trace from the light,
  deposit on diffuse surfaces).
- Jensen, "Global Illumination using Photon Maps", EGWR 1996. Diffuse-surface
  photon deposition + density estimation. Here: a 2D grid on the planar receiver
  (bilinear splat + gather) rather than a kd-tree.
- (MNEE foundation, kept) Jakob & Marschner 2012 "Manifold Exploration"; Hanika,
  Droske, Manakov 2015 "Manifold Next Event Estimation" EGSR, DOI 10.1111/cgf.12681;
  Zeltner, Georgiev, Jakob 2020 "Specular Manifold Sampling" SIGGRAPH,
  DOI 10.1145/3386569.3392408.

## Reference implementation

- **Cycles** `intern/cycles/kernel/integrator/mnee.h` (Apache-2.0, blender/blender
  @main, retrieved 2026-05-29) — `mnee_compute_transfer_matrix` (l.663-731). Both
  the positional and the `light_fixed_direction` (collimated) branches were
  ported into `include/astroray/manifold/manifold_chain.h::chainGeometryTerm` and
  validated (see "What we reproduce"). Apache-2.0 → MIT-compatible.
- Forward light-tracer: own implementation citing Arvo 1986 / Jensen 1996; the
  per-wavelength refraction/Fresnel mirrors `plugins/materials/dielectric.cpp`;
  CIE deposit uses `spectrum.h::cieCmf1964_10deg`.

## What we reproduce (and validated)

- MNEE generalized geometry term (transfer matrix), positional branch — validated
  analytic vs brute-force finite-difference (re-solving the manifold under a light
  perturbation) to ~7.6e-11. `tests/test_mnee_geometry_term.py`.
- MNEE fixed-direction (collimated) branch — validated vs the positional limit
  `dx1_area * D^2 -> dx1_solidangle` to ~2e-4.
- Caster-aimed seed (`mesh_caustic.h::seedChainTowardCaster`) + the normal-
  orientation convention (orient toward x0) — required for the manifold Newton to
  converge on a deviating prism (the straight x0->light seed misses the prism).

## Key finding — why camera-side MNEE fails on a flat prism

1. **No focusing.** A flat prism deviates but does not focus, so there is no
   caustic singularity for the MNEE geometry term to concentrate. The term is
   smooth (G clamps uniformly); localization comes only from path validity.
2. **Seed/deviation mismatch.** The straight x0->light seed only crosses the
   prism for near-zero deviation; a real prism bends the path ~38-52deg, so for
   the receiver points the dispersed beam actually illuminates, the straight seed
   misses the prism. A caster-aimed seed fixes finding the path, but:
3. **Spatial basin chaos.** The camera-side specular connection is a near-delta
   whose Newton basin is spatially chaotic; ~half of band pixels deterministically
   fail to converge -> salt-and-pepper that does NOT reduce with samples (verified
   invariant 64->16384 spp, Newton iters 30->250, sun angular size, resolution).
4. **Weak dispersion vs beam width.** Band-centre pixels connect a wide wavelength
   range -> wash to white; only fringes show pure colour. Not a clean spectrum.

Conclusion: a prism rainbow is a **forward** light-transport phenomenon. The
working BK7 *sphere* dispersion reference works precisely because a sphere
*focuses* (a real chromatic caustic that SMS/MNEE can sample).

## Forward light-tracer (the shipped solution)

`plugins/integrators/light_tracer_caustic.cpp`:
- `beginFrame` (serial, before the parallel camera loop): trace N photons from the
  collimated sun, each a uniform-sampled wavelength. Refract through the two
  caster-flagged prism faces (Sellmeier IOR + Schlick Fresnel transmittance),
  intersect the first diffuse non-caster surface (the floor), and bilinear-splat
  `cieCmf1964_10deg(lambda) * transmittance` into a 2D (x,z) grid on the receiver.
- `sampleFull`: base path-trace + on a horizontal floor hit, bilinear-gather the
  grid (irradiance) * albedo. Deterministic (fixed photon seed), so few camera
  samples suffice and the result is noise-free.

Scope/limits: horizontal (normal ~ +y) diffuse receiver; brightness auto-scaled
(arbitrary, fine for the hue gate) with a `caustic_boost` int knob.

## Acceptance (met)

`benchmarks/reference_bank/scenes/prism-bk7-collimated/` switched to the
triangulated prism + collimated sun + floor + `light_tracer_caustic`. Measured in
the band ROI: **hue_spread = 0.754** (>= 0.7), **bright_coverage = 0.88** (the
continuity discriminator — salt-and-pepper would collapse this well below 0.5).
The rendered band is a clean continuous red->violet rainbow.
`tests/test_prism_caustic_rainbow.py` guards it on CI.

## Differences from the references

- Photon deposition uses a 2D planar grid (not a kd-tree photon map) — the
  receiver is a single plane; this is simpler and exact for that case.
- The MNEE transfer matrix is ported faithfully from Cycles but is currently used
  only by the experimental triangle-caster SMS path; the prism rainbow does not
  use it.
