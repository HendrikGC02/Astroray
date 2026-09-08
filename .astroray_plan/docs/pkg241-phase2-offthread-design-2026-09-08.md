# pkg241 Phase 2 — off-thread viewport render session (design, 2026-09-08)

Architect pass (Opus 4.8). This is a **design document only**: no engine/addon
code, no new spec. Phase 2 is NOT authorised by this doc — the lead runs Codex
Terra on it first. Grounded in the merged Phase 1b code (PR #748),
Phase 1a (PR #739), the Phase-0 design
(`pkg241-cancellation-design-2026-09-07.md`), and the Cycles viewport session
model (`intern/cycles/blender/session.cpp`, Apache-2.0, read via the Blender
`main` mirror — method names cited below are from that file).

> **Revision 2 (2026-09-08).** §1, §2 (the measured problem and the
> blocked call path) and the review record §6/§7/§8 are unchanged. §3–§5 are
> replaced by the implementation-ready design (§3 design, §4 forks + bounded
> plan, §5 test matrix), and a new §9 pins the A2 spike protocol. **Every
> file:line below was re-verified against this worktree's HEAD (32c39836); the
> line numbers differ from Revision 1 and from the §6/§7 review text, which
> were taken against an older tree — cite the numbers in §3–§5/§9, not the
> historical ones in §6/§7.**
>
> **Revision 3 (2026-09-08, this doc).** Codex Terra reviewed Revision 2 and
> returned **BLOCK** with seven ordered corrections (the verbatim review is §10).
> §3.2/§3.3/§3.4/§3.5/§3.6/§3.7/§3.8 and §9 are revised in place to resolve them;
> §1/§2/§6/§7/§8 are intact. **Every file:line in the revised sections was
> re-verified against this worktree HEAD (3fae3db7 — the source files are
> unchanged since 32c39836, both intervening commits are docs-only).** The
> Terra-item → section map is the Revision 3 changelog block below.
>
> **Revision 4 (2026-09-08, this doc).** Codex Terra reviewed Revision 3 (call
> 2/4) and returned **BLOCK** with seven ordered items (the verbatim review is
> **§11**). This is the LAST design round: the lead verifies Revision 4 against
> the seven items and dispatches the §9 spike without another Terra call. §3.1/
> §3.2/§3.3/§3.4/§3.5/§3.6/§3.8, §5 and §9 are revised in place with
> **"Terra review 3 → Revision 4"** resolution blocks; §1/§2/§3.7/§3.9/§6/§7/§8/
> §10 are intact. **Every file:line introduced by Revision 4 was re-verified
> against this worktree HEAD (ede966af — the source files are unchanged since
> 32c39836, all intervening commits are docs-only): `gpu_wavefront_snapshot.cu`
> :1482-1502 / :1669-1750 / :1843-2050, `blender_module.cpp` :2098-2101 /
> :2102-2107 / :2214-2221 / :2252-2264, `exporter.py` :624-632 / :670-723 /
> :701-707 / :709-723, `__init__.py` :1193-1199 / :6674-6694,
> `blender_recorder.py` :391-417 / :449-453, `blender_driver.py` :678-702.** The
> Terra-3-item → section map is the Revision 4 changelog block below.

## Revision 2 changelog — every Terra/lead/owner item → the section that resolves it

| Source | Item | Resolved in |
|---|---|---|
| Terra §6.1 | Diagnosis (both hooks render inline; GIL held on GPU) is correct | §1, §2 (kept) |
| Terra §6.2 | `skip_upload` premise wrong — it only skips `buildAcceleration()`; wavefront re-uploads scene arrays + rewrites process-global `__constant__` bindings every render; `WfContext` is a single-render-thread global | §3.1 |
| Terra §6.3 | A timeout join blocks the UI for its timeout → cannot establish p95 ≤ 33 ms; use non-blocking generation handoff | §3.4 |
| Terra §6.4 | Reference swap safe only if the published buffer is immutable; buffer costs wrong (RGBA f32 = 26.7 MiB, beauty RGB = 20.0 MiB); texture tail (`flat.tolist()`) not sub-ms | §3.3 |
| Terra §6.5 | Worker cannot call `render_viewport_frame` (it touches `bpy`, `GPUTexture`, `update_stats`, `tag_redraw`, `report`); use a main-thread-pumped `bpy.app.timers` queue; add an explicit shutdown owner | §3.2, §3.3, §3.6 |
| Terra §6.6 | One worker restores CPU UI responsiveness but not refinement cadence — report chunk/publish latency + frame age | §3.1, §3.4 |
| Terra §6.7 | Missing: widen GIL to the copy-back/`applyPasses` tail; a main-thread render-request snapshot; a process-wide render arbiter; monotonic generation tags; denoise as a latency concern; worker-exception storage/reporting; an expanded test matrix | §3.7, §3.2, §3.5, §3.4, §3.8, §3.9, §5 |
| Terra §6.8 | BLOCK — ordered pre-implementation list (1)–(6) + a minimal real-Blender A2 spike first | §3 (all), §9 |
| Lead §7.1 | Corrected device-state model; ONE process-wide GPU/session arbiter that F12 and every 3D view share | §3.1, §3.5 |
| Lead §7.2 | Main-thread-only render-request snapshot (plain data); results via a queue pumped by a main-thread `bpy.app.timers` timer | §3.2, §3.3 |
| Lead §7.3 | Generation-tagged non-blocking handoff (cancel, keep last frame, defer restart until worker idle); timed join is never the serialisation; immutable buffer + reference swap; texture tail measured | §3.3, §3.4 |
| Lead §7.4 | Shutdown = acknowledged worker exit before renderer/context release; explicit main-thread lifecycle owner | §3.6 |
| Lead §7.5 | Widen GIL release to the GPU copy-back / `applyPasses` tail; viewport denoise a settled generation | §3.7, §3.8 |
| Lead §7.6 | Pre-implementation A2 spike; go/no-go decides A2 vs a native session (A1) | §9 |
| Owner §8 | Viewport denoise **settled-only** (interactive loop presents raw progressive chunks) | §3.8 |
| Owner §8 | **F12 PAUSES the viewport session** (pause/resume handshake) — no shared-GPU arbiter between F12 and the viewport; the arbiter is only for multiple 3D viewports of one session | §3.5 |

## Revision 3 changelog — Terra review 2 (§10) → the section that resolves it

| Terra 2 item | Correction | Resolved in |
|---|---|---|
| 1 | ONE global non-blocking admission token over EVERY `PyRenderer` mutation (backend/world/materials/lights/transforms/camera/passes/integrator), not only `upload_geometry`; define the scheduler (who acquires, try-acquire admission, queue-newest-generation-on-failure, release points) | §3.5 (token defined), §3.2 (acquired around the commit) |
| 2 | Snapshot commit point + complete fields: `render()` consumes the renderer's EXISTING `Camera`, so the main thread commits camera+settings+upload under the token then hands the token to the worker for the render only; snapshot gains `skip_upload`, full camera inputs, effective device/backend, every renderer-setting mutation; discard rules gain session/backend/device epoch + disposed-engine | §3.2 (commit point + fields + tradeoff), §3.3 (epoch discard rules) |
| 3 | State machine submits only the latest `desired_generation` (never N+1 when N+2 already arrived); every queued notification generation-tagged + validated against desired generation and session epoch; correct "main thread never blocks" — F12 pause and teardown DO wait, bounded, pumping the queue | §3.4 |
| 4 | F12 = process-wide pause gate over ALL viewport sessions: block admissions, cancel/drain every active viewport render, verify the global token is unowned, then start F12; release on every exit path | §3.5 |
| 5 | One central `stop_all()` invoked from `unregister`/`load_pre`/engine disposal (best-effort `__del__`) + a concrete hard-exit hook (`atexit`); process-global quarantine retains STRONG refs so Python finalisation cannot destroy a leaked renderer; never `engine.report` through a disposing engine | §3.6 |
| 6 | Settled-only denoise must operate on the ACCUMULATED image (Python running mean), not a fresh chunk; two options with a recommendation; add the missing tests | §3.8 (fork + recommendation), §5 (tests 11–15) |
| 7 | GIL region ends BEFORE the NumPy packaging (`:2374-2394` stays on the GIL); null-callback byte-identity test defined; §9 spike gains snapshot/token proof, same-device + per-generation CUDA error capture, end-to-end present-latency chain, and a defined correctness comparator | §3.7 (bounded range + identity test), §9 (spike additions) |

## Revision 4 changelog — Terra review 3 (§11) → the section that resolves it

| Terra 3 item | Correction | Resolved in |
|---|---|---|
| 1 | Complete device-state inventory (caustic/sampler/hair/guide/miss-coverage/light-pass/spectral-table rewrites + host per-type bounce mutation) + token scope: the global token is held from the main-thread commit through the completed `render()` **and** the worker's post-render pass extraction, and F12 acquires it before ANY F12-side preparation (renderer construction, configuration, scene conversion), not just before its final `render()` | §3.1 (full inventory + token-span statement), §3.2 (worker holds through pass extraction), §3.5 (F12 acquires before all prep) |
| 2 | Snapshot gains `reset_accumulation`, current/target spp, chunk sizing, and the transfer/reset semantics of the worker's private accumulator; worker-side pass extraction under the token (worker calls render + `get_render_pass_buffer` and nothing else); replace the unbounded `queue.Queue` with a **bounded latest-frame mailbox** (depth 1 per session; control/error on a separate small queue) with a stated memory bound | §3.2 (accumulation fields + pass ownership), §3.3 (bounded mailbox + memory bound) |
| 3 | Notification validation by class — data-plane frames require the current desired generation; control-plane idle/exited require the current in-flight generation + epochs (so a late `idle(N)` after desired N+2 advances the machine); errors are processed for the current session/epoch even when superseded; F12/teardown waits get an explicit timeout (5 s, with rationale) that yields the GIL so the worker's cancel callback can run | §3.4 (three validation classes + §3.4 contradiction fix + timeout/GIL-yield) |
| 4 | F12/teardown no-ack behaviour: F12 must NOT start if any viewport fails to drain within the timeout; that session is quarantined/terminal and the user gets one report from the module-level owner; timeout/failure behaviour for `load_pre` and `atexit` too | §3.5 (F12 no-ack), §3.6 (`load_pre`/`atexit` timeout/failure) |
| 5 | Session-scoped, idempotent lifecycle: split `stop_session(session)` from `stop_all()`; both idempotent and safe during disposal/finalisation; one engine's `__del__` never stops unrelated viewports; `engine.report` prohibited once disposal begins; fix the §3.6 "stop every live session" vs "stop_all for this session" wording | §3.6 (split + idempotence + wording fix) |
| 6 | Settled denoise on the accumulated image must define accumulation of the guide AOVs (albedo/normal) alongside beauty (same running mean, reset behaviour, immutable publication); settled denoise runs on the worker as its own token-holding job and yields/discards on a new edit; add the missing tests | §3.8 (guide-AOV accumulation + worker scheduling + discard), §5 (tests 18–23) |
| 7 | Spike gains a generation-tagged event schema (request, commit/token acquire+release, render start/end, cancel/idle ack, mailbox enqueue/dequeue + depth, texture-upload end, first blit); recorder + driver listed in touched files; pinned comparator (nonzero fixed seed, resolution+divisor, spp, linear output, per-channel mean-ratio ±5 % AND a max-abs-diff bound with derivation), a present-rate rule (presents ≥ 0.9 × completed generations), a mailbox-depth bound, and the texture-tail p95 rule (alternate `gpu.types.Buffer`-from-numpy path + passing rerun before GO) | §9 (event schema + touched files + pinned thresholds) |

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
  edit-boundary event to the **scene-sync handshake** (§3.4).

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
Cycles structure (§3.1/§3.4).

---

## 3. Revised design (Revision 2, implementation-ready)

Direction unchanged from Revision 1: **A2** — an addon-owned Python worker
thread drives the existing (GIL-released) binding; `bpy` never leaves the main
thread. Terra confirmed A2 is viable and that CUDA primary-context sharing does
not force a native session (§6.2). What follows corrects every premise Terra
flagged and makes the ownership, serialisation, lifecycle, and measurement
concrete against this HEAD.

### 3.1 Corrected device-state model — what `render()` actually touches

Revision 1 wrongly claimed `skip_upload=True` renders "from already-uploaded
device state" so the worker only reads. **That is false for the wavefront GPU
path.** Verified against HEAD:

- `skip_upload=True` only skips the CPU-side `renderer.buildAcceleration()`
  (`module/blender_module.cpp:2071-2072`). It does **not** skip the GPU upload.
- The wavefront driver `cuda_wavefront_render` (`src/gpu/wavefront/gpu_wavefront_snapshot.cu:1366`,
  cancel-hook parameter at `:1384`) calls `buildSceneArrays(renderer, &cam)` and
  uploads the scene slices on **every** render (`:1411`), then rewrites a set of
  process-global `__constant__` device bindings **every frame** via the host
  `setWavefront*Binding` calls: texture/normal/bump binding
  (`setWavefrontTextureBinding`, `:1447`), op-VM program binding
  (`setWavefrontProgramBinding`, `:1462`), world-volume + pixel-filter + bounce
  limits (`:1465-1499`), env-NEE binding (`setWavefrontEnvNeeBinding`, `:1618`),
  guide-AOV binding (`setWavefrontGuideBinding`, `:1693`), light-path-pass binding
  (`setWavefrontLightPassBinding`, `:1742`), and the adaptive-sampling binding
  republished **per round** inside the pass loop (`setWavefrontAdaptiveBinding`,
  `:1843`).
- All of this lives in one process-global `struct WfContext`
  (`gpu_wavefront_snapshot.cu:1026-1087`) reached through the function-local
  `static WfContext ctx` singleton (`wfCtx()`, `:1089-1092`). The file states the
  contract in a comment: **"Single render thread assumed"** (`:988`). The context
  caches grow-only device allocations, the ReSTIR reservoir SoA, and the
  cryptomatte/guide buffers — all mutated in place per render.
- The host cancel poll is checked only *between* wavefront passes
  (`if (cancelRequested && cancelRequested()) { ... break; }`, `:1883`), and the
  render ends on a `cudaDeviceSynchronize()` (`:1992`).

**Therefore the worker's `render()` call is a writer of process-global device
and `__constant__` state, not a reader.** The serialisation obligation is
absolute: a worker `render()` must never overlap (a) a main-thread
`upload_geometry` / `buildAcceleration` (which mutate the same host renderer and
BVH the worker's `buildSceneArrays` reads), or (b) any *other* `render()` — a
second viewport's worker, or an F12 final render, which reaches the same
`WfContext` and `__constant__` bindings even though F12 constructs its own
`astroray.Renderer()` object (`blender_addon/__init__.py:1193`). This is the
single load-bearing correctness fact and it forces one process-wide render
arbiter (§3.5). CPU is analogous but cheaper: the OpenMP-off addon render is one
serial tile loop over the same host renderer, so the same non-overlap rule
applies without any device global.

The consequence for the CUDA context (Terra §6.2): the Runtime primary context
is shared per process, made current per host thread by `cudaSetDevice`. The
worker's first device call must therefore `cudaSetDevice(dev)` to the same
device the main thread uploaded on; the spike proves this before any production
worker (§9).

> **Terra review 3 → Revision 4 (item 1) — complete device-state inventory + the
> token span.** The bindings enumerated above are the *complete* set of
> process-global state `render()` rewrites on every frame, re-verified against
> HEAD: pixel-filter + per-type **bounce** limits + **caustic** gate + progressive
> **sampler** mode + **hair** enable (`gpu_wavefront_snapshot.cu:1482-1502`),
> **guide**-AOV binding + **miss-coverage** + **light-path-pass** binding +
> **spectral**-table upload (`:1669-1750`), and the **adaptive**-sampling binding
> republished **per pass round** in the render loop (`:1843-2050`). Terra adds one
> more writer the earlier text missed: the GPU branch also **mutates per-type
> bounce state on the host renderer before dispatch** — `renderer.setPerTypeBounces(...)`
> at `blender_module.cpp:2102-2107`, executed on whatever thread calls the binding.
> The token span is therefore stated explicitly and is load-bearing:
>
> - **the global admission token is held continuously from the main-thread commit
>   (§3.2 — `setupCamera` + the `set_*`/`add_pass`/`upload_*` mutators, and the
>   `setPerTypeBounces` host mutation that the GPU path performs) through the
>   completed `render()` AND the worker's post-render pass extraction** (the
>   `get_render_pass_buffer` calls for non-combined passes, §3.2/§3.3). "Worker
>   idle" alone is never the safety mechanism; the retained token is. Only when the
>   worker enqueues "idle" — *after* it has finished render + pass extraction — is
>   the token released.
> - **F12 acquires the token before ANY F12-side preparation**, not merely before
>   its final `render()`: F12 constructs a fresh `astroray.Renderer()`, configures
>   it, and converts the scene at `__init__.py:1193-1199`, and every one of those
>   steps reaches the same host renderer BVH / device `WfContext` / `__constant__`
>   bindings. The F12 gate (§3.5) therefore raises before renderer construction, not
>   at the render call.

### 3.2 Main-thread render-request snapshot + commit point (the main thread commits; the worker only renders)

Terra §6.5 is correct that the worker **cannot** call `render_viewport_frame`
(`blender_addon/exporter.py:599`): that method reads Blender context through
`setup_viewport_camera` (`:634` → `_setup_viewport_camera`,
`blender_addon/__init__.py:1733`, which reads `context.region_data` /
`space_data` / the scene camera), creates a `GPUTexture`
(`update_viewport_texture` → `_update_viewport_texture`, `__init__.py:1801-1813`),
updates RenderEngine stats (`update_viewport_status` → `_update_viewport_status`
→ `self.update_stats`, `__init__.py:1393-1400`), and `tag_redraw`
(`_request_viewport_redraw`, `__init__.py:1387-1391`) is an engine call. None of
those may run off the main thread ([Blender threading
guidance](https://docs.blender.org/api/main/info_gotchas_threading.html)).

The fix is a **plain-data render-request snapshot** built entirely on the main
thread. **Corrected commit model (Terra 2, item 2).** Revision 2 implied the
worker consumes the snapshot and calls `render()` to apply it. That is wrong:
`render()` (`blender_module.cpp:2025`, `if (!camera) throw` at `:2029`) **consumes
the renderer's already-committed `Camera` member** — it does not take camera
inputs as arguments. A new camera reaches the engine only through `setupCamera`
(`blender_module.cpp:1543-1569`, which rebuilds `renderer.camera` in place), and
every viewport setting reaches it only through the `set_*`/`add_pass`/`upload_*`
mutators (`exporter.py:544-568` in `sync_viewport_scene`; `:634-668` in
`render_viewport_frame`). A worker that "only calls `render()`" therefore cannot
apply any edit. **So the snapshot must be *committed* into `PyRenderer` by
someone holding the admission token before the render runs.**

**Who commits, and when — the recommended split (main-thread commit).** The
**main thread** acquires the admission token (§3.5) and commits the whole
snapshot into the persistent `PyRenderer` — `setupCamera`, the `set_*` /
`clear_passes` / `add_pass` / `set_wavelength_range` / `set_integrator` mutators,
and `upload_geometry`/`upload_materials`/… — exactly the calls
`sync_viewport_scene` + `render_viewport_frame` make today, **still on the main
thread**. It then **hands the token to the worker for the `render()` call only**.
The worker does no `PyRenderer` mutation; it calls `render(..., skip_upload=True)`
against the now-committed state, accumulates into its private buffer, and releases
the token on idle.

> **Design fork — main-thread commit vs worker commit.** Two real placements for
> the mutator calls: **(a) main-thread commit** (recommended) — every `bpy`-derived
> write (`setupCamera` reads the resolved camera, the `set_*` reads `settings`, and
> `upload_geometry` reads the depsgraph) stays on the main thread; the worker only
> owns the pure-native `render()`. **(b) worker commit** — the snapshot carries
> *plain data only* (floats/ints/lists, never `bpy`), and the worker replays the
> plain-data mutators (`setupCamera(floats…)`, `set_integrator(name)`, …) before
> `render()`, keeping the main thread cheaper by moving the mutator loop off it.
> Tradeoff axes: (a) keeps 100 % of `bpy`-touching code on the main thread and
> makes the token hand-off trivially "commit done, render only" — but the main
> thread pays the mutator cost every generation; (b) shaves that cost off the UI
> thread but requires proving every mutator on the worker path is pure-native
> (no `bpy`, no `GPUTexture`) and lengthens the worker's token hold to include the
> uploads, widening the window a second viewport waits. **Recommend (a):** the
> mutator cost is small relative to `render()`, the depsgraph read
> (`upload_geometry`) is inherently `bpy` and cannot move to the worker anyway, and
> a "commit then render-only" hand-off is the simplest correct token protocol.

The snapshot the main thread commits from carries the **complete** set (Terra 2,
item 2 — Revision 2's list omitted these):

- **resolved camera, full inputs**: `look_from`/`look_at`/`vup`/`vfov`/`aspect`
  plus `aperture`, `focus_distance`, `shift_x`/`shift_y`, sensor/lens and ortho
  scale — every argument `setupCamera` (`blender_module.cpp:1543-1546`) and the
  perspective/ortho branch of `_setup_viewport_camera` (`__init__.py:1733`) take,
  computed on the main thread and stored as floats, never `rv3d`;
- **`skip_upload`** (the pkg114 `_viewport_skip_upload_next` flag, `exporter.py:524`)
  — whether this generation refits transforms only or does a full upload;
- `width`, `height`, and the `res_divisor` (the pkg196/pkg241 budget divisor from
  `_budget_start_divisor()`, `exporter.py:378`);
- `spp_chunk` and the per-type bounce limits (already plain ints);
- **effective device/backend** (the `device_mode`/`configure_backend` result,
  `exporter.py:502-505`) so the worker's `cudaSetDevice` and the arbiter agree on
  the target device;
- **every renderer-setting mutation** `sync_viewport_scene` + `render_viewport_frame`
  perform today: adaptive/clamp/filter-glossy/caustics/light-sampler
  (`exporter.py:544-568`), wavelength range + output mode + integrator + the AOV
  pass selectors and denoise toggle (`:634-668`);
- `generation` (a monotonically increasing int, §3.4), `session_epoch` and
  `device_epoch` (§3.3 discard rules), and `render_key` (`exporter.py:616`, the
  existing accumulation key);
- `denoise = False` for interactive frames (§3.8).

The worker's loop is: wait for the token hand-off on a committed generation →
`cudaSetDevice(dev)` (first call, §3.1) → `renderer.render(..., skip_upload=…)`
against the persistent renderer handle (the one native object it touches) →
accumulate into its **private** buffer → enqueue a "frame ready(generation)"
notification → release the token. Everything `render_viewport_frame` does today
that is Blender-facing — `setup_viewport_camera`, `GPUTexture` creation,
`update_stats`, `tag_redraw`, `report`, and the depsgraph-driven `upload_geometry`
— **stays on the main thread**: the main thread runs `upload_geometry` (still
inside `view_update`, reading the depsgraph) and the commit, and, when a
frame-ready notification arrives, does the `GPUTexture` upload + `tag_redraw` +
stats.

> **Terra review 3 → Revision 4 (item 2) — accumulation/reset fields in the
> snapshot, and worker-side pass extraction under the token.** The snapshot the
> main thread commits from is extended with the **operational accumulation state**
> the render loop already keeps today, so the worker owns a self-contained
> accumulate step:
>
> - **`reset_accumulation`** — the boolean the loop computes at `exporter.py:624-626`
>   (`reset_accumulation or render_key != self._viewport_accum_key or res_divisor !=
>   self._viewport_render_divisor`). When set, the worker's private accumulator is
>   dropped and re-seeded with the next chunk's `chunk.copy()` (the existing
>   first-chunk path, `exporter.py:711-713`);
> - **current spp / target spp** — `self._viewport_current_spp` and
>   `self._viewport_target_spp` (`exporter.py:630-632`); a generation whose current
>   already `>= target` renders nothing (the existing early-out at `:631`), so no
>   worker job is submitted;
> - **chunk sizing** — `spp_chunk` from `viewport_chunk_samples(settings, current_spp)`
>   (`exporter.py:670`) and the `res_divisor` (§3.2 list), which together fix the
>   per-chunk cost;
> - **accumulator transfer/reset semantics** — the worker's private accumulator IS
>   `self._viewport_accum_pixels`'s running mean (`exporter.py:709-721`): first chunk
>   `= chunk.copy()`; subsequent `= (accum*old_spp + chunk*samples)/new_spp`. This
>   accumulator is **private to the worker**; it is only ever *published* by writing
>   a fresh immutable reference (§3.3), never handed out and then mutated. On
>   `reset_accumulation` it is discarded, not carried across generations.
>
> **Worker-side pass extraction under the token (recommended over a native result
> API).** Terra is right that "the worker only calls `render()`" is untrue while the
> loop preserves non-combined viewport passes: after `render()` the loop calls
> `renderer.get_render_pass_buffer(viewport_display_pass)` for any pass other than
> combined/albedo/normal/depth (`exporter.py:701-707`). Rather than add a native
> result API, **the worker performs exactly `render()` + the `get_render_pass_buffer`
> extraction and nothing else**, both under the retained token (§3.1): the extraction
> reads the same `PyRenderer`/`Camera` the render just wrote, so it must be inside the
> token span and before "idle" is enqueued. This is the minimal change (it reuses the
> existing binding) and keeps every `bpy`-facing step on the main thread. A native
> "render-and-return-all-passes" API is the fallback only if a future pass type cannot
> be read back through `get_render_pass_buffer`.

### 3.3 Result publication — immutable buffer per generation, pumped by a main-thread timer

**Publication model (corrects Terra §6.4).** The worker accumulates each chunk
into a *private* numpy array (its own running-mean accumulator, the same math as
`exporter.py:709-721`, seeded with `chunk.copy()` on the first chunk as today at
`:711-713`). When a chunk completes it publishes by writing a **new** array
reference tagged with its `generation`; it never mutates a previously published
array. CPython's reference rebind is atomic under the GIL, so the reader sees
either the old or the new whole array, never a torn one — but this is only safe
*because the published array is immutable after publication*. The next chunk
accumulates into a fresh array (or into the private accumulator that is only
swapped in, never handed out and then mutated).

**Buffer costs (corrected).** At the pinned viewport region 2112×829 the beauty
buffer is RGB float32 = 2112·829·3·4 = **20.0 MiB**; the display RGBA float32 the
texture path builds is 2112·829·4·4 = **26.7 MiB** (Revision 1's "~7 MB" was
wrong). The texture path (`_update_viewport_texture`, `__init__.py:1801-1813`)
allocates the RGBA array, flips it (`rgba[::-1]`), then does
`gpu.types.Buffer('FLOAT', n, flat.tolist())` and builds a `RGBA16F` `GPUTexture`.
`flat.tolist()` converts ~5.8 M floats to a Python list every present — this is
**not** demonstrably sub-ms and is measured in the spike (§9). If it exceeds the
frame budget it is replaced by a `gpu.types.Buffer`-from-numpy path (pass the
contiguous float32 array's buffer directly instead of `tolist()`); that swap is
still main-thread-only.

**Transport (corrects Terra §6.5 / Lead §7.2; bounded per Terra 3 item 2).** The
worker never touches Blender. It publishes each completed frame into a **bounded
latest-frame mailbox** (below) and pushes a small **control/error notification**
onto a separate queue. A main-thread `bpy.app.timers` timer, **registered from the
main thread** at engine start, drains both each tick: it validates the generation
(§3.4), reads the mailbox's current frame, does the `GPUTexture` upload,
`update_stats`, and `tag_redraw`. This is Blender's documented cross-thread pattern
([timer queue pattern](https://docs.blender.org/api/main/bpy.app.timers.html)).
`view_draw` additionally polls the latest published buffer and blits it
(`draw_texture_2d`, `exporter.py:998`), so a redraw triggered by any cause still
shows the freshest frame — the timer guarantees a redraw is *requested* even when
Blender is otherwise idle.

> **Terra review 3 → Revision 4 (item 2) — bounded latest-frame mailbox and its
> memory bound.** An unbounded `queue.Queue` for frames can retain many immutable
> 20–27 MiB frames when the main-thread texture upload lags the worker's render
> rate (a slow `flat.tolist()` tail, §9), growing without limit. Replace it with a
> **bounded latest-frame mailbox, depth 1 per session**: the worker's "publish"
> overwrites the single mailbox slot with the newest immutable frame reference; a
> newer frame **replaces an unconsumed older one** (the older frame is simply
> superseded — a viewport only ever wants the freshest completed chunk). The
> reference rebind is atomic under the GIL, so the timer reads either the old or the
> new whole frame, never a torn one. **Control-plane and error notifications keep a
> separate small queue** (idle/exited/error/exception — never dropped, unlike stale
> frames; see §3.4 for the by-class validation). **Memory bound (per session):** the
> mailbox holds ≤ 1 published frame (≤ 26.7 MiB RGBA / 20.0 MiB RGB) at any instant,
> plus the worker's one private accumulator (≤ 20.0 MiB RGB) and, transiently, the
> main thread's one display RGBA under construction (≤ 26.7 MiB) — a hard ceiling of
> **≈ 3 frame-sized buffers ≈ 60–80 MiB per session, independent of texture-upload
> lag**, versus the unbounded old design. The control/error queue is
> notification-sized (kilobytes) and bounded at a small depth (e.g. 16); an error
> notification is never discarded to stay under it.

> **Design fork — how the redraw is pumped.** Two real options: (i) a
> main-thread `bpy.app.timers` timer that both drains the queue and calls
> `tag_redraw`, with `view_draw` reduced to a pure blit; (ii) rely on
> `view_draw` polling alone (no timer), pumping redraws from within the last
> `view_draw`. Option (ii) stalls the moment Blender stops issuing draws (idle
> viewport, no mouse-over), leaving a finished frame unpresented and the worker's
> notification unconsumed — exactly the failure Blender's docs warn about.
> **Recommend (i)** (timer as the liveness pump + `view_draw` as an opportunistic
> blit); it is the documented pattern and does not depend on Blender choosing to
> redraw. The timer interval is a settled ~16 ms (60 Hz) and unregisters with the
> session (§3.6).

**Discard rules — a published or in-flight frame is dropped when any of these
fails to match the current session state (Terra 2, item 2 adds the epoch and
disposed-engine checks; generation/resolution/scene/stopping are not enough):**

- its `generation` is older than the newest requested generation (superseded);
- its render was cancelled (§3.4);
- its `session_epoch` (or viewport/session identity) differs from the current
  session — a different 3D viewport, or the same viewport after a disposal +
  re-create, must not present a frame produced for the prior session;
- its `device_epoch`/backend differs from the current effective device/backend —
  a device or backend switch (`configure_backend`, `exporter.py:502-505`) bumps
  the epoch and invalidates every in-flight generation, because the frame was
  produced against a different `WfContext`/device state;
- the region resolution changed since it was requested (`width`/`height` mismatch);
- the scene was replaced (`load_pre`, §3.6);
- the session is STOPPING (§3.4/§3.6), or **the owning `RenderEngine` is being
  disposed** — a notification that arrives after `__del__`/`stop_all` began is
  dropped and never routed through the (now-disposing) engine (§3.6 forbids
  `engine.report` on a disposing engine).

Every queued notification (frame / idle / error / exited) carries `generation`,
`session_epoch`, and `device_epoch`; the main-thread timer validates all three on
drain (§3.4). A stale-on-any-axis generation is discarded, never uploaded, which
is what preserves the Phase 1a "no stale present after an edit" guarantee
(`renders_before_present` recorder metric).

### 3.4 Non-blocking generation handoff — the session state machine

The main thread **does not block on the worker for ordinary edits** (corrects
Terra §6.3 / Lead §7.3: a timed join blocks the UI for its timeout and so cannot
itself establish p95 ≤ 33 ms). Serialisation is by generation + state, not by
joining. **Precise claim (Terra 2, item 3): "the main thread never blocks" is
true for ordinary edits only.** The F12 pause (§3.5) and teardown/`stop_all`
(§3.6) DO wait — bounded, and by *pumping the queue* on the main thread until the
"idle"/"exited" acknowledgement arrives, never a blind `thread.join()`. Those two
paths are deliberate synchronisation points; every other edit is non-blocking.

The session tracks a single **`desired_generation`** — the newest generation the
user's edits have requested. It is bumped on every edit and is the *only*
generation ever submitted; intermediate generations that were superseded before
they could start are never submitted (Terra 2, item 3: after N is cancelled, if
N+2 has already arrived the main thread submits N+2, **never N+1**).

**States (per viewport session):**

- **IDLE** — no render in flight; worker parked on its queue.
- **RENDERING(gen N)** — worker is inside `render()` for generation N.
- **CANCEL_REQUESTED(gen N)** — main thread asked N to stop; waiting for the
  worker to report idle.
- **STOPPING** — session tearing down (§3.6); worker must acknowledge exit before
  any renderer/context release.

**Transitions and who owns each:**

- Main thread, on `view_update` (scene/material edit) or a substantive camera
  change in `view_draw`: **bump `desired_generation`** (to N+1, then N+2, … on
  each further edit), set `_request_viewport_cancel()` (`exporter.py:361`) → state
  CANCEL_REQUESTED(N). It **keeps the last published frame on screen** and
  **defers the commit + submit** until the worker reports idle. It does not join.
- Worker: polls the cancel hook (GPU between passes,
  `gpu_wavefront_snapshot.cu:1883`; CPU per tile), returns the partial/last
  frame, drops it if its generation was cancelled, enqueues an
  "idle(gen=N, session_epoch, device_epoch)" notification → the timer moves the
  session to IDLE and **releases the token** (§3.5).
- Main thread, on the next timer tick after a validated "idle": now that no render
  is in flight, acquire the token, run the commit for **the current
  `desired_generation`** (which may be N+2, not N+1 — the intermediate generations
  are never submitted), i.e. `upload_geometry` + the mutators (§3.2, main thread,
  safe — the worker is idle), hand the token to the worker, submit →
  RENDERING(`desired_generation`).

**Notification validation — by class (Terra 2 item 3, corrected by Terra 3 item 3).**
Every queued notification — frame, idle, exited, error — is tagged with
`(generation, session_epoch, device_epoch)`. Revision 3 said "every superseded
notification is discarded" and then that a late `idle(N)` advances to IDLE — a
self-contradiction Terra flagged. Revision 4 splits validation into **three classes
with different rules**, which removes the contradiction:

- **Data-plane frames** — validated against the **current desired generation**: a
  frame whose `generation` is older than `desired_generation`, or whose epoch no
  longer matches (§3.3), is **discarded** and never blitted. This is what preserves
  "no stale present after an edit".
- **Control-plane idle / exited** — validated against the **current in-flight
  generation** (the generation actually running) plus the session/device epochs, not
  against `desired_generation`. So a late `idle(N)` that arrives *after* the user has
  already requested N+2 is **consumed as "the in-flight render N has finished"**: it
  advances the machine to IDLE and releases the token, and the subsequent submit uses
  `desired_generation` = N+2 (never N+1). It is **not** discarded as "superseded" —
  discarding it would strand the state machine in RENDERING forever.
- **Errors** — processed for the **current session/epoch even when their generation
  is superseded**: a CUDA fault or worker exception is *never* dropped for being for
  an old generation (a superseded render can still have corrupted the shared
  `WfContext`/primary context). An error is discarded only if its session/device
  epoch no longer matches (a fully torn-down session).

This closes the N→N+2 race exactly: the render *did* stop, the control-plane
`idle(N)` advances the machine, and the next submit is `desired_generation` = N+2.

So a fresh edit while a chunk renders costs the main thread only the flag +
generation-bump writes (sub-µs); the actual commit/restart happens one timer tick
later, off the UI's critical path. `view_update` is thus reduced to: request
cancel, bump `desired_generation`, return. This is the Cycles structure:
`BlenderSession::view_draw`
blits; scene sync runs under `scene->mutex`; `Session::reset` supersedes the
in-flight sample set rather than joining the render thread.

> **Design fork — deferred-upload vs Cycles `try_lock`-skip.** Terra §6.3 raised
> the Cycles `try_lock` alternative: `view_update` attempts the device lock and,
> if the worker holds it, **skips the upload this frame entirely** (never blocks,
> at the cost of one dropped edit that the next update re-applies). The
> deferred-upload model above instead *always* applies the edit, one tick late.
> Both keep the UI non-blocking. **Recommend deferred-upload**: an interactive
> edit must not be silently dropped (a material tweak that "doesn't take" until
> you nudge again is a worse UX than a one-tick delay), and the generation stamp
> already guarantees no stale/mixed accumulation. `try_lock`-skip stays the
> fallback if the deferred queue ever grows unbounded under a storm of edits
> (bound it: collapse pending edits to the newest generation).

**Worst-case UI-block budget per backend** (the cancel-ack the main thread would
incur if it *did* wait — here it does not, but the worker must still reach idle
promptly so the deferred upload is not perceptibly late). From Phase 1b
in-process cancel-ack (spec Progress): **GPU** worst case is the currently
executing wavefront pass plus its resolve/`cudaDeviceSynchronize`
(`gpu_wavefront_snapshot.cu:1883` poll, `:1992` sync) — measured p95 4.1 ms
(metal), 8.6 ms (big), but not a hard bound (a pass with no interior poll is the
ceiling). **CPU (OpenMP-off addon)** worst case is one complete 16×16 tile at the
requested spp/depth plus pre-loop BVH/integrator setup — seconds on the slow
oracle. The design therefore reports **chunk/publish latency and frame age**, not
a refinement-rate claim, on CPU (Terra §6.6): the CPU viewport stays interactive
(UI free) but presents infrequently, exactly Cycles' CPU-viewport behaviour.

> **Terra review 3 → Revision 4 (item 3) — the F12/teardown wait: bounded timeout
> that yields the GIL.** "The main thread never blocks" is true **for ordinary edits
> only**; the two deliberate synchronisation points — the F12 pause (§3.5) and
> teardown/`stop_session`/`stop_all` (§3.6) — DO wait for the worker's
> "idle"/"exited" acknowledgement. That wait is:
>
> - **bounded by an explicit timeout of 5 s per session.** Rationale: the worker
>   reaches idle within one wavefront pass + `cudaDeviceSynchronize` on GPU (measured
>   p95 4.1–8.6 ms) or one 16×16 CPU tile at viewport spp/divisor (sub-second to a few
>   seconds on the slow oracle); 5 s comfortably exceeds the worst legitimate
>   single-tile cancel-ack at interactive settings while still bounding a genuinely
>   **hung** worker so F12/teardown cannot stall the UI indefinitely. On timeout the
>   session is treated as **no-ack** — quarantined/terminal (§3.5 for F12, §3.6 for
>   teardown), never force-released.
> - **implemented by pumping the queue and yielding the GIL**, never a blind
>   `thread.join()`. The main thread loops on `queue.get(timeout=…)` / short
>   `time.sleep`, both of which **release the GIL**, so the worker's cancel callback
>   — which **reacquires the GIL** at `blender_module.cpp:2252-2264` before touching
>   `progressCallback` — can actually run and report idle. A busy-spin that held the
>   GIL would deadlock the very acknowledgement the wait is for.

### 3.5 The global admission token, multiple viewports, and F12 as a process-wide pause gate

**One global non-blocking admission token (Terra 2, item 1).** Revision 2's
"arbiter" guarded only `render()` (and mentioned `upload_geometry`). That is
insufficient: **every** mutation of the persistent `PyRenderer` touches the same
process-global state and must be mutually exclusive with every other viewport's
render. The depsgraph apply mutates backend, world, materials, lights, and transforms
(`exporter.py:502-533` in `apply_depsgraph_updates`), the scene sync mutates
adaptive/clamp/filter-glossy/caustics/light-sampler + materials + geometry +
lights + world (`:544-580` in `sync_viewport_scene`), the frame setup mutates
camera + wavelength + integrator + passes (`:634-668`), and `setupCamera` rebuilds
`renderer.camera`
(`blender_module.cpp:1543-1569`) — all against one `PyRenderer` whose GPU render
reads a single process-global `WfContext` (§3.1, "Single render thread assumed" at
`gpu_wavefront_snapshot.cu:988`). So the token covers **all prepare / upload /
configure / commit / render work**, not just `render()`. "This worker is idle" is
insufficient to touch the renderer while *another* viewport owns the token.

**The scheduler (module-level singleton, not per-engine):**

- **Who acquires:** the *main thread* acquires the token before any commit
  (§3.2 — `setupCamera`, the `set_*`/`add_pass` mutators, `upload_*`) and holds it
  across the hand-off to the worker's `render()`; the worker holds the token only
  for the `render()` call and releases it when it enqueues "idle".
- **Non-blocking admission (try-acquire):** the main thread never *waits* on the
  token during an ordinary edit. On a `view_update`/`view_draw` edit it bumps its
  `desired_generation` (§3.4) and **try-acquires**. On success it commits + submits;
  **on failure (another viewport holds the token) it does not block** — the edit is
  recorded as that viewport's newest desired generation and retried on the next
  main-thread timer tick (§3.3). Per viewport, only the newest desired generation is
  ever pending; older queued generations collapse into it.
- **Release points:** the worker releases on "idle"/"error"/"exited"; the main
  thread releases immediately after a commit that is *not* followed by a render
  (e.g. a settle with no new work), and after F12 (below). Exactly one holder at a
  time, process-wide.

This is what makes two 3D viewports of one session safe: each viewport's engine
try-acquires the shared token; the loser retries next tick against its collapsed
newest generation, so the two never call `render()` (or mutate the renderer)
concurrently.

**F12 = a process-wide pause gate over ALL viewport sessions (Terra 2, item 4;
owner decision §8).** Revision 2 paused only "the viewport session", but the design
permits multiple viewport sessions, so a *local* pause of one viewport leaves
another free to enter `render()` between that local idle-ack and F12 — a race
through the shared `WfContext`. F12 must instead raise a **process-wide pause
gate**. The handshake, all on the main thread, on entry to `RenderEngine.render`
(the F12 final-render path, `blender_addon/__init__.py:1161`, which builds its own
`astroray.Renderer()` at `:1193`):

1. **Raise the gate: block all new admissions.** Set a module-level
   `f12_paused` flag the token scheduler checks — while it is set, *no* viewport
   may acquire the token (every viewport's try-acquire fails and re-queues its
   newest generation). This is what closes the "another viewport enters `render()`
   between a local idle-ack and F12" window: once the gate is up, no viewport can
   be admitted, so none can start a new render.
2. **Cancel + drain every active viewport session.** For each session,
   `_request_viewport_cancel()` and **pump the queue on the main thread until its
   "idle" arrives** (bounded by the 5 s per-session timeout that yields the GIL —
   §3.4). A session already idle is skipped.
3. **Verify the global token is unowned, then acquire it — before ANY F12-side
   preparation (Terra 3 item 1).** Because the gate blocks admissions and every
   active render has drained to idle (releasing the token), the token is provably
   free; **F12 acquires it now, and holds it across its own renderer construction,
   configuration, and scene conversion** (`astroray.Renderer()` +
   `set_adaptive_sampling` + `convert_scene` + `_configure_backend_for_context`,
   `__init__.py:1193-1199`), not merely across its final `render()`. Those steps
   mutate the same host renderer / device `WfContext` / `__constant__` bindings a
   viewport render reads (§3.1), so the token must enclose them too.
4. Run the F12 render on the main thread exactly as today (it already releases the
   GIL on the CPU path and, after §3.7, on the GPU path too), then release the token.
5. **Lower the gate on every F12 exit path — success, cancel, exception** (a
   `finally`): clear `f12_paused`. Each viewport session resumes with a **new
   generation** (forces a fresh commit + render; the pre-pause partial is discarded
   by the generation bump).

Because the gate blocks admissions process-wide and F12 holds the token only after
every viewport has drained, F12 and any viewport never hold the token
simultaneously — the gate + drain is the serialisation. The token scheduler (above)
remains the serialisation between multiple 3D viewports of one running session.

> **Terra review 3 → Revision 4 (item 4) — F12 no-ack behaviour.** "Verify the
> token unowned" needs an enforceable failure path when a viewport does **not**
> drain. Rule: **F12 must NOT start if any active viewport fails to reach "idle"
> within the 5 s drain timeout (§3.4).** On such a timeout that session is treated as
> **no-ack** and moved to the quarantine registry (§3.6) — marked **terminal**, its
> renderer/thread retained by strong reference, never force-released — and F12
> **still starts** only once *every remaining* session is either idle or quarantined,
> so the token is provably unowned by any *live* worker. (A quarantined worker that
> is genuinely hung inside `render()` is holding no releasable token from the
> scheduler's view because it never acked; the strong-ref quarantine, not a forced
> release, is what keeps it memory-safe.) The user gets **one** report of the
> quarantined session **from the module-level lifecycle owner, not through the
> engine** (§3.6 prohibits `engine.report` on a disposing/faulted engine). The gate
> still lowers on every F12 exit path (step 5), and the quarantined session does not
> resume.

### 3.6 Shutdown / lifecycle — acknowledged worker exit before any release

Terra §6.5 / Lead §7.4: daemon-plus-timeout is insufficient; a use-after-free is
possible if the renderer or CUDA context is released while the worker is live.
Today `unregister()` (`blender_addon/__init__.py:6674`) only unregisters classes
and deletes props — there is **no** worker/session teardown, and there is **no**
`RenderEngine.__del__` in the addon.

Add an **explicit main-thread lifecycle owner** with a **session-scoped /
process-scoped split (Terra 2 item 5, sharpened by Terra 3 item 5)**. Revision 3's
single `stop_all()` was self-contradictory: it "stops every live session" yet the
`__del__` bullet called it "for this session". Revision 4 defines **two idempotent
functions**:

- **`stop_session(session)`** — stops **exactly one** session: request cancel, **pump
  the queue until that session's acknowledged "exited"** arrives (bounded by the 5 s
  timeout, §3.4), then release *its* renderer handle and unregister *its* timer. It
  never touches any other session. Callers: one viewport engine's `__del__` (dispose
  just that engine's session) and the F12 pause of a single session.
- **`stop_all()`** — stops **every** live session: raise the F12-style admission gate
  (§3.5) so nothing new starts, then `stop_session(s)` for each live `s`. Callers:
  addon `unregister`, `load_pre`, and `atexit`.

Both are **idempotent and safe to call during disposal/finalisation**: a second call
(a double `unregister`, or `__del__` firing after `unregister` already ran) is a
no-op — the session is looked up in the live registry and, if absent or already
STOPPING, the call returns immediately without raising and without unregistering a
timer twice. **One engine's `__del__` must never stop unrelated viewports** — it
calls `stop_session(self.session)`, never `stop_all()`. Triggers, their entry points,
and Blender's guarantees:

- **`RenderEngine` disposal — a new `__del__`** (there is none today; only
  `unregister` at `__init__.py:6674-6694`): a *best-effort* **`stop_session(self.session)`**
  (never `stop_all()`). Blender calls `__del__` when a view layer / viewport engine is
  freed but **does not guarantee** it runs promptly, or at all on interpreter/hard
  exit, so it is never the sole guarantee; and because it is scoped to this session it
  cannot terminate another viewport that is still live.
- **`bpy.app.handlers.load_pre` / file replacement** — the scene the renderer
  references is about to vanish; `stop_all()` before the new file loads (register
  a `load_pre` handler on the main thread).
- **Addon `unregister`** — extend `unregister()` (`__init__.py:6674`) to call
  `stop_all()` (cancel → await exit → release) and unregister the timer(s) and the
  `load_pre`/`atexit` handlers.
- **F12 transition** — the pause handshake (§3.5) is the same gate + await-idle path
  (F12 pauses rather than tears down).
- **Hard exit — a concrete `atexit` hook.** Register `stop_all()` via
  `atexit.register` (module import time). It runs during normal interpreter
  shutdown and is the one deterministic hook available (`bpy.app.handlers` has no
  "quit" handler that fires before threads are torn down). **What it can guarantee:**
  an ordered cancel + drain on a *clean* `bpy` quit. **What it cannot:** a
  crash/`os._exit`/native-abort path skips `atexit` entirely — for that the worker
  being a **daemon thread** is the only backstop (the process dies without the
  daemon hanging it), and any in-flight CUDA work is abandoned to driver teardown.

**Quarantine — if the worker does not acknowledge (Terra 2, item 5).** On a timeout
waiting for "exited", the renderer/context is **leaked, not destroyed**: the session
is marked dead and its renderer handle, session object, and thread are moved into a
**process-global quarantine registry that holds STRONG references** to all three.
This is load-bearing — without a strong ref, Python finalisation could later collect
the "leaked" renderer while the unacknowledged worker is still inside `render()`,
which is the exact use-after-free the acknowledgement gate exists to prevent. The
strong ref keeps the renderer alive for the life of the process; no uncoordinated
CUDA context reset is attempted (Terra §6.7: primary contexts are shared resources).
The error is surfaced through the **module-level owner, not `engine.report`** — the
engine that owned a quarantined session may itself be disposing, and calling
`engine.report` on a disposing engine is unsafe (Terra 2, item 5). Daemon status
makes hard-exit safe; it does **not** make release-while-live safe, so release is
strictly gated on the acknowledgement.

> **Terra review 3 → Revision 4 (items 4 & 5) — timeout/failure for `load_pre` and
> `atexit`, and no `engine.report` during disposal.** The same 5 s no-ack rule
> (§3.4/§3.5) applies to every teardown trigger:
>
> - **`load_pre`** — `stop_all()` before the new file loads. If a session does not
>   ack "exited" within the timeout it is **quarantined (strong-ref), not released**:
>   the old scene's file is torn down by Blender, but the leaked renderer/thread stay
>   alive in the process-global registry so the still-running worker cannot touch a
>   freed renderer. The load proceeds; the quarantined session never re-registers.
> - **`atexit`** — `stop_all()` at interpreter shutdown. A per-session ack within the
>   timeout gives an ordered cancel+release on a clean quit; a session that does not
>   ack is left to daemon-thread teardown (the process is exiting anyway), and no
>   forced CUDA reset is attempted. `atexit` cannot cover `os._exit`/native-abort —
>   daemon status is the only backstop there (as above).
> - **`engine.report` is prohibited once disposal begins.** From the moment
>   `stop_session`/`stop_all`/`__del__` starts for a session, that session is
>   disposing and its `RenderEngine` may already be half-freed; all user-facing
>   messages (quarantine notices, worker exceptions, CUDA faults) route through the
>   **module-level lifecycle owner**, never `engine.report`. This is why the error
>   class in §3.4 is surfaced by the owner, not the engine.

### 3.7 GIL — widen the release to the whole GPU render tail

Verified: the GPU path holds the GIL across the entire render. `cuda_wavefront_render`
is called at `module/blender_module.cpp:2267` with no surrounding
`gil_scoped_release` (the comment at `:2249` states "render() holds the GIL for
its whole duration (no gil_scoped_release)"), the host→Camera pixel copy-back loop
runs at `:2277-2293`, and `renderer.applyPasses(*camera)` — the denoise/cryptomatte
pass tail — runs at `:2305`, all under the GIL. The `render` binding
(`:3446-3449`) has **no** `py::call_guard<py::gil_scoped_release>()` (contrast
`upload_geometry`, `:3486`). The CPU path already releases the GIL inside the
function (`py::gil_scoped_release release;`, `:2352`, around
`renderer.render(...)` at `:2353`).

**Change (P2.1) — the exact bounded release range (Terra 2, item 6/7).** Revision 2
called `:2305` a "packaging tail". That is wrong: the NumPy packaging does **not**
happen at `:2305`. `applyPasses(*camera)` at `:2305` is the last *native* step; the
actual NumPy packaging — `py::array_t<float>(shape)` (`:2376`), `result.request()`
(`:2378`), the pixel copy into `buf.ptr` (`:2380-2392`), and `return result`
(`:2394`) — runs **later** and **must stay under the GIL** (it constructs and returns
a Python object). So the release region is **exactly `:2267`–`:2305`** — the
`cuda_wavefront_render` call, the host→Camera copy-back (`:2277-2282`), the
light-path-pass scatter (`:2286-2297`), and `applyPasses` (`:2305`). The GIL is
**re-acquired before `:2374`** so the packaging block (`:2374-2394`) and everything
after it (the `lastRenderInfo*` writes, `:2362-2369`, which precede packaging and
touch no Python) run with the GIL held, matching the CPU path. Objects touched
inside the released region, and their handling:

- `progressCallback` (the cancel hook, `:2252-2265`) — already re-acquires with
  `py::gil_scoped_acquire acquire` at `:2255` before touching the Python object,
  so it is safe inside a released region. **Null-callback byte-identity test
  (Terra 2, item 6 — Revision 2's claim was not testable as written):** when
  `progressCallback.is_none()` the hook is null (`:2252-2253`) and no Python is
  touched. The test is a **fixed-seed GPU render with the callback argument
  *omitted* vs passed explicit `None`**, asserting **byte-identical** output across
  **representative pass/AOV configurations** (combined; albedo/normal/depth AOV;
  cryptomatte; light-path passes; OIDN denoise), plus the **worker-disabled
  regression** (the `ASTRORAY_VIEWPORT_WORKER` flag off path, §5 test 10). Both
  the omitted and explicit-`None` paths must resolve to the same null hook and the
  same fleet code, with or without the release region compiled in.
- `camera->pixels`, `passesOut`, the AOV out-pointers, `renderer`, `camera` — all
  C++ objects, no Python; safe to touch with the GIL released.
- Explicit `cudaSetDevice(dev)` on the worker's first device call (§3.1/§9) so the
  primary context is current on the worker thread.

This is a GIL-semantics change on a Blender-reachable symbol → `cpp-abi-guard`
review + a fresh sm_120 build identity (cuobjdump) are required; OpenMP stays OFF.

### 3.8 Denoise — settled-only (owner §8)

The interactive loop presents **raw progressive chunks**; denoise never runs
inside a refinement chunk. Today `render_viewport_frame` adds the OIDN/OptiX pass
per viewport chunk when `viewport_oidn` is set (`exporter.py:657-662`), and the
GPU path runs `applyPasses` after every render (`blender_module.cpp:2305`).

**Definition of "settled":** the target spp is reached
(`self._viewport_current_spp >= self._viewport_target_spp`, the existing check at
`exporter.py:631`) **or** an idle timeout elapses with no new generation requested.

**Corrected mechanism (Terra 2, item 6 — VERDICT WRONG on "one additional
generation").** Revision 2 said settling submits "one additional generation with
`denoise = True`" and the worker runs it. That does **not** denoise the settled
image. Viewport accumulation is a **Python-side running mean** over the private
accumulator (`self._viewport_accum_pixels`, `exporter.py:709-721`), whereas the
native `applyPasses(*camera)` (`blender_module.cpp:2305`) denoises the `Camera` of
**one individual `render()`** — the freshly rendered chunk, not the accumulated
buffer. So a "denoise generation" would denoise a brand-new single-chunk render and
throw away the many-spp accumulation the user waited for. Two real options resolve
this:

> **Design fork — where the settled denoise runs.**
> **(a) Native denoise entry point over the immutable accumulated buffer.** A new
> binding — e.g. `denoise_buffer(np.ndarray beauty, np.ndarray albedo, np.ndarray
> normal) -> np.ndarray` — that runs OIDN/OptiX over the *accumulated* beauty
> (plus the accumulated guide AOVs) and returns a denoised copy, with **no**
> `Renderer::render` involved. ABI surface: one new pybind symbol taking three
> contiguous `float32` `py::array_t` and returning one; it wraps the existing OIDN
> filter that `applyPasses` already drives, but on a caller-supplied buffer instead
> of `camera->pixels`. **cpp-abi-guard scope:** a new Blender-reachable export →
> guard review + fresh sm_120 identity, same as P2.1; it is **off the fleet path**
> (only the addon's settled step calls it; F12/CLI/tests never do) so it cannot
> regress fleet renders. Tradeoff: correct (denoises exactly the accumulated image),
> cheap at settle (no extra path-trace), but adds native ABI and a second denoise
> code path to keep parity with `applyPasses`.
> **(b) Explicit full-target re-render at settle.** At settle, submit one normal
> generation that renders the **full target spp in a single `render()` with denoise
> on**, replacing the accumulated buffer with that denoised full render. No new ABI.
> **Latency/quality contract:** the settle costs one full-target render (seconds on
> CPU, a full GPU budget on GPU) during which the last raw accumulated frame stays
> on screen; quality equals a fresh full-spp denoise, which can differ slightly from
> the progressive mean (independent sample set). Tradeoff: zero ABI, reuses the
> existing path, but pays a large latency spike at settle and briefly diverges from
> the accumulated pixels the user was watching.
>
> **Recommend (a):** it denoises precisely the image the user accumulated, the
> settle is near-instant (a filter pass, not a re-render), and the ABI cost is one
> off-fleet binding that reuses the OIDN filter `applyPasses` already owns.
> Option (b) is the fallback if the extra binding is judged not worth the ABI
> surface — accept the settle-latency spike instead.

In either option the denoise is **superseded like any other work**: a new edit that
arrives while the settled denoise (the binding call in (a), or the full re-render in
(b)) is pending or in flight bumps `desired_generation` (§3.4), and the denoise
output is discarded. The interactive `denoise = False` snapshots (§3.2) never add
the pass, so refinement chunks stay raw and cheap.

> **Terra review 3 → Revision 4 (item 6) — accumulate the denoise guide AOVs, and
> run the settled denoise on the worker.** Option (a) denoises the *accumulated*
> beauty, so it needs the *accumulated* guide AOVs (albedo, normal) too — but today
> viewport accumulation stores only the display beauty pixels (`exporter.py:709-723`),
> while the GPU guides originate in the native `Camera` buffers each render
> (`camera->albedoBuffer` / `normalBuffer` / `depthBuffer`, published to the driver at
> `blender_module.cpp:2214-2221`). Revision 4 defines their handling:
>
> - **Accumulation.** When the settled path is active, the worker reads back the
>   per-chunk guide AOVs (the same `get_render_pass_buffer`-style extraction, under the
>   token, §3.2) and maintains **one running-mean accumulator per guide** —
>   `_viewport_accum_albedo`, `_viewport_accum_normal` — with the **same weighting as
>   beauty**: first chunk `= chunk.copy()`, subsequent `= (accum*old_spp +
>   chunk*samples)/new_spp` (`exporter.py:709-721`). Depth is not a denoise guide and
>   is not accumulated. (Averaging the normal buffer is the pragmatic choice OIDN's
>   prefilter tolerates; the normals are re-normalised only inside OIDN's own
>   prefilter, not by us.)
> - **Reset.** The guide accumulators reset **together with beauty** on
>   `reset_accumulation` (§3.2) — same key, same divisor, same generation — so a guide
>   frame can never mismatch the beauty frame it denoises.
> - **Immutable publication.** At settle, the accumulated beauty **and** both guide
>   accumulators are frozen into immutable references and passed together to the
>   option-(a) binding `denoise_buffer(beauty, albedo, normal)`; the denoised result is
>   published as a new immutable frame (§3.3). The inputs are never mutated after the
>   call begins.
> - **Scheduling / discard.** The settled denoise **runs on the worker as its own
>   token-holding job** (recommended): it acquires the token like a render, so it is
>   serialised against every other renderer touch, and it **yields/discards on a new
>   edit** — a `desired_generation` bump while it is pending or in flight cancels it
>   (the worker checks the cancel flag before and, for option (b), during the
>   re-render), the token is released, and the interactive loop resumes with the fresh
>   generation. The half-computed denoise output is dropped, exactly like a superseded
>   render frame.

### 3.9 Failure modes

- **Worker exception** (Python or a C++ exception surfaced through pybind): caught
  in the worker loop, **stored** on the session, and **re-raised on the main
  thread** through the timer (exceptions cannot cross the thread boundary
  implicitly). The session is marked dead and `engine.report` (main thread)
  surfaces it. This mirrors the existing Phase 1b stash-and-rethrow for the
  callback exception path (`blender_module.cpp:2333-2337`, rethrow after metadata).
- **CUDA error on the worker** (e.g. an illegal access leaving the primary context
  invalid): **terminal for the session** — stop the worker, mark the session dead,
  report, and do **not** attempt an uncoordinated `cudaDeviceReset` (a shared
  primary context must not be reset out from under any other consumer, Terra §6.7).
- **Device loss** (TDR / driver reset): treated as a CUDA error — terminal, session
  dead, reported; recovery requires a fresh session, not an in-place reset.

## 4. Recommendation + bounded plan

**Recommendation: A2** (Python worker + the existing binding), with the
corrections above. A1 (a native session thread owning both upload and render)
remains the fallback and is chosen only if the §9 spike shows the cross-thread
serialised primary-context model is unsafe; A1 is a much larger native ABI change
and, per Terra §6.2, still cannot own Blender export (the main thread must
populate host renderer state without `bpy` escaping).

**Phases (implementation, gated on the §9 spike):**

- **P2.0 — spike (§9).** Go/no-go decides A2 vs A1. No production worker before it.
- **P2.1 — native GIL widening (GPU).** `py::gil_scoped_release` over
  `blender_module.cpp:2267-2305` + `cudaSetDevice` on the worker entry. `cpp-abi-guard`
  + fresh sm_120 identity. *Verify: GPU render byte-identical on a fixed seed with
  a null callback; a second Python thread makes progress during a GPU render.*
- **P2.2 — session owner + worker + timer pump + arbiter** (`blender_addon/exporter.py`
  + `__init__.py`, main-thread only for all `bpy`). Snapshot (§3.2), immutable
  publication + timer drain (§3.3), generation state machine (§3.4), process-wide
  arbiter + F12 pause (§3.5), lifecycle owner (§3.6). *Verify: the §5 test matrix.*
- **P2.3 — acceptance gate (Blender bridge).** Re-run `blender_driver.py --mode
  ui_latency` with the worker live: **tick-gap p95 ≤ 33 ms** on both scenes, GPU
  and CPU; frames still refine to target spp; a mid-refine edit produces the
  correct new frame with no stale present and no mixed accumulation; cancel-ack
  p95 ≤ 200 ms. Save viewport PNGs (mid-orbit coarse + settled) for Astra/Claude.

**Files:** `module/blender_module.cpp` (P2.1, one GIL region); `blender_addon/exporter.py`
+ `blender_addon/__init__.py` (P2.2, worker + session owner + timer + snapshot +
arbiter; all `bpy` stays main-thread); `benchmarks/viewport_parity/blender_driver.py`
+ recorder (P2.0/P2.3, the `--mode ui_latency` path already exists); `tests/test_pkg241_*`
(P2.2 in-process worker tests). No new native symbols under A2.

**Explicitly NOT in scope:** multi-GPU / device migration; denoise-in-loop (settled
only, §3.8); a native session API (A1) unless the spike proves A2 unsafe;
device-side render preemption; transport-math or backend-selection changes; making
CPU faster (OpenMP stays OFF); F12 final-render *threading* (F12 stays a main-thread
render, only paused/resumed against the viewport session).

## 5. Test matrix (P2.2, in-process with `bpy` stubbed where possible + the bridge)

Each row is an in-process addon test (stub `bpy`, `gpu`, and the timer where the
logic is Python-side) unless it needs the real bridge:

| # | Scenario | Assertion |
|---|---|---|
| 1 | Scene reload (`load_pre`) mid-render | worker cancels + acknowledges exit before the new file loads; no publish of a pre-reload generation |
| 2 | Addon `unregister` mid-render | session owner stops (cancel → await exit → release); timer unregistered; no leaked thread |
| 3 | Two viewports, overlapping edits | arbiter admits one render at a time; each viewport's newest generation wins; no concurrent `render()` |
| 4 | GPU F12 while the viewport refines | viewport session PAUSES, worker reaches idle before F12 renders, resumes with a new generation (bridge, real Blender) |
| 5 | Device loss / CUDA error on the worker | session marked dead, reported on the main thread, no `cudaDeviceReset`; renderer not released while worker live |
| 6 | Worker exception | stored, re-raised on the main-thread timer, session dead, `engine.report` called |
| 7 | Settled-only denoise | no denoise pass on interactive chunks; one denoise generation on settle; a new edit cancels a pending denoise |
| 8 | Cancel that never acknowledges (timeout) | renderer/context leaked (not destroyed), session dead + reported; no use-after-free |
| 9 | CPU backend | UI free while the single worker renders; chunk/publish latency + frame age reported (not a refinement-rate claim) |
| 10 | Byte-identity of the synchronous path with the worker disabled | with the `ASTRORAY_VIEWPORT_WORKER` flag off, `render_viewport_frame` behaviour is unchanged vs origin/main on a fixed seed |
| 11 | Rapid N→N+2 supersession (§3.4) | after N is cancelled and N+2 is requested before `idle(N)` drains, the main thread submits **N+2, never N+1**; an `idle(N)` that arrives late validates and advances state without submitting a stale generation |
| 12 | Token ownership across every uploader (§3.5) | the global admission token serialises **all** `PyRenderer` mutations — `setupCamera`, each `set_*`/`add_pass`, and `upload_*` — not only `render()`; a second viewport's commit cannot interleave a first viewport's render (assert single-holder invariant across a mutation storm) |
| 13 | F12 vs two viewports (§3.5) | with two viewport sessions active, F12 raises the process-wide gate, drains **both** to idle, verifies the token unowned, then renders; neither viewport can acquire the token between its local idle-ack and F12; the gate lowers on the exception path too |
| 14 | Timer deregistration / idempotence (§3.3/§3.6) | the `bpy.app.timers` timer(s) are unregistered exactly once on `stop_all()`; a second `stop_all()` (double `unregister`, or `__del__` after `unregister`) is a no-op and does not raise; no orphan timer keeps firing after teardown |
| 15 | Request-to-present latency + queue depth (§9) | the end-to-end request→idle→queue-drained→texture-uploaded→blit chain reports latency, frame age, queue depth, and successful-present count; a finished frame is never left unpresented (tick-gap passing while nothing reaches the screen is caught) |
| 16 | Null-callback byte-identity (§3.7) | a fixed-seed GPU render with the callback **omitted** vs explicit **`None`** is byte-identical across representative pass/AOV configs (combined, albedo/normal/depth AOV, cryptomatte, light-path passes, OIDN) |
| 17 | Settled-only denoise on the accumulated image (§3.8) | the settle denoises the **accumulated** buffer (option (a) binding over `self._viewport_accum_pixels`, or option (b) full re-render), not a fresh single chunk; interactive chunks carry no denoise pass; a new edit supersedes a pending denoise |
| 18 | Bounded mailbox / backpressure (§3.3) | under a worker that publishes faster than the timer drains (a stalled `flat.tolist()` tail), the latest-frame mailbox stays at **depth 1** — a newer frame replaces the unconsumed older one; total frame-buffer memory stays ≤ the §3.3 per-session bound; no unbounded growth; the control/error queue is never dropped under the same storm |
| 19 | Backend/device switch mid-render (§3.3) | a `configure_backend` device/backend change while a chunk is in flight **bumps `device_epoch`**; every in-flight generation for the old epoch is discarded on drain (never presented); the next generation renders against the new device with both threads on it |
| 20 | Superseded terminal error (§3.4) | a CUDA fault / worker exception tagged with a generation the user has already superseded is **still processed** for the current session/epoch (not discarded as stale); the session is marked terminal and the module-level owner reports it |
| 21 | AOV / non-combined pass presentation (§3.2) | with a non-combined `viewport_display_pass`, the worker extracts it via `get_render_pass_buffer` **under the token** after `render()` and publishes it; the presented buffer is that pass, not the beauty; no `bpy` call leaves the main thread |
| 22 | F12 drain timeout / no-ack (§3.4/§3.5) | a viewport that does not reach idle within the 5 s drain timeout is **quarantined (strong-ref, terminal)** and F12 still starts once every remaining session is idle-or-quarantined; the token is provably unowned by any live worker; the user gets one report from the owner, not `engine.report` |
| 23 | Denoise interrupted while running (§3.8) | a new edit that arrives while the settled denoise job (option (a) binding or (b) re-render) is pending/in-flight cancels it, releases the token, discards the half-computed output, and resumes the interactive loop at the fresh generation |

---

## 6. Codex Terra review (2026-09-08 ~05:10, lead-run, call 3/4) — VERDICT: BLOCK as written

1. VERDICT OK — The diagnosis is correct. Both hooks call `render_viewport_frame()` inline: `view_update` at `blender_addon/exporter.py:791-796`, `view_draw` at `:957-964`, and that calls `renderer.render()` at `:683-691`. Releasing the GIL cannot return the Blender main thread to its event loop while it remains in that synchronous C++ call. GPU holds the GIL across `cuda_wavefront_render`: the code explicitly says so at `module/blender_module.cpp:2245-2251`, calls CUDA at `:2267-2275`, and the binding has no GIL-release guard at `:3446-3449`. CPU alone releases it at `:2351-2355`.

2. VERDICT CHANGE — A2 is viable in principle; CUDA primary-context sharing does not force A1. CUDA Runtime primary contexts are shared per device/process, but `cudaSetDevice()` makes the context current per calling host thread. [NVIDIA CUDA Runtime documentation](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__DRIVER.html) supports that model. Add an explicit same-device selection on both threads and prove it.

   The current code is nevertheless unsafe for overlap. The wavefront driver says “Single render thread assumed” at `gpu_wavefront_snapshot.cu:963`, has a process-global mutable `WfContext` at `:1001-1062`, reallocates and overwrites cached pointers at `:973-999`, uploads scene buffers each render at `:1374-1415`, and rewrites global `__constant__` bindings at `:1413`, `:1635`, `:1684`, `:1692-1706`, and `:1785`. A second host thread touching any of that while a render is live is a race; default-stream semantics do not save the host-side state.

   More importantly, the document’s device-state premise is inaccurate: `skip_upload=True` only skips `renderer.buildAcceleration()` (`blender_module.cpp:2068-2072`); the wavefront path still rebuilds/upload scene arrays on every render (`gpu_wavefront_snapshot.cu:1374-1380`). A1 is not “broken,” but it cannot own Blender export: the main thread must still populate host renderer state without `bpy` escaping to the native worker. It is a larger session/snapshot design, not the required fallback for ordinary serialized A2.

3. VERDICT CHANGE — A timeout join is acceptable only as a “do not mutate/release state yet” outcome, not as the normal UI-serialization mechanism. A join blocks the UI for its timeout, so it cannot itself establish p95 ≤33 ms. Use a non-blocking busy/try-lock or generation-state pattern: request cancel, retain the old published frame, defer the upload/restart until idle.

   GPU worst case is the currently executing wavefront pass, followed by its synchronizing resolve/download; cancellation is checked only before each pass at `gpu_wavefront_snapshot.cu:1820-1825`, then `cudaDeviceSynchronize()` occurs at `:1927-1935`. The reported 8.7 ms p99 is encouraging but is not a hard bound. CPU worst case is one complete 16×16 tile at all requested samples/path depths, plus pre-loop BVH/integrator setup. Cancellation is only observed after a finished tile (`raytracer.h:4072-4075`, `:4192-4195`, `:4421-4426`); with the OpenMP-off addon it is one serial tile. Neither backend currently proves a 33 ms upper bound.

4. VERDICT WRONG — Reference swap under the GIL is safe only if the published array is immutable after publication. The worker must finish its accumulation in a private array, then swap the reference; it must never use that same array for the next accumulation. Current accumulation happens to create a new result (`exporter.py:710-721`), with a first-frame copy at `:711-713`, which is a workable ownership pattern.

   The size claim is wrong: 2112×829 RGBA `float32` is 28,013,568 bytes, about 26.7 MiB—not 7 MB. Current beauty is RGB float32, about 20.0 MiB. The main-thread texture path additionally constructs float RGBA, flips/copies it, converts it to a Python list, and creates a `GPUTexture` (`__init__.py:1801-1813`); “sub-ms” is unsupported and unlikely with `flat.tolist()`. Keep that GPU texture creation/upload on the main thread. Copy only before publication if the result can be reused/mutated; the display conversion/upload is necessarily separate.

5. VERDICT CHANGE — The daemon + stop flag + timed join is insufficient. The proposed worker cannot call the existing `render_viewport_frame()`: it reads Blender context through `setup_viewport_camera` (`exporter.py:634`, `__init__.py:1733-1799`), creates GPU drawing resources (`__init__.py:1801-1813`), updates RenderEngine stats (`:1393-1400`), and `tag_redraw()` is an engine call (`:1387-1391`). Nor may it call `engine.report`.

   Blender’s own guidance says persistent Python threads must not use Blender APIs; its timer documentation recommends a thread-safe queue pumped on the main thread. [Blender threading guidance](https://docs.blender.org/api/main/info_gotchas_threading.html), [timer queue pattern](https://docs.blender.org/api/3.3/bpy.app.timers.html). Install the timer on the main thread; the worker may only enqueue plain-Python notifications.

   There is no explicit RenderEngine destructor/worker shutdown path today; `unregister()` only unregisters classes (`__init__.py:6666-6686`). Add an explicit main-thread lifecycle owner for engine disposal, file/load replacement, addon unregister, and final-render transition. If shutdown join times out, renderer/context release must not proceed while the worker remains live; daemon status does not make use-after-free safe.

6. VERDICT OK — With strict separation, one worker does restore UI responsiveness on CPU: the CPU native render already releases the GIL (`blender_module.cpp:2351-2355`) and the OpenMP-off addon leaves the main Blender thread available. It does not improve CPU render cadence. The design should explicitly report CPU chunk/publish latency and frame age, not imply comparable refinement rate: the documented 1.7–23 s chunks mean a responsive UI but infrequent visible updates.

7. VERDICT CHANGE — Missing implementation-critical items:

   - Expand the GIL-release scope beyond only `cuda_wavefront_render`; GPU copy-back, `applyPasses()` (`blender_module.cpp:2276-2305`), and result packaging currently reacquire/hold it. Measure this tail.
   - Define a main-thread-only render request snapshot: camera, resolution divisor, passes, settings, generation, and render key. Current `render_viewport_frame()` configures all of them before rendering (`exporter.py:613-674`).
   - Add one process-wide GPU render arbiter. Multiple 3D views and F12 can otherwise overlap through the static `WfContext`; F12 creates a separate renderer (`__init__.py:1191-1195`) but reaches the same global wavefront state.
   - Tag every publication with a monotonically increasing generation, not only mutable shared accumulation fields. Discard cancelled, superseded, resolution-changed, or scene-replaced results.
   - Treat denoise as a cancellation/latency concern. It is currently enabled per viewport chunk at `exporter.py:657-662` and GPU invokes the pass pipeline after rendering (`blender_module.cpp:2295-2305`). Either defer it to a settled generation or include it in cancellation/latency gates.
   - Specify worker exception storage, main-thread reporting, and terminal-session behavior. Do not recover a shared primary context with an uncoordinated reset; CUDA documents primary contexts as shared resources.
   - Test scene reload, addon unregister, two viewports, GPU F12 while viewport refines, device loss, worker exception, denoise, and timed-out cancellation—not just ordinary cancel/restart.

8. VERDICT BLOCK — Do not implement the document as written. Before implementation, in order: (1) correct the `skip_upload`/wavefront-upload model and define a strict main-thread request snapshot; (2) make all Blender/GPUTexture/redraw/report work main-thread-pumped; (3) add a process-wide GPU/session arbiter plus generation-based non-blocking handoff; (4) specify shutdown as “acknowledged worker exit before release,” not daemon-plus-timeout; (5) expand the GIL and denoise/cancellation design; (6) correct buffer-cost claims and measure texture-upload tail. The single most important pre-implementation experiment is a minimal real-Blender A2 spike: main thread prepares generation N, worker calls only native GPU render with explicit `cudaSetDevice`, main requests cancel and prepares N+1 only after worker-idle, repeated across the two scenes while measuring tick-gap, cancellation p99, output correctness, and CUDA errors.

## 7. Lead decision (2026-09-08 05:15)

The A2 direction stands (Terra: viable, CUDA primary-context sharing does not force
A1), but the document is NOT implementation-ready. Before any threading code:

1. Revise §3(a)/§4 for the corrected device-state model: `skip_upload=True` only skips
   `buildAcceleration()`; the wavefront driver re-uploads scene arrays and rewrites
   `__constant__` bindings on every render (`gpu_wavefront_snapshot.cu:973-999`,
   `:1374-1415`, `:1413/1635/1684/1692-1706/1785`; "Single render thread assumed" at
   `:963`). Upload and render must be strictly serialised by ONE process-wide GPU/session
   arbiter that F12 and every 3D view share.
2. Define the main-thread-only render-request snapshot (camera, divisor, passes,
   settings, generation, render key) — the worker consumes plain data, never `bpy`,
   never `GPUTexture`, never `tag_redraw`/`report`; results come back through a queue
   pumped by a main-thread `bpy.app.timers` timer (Blender's documented pattern).
3. Generation-tagged, non-blocking handoff (request cancel, keep the last published
   frame, defer upload/restart until the worker reports idle); a timed join is never
   the serialisation mechanism. Publication = immutable buffer + reference swap; the
   texture conversion/upload stays on the main thread and its tail must be measured
   (RGBA float at 2112×829 is 26.7 MiB, `flat.tolist()` is not sub-ms).
4. Shutdown = acknowledged worker exit before renderer/context release, with an explicit
   main-thread lifecycle owner (engine disposal, file load, addon unregister, F12
   transition) — `unregister()` today only unregisters classes.
5. Widen the GIL release to the GPU copy-back / `applyPasses` tail; make viewport
   denoise a settled-generation pass (or include it in the cancel/latency gate).
6. Pre-implementation experiment (the first task of the implementation package): a
   minimal real-Blender A2 spike — main thread prepares generation N; worker calls only
   the native GPU render with explicit `cudaSetDevice`; main requests cancel and prepares
   N+1 only after worker-idle; both pinned scenes; measure tick-gap, cancel p99, output
   correctness, CUDA errors. Go/no-go on that spike decides A2 vs a native session (A1).

Owner input wanted before the spike: whether viewport denoise may move to
settled-only (already the §7 decision "denoise out of the interactive loop") and
whether F12-while-viewport-refines must keep working during Phase 2 (the arbiter
serialises it; the alternative is pausing the viewport session on F12, as Cycles does).

## 8. Owner decisions (2026-09-08 morning)

- Viewport denoise is **settled-only** — drop the "denoise as cancellation/latency concern"
  branch from Terra item 7; the interactive loop presents raw progressive chunks.
- **F12 pauses the viewport session** (Cycles behaviour): the revision replaces the process-wide
  GPU arbiter between F12 and the viewport with a pause/resume handshake (the arbiter is still
  needed between multiple 3D viewports of one session).

## 9. A2 spike protocol — the go/no-go experiment (minimal, real Blender)

The first implementation task. It proves the load-bearing assumptions of §3
(cross-thread serialised primary-context sharing, a non-blocking generation
handoff, and the tick-gap budget) on real hardware before any production worker
is built. It is flag-gated and touches the minimum.

**Code touched (all behind `ASTRORAY_VIEWPORT_WORKER=1`; default off = today's
synchronous path, byte-identical):**

- `module/blender_module.cpp` — the GPU `py::gil_scoped_release` over
  `:2267-2305` (the render + copy-back + `applyPasses` tail, §3.7) and an explicit
  `cudaSetDevice(dev)` on entry so the primary context is current on whatever host
  thread calls `render()`.
- `blender_addon/exporter.py` — a minimal spike worker implementing §3.2–§3.4 for
  the **GPU path only**, camera + material generations: a main-thread snapshot that
  the **main thread commits into the persistent renderer** (`setupCamera` + the
  `set_*` mutators, §3.2) while holding a single spike-local token, a
  `threading.Thread` that then calls only `renderer.render(...)` against the
  now-committed renderer, publish-by-immutable-reference, a `queue.Queue` drained by
  a main-thread `bpy.app.timers` timer, and the cancel→await-idle→**submit the
  current `desired_generation`** handshake (§3.4 — the spike proves the commit
  ordering and the non-blocking handoff, not N+1 specifically). No multi-viewport
  arbiter, no F12 gate, no denoise, no full lifecycle owner yet — the spike is
  single-viewport and measures feasibility, not the full session. It **does** carry
  the minimal token so the "commit-under-token then render" ownership (§3.2/§3.5)
  is exercised end-to-end.
- `benchmarks/viewport_parity/blender_recorder.py` + `benchmarks/viewport_parity/blender_driver.py`
  — **the spike must extend these (Terra 3 item 7).** Today `--mode ui_latency`
  records only **untagged** ticks, whole `render_viewport_frame` spans, and POST_PIXEL
  present timestamps (`blender_recorder.py:391-417`, `:449-453`;
  `blender_driver.py:678-702`), which cannot produce most of the evidence below (a
  passing tick-gap while nothing reaches the screen looks identical to success). The
  spike adds the **generation-tagged event schema** (next block) to the recorder and
  the reduction of those events to the pinned statistics to the driver.

**Measurement:** `benchmarks/viewport_parity/blender_driver.py --mode ui_latency`
(`--port 9877`, `--ui-engines astroray`, `--scenes metal_sweep big`, `--ui-reps 3`,
`--duration-s 10`, `--tick-s 0.005`) on `metal_sweep` and `pkg241_grid_100k`
(the `big` scene), in an **isolated Blender 5.2 profile on port 9877** (never the
owner's live 9876), with an **OpenMP-OFF CUDA addon built from the spike branch**.
Per config, 3 reps × 10 s post-warmup. Record (Terra 2, item 7/8 add the last
four — the first three alone can pass while nothing reaches the screen):

- main-thread **tick-gap p50/p95/p99/max** and `blocked_frac` (the existing
  `--mode ui_latency` metrics — the same recorder that produced the §1 baseline);
- **cancel-ack** (request → worker "idle" report) **p50/p95/p99** across the run;
- **texture-upload tail** ms (`_update_viewport_texture` on the main thread — the
  `flat.tolist()` → `GPUTexture` cost, §3.3);
- **snapshot-commit / token-ownership proof**: assert that on **every** generation
  the main thread committed the snapshot (`setupCamera` + mutators) under the token
  **before** the worker's `render()` ran, and that exactly one holder owned the
  token at any instant (a per-generation ownership trace) — without this the spike
  cannot claim it safely configured the renderer before the worker-only `render()`;
- **same-device verification + per-generation CUDA error capture**: assert both the
  main thread and the worker resolved the **same CUDA device** (`cudaGetDevice`
  after each thread's first `cudaSetDevice`), and capture a CUDA error check
  **per generation** (not just a run total) over ≥ 100 generations (zero required);
- **end-to-end present chain**: for each generation, the
  request→idle→queue-drained→texture-uploaded→**actual blit** latency, the presented
  **frame age**, the `queue.Queue` **depth** at drain, and a **successful-present
  count** — proving refinement actually reaches the screen, not merely that the
  tick-gap budget held;
- **correctness (a defined comparator, not "within MC noise")**: the settled spike
  frame vs the synchronous-path frame on a **fixed seed** (both scenes), compared by
  the **pkg237 per-channel mean-ratio within ±5 %** *and* a **max-abs-diff** bound on
  the fixed-seed GPU render; plus **no stale present after an edit** (the recorder's
  `renders_before_present` / stale guard, Phase 1a).

> **Terra review 3 → Revision 4 (item 7) — generation-tagged event schema + pinned
> thresholds.**
>
> **Event schema (added to `blender_recorder.py`).** Every recorded event carries
> `(generation, t_perf_counter, session_epoch)` so the driver can reconstruct the
> per-generation lifeline. The events, in order per generation:
> `request` (edit bumps `desired_generation`) → `commit_start` / `token_acquire` →
> `commit_end` → `render_start` → `render_end` → (`cancel_request` / `idle_ack` when
> superseded) → `mailbox_enqueue(depth_after)` → `mailbox_dequeue(depth_before)` →
> `texture_upload_end` → `first_blit` (the first POST_PIXEL that presents *this*
> generation). `token_release` is recorded whenever the holder releases. This lets
> the driver compute, per generation: the request→first_blit end-to-end latency, the
> presented **frame age** (`first_blit.t − render_end.t`), the mailbox **depth**, and
> whether a completed generation ever reached a `first_blit` at all.
>
> **Pinned correctness comparator (fixed inputs, no free parameters):**
> - **seed:** a **nonzero fixed seed** on both arms — viewport GPU seed 0 draws a
>   fresh `std::random_device` seed per render (`blender_module.cpp:2098-2101`), so 0
>   is unusable for a byte/threshold comparison; pin e.g. seed = 12345.
> - **resolution + divisor:** the pinned viewport region 2112×829 at **`res_divisor`
>   = 1** (no budget downscaling) so both arms rasterise identical pixel grids.
> - **spp:** a fixed settled target (e.g. 64 spp) reached identically on both arms.
> - **output space:** **linear** (no gamma/tonemap) — a gamma arm would clamp [0,1]
>   and mask an energy divergence (memory `gamma-vs-linear-comparison-artifact`).
> - **metric:** **per-channel mean-ratio within ±5 %** (pkg237) **AND**
>   **max-abs-diff ≤ 2.0e-2** in linear output. *Derivation of 2.0e-2:* with the seed
>   pinned, both arms draw the identical sample sequence, so the only residual is
>   GPU **atomicAdd non-associativity** in the wavefront accumulation, empirically
>   < 1e-3 absolute in linear [0,1] at these spp; a localized colour-space / transform
>   / matrix bug (the failure this max-abs term exists to catch, which a per-channel
>   *mean* ratio averages away) shifts affected pixels by ≥ 1e-1. **2.0e-2 sits one
>   order of magnitude above the atomic-reorder noise floor and one below the bug
>   signal.** The spike **reports the measured max-abs-diff** so the bound is tightened
>   to the observed floor if it is lower; a measured value near 1e-1 is a NO-GO, not a
>   threshold relaxation.
> - **present-rate rule:** **successful presents ≥ 0.9 × completed generations** over
>   the run (a completed generation is one that reached `render_end` without being
>   superseded). This is the numerical form of "successful-present count tracks the
>   render rate": ≥ 90 % of finished frames must reach a `first_blit`; a lower ratio
>   means finished frames are being stranded unpresented despite a passing tick-gap.
> - **mailbox-depth bound:** the frame mailbox **depth never exceeds 1** at any
>   `mailbox_enqueue`/`mailbox_dequeue` (§3.3); a recorded depth > 1 fails the run.
> - **texture-tail exemption rule:** a tick-gap **p95 failure attributed to the
>   texture-upload tail** (`flat.tolist()` → `GPUTexture`, §3.3) is **not** a
>   speculative pass. It requires implementing the alternate `gpu.types.Buffer`-from-
>   numpy path (pass the contiguous float32 buffer directly, no `tolist()`) **and a
>   passing rerun** with that path before GO — no exemption is granted on the argument
>   alone.

**Go / no-go:**

- **GO → A2 proceeds (P2.1–P2.3):** tick-gap **p95 ≤ 33 ms on both scenes**,
  cancel **p99 ≤ 300 ms**, **zero per-generation CUDA errors**, both threads on the
  **same device**, **no stale frame**, **presents ≥ 0.9 × completed generations**
  (frames actually reach the screen), **mailbox depth ≤ 1** throughout, and settled
  correctness within the pinned comparator (**±5 % per-channel mean-ratio AND
  max-abs-diff ≤ 2.0e-2** linear).
- **NO-GO → native session (A1) design task:** any of — tick-gap p95 > 33 ms that
  is not attributable to the texture tail (and only after the alternate
  `gpu.types.Buffer`-from-numpy path has been implemented and rerun, §3.3 / the
  texture-tail exemption rule above), a nonzero per-generation CUDA error count, a
  device mismatch between threads, a stale present, a present rate below 0.9 ×
  completed generations (finished frames stranded despite a passing tick-gap), a
  recorded mailbox depth > 1, or a correctness divergence beyond the pinned
  comparator (mean-ratio outside ±5 % or max-abs-diff > 2.0e-2) — means the
  serialised cross-thread primary-context model is not viable as A2 and the fallback
  native session (a C++ thread owning the render, main thread still owning `bpy`
  export) is designed instead.

---

## 10. Codex Terra review 2 (2026-09-08 ~10:45, lead-run, call 1/4) — VERDICT: BLOCK

Verbatim, with mojibake dashes/quotes normalised to ASCII. This review was taken
against Revision 2; Revision 3 (§3/§5/§9 above) resolves items 1-7 per the
Revision 3 changelog table.

1. VERDICT CHANGE -- The `WfContext`/upload/`__constant__` diagnosis is now correct (`gpu_wavefront_snapshot.cu:988-1090`, `:1408-1463`, `:1832-1843`). But serialization is incomplete: it must cover every mutation of the persistent `PyRenderer`, not only `upload_geometry`. Current sync mutates backend, world, materials, lights, transforms, camera, passes, and integrator state (`exporter.py:500-535`, `:540-580`, `:634-668`; `blender_module.cpp:1543-1569`). A global, non-blocking admission scheduler must own all prepare/upload/configure/render work; "this worker is idle" is insufficient while another viewport owns the token.

2. VERDICT CHANGE -- A main-thread timer draining a plain-data queue is the right mechanism. The snapshot is not yet complete or operationally defined: it omits `skip_upload`, full camera inputs (aperture, focus distance, shifts), effective device/backend and all renderer-setting mutations. More importantly, the doc never says whether the main thread commits that snapshot to `PyRenderer` while holding the token, or the worker does so. The spike's "worker calls only `renderer.render`" cannot apply a new camera by itself. `render()` consumes the renderer's existing `Camera` (`blender_module.cpp:1366-1411`). Discard rules also need viewport/session identity or epoch, backend/device epoch, and disposed-engine handling--not only generation, resolution, scene replacement, and stopping.

3. VERDICT CHANGE -- Ordinary edit handoff is non-blocking and the backend latency analysis is accurate: GPU cancellation is between wavefront passes then synchronizes (`gpu_wavefront_snapshot.cu:1878-1996`); CPU observes cancellation at tile boundaries (`raytracer.h:4192-4195`, `:4421-4426`). Neither has a hard latency bound. However, "the main thread never blocks" is false for the specified F12 and teardown waits. Also, after N is cancelled, a later N+2 edit can arrive before `idle(N)`; the design says to submit N+1 (`pkg241...md:303-305`). It must submit the current `desired_generation`, with every frame/idle/error notification generation-tagged and validated.

4. VERDICT CHANGE -- The multi-viewport arbiter is directionally sound, but F12 is unsafe as written. F12 pauses "the viewport session" (`pkg241...md:352-370`), while the document otherwise permits multiple viewport sessions. F12 needs a process-wide pause gate: block all new viewport admissions, cancel/drain every active viewport render, verify the global token is unowned, then start F12. Release that gate on every F12 success/error path. Otherwise another viewport can enter `render()` between the local idle acknowledgement and F12.

5. VERDICT CHANGE -- The required paths are named, but not fully specified. `__del__` is explicitly best-effort; hard exit has no concrete owner/hook; and `unregister`/`load_pre` need one central `stop_all()` protocol before timers, classes, or engine references disappear. The "ack never arrives -> never destroy" rule is correct, but only if a process-global quarantine retains strong references to the renderer/session/thread so Python finalization cannot destroy the supposedly leaked renderer. Do not call `engine.report` through an engine already being disposed.

6. VERDICT CHANGE -- No additional Python object is touched inside the actual proposed GPU region beyond `progressCallback`, which is correctly reacquired under the GIL (`blender_module.cpp:2252-2265`). But the design calls this a "packaging tail" while its stated range ends at `:2305`; real NumPy packaging occurs later at `:2373-2394` and must remain after GIL reacquisition (`py::array_t`, `request()`, and the returned Python object). The null-callback byte-identity claim is not testable as written. Add a fixed-seed GPU test comparing omitted callback versus explicit `None`, over representative pass/AOV configurations, plus the existing worker-disabled regression.

7. VERDICT WRONG -- Settled-only denoise is not implementable by "one additional generation" as specified. Viewport accumulation is a Python-side running mean (`exporter.py:709-721`), while `applyPasses()` denoises the native `Camera` produced by that individual render (`blender_module.cpp:2295-2305`). A new denoise render would denoise a fresh chunk, not the settled accumulated image. Define either a native pass over the immutable accumulated buffer or an explicit full-target re-render, including its latency/quality contract. Add tests for rapid N->N+2 supersession, token ownership across every uploader, F12 versus two viewports, timer deregistration/idempotence, and request-to-present latency/queue depth.

8. VERDICT CHANGE -- §9 is appropriately small, real-Blender, and uses the right primary UI metric. It is missing:

- Snapshot-commit/token-ownership proof; otherwise the spike cannot safely configure the existing renderer before its worker-only `render()` call.
- Verification that both threads selected the same CUDA device, plus per-generation CUDA error capture.
- Request->idle->queue-drained->texture-uploaded->actual-blit latency, frame age, queue depth, and successful-present count. Tick-gap can pass while refinement never reaches the screen.
- A defined correctness comparator: fixed seed where possible, scene/metric/threshold, rather than "within MC noise."

9. VERDICT BLOCK -- Do not dispatch the spike until the document makes these ordered corrections:

1. Define one global non-blocking admission token covering every renderer mutation, upload, camera/pass/integrator configuration, and render.
2. Define the snapshot commit point and complete its fields, including `skip_upload`, full camera parameters, and session/device epochs.
3. Correct the state machine to submit only the latest desired generation and validate every queued notification.
4. Make F12 a process-wide pause gate covering all viewport sessions.
5. Specify quarantined ownership for unacknowledged workers and concrete lifecycle entry points.
6. Replace the invalid settled-denoise mechanism with one that operates on the actual accumulated image.
7. Bound the GIL-release region before NumPy packaging, add the null-callback identity test, and expand §9 with end-to-end presentation/device measurements.

---

## 11. Codex Terra review 3 (2026-09-08 ~11:00, lead-run, call 2/4) — VERDICT: BLOCK

Verbatim, with mojibake dashes/quotes normalised to ASCII. This review was taken
against Revision 3; Revision 4 (§3.1/§3.2/§3.3/§3.4/§3.5/§3.6/§3.8, §5, §9 above)
resolves items 1-7 per the Revision 4 changelog table. Items 1-8 below are the
per-section verdicts; item 9 is the BLOCK summary with the seven ordered
pre-dispatch corrections.

1. **VERDICT CHANGE** -- The singleton/write diagnosis is correct, but not complete. `render()` also rewrites caustic, sampler, hair, guide, miss-coverage, light-pass, and spectral-table state -- not just the bindings enumerated in §3.1. See `gpu_wavefront_snapshot.cu:1482-1502`, `:1669-1750`, `:1843-2050`. It also mutates per-type bounce state on the host renderer before dispatch (`blender_module.cpp:2102-2107`).

   The token protocol is sufficient only if it encloses every such renderer operation, including F12 preparation and any post-render pass extraction. "Worker idle" alone is not the safety mechanism; retaining the global token from main-thread commit through completed `render()` is.

2. **VERDICT CHANGE** -- A main-thread timer pump is right. The snapshot still lacks operational accumulation state: `reset_accumulation`, current/target spp, and transfer/reset semantics for the private accumulator. These affect chunk sizing and the running mean today (`exporter.py:624-632`, `:670-723`).

   It also does not specify how non-combined viewport passes are returned: current code calls `renderer.get_render_pass_buffer()` after `render()` (`exporter.py:701-707`). The worker cannot truthfully "only call render" while preserving that behavior. Specify worker-side pass extraction under the token, or a native result API.

   Add a bounded latest-frame mailbox. An unbounded `queue.Queue` can retain many 20-27 MiB immutable frames when texture upload lags.

3. **VERDICT CHANGE** -- The backend latency description is accurate: GPU checks cancellation between passes then synchronizes (`gpu_wavefront_snapshot.cu:1878-1883`, `:1992-1996`); CPU observes it at tile boundaries (`raytracer.h:4192-4195`, `:4421-4426`). Neither is a hard bound.

   But §3.4 contradicts itself: it says every superseded notification is discarded, then says late `idle(N)` after desired `N+2` advances to IDLE. Split notifications into:

   - data-plane frames: require current desired generation;
   - control-plane idle/exited: require current in-flight generation and epochs;
   - errors: process for the current session/epoch even if their generation is superseded, since a CUDA fault must not be discarded.

   F12 and teardown deliberately wait, so "main thread never blocks" must remain limited to ordinary edits. Define their timeout and ensure the wait yields the GIL sufficiently for the worker's cancel callback, which reacquires it (`blender_module.cpp:2252-2264`).

4. **VERDICT CHANGE** -- The process-wide pause gate closes the multi-viewport admission race in principle. However, F12 must acquire the token before all F12-side renderer preparation, not merely before its final `render()`: F12 constructs and configures a new renderer and converts the scene (`__init__.py:1193-1199`).

   Also define the no-ack path: F12 must not start if any viewport fails to drain, and the failed session must be quarantined/terminal. Otherwise "verify token unowned" has no enforceable failure behavior.

5. **VERDICT CHANGE** -- Strong-reference quarantine is the right response to an unacknowledged worker. The lifecycle coverage is close, but needs a precise, idempotent split between `stop_session(session)` and global `stop_all()`; §3.6 currently says both "stop every live session" and "stop_all for this session." One viewport engine's `__del__` should not accidentally terminate unrelated viewports.

   Also specify the timeout/failure behavior for F12, `load_pre`, and `atexit`, and prohibit `engine.report` once disposal begins. This matters because current `unregister()` only removes properties/classes (`__init__.py:6674-6694`).

6. **VERDICT OK** -- For the exact proposed released range, the document identifies the relevant Python object. `progressCallback` is reacquired before invocation; the render/copy/pass tail otherwise touches C++ objects only (`blender_module.cpp:2244-2305`). NumPy packaging remains correctly outside that range (`:2373-2394`).

   The omitted-vs-`None` fixed-seed test is testable. It should compare the returned beauty and any requested pass buffers, with fresh equivalent renderer setup per arm.

7. **VERDICT CHANGE** -- The correction that a fresh denoise chunk is wrong is valid. But option (a) must also define accumulation of denoise guide AOVs, not only beauty: current viewport accumulation stores only display pixels (`exporter.py:709-723`), while GPU guides originate in Camera buffers (`blender_module.cpp:2214-2221`). Define their weighting, reset behavior, and immutable publication.

   Add tests for bounded queue/backpressure, backend/device switch mid-render, superseded terminal errors, AOV presentation, F12 drain timeout, and denoise interrupted while running. Specify whether settled denoise runs on the worker and how it yields/discards on a new edit.

8. **VERDICT CHANGE** -- The spike is appropriately real-Blender and narrowly scoped, but the existing measurement path cannot yet produce most claimed evidence. `ui_latency` currently records only untagged ticks, whole `render_viewport_frame` spans, and POST_PIXEL timestamps (`blender_recorder.py:391-417`, `:449-453`; `blender_driver.py:678-702`).

   Add a generation-tagged event schema covering request, commit/token ownership, render start/end, cancel request/idle acknowledgement, enqueue/dequeue depth, texture-upload end, and first actual blit of that generation. Include the recorder/driver in the spike's touched files.

   The correctness gate remains underspecified: the max-absolute-difference limit is absent, and viewport GPU seed zero intentionally produces a fresh random seed per render (`blender_module.cpp:2098-2101`). Pin a nonzero seed, resolution/divisor, spp, output space, and exact max-abs threshold. "Successful-present count tracks render rate" also needs a numerical rule. A texture-tail-attributed p95 failure should require the alternate buffer path plus a passing rerun before GO -- not a speculative exemption.

9. **VERDICT BLOCK** -- Revision 3 resolves the GIL/null-callback correction and materially improves the other six, but the following must land in the design before dispatching the spike:

   1. Complete the device-state inventory and state that the token covers F12 conversion/configuration, worker pass extraction, and all renderer mutations.
   2. Define snapshot accumulation/reset/pass-result ownership and a bounded latest-result mailbox.
   3. Correct notification validation into frame versus idle/exited/error rules, including the late-`idle(N)` case.
   4. Define F12/teardown timeout, GIL-yield, and no-ack behavior; do not start F12 after an undrained viewport.
   5. Make lifecycle shutdown session-scoped, idempotent, and safe during disposal/finalization.
   6. Specify accumulated denoise guide AOVs, scheduling, and cancellation/discard behavior.
   7. Make the spike instrumentable with generation-tagged events and pin all comparator, presentation, and queue-depth acceptance thresholds.

## 12. A2 spike result and lead decision (2026-09-08 ~16:00)

Spike PR #768 (`feat/pkg241-phase2-a2-spike`, flag `ASTRORAY_VIEWPORT_WORKER=1`, default off =
synchronous path unchanged). Full tables:
`benchmarks/viewport_parity/results/2026-09-08-phase2-spike/SPIKE-SUMMARY.md`.

**The load-bearing assumption holds.** Worker-thread GPU render with the GIL released over the
render + copy-back + `applyPasses` tail, `cudaSetDevice` on the worker: correctness comparator
(seed 12345, 2112x829, 64 spp, linear) per-channel mean-ratio 1.000 / 1.000 / 1.000 and
**max-abs-diff 9.5e-7** (bound 2e-2); both threads on device 0; **zero CUDA errors over 400+
generations**; mailbox depth never > 1; headless decoupling proxy: synchronous arm tick-gap 4435 ms
vs worker arm **p95 5.94 ms**. The cancellation suite 9/9.

**GUI `--mode ui_latency` (port 9877, both scenes, worker on):** run A (as committed) tick-gap p95
662 / 324 ms with a texture tail of 222 / 317 ms -> the S9 texture-tail rule applied: the
`flat.tolist()` upload was replaced by `gpu.types.Buffer` from the contiguous float32 array
(**194.8 ms -> 0.0 ms, byte-identical texture**). Run B: tick-gap **p50 7.1 ms** on both scenes
(was 158 / 233 ms in S1), p95 **94 / 75 ms** (budget 33), cancel p99 **341 / 583 ms** (budget 300),
texture tail 13 / 17 ms. `completed = 0` on both runs: the 5 ms ticker never lets a generation be
the latest desired one at its own `render_end`, so the present-rate gate is undefined under this
instrument; separately, worker frames did not visibly reach the GUI (screenshots show Blender's
grid) - a present-wiring defect in the spike, not root-caused.

**Lead decision.** By the letter of S9 two GUI gates fail, but S9's NO-GO clause is "the
serialised cross-thread primary-context model is not viable as A2" - and that clause is falsified by
the proxy, the comparator and the CUDA/device evidence. **A2 stands; A1 is not designed.** The
residual failures are owned by P2.2, whose scope is now concrete:

1. **Present wiring:** the worker's published frame must reach `_update_viewport_texture` and the
   blit (the spike's `presented = 0`); root-cause first (likely an engine-vs-exporter texture
   attribute mismatch), with a bridge test that a settled worker frame appears on screen.
2. **Bound the main-thread commit:** the residual p95 is `sync_viewport_scene` running a full
   upload for every material-edit generation on the main thread. P2.2 must (a) collapse pending
   edits to the newest generation per tick, (b) commit only what changed (materials-only / camera-only
   commits; `skip_upload` for camera; incremental sync per pkg56), and (c) measure the commit cost per
   generation as its own event so the gate can attribute it.
3. **Cancel-ack through the pump:** the worker's idle notification is consumed by the ~16 ms timer;
   with the main thread busy in a commit the ack waits behind it. Record `idle_ack` at enqueue
   time as well as at drain, and bound the commit (item 2) so p99 <= 300 ms is meetable.
4. **Gate instrument:** add a settle window to `--mode ui_latency` (edit bursts followed by idle
   spans) so `completed`, present-rate and frame age are defined; keep the continuous ticker as
   the stress variant.
5. **`gpu.types.Buffer` upload for the synchronous path too** - the 195 ms per present is paid by
   every viewport frame today; a byte-identity test then flip it on unconditionally.

Owner input not required for this decision (A2 vs A1 was delegated to the spike's evidence); the
owner's S8 decisions (denoise settled-only, F12 pauses) are unchanged. Codex Terra was not spent on
the spike result (calls remaining: 2 of 4).

## 13. Codex Terra review 4 (2026-09-09, PR #777) — VERDICT: BLOCK

Terra reviewed the P2.2 code + first GUI measurement on PR #777 (call 3/4) and
returned **BLOCK** with four ordered items plus answers (b)/(c). The verbatim
review is `test_results/2026-09-09-terra/terra_777_verdict.md`; the load-bearing
lines and their resolutions follow.

**Verbatim verdict:**

> VERDICT: BLOCK
>
> 1. `blender_addon/__init__.py:132`, `:5457`; `module/blender_module.cpp:4407`;
> deleted `tests/test_issue769_energy_compensation_bundling.py` and
> `tests/test_issue772_shaderless_world_black.py` — this PR unintentionally
> removes two unrelated, worker-OFF behaviors: staged Disney compensation-table
> discovery/status and explicit black for shaderless worlds. That violates the
> required origin/main-equivalent synchronous path, beyond the intended Buffer
> upload. Minimal fix: restore those hunks, their binding, and both tests (or
> rebase/cherry-pick P2.2 without the reversions).
>
> 2. `blender_addon/exporter.py:1629` — `_worker_view_update()` calls
> `worker.pump()` with its default `present=True`. `view_update` is not a GPU
> draw context, so this repeats the exact failure fixed for the timer:
> `_drain_mailbox()` clears the one-slot mailbox before `_worker_present()` can
> fail, losing the frame before `view_draw`. The timer fix at `:1496` is correct,
> but incomplete. Minimal fix: `worker.pump(present=False)` here, plus a test that
> an update-context pump preserves a queued frame for `view_draw`.
>
> 3. `benchmarks/viewport_parity/blender_driver.py:711-728` — the settle
> instrument still defines a "completed generation" at terminal `render_end`,
> while the worker deliberately publishes progressive chunks before that terminal
> event. Thus `first_blit - render_end` is necessarily negative for valid
> progressive presents, and `completed=0` does not establish a rendering failure.
> Minimal fix: emit a publication/chunk sequence ID and terminal-publication
> marker; compute progressive frame age from `mailbox_enqueue` to that
> publication's `first_blit`, and separately score terminal completion/final
> presentation.
>
> 4. `blender_addon/exporter.py:392-400`, `:591-597`;
> `benchmarks/viewport_parity/blender_driver.py:736-746` — every request is
> recorded as a cancel, including requests while IDLE and repeated requests for an
> already-cancelling render; the reducer then pairs each with any next idle event,
> regardless of generation. This makes the settle cancel p99 invalid and can make
> pump p99 appear lower than worker p99. Minimal fix: emit one `cancel_request`
> only for the actual in-flight generation when cancellation transitions
> false->true; release the token before enqueueing its idle notification; pair
> `cancel_request(g)` only with `idle_ack(g)` / `idle_drain(g)`.
>
> For (b): metric-definition bug, not broken progressive presentation. Progressive
> frame age = `first_blit(publication_id) - mailbox_enqueue(publication_id)` (>= 0).
> A terminal completed generation reaches its marked final publication without
> cancellation while still desired; present-rate denominator = terminal
> generations still current until final blit or run end; require >= 1 eligible
> terminal generation, else UNGRADEABLE. Usable cancel gate =
> `cancel_request(in_flight g) -> idle_drain(g)`; `idle_ack(g)` stays the
> worker-only diagnostic.
>
> For (c): latency thresholds untrustworthy while the CUDA build contended for
> CPU; structural evidence (mailbox depth <= 1, same device, zero CUDA errors,
> present-check content, fixed-seed correctness) trustworthy regardless. Bounded
> continuous-commit fix: replace the deferred `scene_full` path at
> `exporter.py:1679` with a coalesced main-thread-recorded dirty-domain mask,
> replayed as safe material/light/transform upload operations under the token
> after idle; retain full sync only for unknown/geometry changes. The cancel p99
> is architectural: a smaller Python `chunk` does not bound a long wavefront pass.
> P2.3 needs a cancellation-bounded wavefront dispatch at
> `gpu_wavefront_snapshot.cu`'s between-pass poll — interactive-resolution or
> tiled/sub-pass launches with a cancel poll between bounded GPU work units.

**Resolutions (PR #777, terra4 fix lane):**

- **Item 1 — resolved by rebase.** The branch predated PR #774 (#769/#772);
  the deleted tests + `__init__.py`/`blender_module.cpp` hunks were a
  rebase-artifact reversion, not intended P2.2 scope. Rebased onto origin/main
  (896d7f7c): `git diff origin/main --stat` shows no `test_issue769_*`/
  `test_issue772_*` deletions and no `blender_module.cpp` change; `__init__.py`
  is down to the 15 genuine P2.2 Buffer lines with plain `--stat` ==
  `--ignore-space-at-eol --stat` (no line-ending damage). The only remaining
  worker-OFF change is item 5 (unconditional `gpu.types.Buffer` upload), which is
  byte-identity-guarded.
- **Item 2 — fixed.** `exporter.py::_worker_view_update` now pumps
  `present=False` (control-plane only, off the draw context). Guarded by a
  call-site test that spies the pump `present` kwarg
  (`test_worker_view_update_pumps_control_only_preserving_the_frame`) plus the
  existing worker-level frame-preservation test.
- **Item 3 — fixed (Terra (b) implemented exactly).** The worker emits a
  monotonic publication id per chunk and a `terminal_publication(gen, pub_id)`
  marker only when a render reaches target spp without cancellation; the recorder
  derives `first_blit` per publication; the reducer computes progressive frame
  age = `first_blit(pub) - mailbox_enqueue(pub)` (>= 0), scores terminal completed
  generations (reached marked final publication, uncancelled, still current),
  bounds the present-rate denominator to eligible terminal generations
  (superseded-before-blit excluded), and reports **UNGRADEABLE** when none exist.
  New reducer tests: frame-age non-negativity, UNGRADEABLE, superseded-terminal
  exclusion.
- **Item 4 — fixed.** `request()` emits `cancel_request` only for the actual
  in-flight generation on the false->true cancel transition (never while IDLE,
  never repeated); the worker releases the token before enqueueing idle; the
  reducer pairs `cancel_request(g)` only with `idle_ack(g)`/`idle_drain(g)` of
  the same generation, and the usable gate is
  `cancel_request(in-flight g) -> idle_drain(g)`. New tests: exporter emission
  guard + reducer generation-pairing.
- **Buffer byte-identity (Terra note) — added.** An automated in-Blender
  regression: `blender_driver.py --mode buffer_identity` compares
  `bytes(Buffer(np))` vs `bytes(Buffer(flat.tolist()))` over the addon's exact
  array pipeline inside the isolated GUI Blender (a live GPU context;
  `gpu.types.Buffer` cannot be constructed under `blender -b` on Windows). A
  companion pytest attempts the headless path and skips cleanly when no GPU
  context exists.
- **Terra (c) — DEFERRED to P2.3 (bounded-budget escape).** The coalesced
  dirty-domain replay requires computing the domain change-set at `view_update`
  (the only time `depsgraph.updates` is live) and threading that recorded mask +
  its transform matrices into the idle-time commit, replacing the `scene_full`
  full sync. That restructures the correctness-sensitive incremental-sync path
  (`apply_depsgraph_updates` / `sync_viewport_scene`), and its interactive
  material/transform correctness cannot be verified in this lane (no headless way
  to drive live-viewport edits and read back device state). The current behavior
  is already correct — N scene edits deferred while the worker is busy coalesce to
  a **single** full sync at the next idle (`_worker_deferred_scene` is one bool),
  so nothing is hidden behind the settle metric; it is a commit-cost optimization,
  not a correctness gap. Per the lead's explicit <= 2 h budget clause, the
  deferred-replay-under-token (materials/lights/environment first, then the
  transform-recording + instancing-refit subtlety) moves to P2.3, where it can be
  HW-verified alongside the GPU work below.

**P2.3 must contain:**

1. **Cancellation-bounded wavefront dispatch (architectural — Terra (c)).** The
   cancel p99 over budget under the continuous storm is not fixable by a smaller
   Python `chunk`: a single long wavefront pass is unbounded. P2.3 adds a cancel
   poll between **bounded GPU work units** at `gpu_wavefront_snapshot.cu`'s
   between-pass poll — interactive-resolution and/or tiled/sub-pass launches — so
   the worker reaches idle within a bounded GPU interval regardless of the full
   pass length.
2. **Coalesced dirty-domain commit (Terra (c), deferred here).** Replace the
   `scene_full` deferred path with a main-thread-recorded, coalesced dirty-domain
   mask (recorded at `view_update` from the live `depsgraph.updates`) replayed as
   safe material/light/transform upload operations under the token after idle;
   retain full sync only for unknown/geometry changes. Measure per-generation
   commit cost as its own event and re-confirm the tick-gap p95 under the
   continuous storm on an uncontended GPU.
3. **Clean re-measure on an uncontended GPU.** Repair-then-remeasure: the
   generation/publication and cancel-correlation instrumentation is now correct
   (this PR); P2.3 re-measures latency thresholds with no concurrent CUDA build
   contending for CPU (the confound Terra flagged for (c)).

## 13a. Post-review fix — scene-switch CUDA corruption (PR #777, 2026-09-09)

The Terra-4 post-fix graded re-measure surfaced a NEW blocking finding: with
`ASTRORAY_VIEWPORT_WORKER=1`, switching the open `.blend` from `metal_sweep` to
`big` (or back) mid-session poisoned the CUDA context — `stage_env_shadow` /
`stage_shade_bucketed` "illegal memory access", `allocateGPUWavefrontState:
cudaMalloc failed for s.pixel_index` — after which every render in the process
returned 0 presents. Reproduced 3/3; worker OFF handled the identical switch
cleanly.

**Root cause (a partial implementation of §3.5/§3.6, not a native bug).** The
spike's admission token is a *per-worker* `threading.Lock` (`exporter.py`
`_ViewportSpikeWorker._token`), so it serialises `render()` only WITHIN a
session. It is NOT the process-global admission token §3.5 mandates, and §3.6's
acknowledged-exit lifecycle owner (`stop_session`/`stop_all`, the `load_pre` /
`atexit` triggers) was never implemented — the spike had only a best-effort
`Exporter.__del__`. Blender does not guarantee `__del__` runs before the new
file's `RenderEngine` constructs a fresh worker, so on a scene switch the old
worker daemon survives the load and its `render()` races the new worker's
`render()` into the single process-global `WfContext` ("Single render thread
assumed", `gpu_wavefront_snapshot.cu:988`) — two writers of the same grow-only
device allocations and `__constant__` bindings. That is the illegal access +
`cudaMalloc` failure. The pre-Terra-4 `max_present_std=inf` outlier on `big` was
the milder, stale-buffer-read severity of the same latent hazard (§13, third
pass).

**Fix (design §3.6 acknowledged exit, minimal slice — no native change).** A
process-global live-session registry (`_LIVE_VIEWPORT_SESSIONS`) plus
`stop_all_viewport_sessions()`, installed lazily from the first worker start as
(a) a persistent bpy `load_pre` handler and (b) an `atexit` hook. `load_pre`
fires BEFORE the incoming file replaces the scene, so every prior session's
worker is drained to acknowledged idle (or quarantined, §3.6) on the main thread
before any new worker can touch the `WfContext`. The main thread is the
serialisation point (drain in `load_pre`, new worker created later in
`view_update`/`view_draw`), so no two workers ever render concurrently across a
switch. The hooks live in the bpy-free `exporter` module (guarded) so
`__init__.py` stays at the Buffer-only lines. Regression:
`tests/test_pkg241_scene_switch.py` (5 tests) models old-worker-mid-render →
scene switch (`stop_all`) → new session against a shared single-render-thread
device guard: undrained peak concurrency is 2 (the crash), drained is 1.

**What this does NOT do (stays P2.3).** This is the single-viewport / file-switch
slice of §3.5/§3.6. The full process-global admission token that makes *two live
3D viewports of one session* safe (each with its own worker), the F12 process-
wide pause gate, `stop_session` vs `stop_all` split, and the strong-ref
quarantine registry beyond the current `_WORKER_QUARANTINE` list are still P2.3.
Multi-viewport concurrent render() remains unserialised until that token lands.
