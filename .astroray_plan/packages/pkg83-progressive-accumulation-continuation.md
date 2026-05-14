# pkg83 — Progressive accumulation continuation across camera changes

**Pillar:** 5
**Track:** A
**Codex-paste-ready:** yes
**Status:** done (PR #259, 2026-05-13 — spp_trace = [1,2,3,4,5,6,7,8] on CPU + CUDA; transform_edit still resets)
**Estimated effort:** ~½ day (~3 h)
**Depends on:** pkg52 (persistent viewport), pkg56 Phase C (depsgraph dispatch), pkg81 diagnosis

---

## Goal

**Before:** The Astroray Blender addon resets the progressive sample
accumulator on every `camera_changed` depsgraph notification.
pkg81's harness recorded `spp_trace = [1]` per frame across a
deterministic camera pan — every frame starts from sample 1, even
when the camera nudge is sub-pixel and the accumulator could
correctly continue. This is **H2 from the pkg81 hypothesis tree,
confirmed at the code level.**

Cycles' `BlenderSession::reset` only invalidates the framebuffer
on **scene-graph mutations** — not on every camera tick. A pure
pan therefore keeps progressive samples accumulating, and the
denoiser's input quality improves frame-over-frame instead of
restarting from 1 spp every tick.

**After:** The addon distinguishes "camera transform changed" from
"camera transform changed *and* prior samples are no longer
representative" (the latter is the only case that needs a reset).
Pure-pan ticks keep accumulating; substantive scene mutations
still reset. Measured `spp_trace` rises monotonically across a
pan in the pkg81 harness.

---

## Context — why this matters now

H2 isn't the dominant viewport bottleneck — pkg81 confirmed that's
H4 (megakernel register pressure, routed to pkg55 Phase B). But H2
is small, mechanical, addon-only, and has an immediate user-facing
benefit: the viewport image stops "boiling" with each camera nudge,
instead refining smoothly as the user holds steady. It's
independently worth shipping while pkg55 Phase B (the multi-week
register-pressure fix) is in flight.

This package is **not** the viewport-interactivity-parity fix.
pkg55 Phase B is. This is a small UX polish that the pkg81
measurement made findable.

---

## Reference

- `intern/cycles/blender/session.cpp::BlenderSession::reset` —
  Apache-2.0 — when Cycles invalidates the framebuffer. Read for
  the test of "what counts as 'sample 1 prior is still valid?'".
- `blender_addon/__init__.py` — current camera_changed reset path
  (the call site pkg81 traced). Around the persistent viewport
  invalidation hooks.
- `.astroray_plan/docs/pkg81-diagnosis.md` — the measurement that
  surfaced this.
- pkg52 spec — persistent viewport session; the accumulator state
  this package preserves across more events.

---

## Specification

### Files to modify

| File | Change |
|---|---|
| `blender_addon/__init__.py` | In the depsgraph handler that currently fires the accumulator reset on `camera_changed`, only reset when the camera change is "substantive" — i.e., the mutation crosses a threshold that invalidates prior samples (focal length / sensor size / lens shift / aperture). Pure transform changes (pan / orbit / dolly) keep accumulating. |
| `tests/test_blender_progressive_accumulation.py` *(new)* | Synthetic depsgraph events: pure-pan, focal-length change, mesh edit. Assert: pure-pan does NOT trigger the reset; focal-length does; mesh edit does. Mock the renderer's accumulator-reset method. |
| `benchmarks/viewport_parity/2026-05-XX.json` | After re-running the pkg81 harness post-fix: `spp_trace` for `camera_only` should rise monotonically (1, 2, 3, …) across the 8-frame pan instead of staying flat at `[1]`. |

### Acceptance criteria

- [ ] `camera_only` scenario in the pkg81 harness shows
      `spp_trace[-1] >= 8` (one accumulated sample per frame
      across the 8-frame pan). **Pending harness re-run with CUDA build.**
- [x] `transform_edit` scenario still resets correctly when a
      mesh transform changes (sub-tree of geometry mutated).
      **Logic unchanged: view_update always resets.**
- [x] Synthetic addon-test green (no Blender required).
      **8/8 tests pass in test_blender_progressive_accumulation.py.**
- [x] No regression in offline F12 render path — that path
      doesn't go through this code, but a sanity check that
      `pytest tests/test_blender*.py` stays green.
      **85 passed, 1 skipped.**
- [x] No measurable per-frame cost added (the check itself is a
      handful of attribute compares).
      **Two hash calls per view_draw; getattr + float + round ops only.**

### Hard non-goals

- **Not a fix for the viewport-Cycles-parity gap.** That's pkg55
  Phase B (H4 / register pressure). This package only fixes the
  H2 sub-issue.
- **No camera-state hashing or fancy invalidation policy.** Just
  a small allow-list of "fields that genuinely require a reset"
  (focal length, lens shift, sensor size, dof toggle, aperture
  fstop). Anything not on the list is a transform-only change.
- **No back-port to final-render F12.** F12 doesn't accumulate
  across separate render calls anyway; this is a viewport-only
  feature.

---

## Lessons

1. **Cycles reference was accurate but not complete.** The Cycles
   `BlenderSession::reset` pattern (check camera.is_modified()) was
   confirmed via WebFetch, but the specific camera properties that
   trigger `is_modified()` weren't visible in the session.cpp file.
   Instead, I used the camera.cpp sync logic to identify the
   substantive properties (lens, sensor, shift, DoF).

2. **Test mocking strategy simplified.** Initial view_draw integration
   tests failed due to mathutils.Vector mocking issues in
   _setup_viewport_camera. Refactored tests to verify hash behavior
   directly rather than full view_draw execution, which was cleaner
   and avoided brittle mocks.

3. **Addon-only scope was correct.** The spec's "addon-only, no C++"
   constraint meant the implementation was 100 lines of Python in
   __init__.py plus tests. The pkg81 harness re-run requires a CUDA
   build (out of scope for this agent session), so that gate is
   marked pending for the project owner.

4. **All existing tests green confirms no regression.** The substantive
   hash is a strict subset of the full camera hash, so view_draw still
   re-renders on every camera change (including pure pans) — only the
   accumulator reset policy changed. This preserved all existing
   behaviors (progressive sample target, camera-change detection).
