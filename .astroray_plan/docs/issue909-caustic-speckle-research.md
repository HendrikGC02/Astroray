# #909 caustic speckle: diagnosis and fixes (2026-09-26)

Scene: showcase glass (sun, SF11 prism, ball lens), GPU wavefront, 4096 spp.
Repro: 160x120 glass ball on a floor, 4 seeds per spp, per-pixel std in the caustic ROI.

## Root causes (measured on main 2e780100)

1. **One photon map per `render()` call.** `cuda_wavefront_render` traced the map once,
   before the sample loop; the addon renders 4096 spp in one call. ROI median std
   16/64/256/1024 spp = 0.0018/0.0014/0.0012/0.0013 (ideal 8x drop over 64x spp).
   pkg220 reseeded per call, which only helps the viewport (1 spp per call).
2. **K-NN radius singularity.** With fewer than K photons in range, the estimator used
   the farthest found photon as r, so E ~ P/(pi d^2) near an isolated photon. Same
   per-sample spike (~1435) at 64/256/1024 spp; the sparse photon tail showed as dots.
3. **Double counting.** Path-traced refractive caustics (diffuse -> delta glass -> sun)
   ran alongside the gather. Bright sun (irradiance 3): 16-spp max 3340 in the caustic
   ROI (per-sample ~5e4) vs photon-only 1.5.

## Fixes and sources

- Per-round maps: render in rounds of max(16, spp/256) samples; each round traces a
  fresh map with a new photon seed and offsets the sample index. Averaging independent
  photon passes: Hachisuka & Jensen 2009 (SPPM); Knaus & Zwicker 2011 (probabilistic
  PPM, independent passes averaged). No radius reduction (fixed K-NN, alpha = 1):
  variance falls as 1/N, the K-NN blur stays. Radius reduction is a follow-up.
- Estimator radius: Jensen 2001, *Realistic Image Synthesis Using Photon Mapping*,
  App. B `irradiance_estimate`: `dist2[0] = max_dist^2` until the heap holds K photons.
  Applied to CPU `photon_map.h` and GPU `photonGridGatherKnn`.
- Split: Jensen 1996 two-pass photon mapping renders L S+ D only from the caustic map.
  The GPU gather covers exactly: bounce-0 receiver -> caster hits entered/exited in turn
  -> the aimed dedicated lamp. The intersect stage tracks that chain in a per-path byte
  (`GWavefrontPhotonSplit`) and drops the lamp emission only for it. Through-glass
  caustics, other lights and external reflections stay path traced.
- Adaptive sampling: gathered energy now also feeds the even-sample half-buffer.

## Known limits

- Gather is at the primary hit only; a caustic seen through glass stays path traced
  (noisy). Fix: gather at the first diffuse vertex after a specular camera chain.
- External reflections off casters (reflective caustics) are not in the map and stay
  path traced; with a small sun they remain a firefly source.
- Aimed lamp = dedicated light along the aim direction (|cos| > 0.9995); an emissive-
  mesh aim gets no split. TIR / internal Fresnel chains are treated as not covered.
- Photon brightness uses boost/(pi*peak95) per map, not light power / N (separate issue).
- CPU `path_tracer` photon mode (test oracle, not used by the addon) still builds one
  map per render and does not cull.
