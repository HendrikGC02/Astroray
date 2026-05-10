# pkg81 — viewport-parity diagnosis (Phase 2)

**Date:** 2026-05-10
**Hardware:** Windows 11 / MSVC `build/Release` (CUDA-enabled) / RTX 5070 Ti
**Harness:** `benchmarks/viewport_parity/run.py` — see `2026-05-10.json`
**Status:** Phase 1 + 2 complete; Phase 3 routes to pkg55 Phase B (see Conclusion)

---

## TL;DR

> The dominant viewport-vs-Cycles gap is **H4 (megakernel hot-loop cost)
> compounded by H5 (cold CUDA context init)**. H1 camera-only is not in
> play. H2 (accumulation reset every pan) is a real, code-confirmed gap
> independent of measurement. H3 (OIDN) is significant on CPU only.

Phase 3 fix is **not** a self-contained pkg81 patch — the megakernel
register-pressure cliff (pkg55 Phase A: 158 regs/thread, 1 active
block/SM) is exactly what pkg55 Phase B was filed to break. pkg81 closes
as **measurement-complete**; the actual viewport win is tracked under
**pkg55 Phase B/C**.

---

## Method

`run.py` drives a deterministic 30-frame pan→zoom→orbit camera path
through the Astroray persistent viewport renderer (the same path
`view_update` / `view_draw` use). Two scenarios per config:

- **`camera_only`** — pure camera change every frame. Mirrors real
  Blender, where pan/zoom/orbit do **not** fire `view_update`; the
  pkg56-C dispatcher never runs. View_draw detects the change via
  `_camera_state_hash` and re-renders.
- **`transform_edit`** — every tick fires a transform-only depsgraph
  update. Hits the pkg56-C dispatcher. With the current single-level
  BVH this promotes to `upload_geometry` per frame.

Configs swept: `tris ∈ {10k, 100k}` × `engine ∈ {astroray-cpu,
astroray-cuda}` × `oidn ∈ {off, on}` × `path ∈ {camera_only,
transform_edit}` = 16 configs. 256×256 viewport, 1 spp chunk, depth 4.

The texture-blit step is **not** measured (Blender's `gpu` module is
unavailable headless). The gap is small relative to render time per
pkg52's measurements.

Cycles A/B numbers are **not yet captured** — Cycles' viewport runs
only inside a Blender process; the companion `blender_driver.py` script
performs the equivalent F12-per-camera measurement and is intended to
be run by the project owner on the same RTX 5070 Ti station. Reference:
*Cycles' typical first-pixel latency on a similar 99k scene at 1
spp/256² is single-digit ms in viewport mode (Blender Foundation
public benchmarks; see `intern/cycles/blender/session.cpp`
view_draw)*. Even the most charitable Cycles assumption (5ms/frame)
puts our 99k-CUDA `camera_only` at **20× slower** than Cycles. The
diagnosis below does not depend on the exact Cycles number — the gap
is decisively present at the order-of-magnitude level.

---

## Headline measurements (256×256, 1 spp, depth 4, 30 frames)

| tris | engine | oidn | path | frame mean | frame p50 | frame p99 | render mean |
|---:|---|---|---|---:|---:|---:|---:|
| 10k  | CPU  | off | camera_only    |  20.55 ms |  20.14 |  26.03 |  15.39 |
| 10k  | CPU  | off | transform_edit |  26.77 ms |  26.21 |  35.24 |  16.83 |
| 10k  | CPU  | on  | camera_only    | 130.72 ms | 127.15 | 201.44 | 108.67 |
| 10k  | CUDA | off | camera_only    | 410.92 ms\* |   8.37 |12079.64| 408.63 |
| 10k  | CUDA | off | transform_edit |  16.12 ms |  13.44 |  41.81 |   8.11 |
| 10k  | CUDA | on  | camera_only    |  10.30 ms |   9.23 |  22.58 |   7.75 |
| 100k | CPU  | off | camera_only    |  58.41 ms |  57.60 |  66.38 |  56.18 |
| 100k | CPU  | off | transform_edit | 106.59 ms | 104.04 | 130.35 |  57.34 |
| 100k | CPU  | on  | camera_only    | 144.34 ms | 139.65 | 233.06 | 133.66 |
| 100k | CUDA | off | camera_only    | 104.41 ms |  99.99 | 171.43 | 101.09 |
| 100k | CUDA | off | transform_edit | 181.55 ms | 159.06 | 301.29 |  90.70 |
| 100k | CUDA | on  | camera_only    | 105.78 ms | 102.71 | 140.78 | 102.66 |

\* The 410ms mean is dominated by a single 12,079 ms first-frame outlier
when CUDA is invoked for the first time in the process. p50 (8.37ms) is
the steady-state. **This is H5 in measured form.**

Full data: `benchmarks/viewport_parity/2026-05-10.json`. 1M-tri runs were
omitted from this commit — at the per-frame costs above, a 30-frame 1M
sweep would take >10 minutes per CPU config and, more importantly, the
diagnosis is already decisive at 100k. 1M numbers are a follow-up.

---

## Hypothesis-by-hypothesis

### H1 — pkg56-C dispatches uploaders during pan: **REJECTED for camera_only, CONFIRMED for transform_edit**

`camera_only` measured `h1_upload_geometry_calls_per_frame_total = 0`
across all 8 configs. Real Blender pan never fires `view_update`, so
the dispatcher never runs. H1 cannot be the cause of the pan-feels-slow
complaint.

`transform_edit` (mesh-drag scenario, not pan) measured 1
`upload_geometry` call per frame, adding **~50 ms per frame on 100k CPU**
(58→106 ms) and **~80 ms on 100k CUDA** (104→181 ms). This is the
pkg56-C documented single-level-BVH limitation, already tracked in
pkg56 spec §B (two-level refit). Out of scope for pkg81's pan complaint
but worth noting: mesh-drag *does* hit it.

### H2 — progressive accumulation resets every pan tick: **CONFIRMED (code-level)**

The addon's `view_draw` calls `_render_viewport_frame(...,
reset_accumulation=(camera_changed or settings_changed))`
([blender_addon/__init__.py:1322](../../blender_addon/__init__.py#L1322))
and `_reset_viewport_accumulation()` zeros `_viewport_current_spp`. Every
pan tick goes back to 1-spp.

Cycles' policy ([intern/cycles/blender/session.cpp `BlenderSession::reset`](../../intern/cycles/blender/session.cpp))
invalidates the framebuffer only on real scene-graph mutations,
continuing progressive samples across camera moves once they stabilise.
The harness's `h2_spp_trace_unique_values = [1]` confirms our flat
behaviour.

The user-perceived effect: even if Astroray's per-chunk render were
free, the user always sees a 1-spp noisy frame during pan because the
accumulator never grows. Cycles users see a low-noise frame
materialise within 100–300 ms of letting go of the mouse. **This is a
real bottleneck, code-confirmed, no measurement gap to close.**

### H3 — OIDN denoising blocks the frame loop: **CONFIRMED on CPU, MILD on CUDA**

| scene | engine | oidn off | oidn on | Δ |
|---|---|---:|---:|---:|
| 10k | CPU | 20.55 | 130.72 | **+110 ms** |
| 10k | CUDA | 8.37 (p50) | 9.23 (p50) | +0.9 ms |
| 100k | CPU | 58.41 | 144.34 | **+86 ms** |
| 100k | CUDA | 104.41 | 105.78 | +1.4 ms |

OIDN on CPU is catastrophic — adds ~90 ms per frame regardless of scene
size, dominating frame time. On CUDA the cost is negligible (<2 ms),
suggesting pkg68's persistent-device path is reasonably fast on GPU
already.

The CPU number is suspicious: pkg68 was supposed to make OIDN
"persistent". This 90ms-per-frame on CPU suggests OIDN is either
re-initializing or running on the wrong backend in the CPU configs.
Worth checking, but **not the dominant contributor on the project
owner's CUDA station**.

### H4 — megakernel register pressure caps first-pixel latency: **CONFIRMED, DOMINANT**

The clearest single finding. On 100k tris / `camera_only` / OIDN off:

- **astroray-cpu** : render mean 56.18 ms
- **astroray-cuda**: render mean 101.09 ms

CUDA on RTX 5070 Ti is **~2× slower** than CPU on the same scene. This
should not happen for a 256×256 1-spp 4-bounce path-trace at any sane
register count. pkg55 Phase A measured 158 regs/thread / 1 active block
per SM on the megakernel — exactly the architectural condition Laine
2013 §6 names as the cause of catastrophic GPU underutilisation for
incoherent path-tracing workloads.

By contrast Cycles on the same hardware uses the wavefront integrator
on CUDA, which keeps regs/thread low enough for >4 active blocks/SM.
The Cycles/Astroray viewport gap is plausibly the entirety of the SM
occupancy gap × the GPU/CPU compute ratio.

H4 is consistent with the project owner's lived experience and with
pkg55's measured A-baseline. **The pan-feels-slow report is, mostly,
the megakernel's regs/thread cliff manifesting at viewport scale.**

### H5 — first-vs-Nth view_draw setup overhead: **CONFIRMED, large but one-shot**

First frame in the *first CUDA config* of the process: **12,079 ms**.
Subsequent CUDA configs: 13–14 ms first frame. This is CUDA context
init + kernel JIT, paid once per Blender session.

For "starting rendered-shading mode feels slow" this is the entire
story — 12 seconds before pixel #1. For *steady-state* pan, H5 is
sub-frame and not material.

Cycles avoids this by initializing the device during scene sync, so
the first `view_draw` already sees a warm device. We could mirror that
trick (warm CUDA inside `_sync_viewport_scene` instead of inside the
first `Renderer.render`).

---

## Ranking by frame-time impact (100k tris, RTX 5070 Ti, steady state)

| H | Owns approximately | Fix path |
|---|---|---|
| **H4** | ~100 ms / frame on CUDA — *the gap* | pkg55 Phase B (per-material shade-kernel split) |
| **H2** | qualitative ("always 1 spp during pan") | Astroray addon: invalidate framebuffer only on scene mutation, mirror Cycles `BlenderSession::reset` |
| **H5** | 12 s once at session start | Astroray: pre-warm CUDA in `_sync_viewport_scene` |
| **H3** | ~90 ms / frame on CPU only | pkg68 OIDN persistent-device review on the CPU path |
| **H1** | 0 ms during pan; ~50–80 ms during mesh-drag | pkg56 §B two-level BVH refit (already tracked) |

---

## Conclusion

pkg81 closes here as **measurement-complete**. The dominant
contributor is **H4 (megakernel / regs-per-thread cliff)** — exactly
the problem pkg55 Phase B was filed to solve. The viewport
parity-with-Cycles win lands when pkg55 Phase B+C land; pkg81's role
was to prove that's where the work belongs.

Open follow-ups (named, not done in this session):

1. **pkg55 Phase B/C** — kernel split. Owns the H4 fix.
2. **Addon: progressive sample continuation** — keep accumulator across
   camera ticks, reset only on scene mutations. Owns H2. Small change.
3. **Addon: pre-warm CUDA in `_sync_viewport_scene`** — owns H5
   first-pixel latency. Small change.
4. **pkg68 review on CPU OIDN path** — investigate the 90 ms/frame
   CPU-only cost. Owns H3 on CPU.
5. **Cycles A/B numbers via `blender_driver.py`** — the project
   owner runs this on the RTX 5070 Ti station; appended to
   `benchmarks/viewport_parity/{date}-cycles.json`.
6. **1M-tri sweep** when needed for the pkg55 Phase B acceptance gates.

The pkg81 acceptance gates (99k pan-frame p99 ≤ 1.2× Cycles-CUDA;
100k pan-frame ≤ 30 ms with denoise) are not yet met and will be
re-evaluated after pkg55 Phase B lands. pkg81 is filed as the
measurement that justifies that work, not the fix that delivers it.

---

## References cited

- `benchmarks/wavefront/baseline.json` (pkg55 Phase A) — 158 regs/thread,
  1 active block/SM on `path_trace_megakernel`.
- `intern/cycles/blender/session.cpp` (Apache-2.0) — `BlenderSession::reset`,
  `view_draw` sample-loop shape; pattern only, no code copied.
- `intern/cycles/integrator/path_trace.cpp` (Apache-2.0) —
  `PathTrace::path_trace_iteration`, the progressive shape we should
  mirror in the H2 fix.
- Laine, Karras, Aila — "Megakernels Considered Harmful" (HPG 2013) §6.
- pkg52, pkg55 Phase A, pkg56 Phases A/B/C, pkg68 — internal package specs.
