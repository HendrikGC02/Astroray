# pkg225 Stage 1 — ray-curve intersection: algorithm research

CLAUDE.md §6 gate: no invented geometry algorithms. This note records the
canonical sources used for `CurveSegment` (thick/swept-circle CPU ray-curve
intersection) before any code was written, per the `cite-algorithm` skill.

## Chosen primary algorithm: pbrt-v3 `Curve::Intersect` (BSD-2-Clause)

Source: `mmp/pbrt-v3`, `src/shapes/curve.cpp`
(https://github.com/mmp/pbrt-v3/blob/master/src/shapes/curve.cpp), copyright
Matt Pharr / Greg Humphreys / Wenzel Jakob, BSD-2-Clause license (permissive,
compatible). Fetched verbatim 2026-08-31 and diffed against the pbrt book
text; this is the canonical "recursive Bezier-clipping" ray-curve test that
pbrt-v4 also ships (v4 refactors the same math into `pbrt::Curve` with GPU
variants but the CPU algorithm is unchanged).

**Why this one, not Cycles' full `curve_intersect.h` or Reshetov 2017
directly:** the pkg225 spec's own Reference section names all three as
candidates. Cycles' current `kernel/geom/curve_intersect.h` (Apache-2.0,
adapted from Embree's `curve_intersector_sweep.h`) additionally layers
outer/inner bounding-cylinder pruning and a 5-iteration Newton-Raphson
final refinement on top of the same recursive-subdivision idea, explicitly
to hit GPU/SIMD performance targets. That refinement is a Stage-3
(GPU/perf) concern, not a Stage-1 CPU-correctness concern. Reshetov 2017
("Phantom Ray-Hair Intersector") is a fully-analytic single-cylinder test
that is Cycles' *historical* OptiX/embree-adjacent reference for straight
segments; it does not natively cover curved (non-degenerate-tangent)
Catmull-Rom segments without the same kind of iterative correction Cycles
now uses. pbrt's recursive Bezier-subdivision test is (a) exact to a
controllable epsilon for ANY cubic segment including dead-straight ones
(so it gives a clean closed-form-matching analytic parity test), (b)
self-contained (no Newton iteration, no SIMD-specific cylinder-pruning
machinery), and (c) already produces exactly the `u` (along-strand) and
`v` (azimuthal, `CurveType::Cylinder` branch) parametrization the spec
asks `HitRecord` to carry. It is the right scope for "CPU primitive +
analytic parity test."

### Algorithm, as implemented in Astroray

1. **Coordinate frame.** Build a ray-local orthonormal frame with
   `zAxis = ray.direction` (already normalized — Astroray's `Ray` ctor
   normalizes direction, so `rayLength == 1` always; pbrt's `rayLength`
   scaling collapses out) and `xAxis` derived from
   `dx = cross(ray.direction, bezier[3] - bezier[0])` (pbrt's `LookAt`
   orientation trick — keeps the curve's hull close to the local x-axis,
   which tightens the early-out y-bound). Degenerate `dx` (ray parallel to
   the chord) falls back to `buildOrthonormalBasis()` (existing Astroray
   helper, used elsewhere for tangent frames) exactly as pbrt falls back to
   `CoordinateSystem()`.
2. **Project the 4 Bezier control points into that frame** (world-space
   curve, so no object-to-world step — Astroray stores curves directly in
   world space like `Triangle`/`Sphere`).
3. **Adaptive max recursion depth** from pbrt's `L0`/`eps` heuristic
   (second-difference flatness measure vs. `max(radius)*0.1` — pbrt uses
   `width*0.05`; width = 2*radius so the constant carries over unchanged),
   `maxDepth = clamp(round(log4(1.41421356 * 6 * L0 / (8*eps))), 0, 10)`.
4. **`recursiveIntersect`**: at `depth > 0`, `SubdivideBezier` (de Casteljau
   midpoint split, pbrt's closed-form 7-point split) into two half-segments,
   reject each against the ray's local-frame AABB (y first, then x, then z
   against `[0, tMax]`), recurse. At `depth == 0`: reject via the two
   "tangent-perpendicular" edge functions at the segment ends (rejects hits
   past the flattened segment's endpoints), find the closest point `w` on
   the projected chord, evaluate the true Bezier point at `w` for the
   perpendicular distance test against the interpolated radius
   (`dist² > radius(u)²`), and the `z` (=`t`, since `rayLength==1`) bound.
5. **Cylinder (swept-circle) shading frame.** `v ∈ [0,1]` from which side of
   the chord the true curve point falls (edge-function sign), then
   `theta = lerp(v, -90°, 90°)` rotates the flat perpendicular `dpdv` around
   the true-curve tangent `dpdu` — this is pbrt's `CurveType::Cylinder`
   branch, the one that gives a genuine round/azimuthal cross-section
   (as opposed to `CurveType::Ribbon`, which the pkg225 spec defers to
   Stage 3). `hair_u = u`, `hair_v = v` are stored on `HitRecord` per the
   spec's "Key design decisions."

Width vs. radius: pbrt parametrizes by `width` (diameter); Astroray's
`CurveSegment` ctor takes `radius0, radius1` per the spec's
"per-endpoint radius" file-table entry, so every pbrt `width`/`hitWidth`
term is substituted with `2*radius` and the `hitWidth² * 0.25` distance
threshold becomes `radius²` directly — algebraically identical, just
avoids a factor-of-2-then-back-again round trip in the code.

## Catmull-Rom → Bezier control-hull conversion

pbrt's algorithm consumes a **Bezier** control hull; Blender's `Curves`
data-block (and Cycles) use **Catmull-Rom** (uniform, tension 1/2) as the
default basis, which is what the pkg225 spec requires
("Basis: Catmull-Rom cubic (Blender's `Curves` data-block default)").
The bridge is the standard uniform Catmull-Rom → cubic-Bezier identity
(finite-difference tangents `m1=(P2-P0)/2, m2=(P3-P1)/2` fed through the
textbook cubic-Hermite → Bezier conversion `B0=P1, B1=P1+m1/3, B2=P2-m2/3,
B3=P2`) — CLAUDE.md §6 treats this as "trivial textbook math," not an
algorithm to cite-and-borrow, but it was still cross-checked (not asserted
from memory) against Cycles' `catmull_rom_basis_eval` in
`kernel/geom/curve_intersect.h` (Apache-2.0, Blender Foundation):

```c
// Cycles catmull_rom_basis_eval, fetched 2026-08-31:
ccl_device_inline float4 catmull_rom_basis_eval(const float4 curve[4], float u)
{
  const float t = u;
  const float s = 1.0f - u;
  const float n0 = -t * s * s;
  const float n1 = 2.0f + t * t * (3.0f * t - 5.0f);
  const float n2 = 2.0f + s * s * (3.0f * s - 5.0f);
  const float n3 = -s * t * t;
  return 0.5f * (curve[0] * n0 + curve[1] * n1 + curve[2] * n2 + curve[3] * n3);
}
```

Evaluating this basis and its derivative at `u=0` and `u=1` gives
`P(0)=P1`, `P(1)=P2`, `dP/du|_{u=0} = (P2-P0)/2`, `dP/du|_{u=1} = (P3-P1)/2`
— confirms it is exactly the tension-1/2 uniform Catmull-Rom used above, so
the Bezier hull built via `B0=P1, B1=P1+(P2-P0)/6, B2=P2-(P3-P1)/6, B3=P2`
reproduces Cycles' curve position/tangent exactly (both are the same cubic
polynomial in two different but algebraically-equivalent bases).

## Phantom control points at strand endpoints (Cycles convention)

The pkg225 spec requires "boundary handling (phantom points at strand
endpoints) follows Cycles' convention." Cycles' `curve_intersect` in
`kernel/geom/curve_intersect.h` (Apache-2.0) gathers the 4 Catmull-Rom
keys for segment `k0` (`k1 = k0+1`) as:

```c
// Cycles curve_intersect.h, fetched 2026-08-31:
const int k0 = kcurve.first_key + PRIMITIVE_UNPACK_SEGMENT(type);
const int k1 = k0 + 1;
const int ka = max(k0 - 1, kcurve.first_key);
const int kb = min(k1 + 1, kcurve.first_key + kcurve.num_keys - 1);
```

i.e. the phantom point is a **clamped duplicate of the nearest real
endpoint** (`ka == k0` for the first segment, `kb == k1` for the last
segment), NOT a mirrored/extrapolated point. `CurveStrip::buildCurveSegments()`
reproduces this exactly: segment `i` connecting `points[i]`/`points[i+1]`
uses `P0 = (i==0) ? points[i] : points[i-1]` and
`P3 = (i==n-2) ? points[i+1] : points[i+2]`.

## Deferred to later stages (explicitly out of Stage 1 scope)

- Ribbon (camera-facing flat strip) mode — spec marks it a stretch goal for
  Stage 1, required Stage 3. `CurveType::Ribbon`'s normal-interpolation
  branch in pbrt is not ported.
- Newton-Raphson iterative refinement / outer-inner-cylinder pruning
  (Cycles' `curve_intersect_iterative`, Embree-derived) — GPU perf work,
  Stage 3.
- Reshetov 2017 analytic single-cylinder shortcut — not needed once the
  recursive-subdivision path is correct and fast enough for CPU; revisit
  only if Stage 1 CPU perf profiling (dense-hair BVH, per spec "implementation-
  time decision") demands it.
