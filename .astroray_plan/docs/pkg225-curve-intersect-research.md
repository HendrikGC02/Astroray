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

## VERIFY FINDING (2026-08-31, parent build+test on RTX box) — NOT MERGEABLE YET

Builds clean (compiles + links). But `tests/test_pkg225_curve_intersect.py` is
**4 failed / 3 passed**:
- FAIL: `test_straight_cylinder_perpendicular_ray_hit_distance`,
  `test_straight_cylinder_oblique_ray_hit_distance`,
  `test_straight_cylinder_tangent_grazing_normal`,
  `test_endcap_within_segment_extent_hits` — all expect a HIT on a straight
  cylinder at the closed-form distance; the primitive returns **no hit**
  (position (0,0,0)).
- PASS: the two MISS cases + the curved-strand smoke (a curved strand DOES hit,
  40<depth<70). So miss-logic and the curved path work; **straight-cylinder hits
  are wrongly rejected.**

Localization for the next session: the ray-local frame (curves.h:74-115) is
plausible and for a straight strand `L0==0` → `maxDepth==0`, so the bug is almost
certainly in the **depth-0 hit test (curves.h:217-282)** ...

## ROOT CAUSE — CORRECTED (2026-09-02) — the primitive is CORRECT; the bugs were in the TEST

The 2026-08-31 localization above was **wrong on the mechanism**. Two facts
overturn it:

1. `L0 != 0` for a straight strand. The uniform Catmull-Rom → Bézier map of an
   evenly-spaced straight strand produces a **non-uniformly-spaced** Bézier hull
   (middle segment: x = −10, −5, 5, 10). The parametric second difference is 5,
   so `L0 = 5`, `maxDepth = 4` — the straight case *does* recurse, it does not
   take a `maxDepth==0` shortcut.
2. A standalone native harness (compiled against the real `raytracer.h` +
   `curves.h`, driving `CurveSegment::hit` and `BVHAccel::hit` directly, no
   Python/render/camera in the loop) shows the primitive **hits correctly** for
   every "failing" straight case:
   - perpendicular straight hit → `t=60.0`, `pos(0,0,0.15)` ✓
   - endcap-within (single 2-pt strand, x=4 inside [−5,5]) → `t=60.0`,
     `pos(4,0,0)` ✓
   - the outward shading normal at a near-tangent hit is **radial**, matching
     pbrt's `theta=Lerp(v,-90,90)` reconstruction (verified: as dist/radius→1
     the normal → normalize(P*−Q*)).

The four failures were all **test-file bugs**, not primitive bugs:

- **perpendicular / tangent-normal / endcap-within** — `_render_curve_probe`
  hard-coded `vup = (0,1,0)`. These three probes look straight down `-Y`, so the
  up vector was **(anti-)parallel to the view direction**; `u = up × w` collapses
  to a zero vector, the camera basis is NaN, every ray is garbage, nothing hits
  (position (0,0,0) — exactly the "no hit" the parent saw). The two straight MISS
  tests "passed" only because a NaN camera also produces no hit — they were false
  greens. Fix: pick an up vector non-parallel to the view dir.
- **oblique** — the chosen geometry `o=(2,45,−6), d=(0.3,−1,0.4)` has its
  ray↔axis closest-approach at **x ≈ 14.26**, outside the middle segment's
  [−10,10] span (and outside the test's own `−9 < q_axis[0] < 9` guard, which
  fires as an AssertionError). Fix: `o=(−2,40,3), d=(0.1,−1,−0.06)` → closest
  approach x ≈ 2.0, clearance 0.60, clean hit at t=40.31.
- **tangent-normal** — used `radius = clearance + margin` (dist/radius = 0.75,
  v = 0.875, θ = 67.5°), which is *not* tangency, and compared the sign-oriented
  stored normal against the outward radial. `setFaceNormal` (shared with
  Sphere/Triangle) flips the stored normal to face the ray; at a grazing hit the
  radial normal is ⟂ the ray so the flip sign is the degenerate-face convention.
  Fix: probe near tangency (clearance 2, radius 2.05 → v ≈ 0.988) and assert the
  normal is radial **sign-agnostically** (`|dot(n, radial)| > 0.99`).

**Resolution:** `include/astroray/curves.h`, `module/blender_module.cpp`
(`addCurvesBulk`), `plugins/shapes/curve_segment.cpp`, `include/astroray/shapes.h`
and `include/raytracer.h` are UNCHANGED — the Stage-1 primitive shipped correct.
`tests/test_pkg225_curve_intersect.py` was fixed (camera up, oblique geometry,
sign-agnostic normal).

**One adjacent engine gap surfaced and fixed:** the position AOV was never
filled. `SpectralPathTracer` (the `path_tracer` integrator) set the albedo /
depth / normal first-hit AOVs but never `r.position`, so `get_position_buffer()`
returned `Vec3(0)` for **every** shape. It went unnoticed because the only prior
consumer (`test_python_bindings::test_data_pass_buffers_exist_and_are_finite`)
asserts shape + finiteness, not value. Added `r.position = rec.point;` (world-
space first hit = Cycles `PASS_POSITION`) in the AOV block. The pkg225
perpendicular / oblique / endcap-within tests probe this buffer, so they needed
it real; the fix benefits every position-AOV consumer, not just curves.

Merge gate: 7/7 green on a `.pyd` rebuilt from this branch (the parent's earlier
4/7 was on a build since overwritten by a `main` build lacking
`add_curves_bulk`).
