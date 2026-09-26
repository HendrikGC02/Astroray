# pkg286/287 — physical, per-light photon emission (research note)

## Sources
- Jensen, *Realistic Image Synthesis Using Photon Mapping* (2001): §7.1 photon
  power Φ_p = Φ_light / N_emitted (all launched photons); §7.2 radiance
  estimate L = Σ f_r ΔΦ_p / (π r²); §9.1–9.3 emission from point/spot/area/
  directional lights and projection maps; App. B cone filter norm 1 − 2/(3k).
- pbrt-v3 `src/integrators/sppm.cpp` (BSD-2): photon β = Le·|cosθ| /
  (lightPdf·pdfPos·pdfDir); `Light::Sample_Le` in `lights/{point,spot,distant,
  diffuse}.cpp`; `FrDielectric` (exact unpolarised Fresnel).
- Mitsuba 3 `src/integrators/ptracer.cpp` (BSD-3): emitter chosen ∝ power.
- Duff et al. 2017, "Building an Orthonormal Basis, Revisited" (cone frame).

## What the engine does
- `include/astroray/photon_emitter.h` (host + device): `peSampleLe` returns the
  geometric weight W with Φ_p(λ) = S(λ)·W/N_i. Radiometry mirrors each light's
  `sampleLi` via `DeviceLightParams::staticScale`: distant E·A over a square
  aperture (jittered over the sun cone); point/spot I·Ω_cone (spot smoothstep,
  IES via `ies::evalFrame`); area L·cosθ·A·Ω_cone with the #852 spread
  attenuation. Directions are uniform in one cone toward the caster bounding
  sphere (Jensen §9.3 projection map, one cell), so W carries Ω_cone and the
  estimate stays unbiased.
- `photon_lights.h`: one emitter per dedicated lamp; N_i ∝ the luminous flux
  toward the casters (16×16 pilot) — any split is unbiased since each light
  divides by its own N_i. λ ∝ S over 380–720 nm (pkg221), so S/p = I_S.
- No receiver cosine on deposit (the hit density carries it); scale = boost/π.
- Exact Fresnel replaced Schlick: Schlick with the incident-side cosine on a
  glass→air exit ignores TIR onset (R ≈ 0.04 at the critical angle).
- #909 split per light: GPU lamp bitmask; CPU twin in `pathTraceSpectral`
  (`Renderer::photonSplitLamps_`).

## Measurements (CPU, 2026-09-27)
- Slab furnace (delta sun, normal incidence): patch/direct = 0.926 vs T 0.9216;
  deposited flux 2.355 vs E·A·T 2.369.
- Ball lens, point lamp: engine photon flux 1.7246 vs independent numpy trace
  1.7409 (band 380–720 nm drops ~1 %); radial deposit fractions match to 0.1 %.
- Photon vs brute-force PT (16384 spp) caustic core flux: area 1.00, sun
  (0.2 rad) 1.06, point/spot (emissive-sphere stand-in) 1.06–1.07; centroids
  within 0.2 px. At 4096 spp the small-source PT reference was ~15 % low and
  kept drifting, so it is the weak side (the oracle agrees with the photons).
- Thick slabs + point/area lamps: extra light lands in bands from TIR off the
  slab side walls (a real light-guide effect, not a bug).

## Known limits
- One cone per light toward the union of all casters (no per-cluster cones).
- Point/spot radius > 0 emit from the centre (far-field intensity unchanged).
- Mesh / legacy hittable emitters emit no photons (their caustics stay path
  traced and are not culled).
