# pkg192 — Viewport navigation interactivity (3-5 fps vs Cycles ~30 fps)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** in review (PR #605, 2026-08-13 — Suspect A only: camera-only
orbit/pan/zoom frames render with skip_upload=True, skipping the ~48ms per-frame
CPU BVH rebuild; GPU 100k-tri 1280x720 min-of-N: render 103.98->54.68ms,
frame 167.54->118.45ms, 5.97->8.44 fps. Suspect B reduced-res nav + the residual
~27ms wavefront buildSceneArrays/upload floor deferred to a follow-up — see PR)
(filed 2026-08-12 from owner hands-on addon feedback —
memory [[owner-addon-feedback-2026-08-12]], finding #2)
**Estimated effort:** M-L (diagnosis + cheapest high-leverage fixes only)

**Depends on:** the pkg56/pkg83/pkg114 viewport session machinery. Best filed
AFTER pkg191 lands (a stalled progressive loop confounds any fps measurement —
you need the accumulator advancing correctly before profiling frame cost).

---

## Symptom + owner framing (record verbatim in Lessons)

While orbiting the camera in the rendered viewport, Astroray runs at **~3-5 fps
vs Cycles' ~30 fps**. **The owner explicitly does NOT expect full Cycles-parity
interactivity in one package** — this is a tracked long-term gap. The goal of
this package is a **meaningful fps improvement** from the cheapest high-leverage
fixes, backed by a per-frame profile that says where the time actually goes.

---

## MANDATORY FIRST STEP — reproduce + PROFILE on a freshly built current addon

Dated-addon caveat ([[owner-addon-feedback-2026-08-12]]): the owner's build
"might have been sliiiightly dated." Before proposing any fix:

1. Build addon `.pyd` OpenMP-OFF against current `main`, verify mtime/`__file__`
   ([[stale_pyd_locations]], [[pkg119b-harness-runbook]],
   [[mingw_openmp_blender_deadlock]]), stage into Blender 5.1
   ([[blender-5-1-installed-locally]], [[addon-packaging-file-list]]).
2. **Measure the current fps** while orbiting on this build (GPU backend, a
   representative scene). This package is diagnosis-first: the profile is the
   deliverable's foundation, not an afterthought.

There is already a per-stage perf recorder wired through the viewport:
`viewport_perf_record_fn("materials"|"geometry"|"lights"|"environment"|"render",
t0)` (`exporter.py:472-486, 664`) and `viewport_perf_frame_complete_fn`
(`exporter.py:649, 665`). **Use it** — grep `blender_addon/` for
`viewport_perf_record` / `_viewport_perf` to find the sink and dump per-frame
breakdowns; do not add a parallel profiler ([[integration-first-directive-2026-08]],
scripts/README no-duplicate rule).

---

## Where camera-motion cost is paid (verified line refs, current `main`)

Camera-only moves (orbit/pan/zoom) do **not** fire a depsgraph update, so
Blender routes them to `view_draw`, not `view_update` (documented at
`exporter.py:613-614`, `__init__.py:1261-1263`). Per orbit frame,
`view_draw` (`exporter.py:678-753`):

1. detects `camera_changed` via `_camera_state_hash` (`exporter.py:700-704`,
   hash at `__init__.py:1259-1293`);
2. if changed, calls `render_viewport_frame(... reset_accumulation=
   camera_substantive_changed or settings_changed ...)` — **note it passes NO
   `skip_upload` argument, so it defaults to `False`** (`exporter.py:725-729`);
3. `render_viewport_frame` re-runs `setup_viewport_camera` +
   `renderer.render(samples, depth, …, skip_upload=False)` at the **full
   region resolution** `region.width × region.height` (`exporter.py:512-573`).

### The two prime suspects (confirm with the profiler before fixing)

**Suspect A — full geometry re-upload every orbit frame.**
`skip_upload=False` (`exporter.py:725`) means each camera-only frame pays a full
scene push to the device even though geometry is unchanged. Contrast: the
pkg114-inc3d path deliberately sets `skip_upload=True` for transform-only refits
(`exporter.py:441-444, 656-657`, and the F12 `skip_upload=True` note at
`__init__.py:3923`). A pure camera move changes **only** the camera — geometry,
BVH/BLAS, materials, lights are all identical — so it should render from current
device state with `skip_upload=True`. If the profiler shows the "render" bucket
dominated by upload (or a `geometry` bucket firing on orbit), **making camera-only
`view_draw` frames pass `skip_upload=True` is the single cheapest high-leverage
fix.** Verify the C++ `render(..., skip_upload=True)` path is safe when only the
camera changed (camera is set separately via `setup_viewport_camera`, so it
should be).

**Suspect B — no reduced-resolution navigation mode.**
Every orbit frame renders at full `region.width × region.height`
(`exporter.py:512-513`). Cycles renders navigation at reduced resolution first
(progressive-resolution / "start_resolution") and refines to full res once the
camera settles. Astroray has **no** low-res nav path. Adding one — render at
`width/N × height/N` while `camera_changed` has been true within the last few
frames, snap to full res on settle — is the standard Cycles-reference lever.
Cite `intern/cycles/blender/session.cpp` / `BlenderSession::reset` +
`start_resolution` (Apache-2.0) as the reference (already cited in
`_camera_substantive_state_hash`, `__init__.py:1300-1304`).

---

## Diagnosis-first — reproduce → localize → fix

1. **Profile** (mandatory first step above): per-frame breakdown of the
   `materials/geometry/lights/environment/render` buckets while orbiting, GPU
   backend. Establish which bucket dominates. Expected finding: `render` (with
   an embedded full upload) and/or full-res cost dominate; `geometry` should
   ideally be zero on camera-only frames — if it is NOT, that itself is a bug
   (a camera move is re-syncing the scene).
2. **Localize** the dominant cost to Suspect A (upload), Suspect B (resolution),
   or something the profile reveals (e.g. per-frame material re-convert, BVH
   rebuild, texture re-upload). Grep how a camera move could reach
   `sync_viewport_scene`/`apply_depsgraph_updates` (`exporter.py:461-502,
   605-676`) — it should NOT on a pure camera move; if it does, that is the bug.
3. **Fix — cheapest high-leverage only:**
   - (A) route camera-only `view_draw` frames through `skip_upload=True` so no
     geometry re-upload is paid on orbit; guard so the FIRST frame after a real
     scene edit still uploads.
   - (B) add a reduced-resolution navigation render while the camera is moving,
     snapping to full resolution when it settles (reuse the existing
     `camera_changed` signal + a settle timer/redraw).
   - Implement whichever the profile justifies; if both are cheap and additive,
     do both. Do NOT attempt sample reprojection / TAA / motion-vector reuse —
     out of scope, explicitly deferred to a future package.

---

## Acceptance criteria

- [ ] **Reproduced + profiled on a freshly built current-`main` addon** BEFORE
      any fix; the dated-addon caveat discharged in writing.
- [ ] A recorded **per-frame profile** (using the existing
      `viewport_perf_record` plumbing) attributing orbit-frame cost to specific
      buckets, GPU backend, before and after the fix.
- [ ] **Measured, meaningful fps improvement** while orbiting on a representative
      scene (report the before/after numbers; note the RTX clock-drift caveat —
      min-of-N, [[gpu-perf-ab-clock-drift]]). Full Cycles parity is explicitly
      NOT required.
- [ ] Camera-only frames provably avoid full geometry re-upload (Suspect A) —
      instrumented evidence the `geometry`/upload cost is gone on orbit — OR a
      documented reason that was not the dominant cost.
- [ ] No correctness regression: after the camera settles, the viewport still
      converges to the same full-resolution image (the reduced-res nav path, if
      added, must snap back to full res). Owner-visual note confirming orbit
      feels smoother and the settled image is unchanged.

## Hard non-goals

- **No full Cycles-parity interactivity target.** Owner-framed: meaningful
  improvement, not 30 fps.
- **No sample reprojection / temporal reuse / TAA / motion vectors.** Deferred.
- **No engine-side wavefront register work** ([[wavefront-shade-kernels-register-saturated]]) —
  this is an addon-loop/upload-avoidance + resolution-scaling package, not a
  kernel-perf package.
- **No changes to the still-frame progressive loop** owned by pkg191; land pkg191
  first so fps profiling isn't confounded by a stalled accumulator.
