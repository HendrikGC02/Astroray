# pkg296 — mesh-bounded volumes: boundary semantics research (#833)

## Sources

- **Cycles** (Apache-2.0, `SPDX-License-Identifier: Apache-2.0`):
  - `intern/cycles/kernel/integrator/volume_stack.h` `volume_stack_enter_exit`:
    a surface with `SD_HAS_VOLUME` is an EXIT when `sd->runtime_flag & SR_BACKFACING`
    (remove the matching object+shader entry), else an ENTER (append unless already
    present). `SR_BACKFACING` = the ray hits the geometric normal's back side
    (dot(Ng, D) > 0); Ng is flipped for negative-scaled objects, so a closed mesh's
    normal is outward whatever the transform.
  - `intern/cycles/kernel/integrator/intersect_volume_stack.h`
    `integrator_volume_stack_init`: camera-inside detection. A probe ray along +Z
    ("Z up is a guess to get the fewest hits") collects up to `2 * volume_stack_size`
    volume hits; a back-facing hit on an object not entered before along the probe
    means the camera started inside it (`enclosed_volumes`).
  - `intern/cycles/kernel/integrator/shade_volume.h`: the segment is shaded with the
    closures of every stack entry summed (our `spectralTrackOverlap`, #842).
- **pbrt-v4** (Apache-2.0): `MediumInterface` on `GeometricPrimitive`; interface-only
  surfaces skipped (`SurfaceInteraction::SkipIntersection`); one current medium per
  ray. Rejected: no overlapping media (see spec Key design decisions).
- **Watertight ray–triangle**: Woop, Benthin, Wald, "Watertight Ray/Triangle
  Intersection", JCGT 2(1), 2013. Ported from pbrt-v4 `src/pbrt/shapes.cpp`
  `IntersectTriangle` (Apache-2.0): translate/permute/shear, edge functions with
  a double-precision fallback at exact zeros, sign-consistent edge test, scaled-t
  range test, conservative `t > deltaT` bound. Shared edges never leak: a ray
  through an edge hits at least one of the adjacent triangles.
- **Boundary BVH**: pbrt-v4 `BVHAggregate` equal-counts (median) split on the
  largest centroid axis (Apache-2.0); textbook closest-hit stack traversal.

## Semantics chosen (stateless inside test)

A point at ray parameter `t` on a ray `(o, d)` is inside medium k iff the closest
crossing of k's boundary mesh strictly after `t` is back-facing (dot(Ng, d) > 0).
For a closed, consistently oriented mesh this equals the Cycles stack state along
the same ray, because the crossings along any line alternate enter/exit:

- camera inside: the first crossing is an exit ⇒ inside, no init pass needed
  (Cycles needs `integrator_volume_stack_init` only because its stack is path state);
- nested / overlapping: each medium is tested independently and every covering
  medium feeds `spectralTrackOverlap` (Cycles sums the stack entries);
- dedupe on object+shader: one boundary per `BoundedMedium`, so an entry cannot be
  counted twice.

The segment sweep (`spectralTrackSegment`) and the shadow transmittance walk the
coverage intervals: from a cursor, the next crossing is back-facing ⇒ covered up to
it; front-facing ⇒ the medium starts there. Queries use `t > cursor` strictly, so
the crossing that ended the previous piece is never re-found (same triangle, same
float arithmetic ⇒ same t); the cursor strictly increases, so the sweep terminates.

## Divergences (documented)

- **Open meshes**: a ray entering through a hole meets a back face first and counts
  as inside; in Cycles it was never entered. The addon reports non-closed boundaries
  (DEGRADED) and the gates keep ROIs off holes (Suzanne's eyes).
- **Inconsistent winding** behaves the same way (each flipped face inverts the local
  answer). The addon's closed check requires every directed edge to appear once
  with its reverse present (closed and consistently oriented).
- **Surface + volume on the same mesh** (glass shell): the surface triangles stay in
  the scene BVH, a copy is the boundary. The tracking segment starts at 0.001 along
  the new ray, so the crossing at the spawn point (t ≈ 0) is never counted; the
  boundary answer after a refraction into the shell is "inside" (next crossing = the
  far wall, back-facing), after a reflection off the outside "outside".
- Media with a boundary keep their world AABB (from the triangles) as a cheap
  pre-filter; the per-segment direct-light hull (#925) stays the AABB hull (a
  superset: the per-point membership test zeroes the integrand outside the mesh, so
  the estimator stays unbiased).
- VDB Volume objects keep their grid AABB (non-goal: Cycles' active-voxel bounds mesh).
