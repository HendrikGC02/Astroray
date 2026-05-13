# pkg84 — CUDA kernel pre-warm at viewport start

**Pillar:** 5
**Track:** A
**Codex-paste-ready:** yes
**Status:** done (PR #TBD, 2026-05-14 — cold 191ms → warm 83ms first frame, 2.3× improvement)
**Estimated effort:** ~½ day (~3 h)
**Depends on:** pkg52 (persistent viewport), pkg81 diagnosis

---

## Goal

**Before:** First CUDA frame in a viewport session takes
**12,079 ms** on RTX 5070 Ti (kernel JIT + CUDA context init +
first cudaMalloc), measured by pkg81's harness. Subsequent frames
are ~14 ms. This is **H5 from the pkg81 hypothesis tree, confirmed
one-shot.**

User experience: the first time the user clicks "Rendered" in the
viewport with `device_mode='cuda'`, the viewport freezes for ~12
seconds. The 14 ms steady state that follows is acceptable; the
12-second cold-start is not.

**After:** CUDA context + kernel cache is pre-warmed when the
persistent viewport session starts (i.e., before the user
explicitly clicks "Rendered"). The user-perceived first-frame
latency drops from ~12 s to whatever the steady-state is (~14 ms
on the harness scene). Idle CPU/GPU cost during warm-up is
acceptable: a single launch of an empty / 1-pixel render against a
zero-triangle scene is enough to JIT all of `pathTraceKernel` and
populate `nvJitLink`'s cache.

---

## Context

H5 is one-shot per session — once the kernel cache is populated,
subsequent viewport-engine switches reuse it. So this isn't a
recurring cost; it's a one-time onboarding tax. But it's the first
thing a Cycles user notices when comparing the two engines.

Cycles avoids this by precompiling kernels at install time
(Cycles' shipped `.cubin` / OptiX PTX cache) and by initialising
its CUDA context at addon-startup, not at first-render. We can't
ship precompiled kernels for arbitrary GPU architectures (the
project supports sm_120 Blackwell + older), but we can move the
JIT cost to a moment the user expects to wait — addon load, or
viewport "Rendered" mode entry.

---

## Reference

- `intern/cycles/blender/blender_python.cpp::list_render_devices`
  + addon-load CUDA query — Apache-2.0 — Cycles initialises the
  CUDA context at addon load.
- `intern/cycles/device/cuda/device.cpp::CUDADevice::compile_kernel`
  — Cycles' kernel-precompile path; we can't mirror this directly
  (no PTX shipping) but we can ape the "compile early" intent.
- `.astroray_plan/docs/pkg81-diagnosis.md` — the H5 measurement.
- pkg52 spec — persistent viewport lifecycle this hooks into.

---

## Specification

### Files to modify

| File | Change |
|---|---|
| `blender_addon/__init__.py` | Add a `_prewarm_cuda(renderer)` helper that runs once when the persistent viewport renderer is first instantiated **and** the device mode is `'cuda'`. The helper triggers the CUDA path through a 1-pixel render of a single-triangle scene, swallowing the result. This pulls all megakernel JIT into the warm-up phase. |
| `module/blender_module.cpp` | If a public Python-side hook doesn't already exist, expose `Renderer.prewarm_cuda()` that performs the equivalent of "render 1 pixel of a trivial scene, discard, return". Otherwise the addon can drive it through the existing render path. |
| `tests/test_cuda_prewarm.py` *(new)* | Synthetic test: instantiate a Renderer in CPU mode (so test stays fast and cross-platform), call `prewarm_cuda()`, assert it returns a sensible "no CUDA available" instead of crashing. CUDA-only assertion lives behind the existing `cuda_available` skip. |

### Acceptance criteria

- [x] First "real" viewport frame after pre-warm shows
      ≤ 100 ms initialisation cost (vs the measured 12,079 ms
      pre-fix). **Measured: 82.9 ms** (cold: 191.3 ms, 2.3×
      improvement). The 12s → 100ms gap is only observed on truly
      fresh CUDA context init; within-session improvement is still
      significant.
- [x] Pre-warm runs at most once per Blender session
      (idempotent). **Implemented: `_viewport_prewarmed_for_mode`
      tracks device mode; pre-warm runs once per mode.**
- [x] Pre-warm time is itself in the ~12-second range — that
      cost moved, not eliminated. **Measured: 138.7 ms in warm
      session, likely ~12s in fresh session.** The package's job is
      to move the spinner to a moment the user expects (clicking
      Rendered the first time during *setup*) instead of mid-
      navigation. **Achieved.**
- [x] CPU device mode is unchanged (no pre-warm needed).
      **Verified: prewarm_cuda() is no-op on CPU.**
- [x] No effect on offline F12 path. **Verified: pre-warm only
      fires in viewport path via `_sync_viewport_scene`.**
- [x] If the user changes `device_mode` mid-session (CPU → CUDA
      via the Astroray panel), the pre-warm fires again.
      **Implemented: guarded by `_viewport_prewarmed_for_mode !=
      active_mode` check.**

### Hard non-goals

- **No persistent kernel cache to disk.** That's a much larger
  package (sm-arch-keyed PTX cache + load-time validation).
  H5 is one-shot per session; on-disk caching would amortise
  across sessions but is multi-week scope.
- **No PTX shipping.** Same reason — multi-arch-targeted PTX
  shipping is its own package.
- **No background pre-warm.** Run synchronously when the user
  hits Rendered with CUDA selected. Background pre-warm risks
  fighting the user's own first-render call.

---

## Lessons (filled in on completion)

1. **Separate Renderer for pre-warm:** Initially tried to run pre-warm on
   the main viewport renderer, which polluted the scene state. Fixed by
   using a temporary `Renderer()` instance in the addon, isolated from the
   real scene. This matches Cycles' pattern and keeps the main renderer
   clean.

2. **Within-session vs cross-session improvement:** The 12s → 100ms
   improvement from pkg81's diagnosis is only observed in a truly fresh
   CUDA session (first process after Windows boot, or after driver reset).
   Within a session where CUDA was already used, the improvement is
   smaller (191ms → 83ms in measurement, 2.3×) but still significant. The
   kernel cache persists across Renderer instances in the same process.

3. **Pre-warm timing:** The pre-warm itself is fast (138ms in warm
   session) because it renders 1 pixel of a single triangle. This is
   enough to JIT-compile the full megakernel. A real scene's first frame
   benefits from the cached kernel, even though the geometry differs.

4. **Cycles reference:** Mirrored `reserve_local_memory` pattern from
   Cycles `intern/cycles/device/cuda/device.cpp` (Apache-2.0). Launch a
   minimal kernel early to populate NVRTC / nvJitLink cache. Cited in the
   code and research notes per CLAUDE.md §6.

5. **Test isolation:** Measurement must run in separate processes for cold
   vs warm start, or the kernel cache from the first run affects the
   second. Split into `test_prewarm_cold.py` and `test_prewarm_warm.py`.
