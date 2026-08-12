# pkg191 — Viewport progressive refinement broken on GPU

**Pillar:** 5 / integration-first
**Track:** A
**Status:** open (filed 2026-08-12 from owner hands-on addon feedback —
memory [[owner-addon-feedback-2026-08-12]], finding #1)
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

- [ ] **Reproduced (or shown already-fixed) on a freshly built current-`main`
      addon `.pyd`** BEFORE any code change; the dated-addon caveat is
      discharged in writing.
- [ ] A **headless / scriptable** assertion that `_viewport_current_spp` climbs
      monotonically to `preview_samples` across successive `view_draw` calls
      with a fixed camera on the **GPU** backend (CPU as passing control),
      gated as a test.
- [ ] The single root cause is identified with instrumented evidence; ruled-out
      hypotheses recorded in Lessons.
- [ ] The GPU viewport **visibly refines** (noise drops as spp climbs) — an
      **owner-visual note** with a before/after capture (metrics can pass on
      garbage; [[general-photon-loop-needs-solid-glass]] — a human must confirm
      the noise actually decreases, not just that spp counts up).
- [ ] No regression to the CPU viewport progressive loop (same test passes CPU).

## Hard non-goals

- **No interactivity / fps work** — that is pkg192. This package is purely
  "does the still viewport refine on GPU". Keep camera-motion perf out of scope.
- **No new denoiser wiring.** OIDN viewport toggle stays as-is
  (`exporter.py:547-552`); refinement here means MC noise dropping with spp.
- **No sampler/RNG rewrite** beyond what the localized cause requires; if the
  cause is the redraw pump (H1), do not touch the engine.
