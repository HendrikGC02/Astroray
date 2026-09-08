# pkg241 Phase 2 A2 spike — §9 go/no-go measurement (2026-09-08)

RTX 5070 Ti, isolated Blender 5.2 GUI on the mcp bridge port 9877 (never the owner's
live 9876/PID 1676), OpenMP-OFF CUDA addon built from `feat/pkg241-phase2-a2-spike`
(`build_blender_addon_cuda/astroray.cp313-win_amd64.pyd`, built 2026-09-08 12:13, sm_120),
`ASTRORAY_VIEWPORT_WORKER=1`. 3 reps × 10 s post-warmup per (scene, engine).

## In-process gates (under the GPU lock, branch build)

| gate | result |
|---|---|
| cancellation pytest (`tests/test_pkg241_cancellation.py`) | **9/9 pass** (last_render_info device sentinel −1 CPU / 0 GPU; null-hook byte identity) |
| correctness comparator (seed 12345, 2112×829, 64 spp, linear, Cornell) | **PASS** — same_device=True (0/0), per-channel mean-ratio [1.0, 1.0, 1.0], **max-abs-diff 9.5e-07** (≪ 2.0e-2 bound; below the 1e-3 atomic-reorder floor) |
| decoupling proxy (headless, sync arm vs worker arm) | sync tick-gap **4435 ms** (main thread blocked = the §1 failure) vs worker **p50 5.51 / p95 5.94 / p99 9.9 / max 18.49 ms** → **worker_meets_33ms_p95: TRUE**, device 0 |

The proxy isolates exactly the §3.7/§3.1 load-bearing assumption (render on the worker
daemon thread with the GIL released across the GPU tail) and shows it **frees the main
thread** (5.94 ms p95). Correctness across the thread boundary is bit-near-identical.

## GUI ui_latency (the §9 acceptance instrument), worker ON

### Run A — as-committed (tolist() texture upload)

| scene | region | n_ticks | gap p50 | gap p95 | gap p99 | gap max | blocked_frac | tex_tail p95 | cancel p99 | completed | presented | mailbox_max | devices | cuda_err | n_render_dev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2112×829 | 103 | 229.08 | 662.48 | 671.28 | 681.12 | 0.983 | 222.67 | 7507.1 | 0 | 0 | 1 | [0] | 0 | 166 |
| big (100k) | 2100×1221 | 648 | 7.53 | 324.01 | 629.47 | 936.96 | 0.894 | 316.95 | 829.75 | 0 | 0 | 1 | [0] | 0 | 208 |

On `big`, tick-gap p95 (324) ≈ texture tail (317): a **texture-attributable** p95 failure.
Per the §9 texture-tail exemption rule this mandates implementing the
`gpu.types.Buffer`-from-numpy path and rerunning before any verdict.

### §9 texture-tail fix (implemented + verified in-Blender)

`_update_viewport_texture`: `flat.tolist()` → **194.8 ms**; passing the contiguous float32
array straight through `gpu.types.Buffer` → **0.0 ms**, `textures_equal: True` (byte-identical
GPUTexture). Flag-gated on `ASTRORAY_VIEWPORT_WORKER`; synchronous path unchanged.

### Run B — with the §9 gpu.types.Buffer texture-tail fix

| scene | region | n_ticks | gap p50 | gap p95 | gap p99 | gap max | blocked_frac | tex_tail p95 | cancel p99 | completed | presented | mailbox_max | devices | cuda_err | n_render_dev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2112×829 | 1587 | 7.10 | 94.02 | 223.85 | 238.27 | 0.737 | **13.42** | 340.96 | 0 | 0 | 1 | [0] | 0 | 252 |
| big (100k) | 2100×1221 | 1545 | 7.18 | 75.20 | 325.99 | 496.03 | 0.745 | **16.60** | 582.96 | 0 | 0 | 1 | [0] | 0 | 376 |

The fix collapsed the texture tail (222→13 / 317→17 ms), dropped tick-gap **p50 to 7.1 ms**
on both scenes (the median frame is fully decoupled), and lifted n_ticks ~10-15×.

## §9 go/no-go — checklist

| criterion | budget | metal | big | verdict |
|---|---|---|---|---|
| tick-gap p95 | ≤ 33 ms | 94.0 | 75.2 | **FAIL** (7× better than Run A but still > 33; **not** texture-attributable now — tex_tail is 13-17 ms) |
| cancel p99 | ≤ 300 ms | 341 | 583 | **FAIL** |
| per-gen CUDA errors | 0 | 0 | 0 | PASS |
| same device both threads | yes | [0] | [0] | PASS |
| mailbox depth | ≤ 1 | 1 | 1 | PASS |
| settled correctness | ±5% ratio AND max-abs ≤ 2e-2 | ratio [1,1,1], max-abs 9.5e-07 | " | PASS |
| present rate | ≥ 0.9 × completed | completed=0 → **undefined** | completed=0 → **undefined** | INCONCLUSIVE (measurement confound, see below) |
| no stale present | required | frames not observed reaching the screen | " | **CONCERN** |

## What the numbers mean (honest reading)

1. **The cross-thread primary-context model itself is viable** — the proxy proves the
   §3.7 GIL release frees the main thread (5.94 ms p95), correctness is bit-perfect,
   both threads resolve device 0, zero CUDA errors over 400+ generations.
2. **Two GUI gates still fail after the mandated texture fix.** The residual tick-gap
   p95 (75-94 ms) is **not** the texture tail (now 13-17 ms); it is the **main-thread
   commit** — `_worker_commit_and_submit` runs `sync_viewport_scene` (full scene
   upload) on the main thread for every material-edit generation (§3.2 puts the commit
   on the main thread by design). cancel p99 (341-583 ms) is the worker finishing its
   in-flight chunk before it reports idle.
3. **`completed=0 / presented=0` is largely a measurement confound.** The ui_latency
   ticker dispatches an edit every 5 ms and never stops, so no generation is ever the
   "latest desired" at its own `render_end` → every finished frame is scored superseded
   → `completed=0`, and the present-rate gate (which divides by completed) is undefined.
   The §9 present-rate gate implicitly assumes generations settle; this ticker never
   lets them.
4. **Separately, frames do not appear to reach the screen** in the GUI worker path
   (`presented=0`; the RENDERED-shading screenshots show only Blender's default grid,
   no astroray output). This is a worker→present→blit wiring issue in the spike addon
   integration (the engine's `_viewport_texture` vs the exporter's blit check), distinct
   from the texture-tail cost. It does not change the tick-gap/cancel gate outcome.

## Verdict (surfaced to the lead — this is a genuine fork, not a mechanical GO/NO-GO)

By the **pinned §9 protocol the two GUI gates fail → strict NO-GO**. But a strict NO-GO
routes to "the serialised cross-thread primary-context model is not viable as A2," and
the **proxy directly falsifies that** — the model is viable; the residual GUI failures
are (a) the spike's choice to commit/upload on the main thread, (b) a frame-presentation
wiring bug, and (c) the never-settling measurement, **not** the primary-context model.

Recommendation: do **not** mechanically route to A1. Either (1) a bounded P2.2
integration pass — move the scene commit/upload off the main thread (or throttle
full-sync to substantive edits), fix the worker→blit presentation wiring, and add a
settle window to the ui_latency gate so present-rate is defined — then re-measure; or
(2) if the main-thread `bpy` commit is deemed irreducible, A1 (native session).
This is the lead's call.
