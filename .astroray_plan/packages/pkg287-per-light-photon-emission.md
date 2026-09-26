# pkg287 — Per-light photon emission for caustics: spot, point, area, sun (#910)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h): CPU emitter + GPU emitter + aim/projection + tests
**Depends on:** pkg286

---

## Goal

Before: the photon pre-pass traces one collimated beam from the "dominant"
light's direction toward the union AABB of all casters (`buildCausticAim`,
CPU `sunDir` block), so only a sun gives correct caustics; a spot, point or
area light produces a wrong (parallel) caustic and the showcase glass scene had
to use a sun. After: photons are emitted per light with that light's own
geometry (distant: aperture disc; point/spot: cone/sphere with the IES/spread
factor; area: surface × cosine hemisphere), importance-aimed at each caster's
bounds through a per-light projection map (Jensen 2001 §9), each photon
carrying Φ_p from pkg286, CPU and GPU alike.

---

## Context

Caustics are a headline feature (showcase, README) and the only reason the
showcase glass scene is sun-lit. The corpus v2 dispersion scene (pkg284)
lights the prism with a spot to gate this. pkg286 makes the energy physical;
this package makes the geometry right.

---

## Evidence

- 2026-09-26 (#910): `buildCausticAim` aims one beam at all casters; spot/point/area caustics wrong.
- `spectral_path_tracer.cpp:487-489`: `sunDir = (casterC - ls.position)` from a single `lights.sample`, i.e. the emitter is chosen by one power-weighted draw.
- pkg276: IES × spot composition is parity-exact on NEE (`gpu_nee.cuh`), so the spot's angular distribution already exists on both backends.

---

## Reference

- Jensen 2001 §9.1–9.3 (emission from point, spot, area, directional lights; projection maps), §7.1.
- pbrt-v3 `src/integrators/sppm.cpp` + `Light::Sample_Le` (`lights/point.cpp`, `spot.cpp`, `distant.cpp`, `diffuse.cpp`, BSD-2) — per-light photon emission with pdfPos·pdfDir.
- Mitsuba 3 `src/integrators/ptracer.cpp` (BSD-3) — light selection ∝ power, `sample_ray` per emitter.
- `include/raytracer.h` `Light` hierarchy (`DistantLight`, point/spot with `iesProfile`, area with spread), `LightList::sample`, `dedicatedPowers`.
- `include/astroray/gpu_photon_caustic.h`, `src/gpu/photon_caustic.cu` (`kTracePhotons`), `gpu_wavefront_snapshot.cu::buildCausticAim`.
- `.astroray_plan/docs/pkg109-110-111-photon-map-research.md`.

---

## Prerequisites

- [ ] pkg286 merged (Φ_p, no peak calibration).
- [ ] `GDedicatedLight` layout stable (Batch Z added a trailing field; cpp-abi-guard on this package).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/photon_emitter.h` | Host-shared (CPU + CUDA `__host__ __device__`) per-light `sampleLe(light, u4) -> {origin, dir, Φ_p, pdfPos, pdfDir}` for distant/point/spot(IES)/area(spread); projection-map cone toward a caster AABB with the solid-angle fraction folded into Φ_p. |
| `tests/test_pkg287_per_light_caustics.py` | Glass sphere on a floor lit by (a) sun, (b) spot 30° above, (c) point, (d) area: caustic centroid and integrated flux vs a 4096-spp path-traced reference with caustics off but `max_bounces` high (Cycles-style brute-force caustic) within 10 % flux / 2 px centroid; CPU/GPU 5 %. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/spectral_path_tracer.cpp` | `buildPhotonMap`: loop over dedicated lights with photon budget ∝ `dedicatedPowers`; emit via `photon_emitter.h`; flat-prism fast path only for distant lights, general BVH loop otherwise. |
| `plugins/integrators/light_tracer_caustic.cpp` | Same emitter; drop its private sun-only aperture. |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | `buildCausticAim` → `buildCausticAims` (one per light, per caster cluster); upload an aim array. |
| `src/gpu/photon_caustic.cu` | `kTracePhotons` takes the aim array + light index per photon; per-light RNG stream so successive rounds (#909) stay decorrelated. |
| `include/astroray/gpu_photon_caustic.h` | `PhotonCausticAim` → array + `lightIndex`, `fluxPerPhoton`, cone/sphere parameters. |
| `blender_addon/__init__.py` | Remove the "sun required for caustics" degradation note; caustic-caster flag unchanged. |

### Key design decisions

- **Light selection ∝ power, photons per light = N · P_i/ΣP** (Mitsuba ptracer), then per-light importance cone toward each caster AABB; the cone's solid-angle fraction Ω_c/Ω_light multiplies Φ_p so the estimate stays unbiased (Jensen §9.3 projection map with a single cell per caster).
- **Mesh emitters are not photon sources** in this package (they go through the path tracer + #909 cull); dedicated lamps only.
- **Spot/IES:** sample the cone uniformly, weight by the spread/IES factor already used by `gpu_nee.cuh` and `Light::emission` so both paths share one angular model (pkg276).
- **Area with spread:** cosine-weighted hemisphere × the #852 spread attenuation.
- **Double-count cull (#909)** is per aimed light: a path-traced caustic from light i is culled only where light i's photons deposit; other lights' caustic paths keep energy.

---

## Acceptance criteria

- [ ] `test_pkg287_per_light_caustics.py` passes CPU and GPU for sun/spot/point/area (flux 10 %, centroid 2 px, CPU/GPU 5 %).
- [ ] pkg286 furnace test still passes (distant path unchanged in energy).
- [ ] Showcase glass re-rendered with the sun replaced by a spot: caustic under the ball present, lead visual sign-off saved to `benchmarks/blender_showcase/refs/`.
- [ ] cpp-abi-guard MERGE on the `GDedicatedLight`/aim-array layout; shade kernels REG/STACK unchanged.

---

## Non-goals

- No mesh-emitter photons; no MNEE/SMS.
- No adaptive projection maps beyond one cone per (light, caster).
- No change to the gather or the per-round map schedule (#909).

---

## Progress

- [ ] `photon_emitter.h` + CPU emitter loop + test (CPU).
- [ ] GPU aims array + kernel.
- [ ] Showcase spot re-render + addon note.

---

## Lessons

*(Fill in after the package is done.)*
