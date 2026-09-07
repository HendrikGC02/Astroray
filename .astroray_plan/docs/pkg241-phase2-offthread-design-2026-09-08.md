# pkg241 Phase 2 — off-thread viewport render session (design, 2026-09-08)

Architect pass (Opus 4.8). This is a **design document only**: no engine/addon
code, no new spec. Phase 2 is NOT authorised by this doc — the lead runs Codex
Terra on it first (see §5). Grounded in the merged Phase 1b code (PR #748),
Phase 1a (PR #739), the Phase-0 design
(`pkg241-cancellation-design-2026-09-07.md`), and the Cycles viewport session
model (`intern/cycles/blender/session.cpp`, Apache-2.0, read via the Blender
`main` mirror — method names cited in §3a/§2 are from that file).

---

## 1. The measured problem, and what "decoupled" must mean in numbers

Owner (2026-09-07 evening): "the Blender UI still runs at the viewport render's
frame rate with Astroray (Cycles decouples them)."

**Measured (owner, PR #750, RTX 5070 Ti, isolated Blender 5.2, 5 ms UI ticker,
3×10 s runs).** Main-thread tick-gap p50/p95/p99 (ms) — the interval between UI
ticks while a chunk renders, i.e. how long the UI thread is starved:

| engine | scene | p50 | p95 | p99 | UI-thread blocked |
|---|---|---|---|---|---|
| Astroray | metal_sweep | 158 | 179 | 194 | 95 % |
| Astroray | 100k-tri | 233 | 274 | 283 | 97 % |
| Cycles OPTIX | metal_sweep | 6.5 | 9.6 | 11.1 | 24 % |
| Cycles OPTIX | 100k-tri | 6.5 | 8.1 | 9.4 | 27 % |

> Provenance caveat: `benchmarks/viewport_parity/results/2026-09-08-phase2/`
> is **not present in this checkout** (PR #750 unmerged locally at doc time).
> Numbers above are owner-reported and are the acceptance-gate baseline; the
> re-run in §4 re-measures them in-tree.

The UI is blocked ~95–97 % of wall time at ~160–280 ms tick-gaps, versus
Cycles' ~6–11 ms at ~24–27 % blocked. Panels, sliders, and menus stall for a
full chunk render because `view_update`/`view_draw` render **synchronously on
the Blender main thread** (§2).

**"Decoupled" in numbers (the Phase 2 gate):**

- Main-thread UI tick-gap **p95 ≤ 33 ms** while a chunk renders (hold ~30 fps),
  measured by the §4 recorder metric — the pinned budget.
- Frames still **presented at the render's rate**: `view_draw` blits the latest
  completed chunk and refinement continues; the render is not slowed.
- **No stale frame after an edit**: a chunk that reflects superseded
  camera/scene state is never blitted (reuse the Phase 1a present-first +
  `_viewport_present_pending` / stale guard).
- **Cancel-ack p95 ≤ 200 ms** (Phase-0 budget); the Phase 1b host cancel hook is
  the stop signal. In-process cancel-ack is already ~4–9 ms p95 (spec Progress
  block), so this is comfortably met — but Phase 2 promotes cancel from an F12/
  edit-boundary event to the **scene-sync handshake** (§3d).

---

## 2. Where the main thread is blocked today (call path, file:line)

The addon runs one persistent `Renderer` (`exporter.py:349`
`_get_viewport_renderer`) and calls it synchronously from both viewport hooks:

- `view_draw` (`blender_addon/exporter.py:816`) → on any camera/settings/refine
  need, calls `render_viewport_frame` **inline** (`exporter.py:957`), then blits
  with `draw_texture_2d` (`exporter.py:998`). The blit is already non-blocking;
  the *render before it* is not.
- `view_update` (`exporter.py:729`) → `render_viewport_frame` inline
  (`exporter.py:791`) for scene/material edits.
- `render_viewport_frame` (`exporter.py:599`) → `renderer.render(...)`
  (`exporter.py:683`) — a **synchronous** call on the main thread.

Inside the binding (`module/blender_module.cpp`):

- **GPU path holds the GIL for the whole render.** `cuda_wavefront_render` is
  called at `blender_module.cpp:2267` with **no** surrounding
  `gil_scoped_release`; the comment at `:2249` states "render() holds the GIL
  for its whole duration (no gil_scoped_release)". The `render` binding
  (`blender_module.cpp:3446`) has no `py::call_guard<gil_scoped_release>()`
  (contrast `upload_geometry` at `:3485`).
- **CPU path already releases the GIL** but stays synchronous. The Phase 1b fix
  wraps `renderer.render(...)` in `py::gil_scoped_release release;`
  (`blender_module.cpp:2358`) so OpenMP-worker callbacks don't deadlock.

**Key insight the numbers force:** releasing the GIL is *not* decoupling. The
main thread is *inside* the synchronous `render()` C++ call, so it never returns
to Blender's event loop until the chunk finishes — there is no other thread to
run. Decoupling requires the render to execute on a **different thread than the
Blender main thread**, with `view_draw` reduced to a blit. This is exactly the
Cycles structure (§3a).

---

## 3. Design axes (concrete to this codebase)

### (a) Which thread owns the CUDA context / wavefront state

Two candidates:

- **A1 — native worker thread inside the `.pyd`.** A C++ `std::thread` owns the
  CUDA context and the wavefront device state; the binding grows a session API
  (`start_viewport_session` / `submit` / `poll_frame` / `request_cancel` /
  `stop`). Faithful to Cycles (`session->start()` spawns `Session::run`). Cost:
  large new native ABI surface, duplicates the accumulation/divisor logic that
  already lives in Python (`render_viewport_frame`), and every session call is a
  new cross-TU symbol needing `cpp-abi-guard`.
- **A2 — Python `threading.Thread` driving the existing (GIL-released) binding.**
  The addon owns a daemon worker that loops: wait for work → call
  `renderer.render(..., skip_upload=True)` (which releases the GIL) → publish the
  result → request a redraw. Native change is **one line of intent**: add
  `gil_scoped_release` around the GPU `cuda_wavefront_render`
  (`blender_module.cpp:2267`) so the GPU path matches the CPU path. Reuses the
  persistent renderer, the accumulation math, the divisor budget, and the
  Phase 1b cancel flag.

CUDA context constraint: the renderer uses the CUDA **Runtime API** (primary
context, shared per-process across threads that call `cudaSetDevice`). In A2,
`upload_geometry` runs on the **main thread** (it reads `bpy`/depsgraph — see
(c)) while `render` runs on the **worker**. Both touch the same primary
context. This is legal only if (i) the two never run concurrently (single-writer
handshake, (d)) and (ii) the worker's first device touch selects the same device
(`cudaSetDevice`). This cross-thread primary-context sharing is the single
biggest correctness risk (§5, Terra Q1) and must be verified, not assumed.

**Recommendation: A2.** It achieves the same decoupling as Cycles with a minimal
native footprint, keeps the mature Python accumulation/divisor/present-first
logic, and confines `bpy` to the main thread. A1 is only justified if the
cross-thread primary-context sharing proves unsafe — in that case escalate to a
native session that owns *both* upload and render (a much larger change).

### (b) `view_draw` becomes a non-blocking blit + `tag_redraw`

Today `view_draw` renders then blits. Under A2 it must only: read the latest
**published** accumulation buffer, upload it to the `GPUTexture`, `draw_texture_2d`
(`exporter.py:998`), and `request_viewport_redraw` while the worker is still
refining. Publication is a numpy-array **reference swap** under the GIL: the
worker assigns `self._viewport_presented = new_accum` (atomic ref rebind in
CPython), `view_draw` reads that reference. No explicit lock, no copy on the hot
path. Buffer cost at 2112×829 float RGBA is ~7 MB; the *upload* to `GPUTexture`
(main thread) is the only per-frame cost and is sub-ms. The worker builds each
new accum array off-thread, so `view_draw` never touches a half-written buffer.

### (c) `view_update` hands scene edits to the worker

**Hard constraint: `bpy` must never be touched off the main thread.** The scene
export (`sync_viewport_scene` / `apply_depsgraph_updates`, reached from
`view_update` at `exporter.py:751-767`) reads the depsgraph and calls
`renderer.upload_geometry` — this stays **entirely on the main thread**. The
handoff to the worker is therefore *not* a `bpy` snapshot but a device-state
transition: view_update (main thread) exports bpy → native device state via
`upload_geometry`, then signals the worker "state N is ready, (re)start". The
worker only ever calls `render(skip_upload=True)` against already-uploaded
device state. This mirrors Cycles' split: `sync_recalc`/`sync_data` run on the
main thread under `scene->mutex`; `Session::run` renders.

### (d) Cancellation / restart / no mixed accumulation

The unavoidable hazard: while the worker is mid-render (reading device state),
the next `view_update` wants to `upload_geometry` (mutating device state) — a
data race on the BVH/device buffers. Cycles serialises this with `scene->mutex`
+ `session->reset()`. Astroray's equivalent, reusing Phase 1b:

1. view_update sets `_request_viewport_cancel()` (`exporter.py:361`).
2. The worker's `render` polls the cancel hook between passes
   (`blender_module.cpp:2255` GPU hook; CPU tile loop) and returns within one
   pass (~4–9 ms p95, in-process).
3. view_update **waits for the worker to reach idle** (a bounded join, ≤ the
   cancel-ack budget), then `_consume_viewport_cancel` drops the partial accum
   (`exporter.py:372`, keyed on `render_key`), does `upload_geometry`, and
   releases the worker on the new state.

So the main thread blocks only for the ~9 ms cancel-ack, not a full render —
this is what keeps the §1 tick-gap ≤ 33 ms. `render_key` is the single writer of
"which state is live"; a cancelled chunk is never blended (no mixed
accumulation), reusing the existing Phase 1b guard.

### (e) Shutdown / GC ordering

The worker holds a reference to the persistent renderer. If the renderer is GC'd
or the CUDA context torn down while the worker renders → use-after-free / CUDA
crash. Ordering contract, enforced in the engine's stop path
(`RenderEngine.__del__` / view-layer teardown): (1) set a `stop` flag, (2)
request cancel (Phase 1b hook), (3) `join` the worker with a timeout, (4) only
then release the renderer. The worker must be a **daemon** thread that checks
`stop` every pass so a hard Blender exit (which may skip `__del__`) cannot hang.
Never destroy the renderer before the join returns.

### (f) CPU backend (OpenMP-OFF ⇒ single-threaded render)

The addon `.pyd` is built `-DASTRORAY_DISABLE_OPENMP=ON`
(`mingw_openmp_blender_deadlock`: libgomp deadlocks at module init in Blender's
MSVC host — the reason is *init*, not threading, so this stays OFF in Phase 2).
Consequence: the CPU render is **single-threaded**. Moving it to the worker
thread **does** recover UI responsiveness (the main thread is free while the one
worker thread renders) — that is the entire point and it works for CPU too. What
it does **not** do is make CPU faster: per-frame CPU cost is unchanged
(Phase-0: ~1.7 s big-camera to ~23 s metal-material), so the CPU viewport
presents rarely but the UI stays interactive — exactly Cycles' CPU-viewport
behaviour. A single background `threading.Thread` reintroduces no libgomp, so the
deadlock memory does not regress. Do **not** re-enable OpenMP to speed CPU up.

### (g) Failure modes

- **Worker exception** (Python or a C++ exception surfaced through pybind): must
  be caught in the worker loop, stored, and re-raised/reported on the next
  main-thread poll — exceptions cannot cross the thread boundary implicitly.
- **CUDA error on the worker**: the primary context may be left invalid; mark
  the session dead, stop the worker, report via `self.engine.report`, and fall
  back to a clear error rather than spinning on a broken context.
- **Partial CUDA state at cancel**: the Phase 1b hook returns the last
  *complete* host-accumulated frame; a partial pass is dropped, never published.
  No device-side preemption (Non-goal).

### (h) What pkg147's safeguards give and forbid

pkg147 (PR #520) established: **any `.pyd` in Blender must be OpenMP-OFF**
(structural in `build_blender_addon.py`). It *gives* a single-threaded,
libgomp-free CPU engine that a worker thread can drive safely. It *forbids*
re-enabling OpenMP for the addon under any threading scheme. The Phase 1b GIL
release (`blender_module.cpp:2358`) is the companion: `render()` no longer holds
the GIL for the CPU path, which is the precondition that lets a Python worker
thread run `render` while the main thread services the UI.

**Only one option is viable for the `bpy` axis (c):** scene export must stay on
the main thread. There is no safe alternative. Everything else (A1 vs A2) is a
genuine tradeoff, and A2 is recommended.

---

## 4. Recommended design + bounded plan

**Design (A2, five sentences).** Add a `gil_scoped_release` around the GPU
`cuda_wavefront_render` so the GPU render path drops the GIL exactly as the CPU
path already does. Introduce one addon-owned daemon worker thread that is the
sole caller of `renderer.render(skip_upload=True)`, publishing each completed
accumulation buffer by atomic numpy-reference swap. `view_draw` stops rendering
and only blits the latest published buffer + `request_viewport_redraw`;
`view_update` keeps doing the `bpy`→device `upload_geometry` on the main thread,
then hands the new state to the worker through a cancel-then-restart handshake
gated by the Phase 1b cancel hook (~9 ms). Cancellation, stale-frame guarding,
and no-mixed-accumulation reuse the existing `_viewport_cancel_requested` /
`render_key` / present-first machinery. CUDA context stays a single shared
primary context, serialised so upload (main) and render (worker) never overlap.

**Phases:**

- **P2.0 — measurement in-tree (before any threading change).** Land the
  `2026-09-08-phase2/` results and the tick-gap recorder in
  `benchmarks/viewport_parity/blender_driver.py --mode interactive`
  (`exporter.py`/`run.py` recorder extended, not forked — spec §Files). Verify
  §1 baseline reproduces. *Verify: baseline p95 ≈ 179/274 ms recorded in tree.*
- **P2.1 — native GIL release (GPU).** Wrap `cuda_wavefront_render`
  (`blender_module.cpp:2267`) in `py::gil_scoped_release`. No signature change,
  but it is GIL-semantics on a Blender-reachable path → `cpp-abi-guard` +
  fresh sm_120 build identity. *Verify: GPU render byte-identical on a fixed
  seed (null-callback path unchanged); in-process test that a second Python
  thread makes progress during a GPU render.*
- **P2.2 — worker session + view_draw blit + handshake** (`blender_addon/
  exporter.py` only). Daemon worker, publish-by-reference, `view_draw` blit-only,
  view_update cancel→join→upload→restart, shutdown join in `__del__`.
  *Verify: in-process addon tests (bpy stubbed) — worker publishes a frame;
  view_draw blits the published buffer without calling render; a mid-render
  edit cancels+joins before upload (no overlap); shutdown joins before renderer
  release; worker exception surfaces on the main thread.*
- **P2.3 — acceptance gate (Blender bridge).** Re-run the §4/P2.0 recorder with
  the worker live: **main-thread tick-gap p95 ≤ 33 ms** on both scenes, GPU and
  CPU; frames still refine to target SPP; a mid-refine camera/material edit
  produces the correct new frame with no stale present and no mixed accumulation;
  cancel-ack p95 ≤ 200 ms. Save viewport PNGs (mid-orbit coarse + settled full)
  for Astra/Claude visual sign-off. *This bridge re-run is the acceptance gate.*

**Files:** `module/blender_module.cpp` (P2.1, one guard); `blender_addon/
exporter.py` (P2.2, the worker + hooks); `benchmarks/viewport_parity/
blender_driver.py` + recorder (P2.0/P2.3); `tests/test_pkg241_*` (new in-process
worker tests). No new native symbols under A2.

**ABI / GIL review points for `cpp-abi-guard`:**
- The GPU `gil_scoped_release` (P2.1): confirm no Python object is touched inside
  the released region (the cancel hook re-acquires with `gil_scoped_acquire` —
  already the case at `blender_module.cpp:2255`), and that the null-callback path
  is byte-identical.
- Confirm `render` and `upload_geometry` called from **two different threads**
  against one primary context is safe on this build (cross-thread CUDA Runtime
  primary-context sharing) — the load-bearing assumption.
- Fresh `.pyd` build identity (cuobjdump sm_120) after any native touch;
  OpenMP stays OFF.

**Explicitly NOT in scope:** multi-GPU / device migration; denoise-in-loop (OIDN/
OptiX stays a settled-frame pass); a native session API (A1) unless A2's context
sharing is proven unsafe; device-side render preemption; transport-math or
backend-selection changes; making CPU faster (OpenMP stays OFF); F12 final-render
threading (this is viewport-only).

---

## 5. Risks (ranked) and Terra questions

**Risks, highest first:**

1. **Cross-thread CUDA primary-context sharing.** `upload_geometry` (main) and
   `render` (worker) touch one primary context. If the Runtime API does not
   share it cleanly across these threads (or needs an explicit `cudaSetDevice`
   on the worker), renders corrupt or crash. Mitigation: verify with a targeted
   in-process two-thread upload/render test *before* P2.2; fall back to A1
   (native worker owning both upload and render) if it fails.
2. **Handshake race / UI stall.** If view_update's cancel→join is not tightly
   bounded (e.g. a pass that doesn't poll, or CPU where a "pass" is long), the
   main thread blocks > 33 ms and the gate fails. Mitigation: ensure the CPU
   tile loop polls the cancel flag frequently (Phase 1b sets it per-tile); cap
   the join with a timeout and treat a timeout as "keep old state this frame".
3. **Shutdown use-after-free.** Renderer GC'd or context torn down while the
   worker renders (esp. hard Blender exit skipping `__del__`). Mitigation:
   daemon worker + `stop` checked every pass + join-before-release contract (e).

**Lower:** worker exception surfacing (g); `request_viewport_redraw`/`tag_redraw`
thread-safety — whether a redraw can be requested from the worker or must be
pumped on the main thread (see Terra Q3).

**Questions for Codex Terra:**

1. Is CUDA Runtime primary-context sharing between a main-thread
   `upload_geometry` and a worker-thread `render` (serialised, never concurrent)
   safe on this sm_120 build, or must the worker own the context (forcing A1)?
2. Is the cancel→join handshake (main thread waits ≤ cancel-ack for the worker
   to reach a safe point before `upload_geometry`) the right serialisation, or
   should we adopt a Cycles-style `try_lock` on device state where view_update
   skips the upload this frame if the worker is busy (never blocking the UI at
   all, at the cost of one deferred edit)?
3. Can the worker request a redraw off-thread (`RenderEngine.tag_redraw` /
   `bpy.app.timers.register`), or must redraw requests be pumped from the main
   thread — and if the latter, is a modal timer or an idle `view_draw` pump the
   cleaner mechanism?
4. Is A2 (Python worker + existing binding) the right call over A1 (native
   session thread), given the cross-thread-context risk in Q1?
