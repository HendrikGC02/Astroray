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
