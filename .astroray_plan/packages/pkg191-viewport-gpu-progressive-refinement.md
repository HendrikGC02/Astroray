# pkg191 — Viewport progressive refinement broken on GPU

**Pillar:** 5 / integration-first
**Track:** A
**Status:** done (PR #TBD, 2026-08-12 — root cause: GPU dispatch ignored the
renderSeed==0 "non-deterministic" contract, so every viewport chunk rendered
identical noise; fix mirrors the CPU per-call reseed. Baseline repro on a
freshly-built current-`main` .pyd: GPU seed-0 chunks byte-identical
(max_abs_diff=0, accum variance frozen at 0.001055 across iters 1/8/64); CPU
refined. Post-fix: GPU chunks distinct (0.153), accum variance drops
0.00105→0.00043→0.00036, MSE-to-256spp 7.0e-4→4.7e-5→1.3e-5, iter-1/64 PNGs
visibly denoise. filed 2026-08-12 from owner hands-on addon feedback —
memory [[owner-addon-feedback-2026-08-12]], finding #1)

**Lessons / ruled-out hypotheses:**
- **Convicted: H4** (GPU chunk render did not advance the sample stream). The
  viewport renderer runs at the default `renderSeed==0`. The CPU render loop
  special-cases 0 → fresh `std::random_device` seed per call
  (`include/raytracer.h:3028-3030`), so chunks are independent and the Python
  running-mean (`exporter.py:585-597`) converges. The GPU dispatch
  (`module/blender_module.cpp`) passed `renderer.getSeed()` (==0) verbatim to
  `cuda_wavefront_render`; the wavefront RNG is `WavefrontRNG(pixel, sample_idx,
  seed)` (`src/gpu/wavefront/stage_init.cu:189`), so every chunk reproduced
  identical noise and the mean averaged duplicates.
- **Ruled out H1** (tag_redraw pump) **and H3** (camera-hash false reset): both
  are backend-agnostic Python; the existing
  `test_view_draw_progresses_until_preview_sample_target` already gates
  monotonic spp-climbing (its mock renderer returns *distinct* values per call —
  exactly the property GPU violated). If the pump were broken the CPU viewport
  would stall too, but CPU refines.
- **Ruled out H2** (render returns None / fresh 1-spp buffer on chunk ≥2):
  the GPU `render()` returns a valid distinct buffer on every call; the stall
  was identical *content*, not a None early-return.
- Fix is one spot in the GPU dispatch (mirror the documented seed contract); the
  engine RNG and the Python pump are untouched (per the H1 non-goal).
**Estimated effort:** M
**Depends on:** none hard; touches the pkg56/pkg83/pkg84/pkg114 viewport
session machinery (`view_update` / `view_draw` / `render_viewport_frame`).

---

## Symptom (owner, first-hand)

Rendering the viewport with the **GPU backend**, the image "stays static at the
noisy 1-sample state" — it does not visibly refine as samples accumulate. The
**CPU viewport progressively refines** and is the comparison control. So this is
a GPU-path-specific regression in the progressive loop, not a global sampler bug.

---

## MANDATORY FIRST STEP — reproduce on a freshly built CURRENT addon

The owner's installed addon "might have been sliiiightly dated." **Do not debug
the reported symptom until you have reproduced it on a from-current-`main` build.**
Concretely, before any code change:

1. Build the addon `.pyd` OpenMP-OFF against current `main`
   (`build_blender_addon_cuda`; see [[pkg119b-harness-runbook]] and
   [[mingw_openmp_blender_deadlock]]), verify `.pyd` mtime ≥ `git log -1 HEAD`,
   and confirm `astroray.__file__` loads the canonical build output
   (not a shadow `.pyd`; [[stale_pyd_locations]]).
2. Stage the addon from that build (`build_blender_addon.py`; the ADDON_FILES
   allow-list, [[addon-packaging-file-list]]) into Blender 5.1
   ([[blender-5-1-installed-locally]]).
3. Reproduce headlessly if at all possible (see "Headless repro" below) and,
   if not, in the real viewport. **Record whether the current build still
   exhibits the bug.** If it is already fixed on `main`, the deliverable becomes
   a regression test that pins the fix + an owner-visual note; STOP and report
   that, do not manufacture a fix.

---

## Where the loop lives (verified line refs, current `main` fb9538d)

The viewport progressive accumulator is Python-side, in
`blender_addon/exporter.py`:

- `Exporter.render_viewport_frame` (`exporter.py:504-603`) is the per-frame
  worker. It:
  - short-circuits when `self._viewport_current_spp >= self._viewport_target_spp`
    (`exporter.py:521-522`);
  - renders **one chunk** of `viewport_chunk_samples(settings, current_spp)`
    samples (`exporter.py:560`) via `renderer.render(samples, depth, None,
    False, …, skip_upload)` (`exporter.py:565-573`);
  - **accumulates in Python** as a running mean of chunks
    (`exporter.py:585-597`): `accum = (accum*old_spp + chunk*samples)/new_spp`,
    then `_viewport_current_spp = new_spp`;
  - pushes the texture + status (`exporter.py:599-602`) and returns `True`.
- The **redraw pump** is the only thing that turns one chunk into progressive
  refinement: both `view_update` (`exporter.py:671-672`) and `view_draw`
  (`exporter.py:733-734`) call `request_viewport_redraw_fn()` — i.e.
  `RenderEngine.tag_redraw()` (`__init__.py:1244-1248`) — **iff**
  `_viewport_current_spp < _viewport_target_spp`. Each `tag_redraw` should
  schedule another `view_draw`, which renders the next chunk (with
  `needs_progress` true at `exporter.py:705`) and re-accumulates.
- Chunk/target sizing: `_viewport_target_samples` = `preview_samples`
  (`__init__.py:1214-1216`); `_viewport_chunk_samples` = `min(viewport_chunk_spp,
  remaining)`, default chunk 1 (`__init__.py:1218-1223`).

So on paper the design already refines chunk-by-chunk driven by `tag_redraw`.
The bug is that on GPU the pump stalls at the first chunk.

---

## Diagnosis-first — reproduce → localize → fix

### Reproduce
- Headless repro (preferred, scriptable): drive `Exporter.view_draw` in a loop
  with a stub/real `context` whose camera hash is held **constant** (no camera
  motion), GPU backend forced, and assert `_viewport_current_spp` climbs
  `1 → chunk → 2·chunk → … → preview_samples` across successive calls. Do the
  same with the CPU backend as the control. The failing GPU case should plateau
  at the first chunk. Reuse the pkg119-B harness plumbing for a real-Blender
  headless driver if the stub can't exercise the GPU `render()`.
- If it only reproduces in the live viewport, capture the `update_stats`
  "Viewport N/M spp" string (`__init__.py:1250-1257`) over ~2 s of no input on
  GPU vs CPU.

### Localize — the ranked hypotheses (instrument, do not guess)
Add temporary per-call logging of `(_viewport_current_spp, target,
camera_changed, needs_progress, settings_changed, samples, pixels is None,
return value)` in `view_draw` / `render_viewport_frame`, GPU vs CPU:

1. **`tag_redraw` doesn't re-arm `view_draw` on GPU.** If a long GPU
   `render()` holds the draw and the redraw request posted during the draw is
   coalesced/dropped, the loop never re-fires. Compare how many `view_draw`
   calls arrive after input stops on GPU vs CPU. (This is the most likely
   cause given "stuck at frame 1".)
2. **GPU `render()` returns `None` or a fresh 1-sample buffer on chunk ≥ 2.**
   `render_viewport_frame` returns early on `pixels is None`
   (`exporter.py:574-575`) *without* advancing `_viewport_current_spp` — so the
   status would show "1/M" forever and every redraw re-renders chunk 1. Check
   the GPU return on the 2nd call specifically (a first-call prewarm/upload path
   differs, `exporter.py:492-499`).
3. **`camera_changed` / `settings_changed` false-positive on GPU** resets the
   accumulator every frame (`render_viewport_frame:516-518`,
   `_reset_viewport_accumulation`). If the camera hash is nondeterministic frame
   to frame (float jitter in `_camera_state_hash`, `__init__.py:1259-1293`),
   `render_key` flips, `_viewport_accum_key` mismatches, spp resets to the chunk
   size each frame → looks static at "noisy 1-sample". Verify the hash is
   byte-stable across identical-camera GPU frames.
4. **`skip_upload=False` on every GPU chunk re-clears device accumulation.**
   `view_draw` calls `render_viewport_frame` with the default `skip_upload=False`
   (`exporter.py:725-729`), so each GPU chunk re-uploads geometry. If the GPU
   `renderer.render(..., skip_upload=False)` path internally `clear()`s or
   re-seeds identically (same seed → identical noise, [[seed-zero-is-random-sentinel]]),
   the "accumulation" averages identical frames and never denoises. Verify the
   GPU render actually advances its RNG stream per chunk (distinct noise per
   call), else the Python running-mean is averaging duplicates.

Pin the ONE actual cause with evidence before touching code. Record the ruled-out
hypotheses in Lessons.

### Fix
Scope the fix to the localized cause. Likely shapes (do not implement
speculatively — implement the one the evidence selects):
- (H1) ensure a progress redraw is re-armed after the GPU draw completes (e.g.
  a timer-based `tag_redraw`, matching how Cycles pumps progressive viewport
  passes) so the chunk loop advances.
- (H2/H4) make the GPU chunk render advance the sample stream (distinct seed per
  chunk) and return a valid buffer on chunk ≥ 2; treat `pixels is None` as a
  logged error, not a silent stall.
- (H3) stabilise the camera/render-key hash so identical GPU frames don't reset
  the accumulator.

---

## Acceptance criteria

- [x] **Reproduced on a freshly built current-`main` .pyd** BEFORE any code
      change (GPU seed-0 chunks byte-identical; CPU refined). Dated-addon caveat
      discharged: the bug is present on `main`.
- [x] A **headless / scriptable** monotonic-spp assertion across successive
      `view_draw` calls with a fixed camera (backend-agnostic pump) — already
      gated by `test_view_draw_progresses_until_preview_sample_target` (21
      viewport-session tests pass). The GPU-specific chunk-independence + denoise
      is gated by `tests/test_pkg191_viewport_gpu_progressive.py` (GPU + CPU
      control).
- [x] Single root cause identified with instrumented evidence (H4); ruled-out
      hypotheses recorded in Lessons above.
- [x] GPU viewport **visibly refines** — iter-1 (heavy salt-and-pepper noise)
      vs iter-64 (clean smooth sphere) PNGs read by the implementer; accum
      variance and MSE-to-reference both drop monotonically. See owner-visual
      note in the PR.
- [x] No regression to the CPU viewport loop (`test_cpu_seed0_chunks_are_independent`
      + 21 viewport-session tests pass; pinned-seed GPU golden/parity tests stay
      deterministic).

## Hard non-goals

- **No interactivity / fps work** — that is pkg192. This package is purely
  "does the still viewport refine on GPU". Keep camera-motion perf out of scope.
- **No new denoiser wiring.** OIDN viewport toggle stays as-is
  (`exporter.py:547-552`); refinement here means MC noise dropping with spp.
- **No sampler/RNG rewrite** beyond what the localized cause requires; if the
  cause is the redraw pump (H1), do not touch the engine.
