# pkg241 — cooperative cancellation + viewport-response design (2026-09-07)

Phase 0 output. Derived from the static call-path evidence in the spec plus the
real edit->present / F12 latencies measured through the live GUI Blender bridge
(`benchmarks/viewport_parity/results/2026-09-07-phase0/`). Phase 1 is NOT
authorised by this doc; the lead sends it to Codex Terra for approval first.

## 1. Static call-path evidence (re-verified against HEAD)

- `blender_module.cpp:2220-2225` — the CPU progress callback is a
  `std::function<void(float)>`: it calls `progressCallback(progress)` and
  **discards the Python return value**. The addon's `progress_callback`
  (`__init__.py:1209`) returns `False` on `self.test_break()`, but that `False`
  never reaches C++.
- `raytracer.h:4183` — `if (progress) progress(float(++tilesCompleted)/totalTiles);`
  is a void fire-and-forget after each tile. No return is inspected; the tile
  loop cannot break.
- `blender_module.cpp:3280` — the `render` pybind binding has **no**
  `py::call_guard<py::gil_scoped_release>()` (contrast `upload_geometry`
  at :3317). So `renderer.render(...)` **holds the GIL for its whole duration**
  and runs synchronously on Blender's main thread. Nothing Python-side (not even
  the per-tile `test_break`, which re-acquires the already-held GIL) can run
  concurrently, and no ESC/cancel is processed until `render()` returns.
- `blender_module.cpp:2171` — the GPU path calls
  `cuda_wavefront_render(...)` with **no progress or cancel argument at all**:
  zero yield points, so a GPU frame can only be cancelled at frame boundaries.
- `exporter.py:611` — `render_viewport_frame` calls
  `renderer.render(samples, depth, None, ...)`, passing `None` as the progress
  callback. Viewport frames therefore have **no** per-tile callback even on CPU;
  the whole sample chunk must complete before control returns.
- `exporter.py:651 view_update` renders a chunk but does **not** blit; the blit
  (`draw_texture_2d`) only happens in `view_draw` (`exporter.py:865`). A
  depsgraph edit (material) pays a `view_update` render *and* a following
  `view_draw` render before the first pixels are presented (see §2).

## 2. Measured numbers (see JSON for full percentiles)

Region-resolution viewport, RTX 5070 Ti, Blender 5.2, dispatch->present via a
POST_PIXEL draw handler; 3x50 events/class, 5 warmup discarded. CPU material on
the 100k scene is deadline-truncated (marked in the JSON) — CPU is the slow
correctness oracle, not the interactivity target.

edit -> present (ms), full region resolution:

| scene | tris | region | device | class | n | p50 | p95 | p99 |
|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2 220 | 2112x829 | gpu | camera | 150 | 396.8 | 425.6 | 454.2 |
| metal_sweep | 2 220 | 2112x829 | gpu | material | 150 | 809.1 | 882.0 | 957.0 |
| metal_sweep | 2 220 | 2112x829 | cpu | camera | 19* | 11613 | 12446 | 13257 |
| metal_sweep | 2 220 | 2112x829 | cpu | material | 22* | 22370 | 22672 | 22803 |
| big | 101 920 | 2100x1221 | gpu | camera | 150 | 162.1 | 165.0 | 169.5 |
| big | 101 920 | 2100x1221 | gpu | material | 145* | 1350.8 | 1378.5 | 1404.8 |
| big | 101 920 | 2100x1221 | cpu | camera | 25 | 1743.2 | 1756.6 | 1757.6 |
| big | 101 920 | 2100x1221 | cpu | material | 24* | 14150 | 14333 | 14367 |

Cancel full-stop floor (F12 render wall-time, ms): metal_sweep gpu 1107 /
cpu 148 511; big gpu 483 / cpu 16 148. `*` = deadline-capped below the
30-event floor. CPU could not reach 30 events/class within a bounded wall
budget: the socket-driven bridge adds ~20 s/event of fixed overhead (idle-GUI
timer throttling) on top of the render, so CPU counts are the capped maxima.
CPU is the slow correctness oracle, not the interactivity gate; GPU carries the
full n=150.

Structural findings that drive the design (region-resolution viewport, so the
absolute ms scale with pixel count — the JSON logs the region px per config):
- **GPU camera edit->present is render-bound.** At full region resolution it is
  p50 162 ms (100k scene) to 397 ms (metal_sweep at a larger nav-res chunk);
  the block is ~99% inside the single `render()` call, engine-entry latency is
  ~1 ms (event routing is not the bottleneck). Both exceed the p95<=100 ms
  budget, but the cost is the render itself, not the response path — see Open
  Question 1.
- **A material edit costs ~2x its own render** because `view_update` renders an
  un-presented chunk and then `view_draw` renders again before blitting: present
  p50 809 ms vs a 397 ms material render (metal_sweep), 1351 ms vs a 609 ms
  render (100k). First pixels after a material edit are gated on two sequential
  render chunks. The material render is also costlier than a camera render
  because the depsgraph edit forces a re-sync, not just a view-matrix update.
- **CPU is 10-15x slower per frame**; a single CPU frame blocks the main thread
  (and thus any cancel) for ~1.7 s (100k camera) to ~23 s (metal_sweep material)
  depending on scene, and the F12 full-render floor reaches ~148 s on CPU.
- **Cancel full-stop floor == one render call.** With no cooperative break, a
  cancel/ESC cannot take effect until the in-flight `render()` returns. The F12
  probe measures that floor directly (GPU 483-1107 ms; CPU 16-148 s).

## 3. Proposed cooperative-cancellation contract (Phase 1)

Single mechanism, no background threads. The numbers do **not** force threading:
the main-thread block is one `render()` call, and the fix is to make that call
checkpoint a cheap cancel flag and return early, not to move rendering off-thread
(which would add GIL + CUDA-context-ownership risk the spec explicitly flags).

1. **Progress callback returns bool.** Change the native callback type from
   `std::function<void(float)>` to `std::function<bool(float)>` (return `true`
   to continue, `false` to cancel). `raytracer.h:4183` becomes
   `if (progress && !progress(frac)) { cancelled = true; break; }` at the tile
   loop, and the outer sample loop checks `cancelled`. The binding lambda
   (`blender_module.cpp:2222`) forwards the Python return:
   `return py::cast<bool>(progressCallback(progress));` under the acquired GIL.
   `progress_callback` (`__init__.py:1209`) already returns the right bool.
   ABI: this is a signature change on a symbol crossing TUs -> `cpp-abi-guard`
   review + fresh native build identity required.
2. **Viewport passes a real callback.** `render_viewport_frame` (`exporter.py:611`)
   passes a lightweight callback instead of `None`; the callback returns
   `not self._viewport_cancel_requested`. The engine sets that flag from the
   next `view_update`/`view_draw` when the render key / camera changed while a
   render was mid-flight (stale-frame guard, §4).
3. **GPU per-iteration cancel check.** `cuda_wavefront_render` gains a
   host-side `const std::atomic<bool>* cancel` (default null = today's
   behaviour, bit-identical). The wavefront driver checks it between wavefront
   iterations (the natural host-side loop boundary) and returns the
   partial/last-complete frame. No per-ray device-side preemption (Non-goal).
4. **`test_break()` honoured at `__init__.py:1210`.** Already wired; becomes
   effective once (1) lands. No addon change beyond confirming the return path.

## 4. Stale-frame guard + session consistency

- The exporter already stamps `_viewport_accum_key` / `_viewport_camera_hash`.
  On cancel/restart, `_reset_viewport_accumulation()` must run before the next
  chunk so a cancelled frame's partial accumulation is never blended with the
  new camera/material state (no mixed accumulation — Acceptance gate).
- A cancelled render returns whatever samples completed; the accumulator must
  either discard that chunk (if the render key changed) or keep it (same key,
  progressive refine). Decision key = the existing `render_key`.
- Ordinary completion path stays **bit-identical**: `progress == nullptr`
  (final render with no break, GPU with `cancel == nullptr`) takes exactly
  today's code path; the bool is only inspected when a callback/flag is present.

## 5. GIL / CUDA-context ownership

- No new threads => the GIL story is unchanged: `render()` still runs on the
  main thread holding the GIL; the per-tile callback re-acquires (reentrant,
  safe). The only new Python->C++ crossing is a bool return, already inside the
  existing `gil_scoped_acquire` block.
- CUDA context stays owned by the main thread (the thread that built it). The
  GPU cancel flag is a plain host atomic read between iterations — no context
  migration, no partial-launch teardown beyond returning the last complete
  wavefront buffer.

## 6. Test plan (Phase 2)

- Native unit: a render with a callback that returns `false` after N tiles stops
  in <= N+1 tiles (CPU) and returns a valid partial framebuffer.
- Native unit: `progress == nullptr` render is byte-identical to origin/main on a
  fixed seed (ordinary-path invariant).
- GPU: `cancel` atomic set mid-render returns within one wavefront iteration;
  `cancel == nullptr` is byte-identical.
- Blender (bridge, this harness): re-run `blender_driver.py --mode interactive`
  and assert GPU edit->present p95 improves or holds, and that a mid-refine
  camera change cancels the in-flight chunk (no stale present) — reuse the
  recorder's per-event `present_ms`.
- Regression: `pytest tests/` viewport + render suites; visual A/B (Astra) on
  metal_sweep CPU and GPU.

## 7. Open questions (for Terra)

1. **Budget realism:** GPU camera edit->present is already ~130 ms and is
   render-bound. Is the p95<=100 ms budget a target for *this* work (needs a
   render-time reduction, out of pkg241 scope) or for the cancel/response
   contract only? Cancellation cannot lower the ~125 ms render cost.
2. **Material two-render penalty:** should Phase 1 also make `view_update`'s
   chunk presentable (blit the view_update frame) to halve material edit->present,
   or is that a separate viewport-pipeline package?
3. **GPU cancel granularity:** one wavefront iteration is the cheapest safe
   checkpoint. Acceptable, or is a finer (per-tile-launch) checkpoint wanted
   despite the added driver complexity?
4. **Partial-frame policy on final render (F12):** return the partial image to
   Blender's render result, or discard? Cycles returns the partial.
