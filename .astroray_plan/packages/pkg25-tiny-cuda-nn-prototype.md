# pkg25 — tiny-cuda-nn Prototype

**Pillar:** 3
**Track:** C
**Status:** spec drafted
**Estimated effort:** 1-2 sessions (~6 h)
**Depends on:** pkg24

---

## Goal

**Before:** the light-transport plan references Neural Radiance Caching, but
there is no concrete package that scopes the first tiny-cuda-nn experiment.

**After:** Astroray has a disposable prototype package for proving that
tiny-cuda-nn can build alongside the current codebase and run a dummy inference
path without touching production rendering behavior.

---

## Context

This is intentionally not a merge-the-feature package. Its job is to answer a
small feasibility question with minimal blast radius:

> Can tiny-cuda-nn be built and called from an Astroray-side prototype on a
> CUDA-capable workstation?

The outcome can be a throwaway branch, build notes, and a tiny harness. If the
answer is "no" or "not on this machine," that is still a useful result.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Phase 3C`
- Local-agent note: `.astroray_plan/docs/local-agent-integration.md`
- tiny-cuda-nn: https://github.com/NVlabs/tiny-cuda-nn
- NRC paper: Müller et al. 2021

---

## Prerequisites

- [ ] pkg20-pkg24 specs are reviewed so the ReSTIR track is not blocked on this
      experiment.
- [ ] A CUDA-capable machine is available for the prototype run.
- [ ] The operator confirms this work should happen on a workstation intended
      for local experiments, not on a remote or borrowed session.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/tiny-cuda-nn-prototype-notes.md` | Short experiment log: toolchain, build flags, outcome, and blockers. |
| `scripts/tiny_cuda_nn_smoke.*` | Optional throwaway harness for one dummy inference call. Pick the smallest script/binary shape that answers the question. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Only if the prototype needs an opt-in experiment target guarded behind a clear flag. |
| `.astroray_plan/docs/STATUS.md` | Record outcome once the experiment finishes. |

### Key design decisions

- Keep this prototype opt-in and disposable. No always-on dependency should
  land from this package alone.
- Prefer build notes plus a smoke harness over premature renderer integration.
- If a local model or autonomous worker is used for the experiment, its output
  must be reviewed by Codex or Claude Code before any production branch picks
  it up.
- This package is **not for the current machine/session** when local-model or
  CUDA-prototype work is unavailable or inappropriate.

---

## Acceptance criteria

- [ ] A prototype branch or notes document states whether tiny-cuda-nn built
      successfully.
- [ ] If build succeeds, one dummy inference call runs and returns finite
      output.
- [ ] No production integrator, Python binding, or Blender UI depends on the
      prototype target.
- [ ] Any added build flag defaults to off.
- [ ] The outcome is captured in docs even if the experiment is abandoned.

---

## Non-goals

- Do not ship Neural Radiance Caching.
- Do not add a `neural-cache` production plugin.
- Do not make CI depend on tiny-cuda-nn.
- Do not block ReSTIR implementation on this prototype.

---

## Progress

- [ ] Decide prototype host machine.
- [ ] Try minimal build integration.
- [ ] Run dummy inference or capture failure mode.
- [ ] Record outcome and next recommendation.

---

## Lessons

*(Fill in after the package is done.)*
