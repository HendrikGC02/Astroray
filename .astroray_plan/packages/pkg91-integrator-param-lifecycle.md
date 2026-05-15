# pkg91 — Integrator parameter lifecycle (close the silent-no-op footguns)

**Pillar:** 1 (plugin architecture)
**Track:** A (core quality / correctness)
**Status:** open
**Estimated effort:** 1–2 sessions (~6 h); spec + minimal API change + tests + docs
**Depends on:** pkg05 (integrator interface) — done

---

## Goal

**Before:** `Renderer::render(spp, max_depth, ...)` accepts `max_depth` but
silently drops it on the floor when an integrator is registered — the
integrator runs at whatever `max_depth` was captured into the integrator's
private `maxDepth_` member at construction time
(`plugins/integrators/spectral_path_tracer.cpp:45`, `ParamDict::getInt("max_depth", 50)`).
Symmetrically, `PyRenderer::setIntegratorParam` (`module/blender_module.cpp:1136-1138`)
only writes to the staging `integratorParams_` dict; the already-constructed
integrator never re-reads it. Both are silent no-ops that look like they work.

**After:** Calling `set_integrator_param(key, value)` after `set_integrator(name)`
either takes effect on the live integrator, or raises. Calling
`Renderer.render(spp, N)` either applies `N` as the path-depth cap or raises.
There is exactly one path-depth source of truth per render call, and the
API surfaces it clearly.

---

## Context

Two related defects surfaced during pkg55-B' Phase B' Session 2b
(PR #281 close gate, 2026-05-15):

1. **`Renderer.render(max_depth=N)` silently ignored under integrators.**
   The tile loop at `include/raytracer.h:2481+` accepts `maxDepth` but
   never forwards it to `integrator_->sampleFull()`. Production ran at
   the integrator's stored `maxDepth_=50` while the reference oracle ran
   at the requested `max_depth=8`; RNG state desynced; trip-wire fired
   for the wrong reason. Took an instrumentation pass to find.
2. **`set_integrator_param` after `set_integrator` is a no-op.** Setting
   a param after the integrator has been constructed updates the staging
   `ParamDict` only; the live integrator already captured its parameters
   into private members.

Both are the same architectural fact: `ParamDict` is read once at
integrator construction. The API does not advertise this lifecycle, so
two reasonable use patterns silently misbehave. The user got bit on
pkg55-B'; absent a fix, the next user (or the next slot-mutating refactor)
will get bit again.

Fixing these now — not after Phase B' closes — prevents the GPU
wavefront sessions (CUDA port, pkg55 Phase B' Sessions N+2..M) from
inheriting the same footgun in a place where debugging is 10× harder.

---

## Reference

- `include/raytracer.h` lines 2481–2580 — production tile loop;
  `maxDepth` arrives and is dropped.
- `plugins/integrators/spectral_path_tracer.cpp` lines 44–55 —
  ctor reads `max_depth` from `ParamDict` into private member.
- `module/blender_module.cpp` lines 1136–1172 — `setIntegratorParam`
  staging-dict write + `setIntegrator` construction site.
- Pattern reference (handle-based mutation after construction):
  - Cycles `intern/cycles/integrator/path_trace.h` — `set_max_bounces()`
    is a setter on the live integrator; the host re-pushes the value
    to the device on the next render. Apache-2.0.
  - PBRT-v4 `src/pbrt/integrators.cpp` — integrator constructors
    consume `ParameterDictionary` once at scene-build time and do not
    expose mutators; runtime depth changes require a new integrator.
    Apache-2.0.
  - Mitsuba 3 `src/integrators/path.cpp` — `props.get<int>("max_depth")`
    consumed once at construction; mutation is via `traverse()` /
    parameter-update protocol. BSD-3-Clause.

The Cycles pattern (live-setter) and PBRT pattern (rebuild on mutation)
are both viable. The fork is between them — see Key design decisions.

---

## Prerequisites

- [ ] pkg05 integrator interface is in place (done).
- [ ] Build passes on main.
- [ ] No active pkg55-B' work is mid-session-with-uncommitted-state on
      the integrator API — pkg91 may rebase pkg55-B' work-in-progress.

---

## Specification — design forks to resolve at spec-promotion time

This is a **DRAFT promotion-pending** spec. The two architectural forks
below need owner sign-off before implementation.

### Fork A — Q1 (`render(max_depth=N)` semantics)

Three viable resolutions, in order of preference:

1. **Recommended: forward to integrator per-call.** Add
   `Integrator::setMaxDepth(int)` (default impl: stores into integrator's
   private member; integrators may override to fan it out to internal
   state). `Renderer::render` calls
   `integrator_->setMaxDepth(maxDepth)` once at frame start, before the
   tile loop. Same semantics for every integrator. Cycles-style.
2. **Alternative: deprecate the parameter on `Renderer::render`.** Remove
   `max_depth` from `Renderer::render` (or accept it only when no
   integrator is registered, throwing otherwise). Force callers to
   `set_integrator_param("max_depth", N); set_integrator("path_tracer")`
   in that order. PBRT-style. Cleaner contract, but breaks every existing
   caller including the Blender addon and several tests.
3. **Worst: docs warning.** Add a docstring "max_depth is ignored when an
   integrator is registered." Rejected — the user already got bit despite
   reading the code; a docstring won't help the next agent either.

### Fork B — Q2 (`set_integrator_param` after `set_integrator`)

Three viable resolutions, in order of preference:

1. **Recommended: rebuild integrator on param change.** `setIntegratorParam`
   updates `integratorParams_` AND, if an integrator is currently
   registered, re-constructs it via the registry with the updated dict.
   Idempotent (same dict → same integrator). One-line behavior change
   for the user: "params take effect immediately." Cost: integrator
   ctor must be cheap (true for all current integrators; assert in CI if
   it stops being true).
2. **Alternative: live setters per param.** Add a `set(key, value)`
   protocol on `Integrator` itself; integrators opt in to mutable params.
   More surface but more efficient when params change frequently
   (they don't — viewport pan does not retune `max_depth`).
3. **Alternative: throw on post-construction mutation.**
   `setIntegratorParam` raises if an integrator is registered. Forces
   callers to `set_integrator(None); set_integrator_param(...); set_integrator(name)`.
   Cleanest contract, loudest API. May break the Blender addon's
   parameter UI flow — needs measurement.

**Owner's tie-breaker question (to answer at promotion):** Is it
acceptable for `set_integrator_param` to rebuild the integrator object
(option B.1)? If the integrator carries per-frame statistics
(`SpectralPathTracer::smsAttempts_` etc.) that should accumulate across
multiple `render()` calls, rebuilding clears them — confirm this is
acceptable, or pick B.2 / B.3.

### Files to modify (option A.1 + B.1)

| File | What changes |
|---|---|
| `include/astroray/integrator.h` | Add virtual `void setMaxDepth(int)` default impl + comment |
| `plugins/integrators/spectral_path_tracer.cpp` | Override `setMaxDepth` to update `maxDepth_` |
| `plugins/integrators/path_tracer.cpp` | Override `setMaxDepth` |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Override `setMaxDepth` |
| `plugins/integrators/sms_caustic_path_tracer.cpp` | Override `setMaxDepth` |
| `plugins/integrators/restir_di.cpp` | Override `setMaxDepth` |
| `include/raytracer.h` lines 2481+ | Call `integrator_->setMaxDepth(maxDepth)` before tile loop |
| `module/blender_module.cpp:1136-1138` | `setIntegratorParam` rebuilds the live integrator |
| `tests/test_pkg91_integrator_param_lifecycle.py` (new) | Tests for Q1 and Q2 |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg91_integrator_param_lifecycle.py` | (1) `render(max_depth=2)` produces same image as `set_integrator_param("max_depth", 2); render(...)`; (2) calling `set_integrator_param` after `set_integrator` changes subsequent render output |

---

## Acceptance criteria

- [ ] `Renderer.render(spp, max_depth=N)` with a registered integrator
      produces the same image as
      `set_integrator_param("max_depth", N); render(spp, max_depth=999)`
      (bit-exact at fixed seed on Cornell-Lambertian, 1 spp).
- [ ] After `set_integrator("path_tracer")`, calling
      `set_integrator_param("max_depth", 2)` and then `render(64, 50)`
      produces an image whose mean brightness differs from the same
      sequence with `max_depth=50` by ≥ 5% on a Cornell scene (proves
      the param actually took effect post-construction).
- [ ] All 911+ existing tests still pass (no regressions).
- [ ] No new public Python API surface beyond what the spec lists; no
      ParamDict re-architecture.

---

## Non-goals

- Do **not** generalize this to "all integrator params are runtime-mutable
  via a generic dispatcher." `max_depth` is the only param this spec
  addresses by name; everything else flows through the `setIntegratorParam`
  → rebuild path (option B.1) and gets the new behavior for free, without
  per-param plumbing.
- Do **not** redesign `ParamDict`. The dict is fine; the bug is that it's
  read once and never reconsulted.
- Do **not** add deprecation warnings for the old `max_depth` argument
  in this package. If we deprecate, do it in a follow-up — this package
  is a behavioral fix, not an API rename.
- Do **not** touch the wavefront / GPU code paths. pkg91 is CPU-API
  level; the GPU integrators inherit the fix when their host-side
  integrator object's `setMaxDepth` is wired.

---

## Progress

- [ ] Owner answers Fork A + Fork B tie-breakers; spec promoted.
- [ ] Implement `Integrator::setMaxDepth` virtual + per-integrator overrides.
- [ ] Wire `Renderer::render` to call `setMaxDepth` once at frame start.
- [ ] Wire `PyRenderer::setIntegratorParam` to rebuild on registered-integrator.
- [ ] Tests written + passing.
- [ ] CI green on all 911+ tests; no regressions.

---

## Lessons

*(Fill in after the package is done.)*

This spec exists because pkg55-B' Phase B' Session 2b lost roughly a
session to a silent `max_depth` mismatch (production at 50, reference
at 8). The cost of NOT fixing this is paid in future debugging sessions
on the GPU wavefront port; the cost of fixing it is one virtual method
and one ctor-rebuild path.
