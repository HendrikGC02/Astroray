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

<!-- MEASUREMENTS_TABLE -->

Structural findings that drive the design:
- **GPU camera edit->present is already ~130 ms** — near the p95<=100 ms budget
  but the render itself (~125 ms) is the whole cost; engine-entry latency is
  ~1 ms (event routing is not the bottleneck).
- **Material edits cost ~2x a camera edit** because `view_update` renders an
  un-presented chunk and then `view_draw` renders again before blitting. First
  pixels after a material edit are gated on two sequential render chunks.
- **CPU is 10-15x slower per frame**; a single CPU frame blocks the main thread
  (and thus any cancel) for 1.5-30 s depending on scene.
- **Cancel full-stop floor == one render call.** With no cooperative break, a
  cancel/ESC cannot take effect until the in-flight `render()` returns. The F12
  probe measures that floor directly.

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
