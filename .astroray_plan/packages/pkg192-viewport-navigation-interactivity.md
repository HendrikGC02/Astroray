# pkg192 — Viewport navigation interactivity (3-5 fps vs Cycles ~30 fps)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** done (PR #605, 2026-08-13 — HW PASS — Suspect A only: camera-only
orbit/pan/zoom frames render with skip_upload=True, skipping the ~48ms per-frame
CPU BVH rebuild; GPU 100k-tri 1280x720 min-of-N: render 103.98->54.68ms,
frame 167.54->118.45ms, 5.97->8.44 fps. Suspect B landed separately as pkg196
(reduced-res nav, PR #609); the residual ~27ms wavefront buildSceneArrays/upload
floor remains a follow-up — see PR)
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

---

## Hardware verification 2026-08-13 (PR #605, hw-605)

**Hardware/software:** RTX 5070 Ti, Windows 11 Enterprise 10.0.26200, NVIDIA
driver 610.47, CUDA 12.8 (nvcc V12.8.61), sm_120 confirmed via
`cuobjdump --list-elf` on the fresh worktree build (`.pyd` build stamp
sha=9cc88de5, matches PR #605 head). Verified in the implementer worktree
`Astroray-pkg192` (branch `pkg192`), not the main checkout; branch was not
rebased or pushed (freeze respected).

Verifier note: the first `cmd /c build_cuda_worktree.bat ...` invocation from
Git-Bash hit the known false-green failure mode ([[gitbash-cmd-c-pathconv-false-green]])
-- banner-only output, exit 0, `.pyd` mtime unchanged. Re-ran via
`powershell -Command "& '.uild_cuda_worktree.bat' ..."`, which built for
real and confirmed sm_120. The compiled `.pyd` binary content itself did not
change (PR #605 touches only `blender_addon/*.py`, `benchmarks/`, `tests/`),
confirmed by an unchanged `.pyd` mtime post-build with an updated build stamp
SHA -- i.e. nothing to relink, as expected for a Python-only diff.

GPU was cold at test start (405 MHz idle). Burned in to steady P0
(~2895 MHz, matching the documented ~2887 MHz baseline,
[[gpu-perf-ab-clock-drift]]) with ~40s of sustained heavy rendering before
taking any timing measurement.

### 1. Re-measured before/after harness (independent re-run, not copied from PR body)

`benchmarks/viewport_parity/run.py --tris 100000 --width 1280 --height 720
--frames 40 --gpu-only --no-h3 [--camera-skip-upload]`, 3 runs per arm,
min-of-N (post burn-in, GPU steady ~2467-2895 MHz across runs):

| arm | run | render mean (ms) | frame mean (ms) | fps (1000/frame mean) | h1_upload_geometry_calls_per_frame_max |
|---|---|---|---|---|---|
| before (skip_upload=False) | 1 | 104.48 | 166.51 | 6.01 | 0 |
| before (skip_upload=False) | 2 | 103.67 | 165.38 | 6.05 | 0 |
| before (skip_upload=False) | 3 | 103.18 | 165.00 | 6.06 | 0 |
| before **min-of-3** | -- | **103.18** | **165.00** | **6.06** | 0 |
| after (skip_upload=True) | 1 | 54.46 | 115.67 | 8.64 | 0 |
| after (skip_upload=True) | 2 | 54.17 | 115.51 | 8.66 | 0 |
| after (skip_upload=True) | 3 | 54.05 | 115.49 | 8.66 | 0 |
| after **min-of-3** | -- | **54.05** | **115.49** | **8.66** | 0 |

Delta (min-of-N): render -47.6% (1.91x), frame mean -30.0%, fps +42.9%
(6.06 -> 8.66). Independently reproduces the PR body's claimed numbers
(before 103.98/167.54 ms -> 5.97 fps; after 54.68/118.45 ms -> 8.44 fps)
within run-to-run variance (<1% spread across the 3 runs per arm) -- well
clear of the ~5% clock-drift confound. **PASS.**

### 2. Correctness

**Fixed-camera equivalence** (100k-tri harness scene, 1280x720, 64 spp,
depth 6, same camera, `skip_upload=False` vs `skip_upload=True`), per-channel
mean ratio (independent-RNG, not SSIM per [[ssim-wrong-gate-for-independent-rng]]):

| channel | mean (skip=False) | mean (skip=True) | ratio |
|---|---|---|---|
| R | 0.429756 | 0.429847 | 1.000212 |
| G | 0.619995 | 0.619984 | 0.999983 |
| B | 0.827681 | 0.827091 | 0.999288 |
| overall | 0.625811 | 0.625641 | 0.999729 |

All ratios within 64-spp MC noise band (no systematic energy shift). **PASS.**

**Orbit sequence non-black/advancing** (9-frame pan+zoom+orbit path, 640x360,
16 spp, frame 0 full upload then frames 1-8 `skip_upload=True`): all 9 frames
non-black (`max > 1e-6`); consecutive-frame mean absolute pixel difference
0.108-0.143 across all 8 transitions (camera visibly moving, not a stale
blit). **PASS.**

Saved PNGs (absolute paths, this machine):
`C:/Users/hgcom/AppData/Local/Temp/claude/C--Users-hgcom-OneDrive-Astroray-Astroray-repo-Astroray/1651b099-8a7d-4e63-843e-dfb65f5d9f51/scratchpad/pkg192_bench/images/`
(`fixed_camera_skip_false.png`, `fixed_camera_skip_true.png`,
`orbit_frame00.png` .. `orbit_frame08.png`).

### 3. Visual inspection

Inspected `fixed_camera_skip_false.png` vs `fixed_camera_skip_true.png`
(checkered-quad ground plane + sky background, the harness's synthetic
scene) -- visually indistinguishable; only pixel-level independent MC noise
speckle, no systematic shift. Inspected `orbit_frame00/04/08.png` -- camera
visibly pans/zooms/orbits across the sequence (frame08 shows a rotated
viewing angle vs frame00), ground plane geometry and palette colors
unchanged. No fireflies, no banding/quantization artifacts, no NaN
(magenta/black) pixels, no mode regressions. **PASS.**

### 4. Test suite (re-run independently in the pkg192 worktree)

```
pytest tests/test_blender_viewport_session.py tests/test_viewport_parity_harness.py
tests/test_viewport_perf_stats.py tests/test_blender_viewport_passes.py
tests/test_pkg116_exporter_caches.py tests/test_pkg114_exporter_transform_dispatch.py
tests/test_blender_progressive_accumulation.py tests/test_blender_backend_policy.py
```
-> **75 passed** (0 failed), matching the PR body's claimed count exactly,
including the new guard test
`test_view_draw_camera_only_frame_skips_geometry_upload`. **PASS.**

### 5. Guard-logic sanity check (first frame after a real scene edit still uploads)

Read `blender_addon/exporter.py` `view_draw` (lines ~716-760) and
`view_update` (lines ~605-676): real scene edits fire Blender's depsgraph
update and route through `view_update`, which calls
`apply_depsgraph_updates`/`sync_viewport_scene` (full upload, sets
`_viewport_full_synced = True`) and stamps `self._viewport_camera_hash` at
the end of the same call -- *before* `view_draw` runs again. `view_draw`'s
`camera_only_frame` gate is:

```python
camera_only_frame = (
    not did_fresh_sync
    and self._viewport_full_synced
    and camera_changed
)
```

`did_fresh_sync` is `self._viewport_texture is None` (first-ever frame,
still forces upload). For a scene-edit frame with no camera motion,
`camera_changed` is `False` (the hash was already stamped by `view_update`
in the same tick), so `camera_only_frame` is `False` and the render path
takes the `skip_upload=False` default -- no regression. This is exercised
directly by `test_view_draw_camera_only_frame_skips_geometry_upload`
(asserts the initial `view_update` sync renders with `skip_upload=False`,
and only a subsequent camera-only `view_draw` renders with
`skip_upload=True`). **PASS** (code-path confirmed; guard test green).

### Anomalies

None observed. GPU clock varied 2467-2895 MHz between blocks of runs (idle
periods between harness invocations let it step down); did not confound the
~30-43% measured deltas, which are ~6-9x the ~5% documented drift band.

### Verdict: HW PASS

All 5 verification steps pass. Numbers independently re-measured (not copied
from the PR body) and corroborate the PR's claims within run-to-run noise.
