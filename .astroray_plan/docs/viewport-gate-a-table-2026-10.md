# Viewport gate (a) table — 2026-10 (pkg291)

Gate (a) (north-star §2(a), pkg278 instrument): event dispatch → first **correct**
Blender-presented frame, GPU p95 ≤ 100 ms and p99 ≤ 150 ms; cancel-ack p95 ≤ 200 ms,
p99 ≤ 300 ms; zero stale frames presented after a cancellation ack. pkg291 adds a
transform edit and its own target: an object move on the 100k scene presents in
< 20 ms p95.

## How it was measured

- Real GUI Blender 5.2, isolated profile on port 9877, staged addon, RTX 5070 Ti.
  Viewport region 2100×1221 (the isolated window, maximised). GPU, denoise off.
- Scenes: the frozen pkg278 workloads `pkg278_grid_10k.blend` (10,000 tris) and
  `pkg278_grid_100k.blend` (100,000 tris; five 20k-tri strips — a transform edit
  moves ONE 20k-tri object inside the 100k scene; the engine test
  `test_pkg291_transform_inplace.py` moves a full 100k-tri object).
- Edits, serialized, 5 reps × 60 measured events (+5 warm-up) per cell:
  - **camera** — real region-view navigation: `bpy.ops.view3d.view_orbit` ±1°
    (not a camera-object edit; memory `viewport-gate-table-misses-real-navigation`);
  - **material** — Principled Base Color;
  - **transform** — the largest mesh object ±0.05 along its thinnest axis.
- Worker ON: the fail-closed pkg278 generation-chain reducer (request → commit →
  render → publish → texture upload → POST_PIXEL present of THAT generation, with
  pre/post framebuffer hashes); cancel = cancel_request → idle_drain; stale frames
  checked after every floor-raising material cancellation.
  Worker OFF (synchronous, no generation stream): first POST_PIXEL present after a
  `render_viewport_frame` that started after dispatch.
- Driver: `benchmarks/viewport_parity/blender_driver.py --mode gate_a_table`.
- Build `0f57d619` (`.pyd` in `Astroray-at-v/build_cuda`), whole session under one
  GPU lock with the build queue held.

### Measurement windows

| Window | Cells | Python at | CPU load (typeperf, 5 s) | GPU util (nvidia-smi, 5 s) |
|---|---|---|---|---|
| W1 2026-10-03 07:07–07:59 | all 12 | `0f57d619` | mean 25 %, p95 39 %, max 73 % (614 samples) | mean 27 %, max 65 %; SM clock median 2557 MHz |
| W2 2026-10-03 11:18–11:47 | 6 worker-ON | `23de7e94` | mean 30 %, p95 47 % | mean 25 % |
| W3 2026-10-03 13:33–14:00 | 6 worker-OFF | `e5d7b004` + recorder fingerprint fix | mean 20 %, p95 25 %, max 52 % (323 samples) | mean 17.6 %, max 62 % |

W1 also ran the GPU sanity tests (22/22) and the #879 repro (below). W2 re-measured
worker ON after the Python fixes; W3 re-measured worker OFF with the stricter
fingerprint-bound synchronous predicate (W1 OFF predates it). The W2 `.pyd` is
`0f57d619`, W3 is the `e5d7b004` build (only a CPU render-region clear differs; the
edit path is unchanged). Final table = W2 ON + W3 OFF. W3 was the quietest window.

## Table

| scene | edit | worker | events | p50 / p95 / p99 ms | cancel p95 / p99 ms | stale | gate (a) |
|---|---|---|---|---|---|---|---|
| 10k | camera | ON | 300 | 39.2 / 99.7 / 105.4 | 36.2 / 42.7 | 0 | PASS |
| 10k | material | ON | 300 | 52.1 / 92.0 / 122.8 | 32.9 / 42.8 | 0 | PASS |
| 10k | transform | ON | 300 | 42.2 / 93.0 / 98.5 | 35.5 / 38.8 | 0 | PASS |
| 100k | camera | ON | 300 | 32.1 / 44.7 / 67.8 | 32.5 / 44.8 | 0 | PASS |
| 100k | material | ON | 300 | 92.3 / 101.4 / 108.1 | 42.0 / 48.3 | 0 | FAIL (+1.4 ms) |
| 100k | transform | ON | 300 | 33.6 / 46.8 / 48.8 | 34.1 / 36.4 | 0 | PASS (< 20 ms: FAIL) |
| 10k | camera | OFF | 300 | 19.3 / 19.8 / 20.1 | n/a | n/a | PASS |
| 10k | material | OFF | 300 | 67.9 / 91.7 / 99.1 | n/a | n/a | PASS |
| 10k | transform | OFF | 300 | 62.4 / 63.7 / 85.4 | n/a | n/a | PASS |
| 100k | camera | OFF | 300 | 8.2 / 13.8 / 21.6 | n/a | n/a | PASS |
| 100k | material | OFF | 300 | 87.0 / 137.2 / 139.8 | n/a | n/a | FAIL |
| 100k | transform | OFF | 300 | 22.6 / 23.5 / 77.1 | n/a | n/a | PASS (< 20 ms: FAIL) |

0 chain errors in every cell. Both modes pass gate (a) in 5 of 6 cells; 100k material
fails in both. The < 20 ms object-move target is missed in both modes (OFF p95 23.5 ms,
ON 46.8 ms); the engine side is 5.6-6.4 ms. Chart and before/during/after sheet:
`test_results/viewport/edit-latency/`.

### W1 (all cells, before `4a4de583`)

| scene | edit | worker | events | p50 / p95 / p99 ms | cancel p95 / p99 ms | stale after ack | chain errors | gate (a) |
|---|---|---|---|---|---|---|---|---|
| 10k | camera | ON | 300 | 87.0 / 110.2 / 115.9 | 35.9 / 38.2 | 0 | 0 | FAIL |
| 10k | material | ON | 300 | 89.0 / 108.1 / 113.3 | 36.7 / 38.2 | 0 | 0 | FAIL |
| 10k | transform | ON | 300 | 89.5 / 107.8 / 111.6 | 36.8 / 41.3 | 0 | 0 | FAIL |
| 100k | camera | ON | 300 | 19.2 / 20.2 / 21.3 | 37.9 / 43.2 | 0 | 0 | PASS |
| 100k | material | ON | 300 | 78.1 / 99.3 / 115.0 | 29.6 / 36.9 | 0 | 0 | PASS |
| 100k | transform | ON | 300 | 24.1 / 25.7 / 38.4 | 38.2 / 48.5 | 0 | 0 | PASS (< 20 ms: FAIL) |
| 10k | camera | OFF | 300 | 19.2 / 19.7 / 20.1 | n/a | n/a | 0 | PASS |
| 10k | material | OFF | 300 | 65.3 / 88.9 / 90.5 | n/a | n/a | 0 | PASS |
| 10k | transform | OFF | 300 | 60.4 / 84.0 / 84.7 | n/a | n/a | 0 | PASS |
| 100k | camera | OFF | 300 | 21.2 / 22.0 / 22.2 | n/a | n/a | 0 | PASS |
| 100k | material | OFF | 300 | 133.3 / 157.3 / 161.6 | n/a | n/a | 0 | FAIL |
| 100k | transform | OFF | 300 | 75.1 / 82.4 / 83.9 | n/a | n/a | 0 | PASS (< 20 ms: FAIL) |

W1 attribution (lifelines in the raw captures):

- **Worker ON, 10k**: the 10k grid's full-res render (~45 ms at 2100×1221) was under
  the coarse-start threshold, so the first unit rendered AND uploaded at full res
  (render ~45 ms + texture upload 15–25 ms + ~22 ms waiting out the in-flight full-res
  refinement chunk) → p50 87 ms. The coarse-starting 100k grid presents in 19–26 ms.
  Fixed in `4a4de583` (a worker edit slower than one display frame starts at the
  navigation divisor, as the synchronous path already does for camera moves).
- **Worker OFF, 100k material / transform**: the synchronous path renders the edit's
  first frame at full res (start divisor 1; median render 97 ms material, 66 ms
  transform) on the main thread. Not changed here (see residuals).

## What changed (pkg291)

| Change | Commit | Effect (measured) |
|---|---|---|
| #879 path latch + sync path takes the global admission token | `0cdbc56f` | live flip + toggle: baseline crashed 2/2, fixed 0/40 (below) |
| `setup_camera` re-aims a same-size Camera | `383f0920` | 112 ms in-session / 190 ms standalone → 0.02 ms per commit at 2100×1221 |
| spare Camera for the other size | `73e273c6` | coarse ↔ full alternation: 175 ms commit per edit → 0.0 ms |
| present before refinement commit | `73e273c6` | coarse unit ready at +34 ms was shown at +210 ms → shown first |
| drain worker control before `request()` | `aa4f7a05` | 10–12 spurious "cancel lacks idle_ack" chain errors per worker-ON material cell → 0 |
| coarse start above half the budget | `65e2fade` | render share leaves room for commit + upload + draw |
| #875 in-place object move (range delta, BVH refit, GPU patch, OptiX update) | `e43d509e`, `73e273c6`, `e29c42d9` | 100k move: 5.6–6.4 ms CPU (`transform_object_range`), patched move+render vs full re-flatten 30-48 ms vs 96-99 ms (W2) |
| worker first unit at nav divisor above one display frame | `4a4de583` | 10k worker-ON p95 108-110 ms (W1) -> 92-100 ms (W2) |
| worker-OFF capture predicate (rotation/location/distance fingerprint) | `e5d7b004`, W3 fix | measurement only: `view_matrix` is stale right after `view_orbit` |

## #879 root cause

`viewport_worker_enabled()` was re-read on every `view_update` / `view_draw`. A live
`ASTRORAY_VIEWPORT_WORKER=0` flip sent the next `view_draw` down the synchronous path,
which called `renderer.render()` on the main thread while the session's worker thread
was still inside `renderer.render()` — the GPU render releases the GIL
(`gpuGilRelease.emplace()` before `cuda_wavefront_render`), so two threads drove the
process-global wavefront `WfContext` at once and Blender died in `nvcuda64.dll`
(original 2026-09-24 crash log: `EXCEPTION_ACCESS_VIOLATION` reading a host address in
`nvcuda64.dll`, empty Python backtrace). The synchronous path also never took the
global admission token the worker and F12 use.

Fix: the path is latched per Exporter (re-read only at `view_update` with no worker
render in flight; leaving worker mode stops the worker — cancel → join → token
released — before the synchronous path renders), and the synchronous path takes the
global admission token (reaping orphaned sessions first; never waiting on F12).
Test: `tests/test_pkg291_worker_lifecycle.py` (bpy-free + a real-CUDA leg).

Repro (isolated Blender 5.2, 100k grid, GPU, preview samples 100,000 so flips land
mid-render):

| Build | Mode | Result |
|---|---|---|
| main 48ef43b2 (ar-981 `.pyd`) | hot: env 1→0 while the worker renders, ×15 | CRASH at the first flip, 2/2 runs |
| `0f57d619` | hot ×15 | alive |
| `0f57d619` | edit: worker mid-render + flip + real material edit + toggle, ×10 | alive |

## Default flip decision

Worker default stays OFF (owner-agreed). Measured p95, ON vs OFF: 10k camera 99.7 vs
19.8, 10k material 92.0 vs 91.7, 10k transform 93.0 vs 63.7, 100k camera 44.7 vs 13.8,
100k material 101.4 vs 137.2, 100k transform 46.8 vs 23.5 ms. OFF wins five cells and
ties one, loses only 100k material. Caveat: OFF renders synchronously on the Blender
main thread (UI blocked while a frame renders, no cancel). The worker stays opt-in
(`ASTRORAY_VIEWPORT_WORKER=1`); `worker-default-flip.patch` was not applied.

## #721 / #855 disposition

- #879 fixed here (root cause above).
- #875 (in-place move) implemented; the 100k end-to-end move target (< 20 ms) is still
  missed in Blender (OFF 23.5 ms p95), so #875 stays open for the remaining margin.
- #721 / #855: not closed by this work; the numbers above are the evidence for the
  owner to judge them against.

## Residuals

- Synchronous path: material / transform edits render their first frame at full
  resolution on the main thread (100k: 97 / 66 ms median render). Applying the
  worker's coarse-first-unit policy there is a follow-up.
- The < 20 ms object-move target is end-to-end in Blender; see the table for whether
  W2 meets it. The engine-side cost (CPU 5.6 ms + patched GPU upload) is in the
  change table.
- Gate (a) on a 2100×1221 region; a smaller viewport is cheaper everywhere.
- BVH/OptiX refit quality degrades if an object is moved far from where the BVH was
  built; a full re-sync (any geometry edit, file reload) rebuilds it.
