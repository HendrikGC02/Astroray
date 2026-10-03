# #1037 — hair rays re-hit their own strand: research notes

## Problem
Astroray's thick curves use the pbrt-v3 flattened ray/curve test (`curves.h`,
`gpu_curve_intersect.cuh`): the hit point is the ray point at the depth of the
centreline (`t = pc.z`), so it lies INSIDE the swept tube. A continuation or
shadow ray started there sees the same segment within one radius in projection,
so it "hits" it again whenever the closest approach lies ahead of `tMin`. In the
pkg225 tuft probe (radius 0.3 strand, point light, depth 2) same-segment re-hits
carried 0.38 of 0.44 total radiance (both backends). The Chiang 2016 far-field
fibre BSDF already accounts for transport through the fibre, so a re-hit
double-counts it.

## Reference: Cycles self-primitive skip (Apache-2.0)
- `src/kernel/bvh/util.h`: `intersection_skip_self(self, object, prim)` =
  `self.prim == prim && self.object == object`; `intersection_skip_self_shadow`
  adds the light primitive.
- `src/kernel/bvh/shadow_all.h` / `traversal.h`: the check runs before the
  per-primitive switch, so it applies to `PRIMITIVE_CURVE_THICK` too.
- `src/kernel/integrator/intersect_closest.h`: the continuation ray carries
  `ray.self.prim = last_isect_prim`, `ray.self.object = last_isect_object`.
- `src/kernel/light/sample.h` `light_sample_to_surface_shadow_ray`: shadow rays
  carry `self.prim = sd->prim`.
Adjacent segments of the same strand are different primitives and are NOT
skipped (Cycles behaves the same).

## Astroray port (owner/lead decision 2026-10-03: Cycles approach, no epsilon offsets)
- Only curve segments test the skip; triangles/spheres keep the existing
  `tMin` behaviour (byte-identical renders without curves).
- CPU: `Ray::self` (origin primitive) set from `rec.hitObject` at every
  surface spawn site; `CurveSegment::hit` returns false when `r.self == this`;
  `shadowTransmittance` keeps `self` across transparent hops.
- GPU software BVH: `skipPrim` (global ordered-prim index, -1 = none) threaded
  through `gpu_bvh_hit/occluded` and `gpu_tlas_hit/occluded`; only the
  `HasCurves` curve leaf compares it. Continuation rays read the previous hit's
  `hit_prim_id` (bounce > 0; a medium-scatter vertex resets it to -1); surface
  shadow rays read the shading vertex's `hit_prim_id`; volume-segment records
  use -1. OptiX is never used for curve scenes (pkg299 eligibility gate).
