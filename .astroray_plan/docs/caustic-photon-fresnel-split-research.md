# Caustic photons: Fresnel-sampled specular chains and the photon/path split (#959, #1025)

## Sources
- Jensen, *Realistic Image Synthesis Using Photon Mapping* (2001), §5 (photon
  tracing: Russian roulette picks reflection vs transmission at a surface with
  the surface's probabilities, so the photon power is unchanged), §9 (the caustic
  map holds L S+ D paths; the rendering pass must not count those paths again).
- Jensen 1996, "Global illumination using photon maps" (two-pass split).
- pbrt-v3 (BSD-2), `src/core/reflection.cpp` `FresnelSpecular::Sample_f`:
  reflect with probability F = FrDielectric, else refract with 1 - F; in
  importance transport the returned weight / pdf is 1 either way (no eta^2).
  `src/integrators/sppm.cpp` photon pass follows exactly that BSDF sample.

## Findings (2026-10-03, lane au-caustic)
- Oracle: `numpy` forward photon trace of `arb_prism_sun` (exact Fresnel,
  stochastic reflect/refract, Sellmeier SF11, 4 deg sun disc) + camera rays
  traced specularly through the prism; per-path-signature tallies.
- #1025: the `floor_caustic` ROI sees the prism, not the floor; 97 % of its
  value is the sun seen after a TIR off the prism's BOTTOM face, which is
  coplanar with the floor top (z = 0). Every engine z-fights that face pair:
  Mitsuba keeps ~57 % of the TIR light, Astroray GPU 54 %, CPU 48 %. With the
  prism lifted 5 mm: oracle 7.03, CPU 6.93 (0.986), GPU 6.87 (0.978).
- The photon loops refracted deterministically (weight T) and reflected only on
  TIR, while the split cull dropped path-traced twins only for strictly
  alternating enter/exit chains. A TIR chain (T r T) is in the photon map AND
  survives the cull, so it was counted twice: GPU photon render of the lifted
  scene, beam ROIs vs the oracle: left beam (T2 r4 T3) +34 %, down beam
  (T2 r3 T4) +29 %; the photon-minus-PT excess equals the oracle's TIR-chain
  share (0.063 vs 0.065, 0.028 vs 0.029). Pure refraction (the rainbow T3 T4)
  matched the oracle (0.1917 vs 0.1910).

## What the engine does now
- CPU and GPU photon loops pick reflection with probability R (exact Fresnel,
  R = 1 on TIR), else refraction, power unchanged (pbrt-v3 FresnelSpecular).
  The photon map then holds every caster chain L (S_caster)+ D, including
  external reflections (the white beams), not only refraction chains.
- The split cull drops a path-traced lamp hit when every hit after the bounce-0
  receiver was a caster (any face, any lobe): exactly the set the map holds.
- CPU builds the same photon map when `usePhotonCaustics` is set (the addon sets
  it whenever a caster is flagged), so CPU and GPU run one estimator; without it
  the CPU had no point/spot-lamp caustics at all (a delta lamp cannot be hit by
  a path-traced ray).

## Measured after the fix (build 211a4361, 2026-10-03)
Lifted `arb_prism_sun`, 1024 spp x 4 seeds, luminance ratio to the oracle / the
new Mitsuba reference (prism lifted, sun at 1e4 m):

| ROI | oracle | Mitsuba | GPU before | GPU after | CPU after |
|---|---|---|---|---|---|
| floor_rainbow (T T) | 0.2163 | 0.2171 | 1.006 | 0.998 | 0.998 |
| floor_tir_beam (T r T) | 0.2553 | 0.2571 | 1.395 | 0.998 | 0.999 |
| floor_reflection_beam (R + T r T) | 0.2113 | 0.2153 | 1.141 | 1.001 | 1.002 |
| prism_sun_glint (camera, TIR off the base) | 7.03 | 7.07 | 0.978 | 0.978 | 0.987 |

- `tests/test_959_caustic_photon_split.py` (8 deg sun, photons ON / path traced):
  GPU TIR beam 1.317 -> 0.998, reflection 1.085 -> 1.007; CPU 1.007 / 1.004.
- Corpus v2 `v2_dispersion_caustics`, 5 seeds x 64 spp, GPU/CPU (L): prism floor
  1.005, spot floor 1.009 (CPU 0.0782 vs Cycles MNEE 0.0783; the CPU had no spot
  caustic before), sphere limb 1.022.
- Side finding: the CPU's default adaptive sampling reads heavy-tailed path-traced
  caustics 10-25 % low at 2048 spp (stops on a noise estimate the rare sun hits
  have not reached yet); off, CPU and GPU path tracing agree.

## Known limit
- The CPU traces one 3M-photon map per render call; the GPU traces a fresh 4M map
  every 16 spp (#909). At 256+ spp the CPU therefore shows frozen photon-gather
  speckle in sparse regions (photons scattered off the sphere) that the GPU averages
  away. ROI means agree; the noise does not fall with spp on the CPU.
- The photon gather is a Lambertian albedo/pi estimate at the first non-emissive, non-transmissive hit (pkg111, unchanged here), and
  the split cull also drops the path-traced lamp chain after such a surface. A glossy/metallic primary receiver therefore
  gets a diffuse photon estimate instead of its BSDF (Terra re-review MEDIUM, pre-existing; not covered by tests). CPU photon-map
  seeding with renderSeed 0 (the random sentinel) is fixed (Terra LOW). Both are follow-ups.
