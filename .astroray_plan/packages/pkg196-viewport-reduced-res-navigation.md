# pkg196 — Reduced-resolution viewport navigation (pkg192 Suspect B follow-up)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** open (filed 2026-08-13 from the pkg192 profile — PR #605)
**Estimated effort:** M
**Depends on:** pkg192 (PR #605 — camera-only `skip_upload=True`; its profile is the
evidence base), pkg191 (progressive still-frame loop — MUST NOT be disturbed).

---

## Why this exists

pkg192's per-frame profile (GPU RTX 5070 Ti, 100k tris, 1280×720, 1 spp,
`benchmarks/viewport_parity` harness) showed that after the Suspect-A fix
(camera-only frames skip the ~48 ms BVH rebuild), the remaining orbit-frame cost
is **resolution-scaling**: ~63 ms/frame readback + display path and a ~25 ms
kernel floor at full region resolution, plus a ~27 ms unconditional
`buildSceneArrays`/upload floor (tracked separately, NOT this package). pkg192
measured 8.44 fps after Suspect A; the profile projects **~20 fps** with a
reduced-resolution navigation mode layered on top. Cycles does exactly this
(`start_resolution` progressive-resolution navigation).

## Scope

Add a reduced-resolution navigation render path to the addon viewport:

- While the camera is actively moving (the existing `camera_changed` /
  `_camera_state_hash` signal, `exporter.py` / `__init__.py`), render at
  `region.width/N × region.height/N` (N=2 or 4 — pick by measurement) and
  upscale for display.
- On settle (no camera change for a short debounce window / settle timer +
  `tag_redraw`), snap back to full resolution and hand off cleanly to the
  pkg191 progressive accumulation loop — accumulation must restart at full res,
  never accumulate across mixed resolutions.
- Cite the Cycles reference: `intern/cycles/blender/session.cpp`
  `BlenderSession::reset` + `start_resolution` (Apache-2.0) — already cited at
  `__init__.py` `_camera_substantive_state_hash`.
- Reuse the pkg192 harness switch pattern (`benchmarks/viewport_parity/run.py`)
  for before/after measurement; extend, don't fork ([scripts/README.md] rule).

## Acceptance criteria

- [ ] Measured orbit fps before/after on the same harness/scene as pkg192
      (min-of-N, burn-in per [[gpu-perf-ab-clock-drift]]); meaningful gain over
      the 8.44 fps pkg192 baseline (projection ~20 fps; report actuals).
- [ ] Settled image is byte-equivalent to the pre-change settled image (full-res
      convergence unchanged); no stuck low-res frames after settle.
- [ ] pkg191 still-frame progressive loop untouched and verified working
      (accumulator advances at full res after settle).
- [ ] Nav-resolution state machine covered by an addon test (mock RenderEngine
      path, real bindings for any render call).

## Hard non-goals

- No sample reprojection / TAA / motion vectors (still deferred).
- No engine/kernel changes; the ~27 ms unconditional wavefront upload floor is a
  separate follow-up (depsgraph-selective upload), not this package.
- No changes to F12 final-frame rendering.
