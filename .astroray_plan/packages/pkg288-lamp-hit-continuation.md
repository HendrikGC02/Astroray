# pkg288 — Continue the path through a hit dedicated lamp, CPU + GPU (#915)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h) + GPU build
**Depends on:** pkg181

---

## Goal

Before: a BSDF/phase-sampled path that hits a dedicated lamp adds the lamp's
MIS-weighted emission and then `break`s (`include/raytracer.h:3617`), while NEE
shadow rays pass through lamps; the GPU intersect stage does the same. With two
lamps in line, or a lamp in front of an emissive/lit surface, NEE-on and
NEE-off disagree and both differ from Cycles, which adds the lamp contribution
and continues the same ray past it (`integrator_shade_light`). After: on both
backends the path continues from the lamp hit with the same direction and
`tmin = t_lamp + ε`, lamps are transparent to transport except via their
emission term, and NEE-on == NEE-off on a two-collinear-lamp scene.

---

## Context

Found while fixing #912 (Batch AC); the #912 test can only gate the blue-lamp
component because of this. Any scene with a lamp between the camera and lit
geometry (the sky sun disc over a landscape, a visible bulb in front of a
wall) loses everything behind the lamp on BSDF-sampled paths. Cheap, sharply
scoped, and a precondition for pkg284's light-tree scene gates.

---

## Evidence

- 2026-09-26 (#915): `astra_run\batchU\f912\` lamps scene, NEE-on brighter than NEE-off with two lamps in line.
- `include/raytracer.h:3578-3618`: lamp-hit block ends in `break; // path terminates on the lamp`; `:3455` (fog scatter) treats the lamp as the terminating event for free-flight sampling.
- `src/gpu/wavefront/stage_advance.cu:656-720`: lamp hit writes `color` and (below) terminates the wavefront path.
- CPU adds an unweighted lamp hit when `!lightNeeEnabled`; GPU adds nothing in naive mode — a second CPU/GPU disagreement to close here.

---

## Reference

- Cycles `intern/cycles/kernel/integrator/shade_light.h` (`integrator_shade_light`: `film_write_direct_light`… then `INTEGRATOR_STATE_WRITE(state, ray, tmin) = intersection_t_offset(isect.t)` and `integrator_shade_light_next_kernel` → `intersect_closest`), `intersect_closest.h` (`lights_intersect`, `integrator_intersect_next_kernel_after_shadow_catcher`…), Apache-2.0.
- Cycles `kernel/light/light.h` `lights_intersect` (lamps found alongside the surface hit; the nearest wins, the ray is not consumed).
- pbrt-v4 has no hittable delta lamps; area lights are geometry and the path continues through emissive surfaces only if `Le` is on a transmissive material — Cycles is the parity target here.
- `.astroray_plan/docs/issue860-emission-hit-clamp-attribution.md` (bounce-1 clamp convention that the continuation must keep).

---

## Prerequisites

- [ ] Batch AC (#912 pdf fix) merged, so the MIS pdf at the lamp hit is already correct.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg288_lamp_passthrough.py` | (a) two collinear point lamps + white wall: NEE-on == NEE-off within 2 % per channel, CPU and GPU; (b) sun disc (camera-visible) in front of a lit plane: plane mean unchanged with/without the disc; (c) lamp between a mirror and the camera: reflection of the wall behind the lamp is present. Cycles reference via `render_leg.py` for (a). |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Lamp-hit block: after `color += c`, set `ray.origin = ray.origin + ray.direction * (lh.t + eps)` and `continue` the bounce loop without incrementing `bounce` or touching `throughput`/`bsdfPdfPrev`/`misNormalPrev`; fog-scatter `termT` must no longer stop at the lamp (the lamp is not a terminating event; the free-flight sample proceeds to the surface, with the lamp's emission attenuated by `Tr(lh.t)`). Naive mode (`!lightNeeEnabled`) keeps the unweighted add on both backends. |
| `src/gpu/wavefront/stage_advance.cu` | Same: after the lamp contribution, re-issue the ray with `origin += dir·(lampT+eps)` and mark the path active for another intersect without a shade stage (a `lamp_passthrough` flag or a loop inside the intersect stage capped at 4 lamp hits per segment); naive mode adds the unweighted lamp hit (CPU twin). |
| `src/gpu/wavefront/stage_volume_hetero.cu` | Hetero scatter: lamp is not a terminating event (CPU twin of the fog-scatter change). |
| `tests/test_pkg181_dedicated_light_bsdf_visibility.py` | Re-pin anything that encoded termination; the Batch AC #912 test widens its gate from B−R to all channels. |

### Key design decisions

- **Continue, do not re-shade.** The lamp hit is not a vertex: no BSDF, no NEE, no bounce increment, no Russian roulette. Cycles' `shade_light` does exactly this.
- **Cap lamp pass-throughs at 4 per segment** on the GPU (loop in the intersect stage) to bound wavefront work; CPU loops naturally.
- **Clamp category** stays `bounce − 1` for the lamp contribution (#860).
- **Free-flight sampling:** with lamps transparent, `termT` = surface distance; the lamp's emission seen through the medium is attenuated by `Tr(lh.t)` explicitly (the `hasWorldVolume && !fogScatter` branch generalises to always-attenuate-by-segment since the free-flight estimator no longer stops at the lamp). Re-derive against pkg199 Stage 2 comments before editing.
- **Register budget:** the GPU change is in the intersect stage (not the REG 254 shade kernel); confirm with the ptxas report.

---

## Acceptance criteria

- [ ] `test_pkg288_lamp_passthrough.py` (a)(b)(c) pass CPU and GPU; (a) also within 3 % of Cycles.
- [ ] Existing lamp tests (pkg181, pkg218, #883 near-light, #912) pass without widened bands; any re-pin carries attribution.
- [ ] Shade kernel REG/STACK unchanged; intersect-stage delta reported in the PR.
- [ ] Corpus v2 `v2_light_tree` and `v2_sky_sun` ROI ratios (if pkg284 landed) unchanged or moved toward 1.00 with the delta recorded.

---

## Non-goals

- No change to lamp visibility rules (camera-visible flag, #903) or MIS weights.
- No mesh-emitter pass-through (Cycles stops at emissive surfaces too).

---

## Progress

- [ ] CPU continuation + test (a)(b)(c).
- [ ] GPU intersect-stage continuation + naive-mode twin.
- [ ] Re-pins.

---

## Lessons

*(Fill in after the package is done.)*
