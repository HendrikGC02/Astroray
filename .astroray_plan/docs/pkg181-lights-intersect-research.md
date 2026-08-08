# pkg181 — dedicated-light BSDF visibility (Cycles `lights_intersect` parity) research

## Goal
Dedicated lights (`astroray::Light`, sibling to `Hittable`, never in the BVH) are
invisible to BSDF-sampled rays, but NEE still pays the MIS power-heuristic
complement `wt = a²/(a²+b²)` as if a complementary BSDF hit could occur. The
BSDF-share of every non-delta lamp's direct light is therefore discarded and
lamp reflections in specular/low-roughness surfaces are near-black. Root cause
localized by pkg180 Phase 2 (see `.astroray_plan/docs/pkg180-systemic-cycles-dim-diagnosis.md`).

## Cycles reference (Apache-2.0)
- `intern/cycles/kernel/light/light.h` — `lights_intersect()` iterates lamps,
  tests ray intersection for SPOT/POINT/AREA (SUN handled separately), keeps the
  closest, and `light_sample_from_intersection()` /
  `light_eval_from_intersection()` returns the MIS-weighted emission. Lamps are
  skipped for camera rays (`SHADER_EXCLUDE_CAMERA` when
  `PATH_RAY_VISIBILITY_CAMERA`).
- `intern/cycles/kernel/light/area.h` — `area_light_intersect()`:
  - plane point `light_P = klight->co`, plane normal `Ng = klight->area.dir`;
  - one-sided reject: `if (dot(ray->D, Ng) >= 0) return false;`
  - local uv coords `u = dot(P-light_P, axis_u/len_u)`, `v = dot(P-light_P, axis_v/len_v)`;
  - rectangle in-bounds `|u|>0.5 || |v|>0.5 → reject`; ellipse `4u²+4v²>1 → reject`;
  - `eval_fac = M_1_PI_F * invarea` (plain radiance), optional spread attenuation;
  - `pdf *= light_pdf_area_to_solid_angle(Ng, -D, t)` (solid-angle measure).
- Distant/sun: a BSDF ray "hits" the sun when its direction lies within the
  sun's angular-disk half-angle of `-axis`; emission is the sun radiance `S/Ω`.

## Astroray mapping
The Astroray CPU emission/measure conventions already match Cycles per-type
(pkg122): `AreaLight::sampleLi` returns plain radiance
`emission·intensity·(1/area)·(1/π)` with a **solid-angle** pdf
`d²/(area·cosθ)`; `DistantLight::sampleLi` returns radiance `S/Ω` with pdf `1/Ω`.
So the emission-on-hit is exactly the same plain radiance, and the BSDF-hit MIS
leg reuses the existing pkg120 term (`raytracer.h:2416–2447`):

    lp = lights.pdfValue(ray.origin, ray.direction)   // solid-angle, selection-weighted
    wB = bp²/(bp²+lp²)
    color += throughput · L_e · wB          (wB = 1 when the previous bounce was specular / delta)

### The one weight-machinery gap the spec's "already complete" claim missed
`AreaLight::pdfLi()` returned `1/area` (AREA measure, and **direction-independent**,
so it contaminated the pkg120 sum for every direction). NEE samples the area lamp
in SOLID-ANGLE measure (`d²/(area·cosθ)`), so the BSDF-hit leg reconstructed a
pdf in the wrong measure — the MIS weight would be wrong and the AREA-floor gate
would not land in [0.97,1.03]. Fixed `AreaLight::pdfLi` to intersect the lamp and
return the solid-angle pdf `t²/(area·cosθ_light)`, zero when the direction misses
the lamp / hits the back face / falls outside the spread cone. NEE is unchanged
(it uses `sampleLi`'s pdf, not `pdfLi`). This also fixes the pre-existing
contamination of the pkg120 Hittable-emitter term in mixed scenes.

## Scope decision: Point/Spot lights stay NEE-only (intersect returns false)
Astroray's Point/Spot lights are **delta+soft-shadow hacks, not surface emitters**
(pkg122): even with `radius>0`, `sampleLi` returns the point delivery `I/d²`
(`I = P/4π`) with an **area-measure** pdf `1/(4πr²)`. That estimator does not
correspond to any physical sphere of radius `r` (the implied surface radiance
`L_s = 4I = P/π` ≠ the physical `P/(4π²r²)`), so there is no consistent surface
radiance a BSDF ray could collect that MIS-cancels against the existing NEE.
Making them "hittable" would require a pkg122-style radiometric rework of
point/spot sampling — out of this package's scope and unverifiable without a
gate. Point/Spot `intersect` therefore returns `false` (documented in-code), and
this is surfaced to the lead as the single deviation from the spec's letter.
Area + Distant close all 7 gates; Point/Spot reflections in mirrors remain a
pre-existing limitation of the point/spot model, tracked for a follow-up.

## Camera-ray visibility
Cycles keeps lamps invisible to camera rays. Astroray's path loop increments
`bounce` every iteration, so `bounce > 0` == non-camera (indirect/BSDF)
continuation ray. The lamp-intersection pass is gated on `bounce > 0`.
(Divergence note: a transparent/pass-through bounce increments `bounce` in
Astroray while Cycles preserves the camera flag; a lamp directly behind glass
would become visible one bounce "early". Not gate-relevant; noted.)
