# pkg88 — Motion Blur (Cycles parity) — DRAFT

**Pillar:** 5  
**Track:** A  
**Status:** research signed off — **not yet ready to implement**
  (research note exists, §6 design questions unresolved). The `-DRAFT`
  suffix signals this. A real `pkg88-motion-blur.md` spec gets filed
  once an implementer is about to be dispatched and the §6 forks are
  resolved.  
**Estimated effort:** 5–7 weeks across 3 phases (A camera, B object,
  C deformation, D wavefront hook)  
**Depends on:** pkg55-A.1 (done — SoA infra exists, time field can be
  added in Phase D), pkg72 (done — reusable pre-camera snapshot helps
  Phase A)

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

That note is the primary design artifact for this package. It covers
algorithm survey (Cycles vs PBRT-v4), Astroray integration points,
license fence, validation gates, and effort estimates. Read it in full
before writing the real pkg88 spec.

Key cross-references from that note:
- §2.3 — why we adopt Cycles' per-primitive motion BVH over PBRT's
  per-instance `AnimatedTransform` (no instance system in Astroray
  today).
- §3 — phased implementation plan and Astroray surface touched per
  phase.
- §6 — the unresolved design forks (10 items). **This draft cannot
  be promoted to a real spec until those are decided.**

---

## Phase list

The full plan from research §3:

| Phase | Scope | Effort | Blocking |
|---|---|---|---|
| **A** | **Camera motion blur** — `Camera::getRay` takes a sampled time; camera basis interpolated between pre/post shutter poses. No BVH or scene-upload changes. | 1–2 weeks | nothing |
| **B** | **Object motion blur** — per-object animated transforms. Strategy: *bake into deformation* at the Blender addon boundary (research §3.2). No first-class instance/animated-transform system. | 0.5–1 week (mostly subsumed by C) | A, C |
| **C** | **Deformation motion blur** — per-vertex time-varying positions. Adds a motion-vertex attribute buffer, leaf-level `prim_time` early-out, and Cycles' "split motion primitives by time step" BVH strategy. | 2–3 weeks | A |
| **D** | **Wavefront SoA integration** — adds `time[i]` to `IntegratorStateSoA`, `stage_intersect` dispatches to a motion-aware BVH traversal. Designed at contract level only here; details depend on pkg55-B/C final layout. | 0.5–1 week | pkg55-B/C |

Recommended landing order: A → C → B (B trivially follows C in the
current design) → D.

---

## Non-goals

This package does **not** do any of the following. Each is a hard stop;
escalate before expanding scope.

- **Rolling shutter** (per-scanline time offset). Cycles ships
  `rolling_shutter_type`/`duration`; we defer to a future package.
- **Motion-aware OptiX denoiser** (pkg73). Adopt the Cycles
  constraint: per-sample motion blur and the motion-vector AOV
  (pkg72) are mutually exclusive at the UI level. No work needed
  inside the OptiX denoiser path.
- **Shutter curve** (non-rectangular shutter). Default box shutter
  only. Optional Phase A.2 follow-up.
- **First-class instance + `AnimatedTransform` system** (the PBRT-v4
  pattern). We bake animated transforms into per-vertex motion
  instead. The instance abstraction is a separate future spec.
- **Hermite / spline vertex interpolation between motion steps.**
  Linear blend only, matching Cycles. Adequate for ≤ 3 motion steps.
- **Light-source motion as a separate code path.** Lights are baked
  into world space at scene-upload time, so light motion falls out of
  the Phase B+C pipeline for free.
- **Non-camera DoF interactions** beyond what's already sampled.
  Existing pixel-sampler dimensions (pixel jitter, lens) extend
  cleanly to a new time dimension; no DoF rework required.
- **Stepped/fake motion blur** (compositor trick of stacking
  sub-frame renders).

---

## Open design questions (must be resolved before implementing)

Copied from research §6 verbatim — the real pkg88 spec must pick one
answer per row and justify the call.

1. Camera basis interpolation: matrix-element lerp (fast, wrong under
   large rotations) vs T/R/S decomposition + slerp (correct, ~50
   lines).
2. Object motion blur: bake into deformation at addon boundary vs
   first-class animated-transform system.
3. BVH motion strategy: per-primitive time-step split (Cycles) vs
   per-node bounds-over-time vs union-AABB-only static BVH.
4. BVH Time Steps default: 0, 2, or other.
5. Time sampling: per-spp stratified vs Halton vs Sobol.
6. Shutter curve support: Phase A or defer.
7. Motion-vector AOV (pkg72) and OptiX temporal denoiser (pkg73)
   exclusivity: enforce at addon UI or at renderer.
8. Wavefront integration timing: ship A/B/C against megakernel and
   add D later, or wait for pkg55-B/C and ship together.
9. Per-object motion-step count: per-object setting or scene-wide
   only.
10. `Camera::getRay` signature break: one-PR sweep vs introduce
    overload and migrate gradually.

See research note §6 for recommended answers and rationale per item.

---

## When this draft becomes a real spec

When all of the following are true:

- pkg55-B (wavefront shade stage) is at least design-frozen, so
  Phase D's `time[i]` integration can be scoped.
- An implementer is available to start work in the next round.
- §6 questions 1, 2, 3, and 5 have agreed answers (the rest can be
  resolved in PR review).
- The Round NEXT_STAGE_REPORT has motion-blur in the deployable set.

At that point: copy this draft to `pkg88-motion-blur.md` (no
`-DRAFT` suffix), fill in the `## Specification` "Files to create" and
"Files to modify" tables phase-by-phase using the integration points
listed in research §4, and resolve §6 questions inline.
