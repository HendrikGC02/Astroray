# pkg88 — Motion Blur (Cycles-shaped, STBVH-aware)

**Pillar:** 5
**Track:** A
**Status:** Phases A+C.0 done (A: PR #284, C.0: PR #437, 2026-06-11 — deformation motion blur: add_triangles_bulk_motion bulk binding, time-aware Triangle::hit + gpu_triangle_hit_motion, union-AABB BVH, GRay.time end-to-end both megakernels, Camera::getRay zero-shutter carries sampled time; RTX: no-op bit-identity, CPU+GPU streak, union-AABB extremes, cross-backend motion/static energy-shift parity). REMAINING (all blocking preconditions now met, 2026-07-25):
- **Phase B — addon bake: DISPATCHABLE** (pkg114 TLAS/instancing landed; addon-only change in `blender_addon/__init__.py` `convert_scene`, no renderer surface).
- **Phase D — wavefront motion: DISPATCHABLE** (pkg55 completed via PR #524; megakernels deleted). The Phase-D scope below is superseded by the "Phase D — wavefront-only reword (post-#524)" addendum — READ IT FIRST: `path_time` and `d_motionVerts` threading already landed in the wavefront under pkg55-C4/C.0, so a large part of Phase D may already be satisfied; the remaining work is init-time shutter-time sampling + parity re-baselining, and D1's "vs megakernel" oracle no longer exists.
- **Phase C.1 — per-primitive split: perf-gated** (ships only if C.0 measures > 1.5× slower than Cycles on the B/C4 scene; not otherwise dispatchable).
**Estimated effort:** 5–7 weeks across 4 phases (A camera, B object,
  C deformation, D wavefront hook).
**Depends on:** pkg55-A.1 (done — SoA infra exists, time field can be
  added in Phase D), pkg72 (done — reusable pre-camera snapshot helps
  Phase A).
**Composes with:** pkg89 (dedicated lights — light motion falls out of
  the world-space-bake pipeline for free; see "Cross-package notes"),
  pkg86 (Light Tree — orientation-cone over time is unchanged in v1).

---

## Goal

**Before:** Astroray renders each ray at `t = 0`. Camera, mesh
transforms, and vertex positions are static across the shutter. Fast
camera pans render as razor-sharp, animated characters render as crisp
freeze-frames — visually wrong relative to Cycles output for any
non-trivial animation.

**After:** Astroray samples a shutter time `t ∈ [0, Δ]` per ray and
evaluates the camera, animated transforms, and animated vertex
positions at `t`. The Blender addon emits motion data from a
time-stepped depsgraph evaluation. Rendering a translating cube or a
panning camera at production settings produces correct streaks; Cycles
SSIM parity ≥ 0.95 on the standard motion-blur test scenes.

---

## Reference

Comprehensive research note:
[.astroray_plan/docs/motion-blur-research.md](../docs/motion-blur-research.md)

That note is the primary algorithmic source of truth. This spec
resolves the 10 design forks from research §6 and adds the
architect-spec-promotion addendum the research note carries at its tail
(STBVH evaluation — see "Design decisions" Q3).

Key cross-references from that note:
- §2.3 — Cycles' per-primitive motion BVH with `prim_time` early-out.
- §2.4 — PBRT-v4's `AnimatedPrimitive` alternative (rejected, no
  instance system).
- §3 — phased implementation plan and Astroray surface touched per
  phase.
- §4 — Astroray integration points file-by-file.
- §6 — the 10 design forks, resolved below.

---

## Phase list

| Phase | Scope | Effort | Blocking |
|---|---|---|---|
| **A** | **Camera motion blur** — `Camera::getRay` takes a sampled time; camera basis interpolated between pre/post shutter poses (T/R/S decomp + slerp from day one — see Q1). No BVH or scene-upload changes. | 1–2 weeks | nothing |
| **B** | **Object motion blur** — bake animated rigid transforms into per-vertex motion at the Blender addon boundary (no first-class instance system; see Q2). Structurally subsumed by Phase C on the renderer side. | 0.5–1 week (addon-only) | A, C |
| **C** | **Deformation motion blur** — per-vertex time-varying positions. C.0: motion-union AABB static BVH (1 week, ships correct-but-slower). C.1: Cycles' per-primitive time-step split + leaf `prim_time` early-out (1–2 weeks, gates on a measured regression vs Cycles). | 2–3 weeks | A |
| **D** | **Wavefront SoA integration** — adds `time[i]` to `IntegratorStateSoA`, `stage_intersect` dispatches to a motion-aware BVH traversal. Designed at contract level only here; details depend on pkg55-B/C final layout. | 0.5–1 week | pkg55-B/C |

Recommended landing order: A → C.0 → C.1 (only if measured) → B
(addon-only finish) → D.

**Phase progress:**
- **A done** (PR #284 + pkg103b addon wiring PR #372).
- **C.0 implemented** (branch `feat/pkg88-c0-deformation-mb`, 2026-06-10 — PR
  pending): per-triangle motion vertex buffer (`add_triangles_bulk_motion`
  bulk binding, K=2 pre/post-shutter steps, linear blend per Cycles
  `motion_triangle.h` Apache-2.0), time-aware `Triangle::hit` +
  `gpu_triangle_hit_motion`, union-AABB `boundingBox`, `GRay::time` +
  end-to-end time threading (primary/bounce/shadow rays, BOTH kernels —
  the MW megakernel samples per-spp Halton time; its camera remains
  non-interpolated, a known Phase-A gap), `d_motionVertices` upload.
  `Camera::getRay`'s zero-shutter path now carries the sampled time (the
  shutter flag gates CAMERA interpolation only; A3 holds — static scenes
  have no time consumers, verified bit-identical). RTX-verified: no-op
  bit-identity, CPU+GPU streak gates, union-AABB extremes, cross-backend
  motion/static energy-shift parity. Deformation motion on INSTANCED meshes
  (pkg114 TLAS) is out of scope v1; the wavefront/photon/SMS paths stay
  static (documented nullptr).

---

## Non-goals

Each is a hard stop; escalate before expanding scope.

- **Rolling shutter** (per-scanline time offset). Cycles ships
  `rolling_shutter_type`/`duration`; we defer to a future package.
- **Motion-aware OptiX denoiser** (pkg73). Adopt the Cycles
  constraint: per-sample motion blur and the motion-vector AOV
  (pkg72) are mutually exclusive at the UI level. No work needed
  inside the OptiX denoiser path. See Q7.
- **First-class instance + `AnimatedTransform` system** (the PBRT-v4
  pattern). We bake animated transforms into per-vertex motion
  instead. The instance abstraction is a separate future spec.
- **Hermite / spline vertex interpolation between motion steps.**
  Linear blend only, matching Cycles, Mitsuba 0.6, RenderMan. Adequate
  for ≤ 3 motion steps. Cycles' `motion_triangle.h` is the canonical
  implementation we mirror.
- **STBVH per-node spatiotemporal bounds (Woop et al., HPG 2017).**
  See "Architect addendum" below. Real measurable benefit at high
  motion-step counts (4+), but requires growing `LinearBVHNode` from
  32 B to ≥48 B and reworking the GPU `GBVHNode`. Out of scope for
  v1; surface as `pkg88-stbvh` follow-up if pkg86 + pkg88 production
  scenes show C.1 still inadequate.
- **Light-source motion as a separate code path.** Lights are baked
  into world space at scene-upload time, so light motion falls out of
  the Phase B+C pipeline for free. pkg89 lands time-agnostic (its Q9
  punts to here); when pkg89 + pkg88 are both in tree, light motion
  is implicitly correct.
- **Non-camera DoF interactions** beyond what's already sampled.
- **Stepped/fake motion blur** (compositor trick).
- **Per-bounce shutter sampling** (Christensen–Jarosz 2016) — exotic
  and not needed; standard Cook 1984 sampling is tight enough.

---

## Design decisions (forks from research §6)

This section is the resolution of every fork in research §6. Each row
has rationale and a citation. Owner-preference forks are extracted to
the next section.

### Q1. Camera basis interpolation: matrix-element lerp vs T/R/S + slerp

**Resolved by architect: T/R/S decomposition + slerp from Phase A
day one.** The research note recommended "lerp first, upgrade later",
but the upgrade is ~40 lines, has a known-good reference
implementation (PBRT-v4 `src/pbrt/util/transform.cpp`
`AnimatedTransform::Decompose` + `Interpolate`), and the lerp variant
is silently incorrect under rotations > ~5°. Shipping the wrong-math
version even temporarily creates a "works on my pan, broken on my
orbit" footgun. Ship correct math from day one.

- Reference: PBRT-v4 `src/pbrt/util/transform.{h,cpp}` (Apache-2.0).
- Algorithm: Shoemake 1985 quaternion slerp; Shoemake & Duff 1992
  polar decomposition not needed (T/R/S is sufficient for camera
  transforms which never contain shear).
- Effort delta vs the "lerp first" plan: +2–3 days in Phase A. Worth
  it.

### Q2. Object motion blur: bake into deformation vs first-class transforms

**Resolved by architect: bake into deformation at the Blender addon
boundary.** Astroray has no instance / `TransformedPrimitive`
abstraction today; building one to support object motion blur is a
weeks-of-engineering side quest. Cycles itself ships object motion
blur as a separate kernel feature (`__OBJECT_MOTION__`,
`DecomposedTransform[motion_steps]` per object) precisely because it
*has* an instance system to extend. We don't, so we collapse the
keyframes at the addon → renderer boundary. Cost: factor-K memory on
the few moving objects per scene. Acceptable; revisit when (if) an
instance system lands.

- Reference: research note §3.2.
- Open architectural decision deferred: when an instance system
  eventually lands (separate future package), `pkg88` does not block
  it — the per-vertex baked motion buffer can be replaced by a
  per-object animated transform without changing the integrator or
  BVH traversal contract.

### Q3. BVH motion strategy

**Resolved by architect: ship C.0 (union-AABB static BVH) first; gate
C.1 (Cycles per-primitive time-step split) on a measured regression
vs Cycles.**

The research note recommended Cycles' time-step split. The
architect-pass STBVH research (Embree's
[AABBNodeMB4D](https://github.com/RenderKit/embree) /
[Woop et al. 2017 STBVH paper](https://www.embree.org/papers/2017-HPG-msmblur.pdf))
revealed a third option the original note dismissed too quickly:
**per-node spatiotemporal bounds with a modified MBSAH builder**.
STBVH is genuinely more efficient than Cycles' approach at ≥ 4 motion
steps. However:

- STBVH requires `LinearBVHNode` to grow from 32 B (one AABB) to
  ≥ 48 B (one AABB + one float2 time interval + linear AABB delta),
  and a matching change to `GBVHNode`. This is a substantial GPU
  scene-upload rewrite.
- Cycles' split-by-time-step approach matches our existing node
  layout and is well-documented in the Cycles tree (commit c4890cd354).
- At the ≤ 3 motion-step counts Cycles defaults to (and Astroray will
  default to), the perf delta between STBVH and split-by-time-step is
  small per the Pixelary benchmark (~10 %).

**Decision:** C.0 ships a union-AABB static BVH (literally: each
primitive's AABB grows to enclose all time steps; the BVH is built
once and never sees time). This is correct (will not return wrong
results), just slower than Cycles on high-motion scenes. C.1 then
adds Cycles' per-primitive split if perf measurement shows C.0 is
> 1.5× slower than Cycles on a matched scene. STBVH is filed as
`pkg88-stbvh` if C.1 itself proves inadequate.

- Reference: Cycles `intern/cycles/scene/bvh/*`, commit c4890cd354
  (Apache-2.0); Woop, Benthin, Wald, "STBVH: A Spatial-Temporal BVH
  for Efficient Multi-segment Motion Blur", HPG 2017.

### Q4. BVH Time Steps default value

**Resolved by architect: default 2, expose as a render setting.**
Cycles defaults to 0 (off, no split) for built-in BVH and lets Embree
do better when present. The Pixelary benchmark shows `num_bvh_time_steps = 2`
is the sweet spot for matching the BVH build cost vs traversal cost
trade-off on moderate motion. Default 2; expose `BVHTimeSteps` slider
in render settings, valid range [0, 4]. Only consumed by Phase C.1.

- Reference:
  [Pixelary perf post](https://blog.thepixelary.com/post/160385936642/investigating-cycles-motion-blur-performance).

### Q5. Time sampling: per-spp stratified vs Halton vs Sobol

**Resolved by architect: Halton with new dimension (8 or 9) +
per-spp stratification.** Astroray's existing pixel sampler is
Halton-based (`Renderer::renderFrame`); time becomes one more Halton
dimension, consistent with how lens and pixel jitter are already
sampled. Per-spp stratification (`time = (i + ξ) / spp`) layered on
top reduces variance further at low spp. Cycles uses Sobol for time
specifically because of its production focus on out-of-focus
motion-blurred scenes; for v1, Halton is sufficient and consistent
with the rest of Astroray. Sobol upgrade is a follow-up if
measurement shows Halton's variance is the bottleneck.

- Reference: Cycles `init_from_camera.h` (Apache-2.0) for Sobol; PBRT
  §13 for sampler design; Astroray `Renderer::renderFrame` for the
  existing Halton machinery.

### Q6. Shutter curve support

**Owner-preference deferred** — see next section.

### Q7. Motion-vector AOV (pkg72) and OptiX temporal denoiser (pkg73) exclusivity

**Resolved by architect: enforce at the Blender addon UI level, not
at the renderer.** Cycles enforces the exclusivity in the addon
(grays out per-sample motion blur when temporal denoising is on, and
vice versa). The renderer can stay agnostic — if both are toggled on,
the renderer produces undefined-by-spec output and the addon is
responsible for preventing that. This keeps the renderer's
configuration surface minimal.

- Reference:
  [.astroray_plan/docs/motion-vectors-research.md](../docs/motion-vectors-research.md).

### Q8. Wavefront integration timing

**Resolved by architect: ship A/B/C against megakernel; Phase D
follows pkg55-B/C as a thin follow-up.** The research note's
recommendation. The megakernel's per-pixel loop trivially carries a
sampled time field through `Ray::time` (already in the struct). Phase
D's `IntegratorStateSoA` addition is purely additive and can land in a
separate PR once pkg55's final SoA layout is frozen.

- Reference: research note §3.4 + §4.7.

### Q9. Per-object motion-step count

**Owner-preference deferred** — see next section.

### Q10. `Camera::getRay` signature break: one-PR sweep vs overload

**Resolved by architect: one-PR sweep, no default argument.** The
research note recommended one-PR with `time = 0.0f` default. The
architect refines: **no default argument**. Every caller must pass
the time value explicitly. This makes the contract visible in every
integrator, which matters because adding motion blur is the kind of
change that's easy to silently miss in code review if the default
makes pre-pkg88 code "still compile". Mechanical change across
`default_integrator.cpp`, `path_tracer`, `multiwavelength_path_tracer`,
`restir_di`, `neural_cache`, `caustic_path_tracer`. One PR.

- Reference: CLAUDE.md §3 (surgical changes; every changed line traces
  to "carry time through the camera").

---

## Owner-preference questions deferred to owner

Each of these is a user-preference fork. Answer in this conversation;
implementer cannot start work on the affected phase until answered.

### Q-Owner-1 (was research §6.Q6): Shutter curve support

Cycles ships a 1D `shutter_curve` (box / cubic / Gaussian / custom)
with an inverted-CDF sampling implementation. PBRT-v4 does not — it
assumes a box shutter. The curve helps cine artists match physical
camera response. **Architect recommendation:** defer to Phase A.2
(out-of-scope for pkg88 v1), ship box-only.

**Question for owner:** ship Phase A with **box-shutter-only** and
defer non-box curves to a follow-up `pkg88-shutter-curve`, or include
a box+cubic+Gaussian preset list in Phase A?

**Owner answer:** **Box only in v1** (architect rec accepted, 2026-05-14). Non-box curves → `pkg88-shutter-curve` follow-up.

### Q-Owner-2 (was research §6.Q9): Per-object motion-step count

Cycles exposes `motion_steps` *per object* (default 1 = pre/post
only; range 1–7). More steps = better blur for non-linear motion
(e.g., rotating wheels). PBRT-v4 ships scene-wide only. **Architect
recommendation:** scene-wide only in v1; per-object as
`pkg88-per-object-steps` follow-up if test footage needs it.

**Question for owner:** scene-wide `motion_blur_steps` only in v1,
or per-object override exposed in Phase B from day one?

**Owner answer:** **Scene-wide only in v1** (architect rec accepted, 2026-05-14). Per-object override → `pkg88-per-object-steps` follow-up if needed.

### Q-Owner-3 (new, not in original research): Shutter time default

The shutter window `Δshutter` is a user-facing parameter. Cycles
defaults to 0.5 (= 180° shutter angle, the "film standard"), exposed
as the `motion_blur_shutter` slider in scene properties. PBRT-v4
specifies `shutterOpen` / `shutterClose` directly with no implied
default. **Architect recommendation:** match Cycles — default 0.5
frames, expose `shutter` and `shutterPosition` (`START` / `CENTER` /
`END`) in render settings.

**Question for owner:** confirm the Cycles-default (0.5 frame, center
on frame), or pick a different default?

**Owner answer:** **Cycles-default (0.5 frame, centered)** (2026-05-14).

### Q-Owner-4 (new, surfaced during architect pass): Stratification policy

Research §6.Q5 resolved to "Halton dim 8 or 9 + per-spp
stratification". The stratification has a sub-choice: should time be
**stratified across all spp jointly** (so the N samples are
guaranteed to cover [0, 1] uniformly within ±1/N) or
**domain-warped per spp** (so each sample independently draws from
[0, 1] with a single Halton dimension)? Cycles does the former
(stratified). PBRT-v4 leaves it to the sampler's prerogative. Joint
stratification gives lower variance for low spp; independent sampling
parallelizes more cleanly across the wavefront. **Architect
recommendation:** joint stratification (Cycles convention) for the
megakernel, falling back to independent Halton for the wavefront
Phase D (where joint stratification across all concurrent paths is
expensive). Megakernel result is the visual reference; wavefront
matches within the SSIM gate.

**Question for owner:** OK to ship two slightly different
stratification policies (megakernel: joint; wavefront: independent)
as long as both pass the SSIM gate, or insist on one consistent
policy across both code paths?

**Owner answer:** **One consistent policy across both code paths** (2026-05-14). Owner reasoning: consistency saves maintenance headaches when wavefront eventually subsumes megakernel via pkg55-C. Implementer should pick the policy that's tractable for both contexts (likely independent Halton at the cost of slightly higher variance at low spp; document the trade in pkg88 Lessons). Architect rec of "joint for megakernel, independent for wavefront" is OVERRIDDEN per owner direction.

---

## Architect-pass addendum (delta from research note)

The original research note (880 lines, 2026-05-14) is sound. Two
additions from the architect spec-promotion pass:

1. **STBVH (Embree's `AABBNodeMB4D`)** was not surfaced in the
   research note as a viable third BVH-motion strategy beyond Cycles'
   per-primitive split and PBRT-v4's `AnimatedTransform`. After
   architect-pass WebSearch
   ([Embree STBVH paper](https://www.embree.org/papers/2017-HPG-msmblur.pdf),
   [Embree source](https://github.com/RenderKit/embree)), it's
   confirmed to be the modern state-of-the-art *for high-motion-step
   scenes*. The research note's dismissal of "per-node bounds-over-
   time" was based on the static `LinearBVHNode` not accommodating
   per-node time intervals — which is true for our current layout,
   but STBVH's actual gain at ≥ 4 motion steps would justify the node
   layout change. For pkg88 v1 we adopt Cycles' approach because
   matching layout is the lower-risk path; STBVH is filed as
   `pkg88-stbvh` follow-up.

2. **Mitsuba 3 does not ship motion blur.** This was assumed in the
   research note but not stated. Confirmed via WebSearch 2026-05-14:
   Mitsuba 3 dropped the feature from 0.6 → 3.0 and has not restored
   it. This means the active production-grade references are
   **Cycles** (Apache-2.0, the codebase we mirror), **PBRT-v4**
   (Apache-2.0, the design we cite), and **Embree** (Apache-2.0, the
   STBVH reference if/when we file the follow-up). RenderMan,
   Arnold, and Maxwell are commercial and not citation-eligible.

3. **Q10 refinement.** Research note recommended a `time = 0.0f`
   default arg. This spec rejects defaults; every caller passes time
   explicitly. Rationale in Q10 above.

4. **Q1 refinement.** Research note recommended a two-step landing
   (lerp first, slerp later). This spec ships slerp from day one.
   Rationale in Q1 above.

---

## Cross-package notes

- **pkg86 (Light Tree).** Unaffected. The Conty 2018 metric reads
  per-light `power` / `bounds` / `orientationCone`; none of these
  are time-dependent in v1. If a future spec adds time-aware light
  tree sampling, it lands as `pkg86-temporal` / `pkg88-light-tree`.
- **pkg89 (Dedicated Lights).** Punted in pkg89's Q9 to whichever
  package lands second. **If pkg88 lands first**, the `Light::sampleLi`
  signature in pkg89 will include a `float time` parameter (added in
  this PR). **If pkg89 lands first**, this spec adds the parameter
  via the pkg88 PR.
- **pkg72 (Motion Vectors).** Phase A reuses the pre-frame camera
  snapshot already maintained by pkg72.
- **pkg55-B/C (Wavefront).** Phase D depends on pkg55-B's final SoA
  layout. See research §3.4 + §4.7.

---

## Specification (files to create / modify, by phase)

### Phase A — Camera motion blur

| File | Change |
|---|---|
| `include/raytracer.h` (Camera) | Add `Transform shutterStart, shutterEnd` (T/R/S decomposed). Add `float shutter`, `enum class ShutterPosition { Start, Center, End } shutterPosition;`. Modify `getRay(s, t, time, gen)` signature: required `float time` parameter (no default). |
| `include/raytracer.h` (Renderer / `renderFrame`) | Per spp, sample `time` from Halton dim 8 + per-spp stratification; pass to `getRay`. |
| `src/gpu/cuda_renderer.cu` (`GCameraParams` upload) | Upload both shutter keyframes (T/R/S decomposed); device-side interpolation. |
| `src/gpu/path_trace_kernel.cu` | Sample time in `init_rng`; pass to camera. |
| `blender_addon/__init__.py` (`convert_scene`) | Detect `scene.render.use_motion_blur`, read `motion_blur_shutter` and `motion_blur_position`; call `engine.frame_set(frame, subframe)` for pre+post shutter to capture both camera matrices. |
| `tests/scenes/motion_blur_camera_pan.py` (NEW) | Phase A validation scene. |

### Phase B — Object motion blur (addon-only)

| File | Change |
|---|---|
| `blender_addon/__init__.py` (`convert_scene`) | For each animated `bpy.types.Object`, capture `obj.matrix_world @ vertex` at K shutter sub-times; emit as per-vertex motion buffer (consumed by Phase C). |

### Phase C.0 — Deformation motion blur (union-AABB static BVH)

| File | Change |
|---|---|
| `include/astroray/shapes.h` (Triangle) | Add optional pointer into scene-wide motion-vertex buffer; `Triangle::hit` becomes time-aware, interpolates `(1-α) v[s] + α v[s+1]`. |
| `include/raytracer.h` (BVHAccel) | At build time, if any primitive has motion, the primitive's AABB grows to enclose all K time-step AABBs. BVH structure unchanged. |
| `src/gpu/scene_upload.cu` | Emit `d_motionVertices: GVec3*` device array, sized `nVerts × (K - 1)`; center step reuses `d_triangles`. |
| `include/astroray/gpu_bvh.h` (`gpu_bvh_hit`) | At leaf, interpolate vertices at `ray.time` before Möller–Trumbore. |
| `tests/scenes/motion_blur_translating_cube.py` (NEW) | Validation. |

### Phase C.1 — Cycles per-primitive split (gated on perf measurement)

| File | Change |
|---|---|
| `include/raytracer.h` (BVHAccel) | At build, expand each motion primitive to K − 1 references with per-interval AABB and `prim_time = float2`; SAH builder treats each as a normal primitive. |
| `include/raytracer.h` (LinearBVHNode) | **Unchanged** (32 B). New parallel `std::vector<float2> primTimes`. |
| `include/astroray/gpu_types.h` (GBVHNode) | **Unchanged**. New `d_primTime: float2*` parallel array. |
| `include/astroray/gpu_bvh.h` (`gpu_bvh_hit_motion`) | New variant; at leaf, read `d_primTime[primOffset]`, early-out if outside; otherwise interpolate vertices and intersect. |
| Render setting | Add `BVHTimeSteps` (default 2, range [0, 4]). |

### Phase D — Wavefront SoA hook

| File | Change |
|---|---|
| `include/astroray/integrator_state_soa.h` | Add `float* time` to `IntegratorStateSoA`. |
| `src/gpu/wavefront/stage_init.cu` | Sample time from same Halton stream as pixel/lens; write to `state.time[i]`. |
| `src/gpu/wavefront/stage_intersect.cu` | Read `state.time[i]`; dispatch `gpu_bvh_hit` or `gpu_bvh_hit_motion` on a single `has_motion_blur` flag. |

### Phase D — wavefront-only reword (post-#524, 2026-07-25)

PR #524 (pkg55-C7) deleted BOTH megakernels; the wavefront is the only GPU
path. Every "megakernel" reference in Q8, the Phase-D row above, and gates
D1/D2 below is stale. Corrected scope:

- **The SoA time field already exists.** `GPUWavefrontState::path_time`
  (`include/astroray/gpu_wavefront_state.h`) was added under pkg55-C4/pkg88-C.0
  — NOT `IntegratorStateSoA::time` as the table says (that struct was the
  Phase-A.1 layout, since replaced). Sampled once per path at init via
  `gpu_mw_haltonBase2(sample_idx + 1)` and carried through all bounces.
- **Motion traversal is already threaded.** `d_motionVerts` (`const GVec3*`)
  is a parameter of `launchStageAdvance` / `launchStageAdvanceQueued` /
  `launchStageIntersectQueued` and flows into the wavefront intersect, so the
  "add time[i] + dispatch motion-aware traversal" core of Phase D is largely
  DONE. **First implementer action: verify what is already live** (does the
  wavefront actually interpolate motion vertices at `path_time`, and is the
  init-time shutter sampling correct?) before writing anything new.
- **Remaining Phase-D work (if any):** (1) confirm `stage_init.cu` samples the
  shutter time on the SAME Halton stream/dimension the CPU uses (owner mandated
  ONE consistent stratification policy, Q-Owner-4; the wavefront is now the
  surviving path); (2) camera-basis interpolation over the shutter in the
  wavefront primary-ray init — the C.0 note flags the MW camera as
  non-interpolated, and that gap must not survive into the wavefront;
  (3) parity re-baseline (below).
- **Q8 is historical.** "ship A/B/C against megakernel; Phase D follows
  pkg55-B/C" is done; the megakernel reference path is gone.

### Phase D gates — reworked (megakernel oracle removed)

- **D1 (reworked) — wavefront motion correctness.** The old "wavefront vs
  megakernel SSIM ≥ 0.985" is void (no megakernel). Replace with: wavefront
  translating-cube / pan-camera streaks match the **CPU** motion result
  (per-channel mean-ratio band) AND the analytical streak extent (reuse the
  A1/B-C1 analytical arc); SSIM vs a 2048-spp wavefront reference ≥ 0.97.
- **D2 (unchanged in intent) — time-field zero cost when off.**
  `has_motion_blur=false` must not regress the wavefront > 0.5% vs the
  pkg88-reverted wavefront baseline.

---

## Validation gates

Per research §7. Tightened by architect:

### Phase A gates

- **A1 — Pan-camera streak test.** Render static Cornell-box scene at
  64 spp with camera panning horizontally over the shutter
  (`shutter = 0.5` frame). Vertical edge of static cube should be ≥ N
  pixels wide where N matches the analytical motion arc. SSIM vs
  2048-spp reference ≥ 0.97.
- **A2 — Time-uniformity check.** Per-pixel `ray.time` distribution
  is uniform across [0, 1] within 1 % per histogram bin at 1024 spp.
- **A3 — Zero-shutter regression.** `shutter = 0` produces bit-
  identical pixels to pre-pkg88 baseline across the entire test
  suite.
- **A4 — Rotating camera correctness.** Camera rotating 30° during
  shutter renders rotationally-symmetric streaks (T/R/S slerp gate;
  proves Q1's choice).

### Phase B/C gates

- **B/C1 — Translating-cube streak test.** Single cube, linear
  translation, shutter 0.5, 64 spp. Streaks match analytical extent;
  SSIM vs 2048-spp reference ≥ 0.97.
- **B/C2 — Deforming-bunny test.** Stanford bunny with vertex motion
  cache; 64 spp; SSIM vs Cycles ≥ 0.95.
- **B/C3 — Static-scene perf regression.** No-motion scene must not
  show BVH traversal regression > 2 % vs pre-pkg88 baseline.
- **B/C4 — C.0 vs Cycles perf gate.** Translating-bunny at 64 spp:
  if C.0 is > 1.5× slower than Cycles on the same scene, ship C.1.
  If ≤ 1.5×, file C.1 as "won't fix" and close.

### Phase D gates

- **D1 — Wavefront vs megakernel parity.** Same translating-cube
  test via both paths: SSIM ≥ 0.985.
- **D2 — Time-field zero cost when off.** `has_motion_blur=false`
  via wavefront must not regress > 0.5 % vs pkg88-reverted baseline.

---

## License fence (research note §5 verified)

| Source | License | Use |
|---|---|---|
| Cycles `intern/cycles/scene/object.cpp`, `kernel/geom/motion_triangle.h`, `kernel/integrator/init_from_camera.h`, `scene/camera.cpp`, `scene/bvh/*` | Apache-2.0 | Mirror with file-level "Mirrored from cycles/… (Apache-2.0)" comments. |
| PBRT-v4 `src/pbrt/util/transform.{h,cpp}`, `util/quaternion.h` | Apache-2.0 | Mirror `AnimatedTransform::Decompose` / `Interpolate` for Q1's T/R/S slerp. |
| Embree `kernels/bvh/bvh_intersector_node.h` (STBVH path) | Apache-2.0 | **Not mirrored in pkg88 v1**; reserved for `pkg88-stbvh` follow-up. |
| Cook–Porter–Carpenter 1984; Shoemake 1985 | Papers, cite-only | Comments at sample / slerp call sites. |
| sorecords/true_motion_blur Blender addon | **GPL-3.0** | **Do not mirror.** API reference only. |

No GPL-only code paths.

---

## Effort estimate (research §8 confirmed)

| Phase | Effort | Blocking |
|---|---|---|
| A — Camera motion blur (with T/R/S + slerp) | 1.5–2 weeks | nothing |
| B — Object motion blur (addon-only bake) | 0.5–1 week | A, C |
| C.0 — Deformation with union-AABB BVH | 1–1.5 weeks | A |
| C.1 — Cycles per-primitive split (gated on B/C4) | 1–2 weeks | C.0 |
| D — Wavefront SoA `time[i]` | 0.5–1 week | pkg55-B/C |
| **Total** | **5–7 weeks** | — |

---

## When this spec is ready to dispatch

When all four owner-preference questions (Q-Owner-1 through
Q-Owner-4) are answered in this conversation and the answers are
edited into the spec body above. No further architect pass required.
