# Motion Blur — Research Notes (pkg88 deep research session)

Background reading for the future **pkg88 — Motion Blur for Cycles
parity** package. Saved per CLAUDE.md §6 ("cite, borrow, verify"). The
goal of this document is to make the *future* pkg88 implementer's job
mechanical: every algorithmic choice should already have a paper, a
permissively-licensed reference implementation, and an Astroray
integration point named here.

This is research, not a spec. The thin draft spec at
`.astroray_plan/packages/pkg88-motion-blur-DRAFT.md` points back here
and lists the design forks the real implementation spec must resolve.

---

## §0 — TL;DR

- **Motion blur in a physically-based path tracer is sampling time as a
  fifth ray dimension.** Cook–Porter–Carpenter 1984 (the original
  "distributed ray tracing" paper) reduces the problem to: each pixel
  sample picks a time `t ∈ [0, Δshutter]`, and every scene query
  (camera, transforms, vertex positions, BVH bounds) is parametric in
  `t`. We do this every spp and average. See §2.1.
- **Three sources compose independently:** camera, rigid-object,
  deformation. Cycles, PBRT-v4, and Embree treat them as three
  independent toggles. Astroray should do the same. See §2.2.
- **`Ray::time` already exists** in `include/raytracer.h:391`. It is
  written by `Camera::getRay` as the literal `0.0f` and read nowhere
  else of consequence. The plumbing for time-parametric rays is in
  place; nothing currently consumes it.
- **Cycles' BVH operates at the *primitive* level, not at the *node*
  level**, for motion blur. Each motion primitive carries a
  `prim_time = float2(t_min, t_max)` visibility interval, and the
  builder optionally *splits* a motion primitive into N references with
  tighter per-interval bounds, controlled by the user-exposed
  "BVH Time Steps" parameter. This is Cycles' deliberate trade for
  build speed versus traversal speed. See §2.3.
- **PBRT-v4 does it differently:** wraps animated geometry in
  `AnimatedPrimitive`/`AnimatedTransform`, computes a `MotionBounds()`
  AABB-over-time, and lets the BVH treat the motion union as a static
  bound. Decomposes transforms into (T, R as quaternion, S) and
  *slerps* rotation. ~5.4× the per-instance footprint vs static. See
  §2.4.
- **Astroray's right path is Cycles-shaped, not PBRT-shaped**, because
  (a) we already ship a flat `LinearBVHNode` SAH builder that mirrors
  Cycles' node layout, (b) we have no instance/`TransformedPrimitive`
  abstraction to extend, and (c) the GPU BVH (`GBVHNode`, 32 bytes) is
  already laid out for cache-coalesced traversal of a single bounds
  field per node — switching to per-time-step node bounds would balloon
  the structure or require a parallel motion-bounds array.
- **Camera motion blur (Phase A) is cheap and standalone**: a 1–2 week
  task that touches `Camera::getRay` and the renderer's per-pixel loop,
  with zero scene-upload or BVH changes. Object and deformation phases
  are 2–3 weeks each and require BVH work.
- **Wavefront (pkg55) interaction is significant.** Whoever implements
  pkg88 Phase B/C must coordinate with pkg55-B/C: the SoA path state
  needs a `time[i]` field (4 bytes/path), and `stage_intersect` must
  call a time-aware BVH traversal. This is flagged but not designed in
  this round.

Total estimate: 5–7 weeks across four phases.

---

## §1 — Problem statement

### 1.1 What motion blur is

Motion blur is the temporal integral of incident radiance at the sensor
across a finite shutter open interval. The pixel value `I(x, y)` becomes:

```
I(x, y) = ∫_{t=0}^{Δ} L( ray(x, y, t), t ) dt
```

where `ray(x, y, t)` is the camera ray for pixel `(x, y)` evaluated at
time `t`, and `L(ray, t)` is the radiance returned by tracing that ray
through a scene whose geometry is also parametric in `t`.

A path tracer estimates this integral by Monte Carlo: pick `tᵢ ∈ [0, Δ]`
per sample, trace `ray(x, y, tᵢ)` through a `t=tᵢ` snapshot of the
scene, accumulate. The cost is bounded by the same `N` samples we
already pay for antialiasing; we just spend one extra random dimension
per sample. This is the Cook–Porter–Carpenter result.

Reference: Cook, R.L., Porter, T., Carpenter, L., "Distributed Ray
Tracing", SIGGRAPH '84, DOI [10.1145/800031.808590](https://dl.acm.org/doi/10.1145/800031.808590).
PDF: <https://artis.inrialpes.fr/Enseignement/TRSA/CookDistributed84.pdf>.

### 1.2 What's missing in Astroray today

Surveyed against the current codebase (branch `main` @ a71100a):

| Surface | Today | What motion blur needs |
|---|---|---|
| `Ray::time` (include/raytracer.h:391) | Field exists, always set to `0.0f` | Sampled `t ∈ [0, Δ]` per spp |
| `Camera::getRay` (include/raytracer.h:1715) | Static camera basis (`origin, u, v, w_axis`) | Interpolated camera at sampled time |
| `Camera` shutter state | None | `shutterDuration`, `shutterPosition`, optionally `shutterCurveCDF`, pre/post camera transforms |
| `Hittable::hit` family | Static | Time-aware variant; intersection of triangles with interpolated vertices |
| `BVHAccel` (include/raytracer.h:1060) | Static AABB per node | Either motion-aware bounds, or per-primitive time interval + leaf split |
| `LinearBVHNode` (include/raytracer.h:1052) | 32 B static `AABB bounds` | Possibly two bounds (`bounds[0]`, `bounds[1]`) for pre/post, or a parallel motion-bounds array |
| GPU `GBVHNode` (include/astroray/gpu_types.h:212) | 32 B, mirrors CPU exactly | Same dilemma on device side |
| `Triangle` (include/astroray/shapes.h via pkg04) | Single `v0,v1,v2` | Per-vertex motion attribute array (multiple time steps) for deformation |
| Scene upload (`src/gpu/scene_upload.cu`) | One-shot static copy | Either per-shutter-step rebuild, or motion-primitive expansion + upload once |
| Wavefront SoA (`include/astroray/integrator_state_soa.h`) | No `time` field | `time[i]` per concurrent path; intersect stage consumes it |
| Blender addon (`blender_addon/__init__.py`) | Single `depsgraph` snapshot per render | Multi-step `depsgraph.scene_eval.frame_set(frame, subframe)` or `engine.frame_set()` to sample motion |

Current usages of `Ray::time` (grep): the field is initialised, copied
on ray transformation, and never read for any decision. So adopting
time-parametric rays does not require touching the BSDF/integrator code
in any way that affects determinism for the static `t=0` case — every
existing test continues to pass with `Camera::getRay` writing `0.0f`.

---

## §2 — Algorithm survey

### 2.1 Time as a stochastic ray dimension

Stratify `t` across spp. Three common patterns, ranked by quality:

1. **Stratified-by-sample**: for `spp = N`, sample `i ∈ [0,N)` gets
   `tᵢ = (i + ξ) / N · Δ` with `ξ ∈ U[0,1)`. Best variance for shutter
   integration; what Cycles does (see `init_from_camera.h`, sample 0 is
   the special centre case, all others stratified via
   `path_rng_3D()`).
2. **Quasi-Monte-Carlo over (pixel, lens, time)**: Sobol or Halton with
   time as the first dimension — Cycles' actual strategy. The comment
   in `init_from_camera.h` notes time is `rand_time_lens.x` "for better
   convergence with Sobol sampling for motion-blurred, out-of-focus
   objects." Astroray's current pixel sampler (Halton, jittered box
   filter, see Renderer::renderFrame) extends cleanly.
3. **Plain jittered uniform**: `tᵢ = ξᵢ · Δ`. Sufficient for Phase A
   validation but visibly noisier than (1) at low spp.

**Shutter curve** (non-rectangular shutter): Cycles exposes a 1D
`shutter_curve` controlled by the user and stores its inverted CDF.
Sampling becomes `t = invCDF(ξ)`. PBRT v4 does not expose this; it
assumes a box shutter. **Recommendation:** punt to Phase A.1 or later —
the curve helps cine artists but adds zero structural complexity once
Phase A is in.

**Shutter position** (Cycles: "Start on Frame" / "Centre on Frame" /
"End on Frame"): only affects the meaning of `t=0`. Internally `t ∈
[0, 1]` and the addon decides what world-time interval that maps to.
Trivial.

References:
- Cycles `intern/cycles/kernel/integrator/init_from_camera.h` (Apache-2.0),
  fetched 2026-05-14: time is sampled via `rand_time_lens.x` and passed
  to `camera_sample()`. Sample 0 uses pixel centre but still stratifies
  time. ([github.com/blender/cycles](https://github.com/blender/cycles/blob/main/src/kernel/integrator/init_from_camera.h))
- Cycles `intern/cycles/scene/camera.cpp` (Apache-2.0): `shutter_curve`,
  `transform_motion_decompose()`, `motion_position`,
  `rolling_shutter_type/duration`, `use_perspective_motion`.
- PBRT v4 sampler camera-sample time: a single `Float time` in
  `CameraSample`, mapped to `Lerp(time, shutterOpen, shutterClose)`.
  See pbr-book.org §6.1 (3rd ed., still accurate for v4 box-shutter
  case).

### 2.2 Three independent motion sources

| Source | What varies with `t` | Storage delta | Sampling cost |
|---|---|---|---|
| **Camera** | Camera origin, basis vectors, focal length / FoV, lens | Two `Camera` snapshots (pre/post), or N keyframes for slerp | O(1) per ray |
| **Object** (rigid) | Per-object world transform | Per-object `Transform[K]` array, `K=2` typically | O(1) per intersection (rare for top-level non-instanced scenes) |
| **Deformation** | Per-vertex positions (skinning, sim) | Extra vertex buffer of size `nVerts × (Ksteps−1)` | O(1) per triangle test if leaf-split; otherwise O(Ksteps) interpolation lookups |

All three compose: a deforming character on a moving platform shot by a
panning camera all add up. Cycles makes each independently
toggleable; the user enables them via the render properties panel
("Motion Blur" master toggle, then per-object `cycles.use_motion_blur`
and `cycles.use_deform_motion`).

For Astroray, object motion blur is **less important than camera and
deformation** for two reasons: (a) Astroray's scene model is
flat — there is no first-class "instance" or animated transform stack;
objects are baked into world space at scene-upload time. (b) Most
visible motion in test footage comes from camera and from deforming
characters/fluids. We still implement it (Phase B) but it's worth
noting it's the least-bang-for-buck of the three for our user base.

### 2.3 Cycles' motion BVH — per-primitive intervals, not per-node bounds

This is the most-cited surprise of the research: **Cycles' BVH stores
motion at the primitive level, not the internal-node level.** From the
[Behind The Pixelary blog post](https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance)
and the Blender DeepWiki page on
[Acceleration Structures](https://deepwiki.com/blender/cycles/2.5-acceleration-structures):

> "Cycles' custom BVH supports motion blur at the primitive level, not
> at intermediate nodes."

Mechanically:

1. For each motion-blurred triangle, Cycles evaluates the triangle's
   AABB at each of the user's "BVH Time Steps" (`num_bvh_time_steps`,
   typically 1–3). It treats the result as **N − 1 BVH references**,
   one per interval `[tᵢ, tᵢ₊₁]`, each with its own tight AABB and a
   stored `prim_time = float2(tᵢ, tᵢ₊₁)` visibility interval. This is
   the "split motion primitives" approach, landed in commit
   c4890cd354 ("Cycles: Add option to split triangle motion primitives
   by time steps", documented in the
   [bf-blender-cvs mail archive](https://www.mail-archive.com/bf-blender-cvs@blender.org/msg78676.html)).
2. The SAH builder then sees N − 1 references instead of one and packs
   them into the tree; internal-node bounds union normally. No motion
   awareness in the node format itself.
3. At traversal time, the leaf intersection function (`motion_triangle_intersect`)
   first early-outs if `ray.time < prim_time.x || ray.time > prim_time.y`,
   then evaluates the interpolated vertex positions at `ray.time` and
   intersects.
4. Per the commit message, BVH time steps trade memory for traversal
   speed in a strongly favourable way at low motion (46 s → 27 s → 18 s
   → 15 s as steps go 0 → 3, with memory 260 → 826 MB on the documented
   benchmark).

For *rigid-object* motion blur, Cycles uses a different mechanism: a
`__OBJECT_MOTION__` kernel feature flag, decomposed
`DecomposedTransform[motion_steps]` arrays per object stored in
`object_motion`, and the leaf intersection applies the inverse of the
time-interpolated object transform to the ray before triangle
intersection. The BVH is built in object-local space and is therefore
*itself static*. The motion is realised by transforming the ray, not
the geometry. This is essentially Cycles' analogue of PBRT's
`AnimatedTransform`.

Bottom-line for Astroray (no instance system yet): we'd implement
deformation motion blur the Cycles way (per-primitive split + leaf
intersection), and object motion blur effectively by *baking* into
deformation — the few keyframe transforms get applied to each vertex
and the result is fed through the deformation pipeline. This trades a
factor of N memory for not needing an instance abstraction. Acceptable
for now; flag for revisit when instancing arrives.

Sources:
- Cycles `intern/cycles/scene/object.cpp` (Apache-2.0): per-object
  `array<Transform> motion`, `object_motion_pass`, `object_motion`,
  `motion_offset`, `num_tfm_steps`, `num_geom_steps`. Two modes:
  `MOTION_PASS` (pre/post transforms for the motion AOV — already what
  pkg72 mirrors for motion vectors) and `MOTION_BLUR` (decomposed
  transforms for interpolation).
- Cycles `intern/cycles/kernel/geom/motion_triangle.h` (Apache-2.0):
  linear interpolation only — `(1-t)*verts[step] + t*verts[step+1]`.
  Normals likewise, re-normalised post-blend. No Hermite, no spline.
  This is the same simplicity Pixar's RenderMan and Mitsuba 3 ship
  with.
- Manual: <https://docs.blender.org/manual/en/latest/render/cycles/render_settings/motion_blur.html>
  (403 over WebFetch from sandbox; user-facing surface confirmed via
  the [BlenderWiki 2.71 release notes](https://archive.blender.org/wiki/2015/index.php/Dev:Ref/Release_Notes/2.71/Cycles/)
  and the [Pixelary perf post](https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance)).

### 2.4 PBRT-v4's approach — `AnimatedTransform` + `MotionBounds()`

Different design, worth knowing because it's cleaner for first-pass
implementations:

- `AnimatedPrimitive` wraps a `Primitive` (which may itself be a BVH of
  many triangles in object space) plus an `AnimatedTransform`.
- `AnimatedTransform` stores `startTransform`, `endTransform`,
  `startTime`, `endTime`, plus a *decomposition* of each into
  `T[2]`, `R[2]` (quaternion), `S[2]` (4×4 scale/skew). At interpolate
  time: `T = lerp`, `R = slerp` (Shoemake 1985), `S = lerp` of matrices
  (PBRT §6.1.5). The decomposition is ~696 bytes/instance vs 128 bytes
  for static `Transform`.
- `MotionBounds(Bounds3f localBounds)` computes a conservative
  world-space AABB over the entire shutter — using the analytical
  result that any point's motion under a slerp-interpolated transform
  is bounded by a sphere swept along a curve. Source:
  `src/pbrt/util/transform.h`/`.cpp` in pbrt-v4 (Apache-2.0).
- The outer BVH uses these motion bounds as static AABBs. Each
  `AnimatedPrimitive::Intersect()` does an inverse-transform of the
  ray at `ray.time` and recurses.

This is the canonical "instance-with-AnimatedTransform" path. We'd
want it eventually for true instancing. Today we don't have
`TransformedPrimitive`, so this is filed as a Phase B *alternative*
for if and when an instance system lands. Per §2.3 we proceed with
the Cycles-shaped path.

Sources:
- PBRT v4 `src/pbrt/util/transform.h`/`.cpp` (Apache-2.0):
  `AnimatedTransform` decomposition into `Vector3f T[2]`,
  `Quaternion R[2]`, `SquareMatrix<4> S[2]`, plus `MotionBounds()`,
  `BoundPointMotion()`. Confirmed via WebFetch 2026-05-14.
- PBRT v4 `src/pbrt/cpu/primitive.h`/`.cpp` (Apache-2.0):
  `AnimatedPrimitive` parallels `TransformedPrimitive`.
- pbr-book.org §3.8 (motion blur), §6.1.5 (animated transforms),
  §13 (sampling). Apache-2.0 ref-impl, CC BY-NC-ND for the prose
  (citation only, no prose mirroring).

### 2.5 Quaternion slerp recap

For the Phase B object-motion-blur path, we'll need slerp for rotation
even if we go the "bake into deformation" route — because baking N
keyframes by linearly interpolating the matrix elements is *wrong*
under rotation (linear blend of rotation matrices is not a rotation;
it shrinks). Two options:

1. Decompose `M = T · R · S`, slerp `R`, lerp `T` and `S`, recompose.
   PBRT does this. ~12 floats of state per keyframe pair after
   decomposition.
2. **Polar decomposition** (Shoemake & Duff 1992,
   "Matrix Animation and Polar Decomposition"). More robust for
   shear-containing matrices but slower. Used by Mitsuba.

Recommendation: PBRT's decomposition. Same trick, well-validated, the
reference code is right there to mirror.

### 2.6 Cook–Porter–Carpenter on stochastic shutter sampling

Section 2 of the 1984 paper is exactly what we want. Two-sentence
summary: each pixel sample is one ray; that ray carries a time
sampled from the shutter PDF; everything else (depth of field,
penumbras, glossy reflection, motion blur) falls out for free as
additional sampling dimensions on the same ray. There is no separate
"motion blur pass" in a Cook 1984-style renderer.

Astroray already follows this architecture (we sample lens + pixel
per ray for DoF + AA). Time is the missing fifth dimension. There is
no clever Christensen–Jarosz 2016 / shutter Russian-roulette
optimisation that's worth implementing — the standard approach is
already tight.

### 2.7 What's *not* in scope here

- **Rolling shutter** (Cycles `rolling_shutter_type`,
  `rolling_shutter_duration`): time becomes a function of `y`-pixel.
  Useful for matching CMOS camera footage; non-trivial integration.
  Push to a future spec.
- **Per-bounce motion blur** (motion of light sources during shutter):
  Astroray's NEE samples `light` at the same time the BSDF samples
  `ray.time`. If lights are baked into world space, light motion is
  automatic once `Renderer` is time-aware. No extra work needed beyond
  Phase B+C, *if* lights' world transforms are part of the per-object
  motion pipeline. Worth a one-line note in pkg88; not a separate
  phase.
- **Motion-aware OptiX denoiser** (pkg73) — pkg72/pkg73 already cover
  the motion-vector AOV path that consumes per-frame camera motion.
  Per-sample motion blur is *mutually exclusive* with temporal
  denoising in Cycles, and we should adopt the same constraint to
  avoid the design rabbit hole. Cite the
  [motion-vectors-research.md](./motion-vectors-research.md) note's
  finding on this: Cycles enforces this exclusivity at the UI level.
- **Stepped / fake motion blur** (multiple discrete sub-frames
  composited): a compositor trick. Not a renderer feature.
- **Spectral/wavelength-dependent shutter** (chromatic aberration
  over time): exotic; defer.

---

## §3 — Implementation phases

The split below assumes Phase A lands standalone (deliverable on its
own), Phase B and C land after, and Phase D piggybacks on pkg55-B/C.

### 3.1 Phase A — Camera motion blur (1–2 weeks)

**Scope:** the camera moves during the shutter. Geometry is still
static.

**What changes:**

1. `Camera` grows pre/post transform state. Either store
   `prevOrigin/prevU/prevV/prevW` (already there for pkg72 motion
   vectors — perfect, we can reuse exactly that snapshot) plus a new
   `nextOrigin/...` for the post-shutter pose, or store a single
   `Transform[2]` of decomposed (T, R, S). Recommend the latter; align
   with PBRT pattern; pkg72's snapshot is the "previous frame", which
   is conceptually different from "previous shutter open" but in
   common cases the same.
2. `Camera::getRay(s, t, gen)` becomes `getRay(s, t, time, gen)`. The
   sampled `time ∈ [0, 1]` is interpolated to rebuild the camera basis
   in-place per ray:
   - `origin = lerp(o0, o1, time)`
   - `(u, v, w) = slerp(rot0, rot1, time)` decomposed-recomposed
   - `lowerLeft`/`horizontal`/`vertical` recomputed (cheap; can be
     pre-cached if shutter is small and we want the integrator to be
     fast; not required for correctness).
3. `Renderer` samples shutter time per spp via the existing pixel
   sampler. Stratify across `spp` with `time = (i + ξ) / spp`.
4. `Ray::time` is set to the sampled value. **Nothing downstream
   reads it yet** — that's Phase B. So Phase A's "correctness" is
   purely the camera moving across the shutter, which produces the
   correct streaks for the static scene under camera pan.

**Astroray integration points:**

| File | Change |
|---|---|
| `include/raytracer.h` Camera | Add `Transform shutterStart, shutterEnd` (or `Vec3 originStart/End` + slerp quat). Modify `getRay()` to take `float time` and lerp/slerp. |
| `include/raytracer.h` Renderer / `renderFrame` | Sample `time` per spp; pass to `getRay`. |
| `src/gpu/cuda_renderer.cu` `GCameraParams` upload | Upload both keyframes; device-side `camera_get_ray()` interpolates. |
| `src/gpu/path_trace_kernel.cu` `init_rng`/path init | Sample time, pass to camera function. |
| `blender_addon/__init__.py` `convert_scene` | Read `scene.render.use_motion_blur` and `scene.render.motion_blur_shutter`; emit shutter-pre and shutter-post `matrix_world` by calling `engine.frame_set(frame, subframe=-shutter/2)` and `frame_set(frame, subframe=+shutter/2)` per `scene.render.motion_blur_position`. |

**Scene-upload changes:** *None*. The CPU BVH is untouched. The GPU
BVH is untouched. Only `GCameraParams` grows from one set of basis
vectors to two (or to T/R/S decomposition).

**Why this is cheap:** the BVH never sees a time-parameterised query.
Every triangle is exactly where it was. Only `Camera::getRay` cares
about `t`, and it's a 10-line change.

**Validation:** render a static cube while panning the camera at 64
spp; pre/post the change, before should produce a crisp cube, after
should produce a horizontally-blurred cube. SSIM vs ground truth (a
2048-spp camera-blur render with the same shutter) ≥ 0.97. See §7.

### 3.2 Phase B — Object motion blur (2–3 weeks)

**Scope:** rigid-body motion of meshes during the shutter. Camera
already covered (Phase A). Deformation still static.

**Strategy chosen:** *bake into deformation*. Per the §2.3 rationale,
Astroray has no instance system, so per-object animated transforms
would require building one from scratch. Instead, we bake: the Blender
addon evaluates each animated object's `matrix_world` at K shutter
sub-times, transforms vertices to world space at each, and emits the
resulting vertex set as if it were deformation motion. The renderer
sees only deformation motion, never object motion.

This is suboptimal for animation-heavy scenes (cost scales linearly
with `K` per moving object). But it makes the renderer simpler and
defers the instance question to a future spec.

**Renderer-side changes** are therefore folded into Phase C. **Phase
B is purely an addon-side and scene-upload change**:

1. Blender addon does `engine.frame_set(frame, subframe=ξₖ)` for each
   of K motion steps (`K = scene.render.motion_blur_steps`, default 1
   in Cycles = pre/post only).
2. For each animated object, capture `obj.matrix_world @ vertex` for
   every vertex. Emit as a deformation vertex buffer.
3. Upload to GPU as a deformation attribute (see Phase C).

**Open design question** (escalated to §6): is "bake into deformation"
acceptable as a permanent answer, or should we plan a proper instance
system later? Recommend permanent unless/until pkg72.X reveals
performance hot-spots.

### 3.3 Phase C — Deformation motion blur (2 weeks)

**Scope:** per-vertex positions vary with time. Drives both
deformation (character animation, soft bodies, fluids) and — via §3.2
baking — object motion.

**What changes:**

1. `Triangle` (in `include/astroray/shapes.h` per pkg04) grows an
   optional `Vec3 v0_motion[K-1], v1_motion[K-1], v2_motion[K-1]`
   attribute, or — better — the triangle stores a *pointer* into a
   shared scene-wide vertex motion buffer keyed by vertex id.
   Cycles' approach is the latter
   (`ATTR_STD_MOTION_VERTEX_POSITION` mesh attribute, vertices stored
   per-step, center step omitted to save space). Mirror that.
2. `Triangle::hit` becomes time-aware: at `ray.time`, find the two
   bracketing motion steps `(s, s+1)`, compute
   `v_interp = (1-α)·v[s] + α·v[s+1]` (Cycles linear blend, see §2.3),
   intersect.
3. `BVHAccel`: switch motion primitives to the "split by time step"
   strategy (Cycles' `num_bvh_time_steps`). For each motion triangle,
   compute its AABB at K time steps, emit K-1 BVH leaf references each
   carrying `prim_time = float2(tᵢ, tᵢ₊₁)` and bounds of that sub-
   interval. SAH builder treats each reference as a normal primitive.
   - The `LinearBVHNode` struct doesn't grow; we still have 32 bytes.
   - We grow a parallel `std::vector<float2> primTime` indexed by
     primitive-offset, sized to the *expanded* primitive count.
   - Leaf intersection function reads `primTime[primIndex]` and
     early-outs if `ray.time` is outside.
4. GPU side: same structure mirrored. `GBVHNode` unchanged; a new
   `d_primTime: float2*` parallel array.
5. Scene upload: emit the motion-vertex buffer once, after pkg55-B/C's
   buffer pool is ready or alongside.

**Cost model:** `num_bvh_time_steps = 2` (the Cycles default for
"on") roughly doubles BVH leaf primitive count on the moving
subscene. Render time per the
[Pixelary benchmark](https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance)
*decreases* from the `num_bvh_time_steps = 0` baseline because of
tighter bounds, despite the larger tree. We should expect the same
shape on Astroray.

**Validation:** translating-cube test (single object, linear
translation, 64 spp); render with motion blur on vs. off; on-version
should show streaking; SSIM vs 2048-spp reference ≥ 0.97. Add a
deforming-bunny test (vertex animation cache) for the deformation
proper. See §7.

### 3.4 Phase D — Wavefront integration (1 week, blocked on pkg55-B/C)

**Scope:** the wavefront SoA path tracer (pkg55) needs to know about
ray time too.

**What changes** (designed at the contract level, not in detail —
that's pkg88's downstream concern when pkg55-B/C lands):

1. `IntegratorStateSoA` gains `float* time` (4 B/path × 65 536 paths =
   256 KB). Allocation in `src/gpu/wavefront/stage_init.cu`.
2. `stage_init` samples shutter time per path and writes `time[i]`.
3. `stage_intersect` reads `time[i]` and passes to a time-aware
   `gpu_bvh_hit_motion(...)` variant. The variant checks
   `prim_time` per leaf and interpolates vertices at hit.
4. `stage_shade` and downstream stages are unchanged (radiance and
   BSDF eval are time-independent; the geometry already snapped to the
   correct time at intersect).

**Risk:** if pkg55-B/C lands *before* pkg88 Phase C, we'll have to
add the `time[i]` field in a follow-up that touches the wavefront
hot path. To avoid double-touching, pkg88 Phase D should ideally land
**immediately after pkg55-B/C** but in the same round. Surface this
to whoever schedules pkg55 vs pkg88.

If pkg55-B/C is not yet final when this research is read: pkg88 Phase
D may need rework after pkg55's final SoA layout. We are not
designing it here.

---

## §4 — Astroray integration points (detailed)

Cross-reference for the future pkg88 implementer.

### 4.1 Where shutter time is sampled

**Insertion point:** `Renderer::renderFrame()` (the per-pixel,
per-sample loop). The existing pixel sampler is the natural carrier
for the time dimension.

Strawman:

```cpp
// Inside the spp loop, after sampling pixel (s, t) and lens (u, v):
float xi_time = haltonSample(sampleIndex, dim_time);   // or stratified
float ray_time = xi_time;                              // ∈ [0, 1]
Ray r = camera.getRay(s, t, ray_time, gen);
// trace as before
```

`dim_time` is a new Halton dimension (we already use dimensions for
pixel + lens; per `wavefront-gpu-research.md`, Halton indices ~6 are
where DoF and pixel-jitter live, so time can take dim 8 or 9).

### 4.2 Camera changes

`Camera::getRay(float s, float t, float time, std::mt19937& gen)`
becomes the new signature. Default value `time = 0.0f` preserves
behaviour for non-motion-blur tests, but we should NOT use a default —
require all callers to pass it, even if explicitly 0, to keep the
contract visible.

Internal: interpolate basis vectors. Easiest first cut: linearly lerp
`origin`, `u`, `v`, `w_axis` between two stored snapshots. This is
incorrect for large rotation (matrix-elements-of-rotation lerp isn't
a rotation) but Phase A scenes typically have <5° rotation per
shutter, where the error is sub-pixel. Phase A.1 (or a sub-PR)
upgrades to slerp.

### 4.3 BVH motion (Phase C)

Files touched in `BVHAccel` construction (`include/raytracer.h:1131`):

- Constructor takes an optional `std::vector<MotionVertexBuffer>`
  parameter (or per-primitive motion data). For each primitive that
  reports motion, expand to K-1 references with per-interval AABBs.
- `LinearBVHNode` stays 32 B. The flat `nodes` array uses primitive
  offsets that point into the *expanded* primitive list.
- New parallel array `std::vector<float2> primTimes` indexed by
  primitive offset.
- `BVHAccel::hit` becomes time-aware: at leaf, check `primTimes[i]`
  before recursing into the primitive's `hit()`.

The existing static path (no motion primitives) is unchanged —
`primTimes` is empty or sentinel-filled and the early-out is a
predictable branch.

### 4.4 GPU scene upload

`src/gpu/scene_upload.cu` currently flattens BVH and primitives in a
single pass. Motion adds:

- A new `d_primTime: float2*` device array, uploaded alongside
  `d_primitives`. Same size as the expanded primitive list.
- A new `d_motionVertices: GVec3*` device array for deformation,
  sized `nVerts × (K - 1)`. The center step uses `d_triangles` as
  today (no duplication, mirrors Cycles).
- `GCameraParams` grows to carry both pre/post camera state, or a
  decomposed (T, R, S) pair.
- `uploadScene()` reads new state from `Renderer` and Camera.

`scene_upload.cu` is currently 353 lines and reasonably structured;
this is an additive change, no rewrite required.

### 4.5 GPU intersection

`include/astroray/gpu_bvh.h` `gpu_bvh_hit()` (currently the static
device traversal) gets a sibling `gpu_bvh_hit_motion()` that:

1. Walks the same node tree (static bounds).
2. At each leaf, before calling `gpu_triangle_hit`, reads
   `d_primTime[primOffset]`. Skips if outside.
3. Calls `gpu_motion_triangle_hit(primOffset, ray.time, ...)`:
   - Looks up the two motion vertex sets bracketing `ray.time`.
   - Interpolates v0, v1, v2.
   - Runs the regular Möller–Trumbore intersection.

The static path remains for non-motion-blur renders. Dispatch on a
scene-level `has_motion` flag at kernel-launch time; or fold the
predicate into the leaf loop with `if (d_primTime != nullptr)` —
trivial divergence cost on a uniform-across-warp predicate.

### 4.6 Blender addon — time-stepped depsgraph

This is the part most likely to bite. The `engine.frame_set(frame,
subframe)` API exists (Blender 2.81+) and is the correct way to
re-evaluate the depsgraph at a non-integer frame for motion blur. The
addon needs to:

1. Detect `scene.render.use_motion_blur` and
   `scene.render.motion_blur_shutter` in `RenderEngine.render()`.
2. Determine shutter centre by `scene.render.motion_blur_position`
   (`'START'` / `'CENTER'` / `'END'`).
3. For Phase A (camera only): call `engine.frame_set(frame, -shutter/2)`,
   capture `scene.camera.matrix_world`, then `frame_set(frame,
   +shutter/2)` and capture again. Convert to Astroray
   `Transform`s. Restore frame at end.
4. For Phase C (deformation): the same shutter sub-frame loop, but
   for *every* animated mesh, evaluate vertex positions and stash a
   per-vertex motion buffer. Cycles' `motion_steps` per-object value
   controls how many sub-times we sample (default 1 = just
   pre/center/post).

Confirmed via search that this is the documented mechanism. Known
gotcha (Blender bug T79889 / T80373):
[`RENDER_OT_render` called with `EXEC_DEFAULT`](https://developer.blender.org/T79889)
freezes when called from Python with EEVEE motion blur enabled. Not
our issue (we're a Cycles-style RenderEngine and we're driving
frame_set ourselves), but worth being aware of when writing
addon-side tests.

References:
- [Scene.frame_set API docs](https://docs.blender.org/api/current/bpy.types.Scene.html)
- [devtalk: set_frame outside of RenderEngine class](https://devtalk.blender.org/t/how-to-set-frame-outside-of-the-renderengine-class/24624)
- [devtalk: depsgraph for arbitrary (not current) frame](https://devtalk.blender.org/t/any-way-to-evaluate-with-depsgraph-for-a-given-not-current-frame-non-destructively/26400)
- [sorecords/true_motion_blur addon (GPL3)](https://github.com/sorecords/true_motion_blur) — useful as worked example for the API call pattern; **not** as a code mirror (GPL3 vs our Apache-2.0 boundary).

### 4.7 Wavefront SoA hook (Phase D, design-only)

For pkg55 designers reading this:

- Add `float* time` to `IntegratorStateSoA` (4 B/path).
- `stage_init.cu` writes it from the same Halton/Sobol stream as the
  pixel sample.
- `stage_intersect.cu` reads it and chooses between
  `gpu_bvh_hit()`/`gpu_bvh_hit_motion()` based on a single
  scene-wide `has_motion_blur` flag.
- `path_sort_key` is unaffected — sorting by material type, not by
  time.
- No other stage needs to know about `time`.

This is the minimum surface for Phase D and should be costless
when motion blur is off.

---

## §5 — License fence (CLAUDE.md §6 compliance)

| Source | License | Use here |
|---|---|---|
| Cycles `intern/cycles/scene/object.cpp`, `kernel/geom/motion_triangle.h`, `kernel/integrator/init_from_camera.h`, `scene/camera.cpp`, `scene/bvh/*` | Apache-2.0 | Mirrorable. The Phase B/C/D implementations should port these directly with file-level "Mirrored from cycles/… (Apache-2.0)" comments and a per-routine citation. |
| PBRT v4 `src/pbrt/util/transform.{h,cpp}`, `src/pbrt/cpu/primitive.{h,cpp}` | Apache-2.0 | Mirrorable second-opinion. We won't take its `AnimatedTransform` wholesale in Phase B (we're going the Cycles route), but `Quaternion` slerp from `pbrt/util/quaternion.h` is a candidate for the camera basis. |
| Cook, Porter, Carpenter 1984 ("Distributed Ray Tracing") | ACM-published; cite as paper, no code | Cite in code comments at the time-sample insertion point in `Renderer`. |
| Shoemake 1985 ("Animating Rotation with Quaternion Curves") | SIGGRAPH paper; cite as paper | Cite at slerp call sites. |
| Shoemake & Duff 1992 ("Matrix Animation and Polar Decomposition") | Same | Cite if we later switch from T/R/S decomposition to polar decomposition. Not needed in v1. |
| sorecords/true_motion_blur Blender addon | **GPL-3.0** | **Do not mirror.** Useful only as a Python API walkthrough; any addon-side code we write must be from-scratch following the documented `bpy.types.Scene.frame_set` / `RenderEngine.frame_set` API, citing those docs and not the addon. |
| Mitsuba 3 motion blur | BSD-3 | Mirrorable second-opinion if we want it. Not needed unless Cycles+PBRT references prove insufficient. |
| Pixelary blog perf post | Editorial | Cite as a perf data source only. |
| Blender DeepWiki / mail-archive commit message | Editorial / mailing-list-archived | Cite as a sourcing breadcrumb. The actual source code we'd mirror lives in the Cycles tree. |

No GPL-only code paths anywhere in the dependency surface. Clean fence.

---

## §6 — Open design questions (the forks pkg88 must resolve)

These are **deliberately unresolved** — the implementer of pkg88 needs
to confront them before writing code, but they're the kind of decision
that benefits from being made with a half-built prototype in hand
rather than in advance. Each is phrased as a binary choice so the
implementation spec can pick one and move on.

1. **Camera basis interpolation: matrix-element lerp vs T/R/S
   decomposition with slerp.** Phase A could land with naive lerp
   (10-line change, wrong under rotation > ~5°) or with the proper
   decomposed slerp (~50 lines, correct). Recommend: lerp first (so
   Phase A ships in a week), upgrade in a Phase A.1.

2. **Object motion blur strategy: bake into deformation vs first-class
   per-object transforms.** §2.3 / §3.2 recommend "bake". Open question
   is whether to architect for a future swap (carry the keyframe
   transforms through the API even though we collapse them) or just
   collapse at the addon boundary. Recommend: collapse at the addon
   boundary; revisit when instancing arrives.

3. **BVH motion strategy: per-primitive split (Cycles) vs per-node
   bounds-over-time vs static-bounds-of-union-AABB.** §2.3 recommends
   the Cycles "split by time steps" approach because it matches our
   existing `LinearBVHNode` layout. But the simplest possible thing —
   build the static BVH using each primitive's *motion-union AABB* —
   would land in 1 day and ship correct (just slower) results. Phase C
   could be split: C.0 = static-union (1 week), C.1 = time-step split
   (1 week). Recommend: ship C.0 first, gate C.1 on a measured
   regression vs Cycles.

4. **BVH Time Steps default value.** Cycles defaults to 0 (off, no
   split) for built-in BVH and lets Embree do better. We need to pick a
   default. The
   [Pixelary benchmark](https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance)
   suggests `num_bvh_time_steps = 2` is the sweet spot. Recommend:
   default 2, expose as a render setting.

5. **Time sampling: per-spp stratified vs Sobol.** Cycles uses Sobol
   for production. Astroray currently has Halton + jittered. Halton
   over a new dimension is consistent with the rest of our sampling.
   Recommend: Halton dim 8 or 9 with stratification.

6. **Shutter curve support.** Cycles ships it. PBRT does not. Ship in
   Phase A or defer? Recommend: defer to a Phase A.2 unless an explicit
   shot calls for it.

7. **Interaction with motion-vector AOV (pkg72) and OptiX temporal
   denoiser (pkg73).** Cycles' rule: motion-blur and motion-vector AOV
   are mutually exclusive. Recommend: adopt the same rule, surface in
   the Blender addon as a UI-level constraint.

8. **wavefront integration timing.** Phase D is blocked on pkg55-B/C
   final design. Open: do we ship Phases A/B/C against the megakernel
   first (works fine; today's megakernel uses `Ray::time` 0 and would
   trivially carry a sampled time) and then add Phase D later, or wait
   for pkg55 and ship all four together? Recommend: ship A/B/C against
   the megakernel; Phase D is a thin follow-up.

9. **Per-object motion-step count.** Cycles exposes `motion_steps` per
   object (1, 2, 3, ...). For deformation, more steps = better blur
   for non-linear motion. For Astroray Phase C, do we expose
   per-object or scene-wide? Recommend: scene-wide initially; per-
   object follows if test footage shows need.

10. **Backwards compatibility of `Camera::getRay` signature.** The
    change `getRay(s, t, gen)` → `getRay(s, t, time, gen)` is breaking.
    Audit needed: all integrators (`default_integrator.cpp`,
    `path_tracer`, `multiwavelength_path_tracer`, `restir_di`,
    `neural_cache`, NRC) need updating. Trivial mechanical change but
    must be done in one PR or the build breaks. Recommend: one
    Phase-A PR touches every call site, default `time=0.0f` only at
    the Renderer level (callers always pass an explicit value).

---

## §7 — Suggested validation gates

For the future pkg88 spec, the proposed acceptance criteria. These
should be tightened by the implementer before they become contracts.

### Phase A gates

- **A1 — Pan-camera streak test.** Render a static Cornell-box scene
  at 64 spp with camera panning horizontally over the shutter
  (`shutter = 0.5` of a frame). With motion blur off, the cube's
  vertical edge is < 1 pixel wide; with motion blur on, it should be
  ≥ N pixels wide where N matches the analytically computed motion
  arc. SSIM vs 2048-spp reference ≥ 0.97.
- **A2 — Time-uniformity check.** Render a featureless white plane
  with the camera panning. Inspect per-pixel sample distribution of
  `ray.time` — should be uniform across [0, 1] within 1% per pixel
  histogram bin at 1024 spp.
- **A3 — Zero-shutter regression.** With `shutter = 0`, every test
  in the existing suite must produce identical pixels to before the
  change (`Camera::getRay` becomes degenerate to its pre-pkg88
  behaviour).

### Phase B/C gates

- **B/C1 — Translating-cube streak test.** Single cube translating
  during a 0.5-shutter window, otherwise static camera + scene; 64
  spp. Should show streaks of the correct extent; SSIM vs 2048-spp
  reference ≥ 0.97.
- **B/C2 — Deforming-bunny test.** Standard Stanford bunny with a
  hand-crafted vertex motion cache; 64 spp; output compared against
  Cycles' rendering of the same scene with identical motion-step
  count. SSIM vs Cycles ≥ 0.95 (we expect minor differences from
  shutter-curve and stratification choices).
- **B/C3 — BVH perf regression.** A static (no-motion) scene must
  not show BVH traversal regression > 2% vs pre-pkg88 baseline,
  proving the `primTime` early-out is genuinely free for the static
  path.

### Phase D gates

- **D1 — Wavefront vs megakernel parity under motion blur.** Same
  translating-cube test rendered via both paths must SSIM ≥ 0.985,
  matching the static-scene parity gate from pkg55.
- **D2 — Time field zero cost when off.** `has_motion_blur=false`
  render via wavefront must not regress more than 0.5 % vs the same
  render compiled with pkg88 reverted.

---

## §8 — Estimated effort

Per phase, including spec authoring, implementation, validation, and
PR cycles:

| Phase | Effort | Blocking |
|---|---|---|
| A — Camera motion blur | 1–2 weeks (1.5 expected) | nothing |
| B — Object motion blur (bake-into-deformation) | 0.5–1 week (small if C lands first); structurally subsumed by C | C |
| C — Deformation motion blur + motion BVH | 2–3 weeks | A |
| D — Wavefront SoA `time[i]` integration | 0.5–1 week | pkg55-B/C final SoA layout |
| **Total** | **5–7 weeks** | — |

Recommended order: A → C (B is mostly C from the renderer's point of
view) → D. Phase B is really an addon-side change once C exists.

Risk amplifiers: (a) if pkg55-B/C lands later than expected, D
slips; (b) if the Cycles BVH-time-step split proves harder than §2.3
suggests, fall back to Phase C.0's union-AABB approach and ship
slower-but-correct; (c) the Blender addon depsgraph time-stepping
has known bugs (T79889, T80373); allocate a day for working around
edge cases on Blender 5.x.

---

## §9 — References (canonical list)

### Cycles (Apache-2.0)
- `intern/cycles/kernel/integrator/init_from_camera.h` — shutter time sampling.
- `intern/cycles/scene/camera.cpp` — `shutter_time`, `motion_position`, `shutter_curve`, `transform_motion_decompose`, `rolling_shutter_*`.
- `intern/cycles/scene/object.cpp` — `array<Transform> motion`, `object_motion`, `motion_offset`, `num_tfm_steps`, `num_geom_steps`.
- `intern/cycles/kernel/geom/motion_triangle.h` — linear interpolation of vertex positions.
- `intern/cycles/scene/bvh/*` — BVH builder with motion-primitive splitting (commit c4890cd354).
- `intern/cycles/kernel/bvh/traversal.h` — `BVH_FEATURE(BVH_MOTION)`, `motion_triangle_intersect()`, `bvh_instance_motion_push()`, `prim_time` early-out.
- GitHub mirror: <https://github.com/blender/cycles>

### PBRT-v4 (Apache-2.0)
- `src/pbrt/util/transform.h`/`.cpp` — `AnimatedTransform`, decomposition into T/R/S, `Interpolate`, `MotionBounds`, `BoundPointMotion`.
- `src/pbrt/util/quaternion.h` — Shoemake slerp.
- `src/pbrt/cpu/primitive.h`/`.cpp` — `AnimatedPrimitive`.
- `src/pbrt/cameras.{h,cpp}` — shutter open/close.
- pbr-book.org §3.8 (motion blur), §6.1.5 (animated transforms).
- GitHub: <https://github.com/mmp/pbrt-v4>

### Papers
- Cook, R.L., Porter, T., Carpenter, L., "Distributed Ray Tracing", SIGGRAPH '84. DOI: [10.1145/800031.808590](https://dl.acm.org/doi/10.1145/800031.808590). PDF: <https://artis.inrialpes.fr/Enseignement/TRSA/CookDistributed84.pdf>.
- Shoemake, K., "Animating Rotation with Quaternion Curves", SIGGRAPH '85.
- Shoemake, K., Duff, T., "Matrix Animation and Polar Decomposition", Graphics Interface '92.

### Blender / Cycles docs
- Manual: <https://docs.blender.org/manual/en/latest/render/cycles/render_settings/motion_blur.html>
- Dev docs (BVH): <https://developer.blender.org/docs/features/cycles/bvh/>
- DeepWiki Acceleration Structures: <https://deepwiki.com/blender/cycles/2.5-acceleration-structures>
- Pixelary perf post: <https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance>
- Commit c4890cd354 (mail archive): <https://www.mail-archive.com/bf-blender-cvs@blender.org/msg78676.html>
- 2.71 release notes: <https://archive.blender.org/wiki/2015/index.php/Dev:Ref/Release_Notes/2.71/Cycles/>

### Blender Python API
- Scene.frame_set: <https://docs.blender.org/api/current/bpy.types.Scene.html>
- devtalk on frame_set outside RenderEngine: <https://devtalk.blender.org/t/how-to-set-frame-outside-of-the-renderengine-class/24624>
- devtalk on non-current-frame depsgraph evaluation: <https://devtalk.blender.org/t/any-way-to-evaluate-with-depsgraph-for-a-given-not-current-frame-non-destructively/26400>
- Known bugs T79889 / T80373 (EEVEE/render_OT_render motion-blur freezes).

### Astroray cross-references
- `include/raytracer.h:391` — `Ray::time`.
- `include/raytracer.h:1649` — `Camera`.
- `include/raytracer.h:1052` — `LinearBVHNode`.
- `include/raytracer.h:1060` — `BVHAccel`.
- `include/astroray/gpu_types.h:212` — `GBVHNode`.
- `include/astroray/integrator_state_soa.h` — wavefront SoA state (pkg55).
- `.astroray_plan/docs/wavefront-gpu-research.md` — pkg55 design.
- `.astroray_plan/docs/motion-vectors-research.md` — pkg72/pkg73; motion-blur vs temporal-denoise exclusivity constraint.
- `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` — wavefront phasing.
- `.astroray_plan/packages/pkg72-motion-vectors.md` — already-landed prev-camera snapshot we can reuse for Phase A's "pre" shutter pose.
- `.astroray_plan/packages/pkg88-motion-blur.md` — the promoted spec that points back here.

---

## §10 — Architect spec-promotion addendum (2026-05-14)

This addendum is appended during the spec-promotion pass that
promoted `pkg88-motion-blur-DRAFT.md` → `pkg88-motion-blur.md`. It
records the deltas between this research note and the promoted spec,
plus one external-research finding the original note missed.

### 10.1 STBVH was not considered as a third BVH motion strategy

The note (§2.3 / §2.4) framed BVH motion as a binary choice between
Cycles' per-primitive split (with `prim_time` leaf early-out) and
PBRT-v4's `AnimatedTransform` (with per-instance `MotionBounds`).
The architect pass discovered a third option that has become
production-grade since the original note:

- **STBVH — Spatial-Temporal BVH** (Woop, Benthin, Wald, HPG 2017,
  [paper](https://www.embree.org/papers/2017-HPG-msmblur.pdf))
  ships in Embree as `AABBNodeMB4D`. Per-node bounds carry both an
  AABB and a `float2` time interval; the SAH builder is replaced by
  an MBSAH (Motion-Blur SAH) that accounts for per-node temporal
  occupancy. At ≥ 4 motion steps it's measurably faster than
  Cycles' approach; at ≤ 3 steps the perf delta is small.

The note dismissed "per-node bounds-over-time" in §2.3 with the
reasoning "would balloon `LinearBVHNode` or require a parallel
motion-bounds array". That's *correct for our current 32 B node*,
but STBVH's actual gain at high motion-step counts would justify
the node growth. The promoted spec resolves Q3 by adopting Cycles'
approach for v1 (lower risk, matches existing node layout) and
filing `pkg88-stbvh` as a follow-up if measurement shows Cycles'
approach is the bottleneck.

### 10.2 Mitsuba 3 has no motion blur

The note assumed (correctly) that Mitsuba 3 was a viable third
reference. Architect-pass WebSearch confirmed (2026-05-14) that
Mitsuba 3 dropped motion blur from 0.6 → 3.0 and has not restored
it. The active production-grade references are therefore Cycles
(primary mirror) + PBRT-v4 (design citation) + Embree (STBVH
follow-up reference only). RenderMan / Arnold are commercial.

### 10.3 Fork resolutions

Of the 10 forks in §6:

- **8 resolved by architect:** Q1, Q2, Q3, Q4, Q5, Q7, Q8, Q10.
- **2 deferred to owner-preference:** Q6 (shutter curve), Q9
  (per-object motion-step count).
- **2 new owner-preference forks surfaced:** Q-Owner-3 (default
  shutter time), Q-Owner-4 (stratification policy across megakernel
  vs wavefront).

Two architect refinements beyond the note's recommendations:

- **Q1 (camera basis interpolation).** Note recommended "lerp first,
  slerp later". Spec mandates slerp from day one — the upgrade is
  small, the lerp variant is silently wrong, and shipping silently-
  wrong-math even temporarily creates downstream debugging cost.
- **Q10 (`Camera::getRay` signature break).** Note recommended a
  `time = 0.0f` default arg. Spec mandates no default; every caller
  passes time explicitly. Makes the contract visible in code review.

### 10.4 Cross-spec coordination

pkg89 (Dedicated Lights) was promoted in the same pass. The Q9
coupling ("light gets a `time` parameter") is resolved as: whichever
of pkg88 / pkg89 lands second absorbs the signature widening. Both
packages can dispatch independently of each other.
