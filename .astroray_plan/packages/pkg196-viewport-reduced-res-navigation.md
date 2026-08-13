# pkg196 — Reduced-resolution viewport navigation (pkg192 Suspect B follow-up)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** done (PR #609, 2026-08-13 — divisor N=2; orbit fps 8.36→18.52 p50 / 8.54→18.99 min, 2.2x; 100k tris 1280×720 1spp GPU, same harness as pkg192)
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

---

## Hardware verification 2026-08-13 (PR #609, hw-609)

**Hardware/software:** RTX 5070 Ti, Windows 11 Enterprise 10.0.26200, NVIDIA
driver 610.47, CUDA 12.8 (nvcc V12.8.61), sm_120 confirmed via
`cuobjdump --list-elf` on the pre-existing worktree build (`.pyd` mtime
2026-08-13T22:34:59+10:00, newer than the last engine-touching commit
b0e489a "pkg194" at 21:47:08 -- no rebuild needed since PR #609 diff is
Python-only: `blender_addon/exporter.py`, `benchmarks/viewport_parity/run.py`,
`tests/test_pkg196_nav_resolution.py`). Verified in the implementer worktree
`Astroray-pkg196` (branch `pkg196`, HEAD `aef09d664a3fa249b806326baf651baf0d2d505e`,
matches PR #609 head), not the main checkout; branch was not rebased or pushed
(freeze respected). GPU-only smoke check confirmed `astroray.__file__` resolves
to the canonical `build_cuda\astroray.cp313-win_amd64.pyd`, `gpu_available=True`.

### 1. fps A/B -- re-measured independently (not copied from PR body)

Harness: `benchmarks/viewport_parity/run.py --tris 100000 --width 1280
--height 720 --frames 40 --gpu-only --no-h3 --camera-skip-upload
--nav-res-divisor {1,2,4}` (same scene/settings as the pkg192 hw-605
verification). GPU clock was highly volatile this session (967-2625 MHz
observed across the run, well outside the ~2887 MHz steady-P0 baseline in
[[gpu-perf-ab-clock-drift]] despite repeated burn-in attempts at both 1M-tri
and 100k-tri loads) -- see note below.

**First pass** (3 runs per arm, sequential blocks -- divisor 1 block, then 2,
then 4):

| divisor | frame mean (ms), 3 runs | min-of-3 (ms) | fps |
|---|---|---|---|
| 1 (baseline) | 125.254, 128.988, 128.640 | 125.254 | 7.984 |
| 2 (shipped) | 60.874, 61.276, 61.941 | 60.874 | 16.427 |
| 4 | 44.650, 41.163, 41.546 | 41.163 | 24.294 |

Speedup 1 to 2: 2.058x. This ratio undershot the PR claimed 2.22x by enough to
warrant a second, more rigorous pass -- the sequential block order is
vulnerable to session-wide clock drift biasing the arms differently.

**Second pass** (interleaved in-process, order 1,2,4 repeated x5, so all three
arms sample the same clock trajectory; clock logged before/after every rep):

| divisor | frame means (ms), 5 reps | min-of-5 (ms) | fps (1000/min) |
|---|---|---|---|
| 1 (baseline) | 129.457, 127.442, 128.519, 132.765, 130.796 | 127.442 | 7.847 |
| 2 (shipped, VIEWPORT_NAV_RES_DIVISOR) | 57.298, 57.593, 58.873, 58.488, 56.943 | 56.943 | 17.561 |
| 4 | 40.675, 39.079, 39.697, 39.306, 39.149 | 39.079 | 25.589 |

Despite clock swinging 1012 to 2602 MHz within single reps, frame-mean spread
per arm was tight (<=4.3% divisor=1, <=3.3% divisor=2, <=4.0% divisor=4) --
this workload is not clock-throughput-bound at these frame times (dispatch +
launch + readback overhead dominates), so the interleaved min-of-5 is treated
as the more reliable number.

**Speedup (interleaved, min-of-5): 1 to 2 = 2.238x (127.442/56.943), fps
7.847 to 17.561. 1 to 4 = 3.261x, fps 7.847 to 25.589.**

PR body claims 8.54 to 18.99 fps (2.22x). Independent reproduction: ratio
matches within 1% (2.238x vs 2.22x); absolute fps run ~8-9% below the PR
committed numbers, consistent with session-to-session GPU variance already
documented for this exact harness/scene ([[gpu-perf-ab-clock-drift]] -- the
hw-605 pkg192 verification saw the opposite sign, its "after" arm measuring
above the PR body claim that time). Acceptance criterion ("meaningful gain
over the 8.44 fps pkg192 baseline") is unambiguously met at both measurement
passes. **PASS.**

`h1_upload_geometry_calls_per_frame_max = 0` at all three divisors -- the
reduced-res nav frame still uses the pkg192 skip_upload=True fast path (no
per-frame BVH rebuild); reduced resolution layers on top, not instead.

### 2. Settle correctness

**Code-path identity check (real GPU render, not the mock harness):** loaded
`blender_addon/exporter.py` at HEAD (post-#609) and at its parent commit
`ab4152b0a9` (pre-#609, includes pkg192/pkg193) side by side, drove
`Exporter.render_viewport_frame` directly with a real `astroray.Renderer`
(100k-tri scene, 1280x720, 64 spp accumulated in 8-spp chunks, skip_upload=True,
res_divisor=1 on the new side), and compared per-channel means:

| channel | mean (pre-#609) | mean (post-#609, divisor=1) | ratio |
|---|---|---|---|
| R | 0.430693 | 0.430682 | 0.999975 |
| G | 0.620884 | 0.620864 | 0.999968 |
| B | 0.828396 | 0.828717 | 1.000387 |

All ratios within MC noise at 64 spp (per-channel mean-ratio method, not
SSIM, per [[ssim-wrong-gate-for-independent-rng]]). The res_divisor=1 path
is numerically equivalent to the pre-#609 code -- confirms the acceptance
criterion "settled image is byte-equivalent" claim (equivalent code path,
not RNG-identical bytes, which MC rendering never guarantees run-to-run).

**No stuck low-res / accumulation-reset-on-switch:** confirmed by code read --
res_divisor is folded into the reset check in two places:
`render_viewport_frame` itself (`res_divisor != self._viewport_render_divisor`
triggers `_reset_viewport_accumulation()`, `blender_addon/exporter.py:547-551`)
and `view_draw`'s `resolution_switch` flag, which forces
`reset_accumulation=True` on the call into `render_viewport_frame`
(`blender_addon/exporter.py:764,815-816`). The addon test suite exercises
this with a mock renderer: `test_settle_snaps_back_to_full_resolution`
asserts `_viewport_current_spp == 1` immediately after the divisor flips back
to 1 (i.e. accumulation restarted fresh, not blended with the low-res
buffer), and `test_no_stuck_low_res_after_settle` drives 3 additional quiet
frames past the settle window, asserting `_viewport_render_divisor == 1`
holds on every one (no re-reduction / stuck state). **PASS.**

### 3. Visual inspection

Rendered via the real `Exporter.render_viewport_frame` production code path
(same 100k-tri scene): a converged 64-spp settled full-res frame, and single
1-spp nav frames at divisor 2 and divisor 4 (matching what a real motion tick
renders), nearest-neighbor-upscaled to region size for inspection. Caveat:
the real addon upscales via Blender's `draw_texture_2d` (GPU-textured blit,
typically bilinear-filtered), which will look smoother than the
nearest-neighbor mockup used here -- this check validates the underlying
pixel data is spatially correct, not the exact on-screen filter look.

- `pkg196_settled_fullres.png` -- clean, converged, no fireflies/banding/NaN.
- `pkg196_nav_divisor2_upscaled.png`, `pkg196_nav_divisor4_upscaled.png` --
  expected 1-spp Monte Carlo speckle plus blocky nearest-neighbor upscale
  artifacts (2x/4x pixel replication) -- this is the expected "softened, not
  broken" look for a reduced-res single-sample nav frame. No tearing, no
  quadrant misplacement, no black bands, no magenta/solid-black NaN pixels.
  No mode regression (still RGB combined pass, no spectral leak).
- Explicit NaN/Inf scan on the raw float buffers (not just the PNGs):
  nan=0 inf=0 for all three (settled full-res, divisor=2 1spp, divisor=4
  1spp); max values <=1.97 (bright-sky 1-spp variance, not a firefly
  explosion -- settled buffer maxes at 1.30, expected for an un-tonemapped
  linear buffer with a bright quad).

**PASS.**

### 4. Test suite

`tests/test_pkg196_nav_resolution.py` (all 6 pkg196-specific state-machine
tests) plus the adjacent viewport suites the PR touches indirectly
(`test_blender_viewport_session.py`, `test_blender_viewport_passes.py`,
`test_pkg191_viewport_gpu_progressive.py`, `test_blender_backend_policy.py`,
`test_blender_light_sampler_wiring.py`):

```
50 passed in 1.61s
```

(The `ModuleNotFoundError: No module named 'gpu'` tracebacks interleaved in
the output are pre-existing, caught-and-logged behavior in view_draw's
except block for the headless test environment -- not new to this PR, not a
failure; identical pattern appears in the pre-existing
`test_blender_viewport_session.py` view_draw tests.)

Broader addon-regression sweep (`test_blender_accretion_model_selector.py`,
`test_blender_auto_integrator.py`, `test_blender_camera_motion_blur_wiring.py`,
`test_blender_compositor_denoise_passes.py`, `test_blender_material_preview.py`,
`test_blender_named_uv_layers.py`, `test_blender_native_nodes.py`,
`test_blender_nonmesh_to_mesh.py`, `test_blender_object_motion_blur_wiring.py`,
`test_blender_parity_harness.py`, `test_blender_parity_matrix.py`,
`test_blender_principled_texture.py`, `test_blender_progressive_accumulation.py`,
`test_blender_uv_plumbing.py`, `test_blender_view_layers.py`,
`test_pkg193_camera_view_overlay_alignment.py`):

```
129 passed, 1 warning in 18.93s
```

(The 1 warning is an unrelated UnicodeDecodeError in a subprocess reader
thread inside test_blender_parity_matrix.py, pre-existing/cp1252-related,
not a failure and not touched by this PR.)

**PASS.**

### 5. Accumulation-reset condition sanity check

Confirmed by code read (`blender_addon/exporter.py`): res_divisor is a
first-class input to the reset decision in both call sites -- see section 2
above. Mixed-resolution accumulation blending is structurally prevented
(double guard: the low-level render_viewport_frame re-checks divisor-vs-cached
regardless of what the caller passes for reset_accumulation). **PASS.**

### Verdict: HW PASS

All 5 verification steps pass. The perf gain reproduces at the claimed order
of magnitude (ratio within 1% of the PR number; absolute fps within normal
session-to-session GPU variance for this harness). Settle correctness is
numerically confirmed on real GPU renders, not just the mock test suite.
Visual inspection found no regressions. See PR #609 comment for the full
measured table.
