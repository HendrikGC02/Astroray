# pkg148 — `integratorName_` default-constructs empty: GPU dedicated-light scenes silently render black

**Pillar:** 3 (light transport plumbing / API footgun)
**Track:** A
**Codex-paste-ready:** no (small, but the fix choice is a convention decision + needs an RTX-verified render gate)
**Status:** open — dispatchable (small; may run in the 2026-07-23 overnight if a slot frees — serialize the RTX leg behind the GPU lock)
**Estimated effort:** S
**Depends on:** none

**Origin:** HW-verifier finding during PR #515 verification. **Pre-existing behavior,
not a regression.** Same class as the silent-black-render bugs in the
`gr-emission-model-wiring-checklist` memory: green CI, black render, only the HW
visual gate catches it.

---

## Repro (measured)

1. Fresh `Renderer` + GPU device + a dedicated light (e.g. AREA lamp) + `render()`
   **without** calling `set_integrator` → **solid black**.
2. Same scene with an explicit `set_integrator("path_tracer")` → correct render.
3. The CPU path has no such gate at default construction, so **CPU and GPU disagree
   on a default-constructed renderer** — the worst kind of parity trap for test authors.

## Mechanism (anchors on `main`)

`module/blender_module.cpp:361` — `std::string integratorName_;` default-constructs
**empty**. The render dispatch gates named-integrator behavior on
`!integratorName_.empty()` (`blender_module.cpp:2177/2190/2200`), and the GPU
dedicated-light NEE wiring only engages inside the named-integrator branches
(`:1745-1766` — e.g. `enableNEE = (integratorName_ == "path_tracer")`). Empty name →
legacy fallback path → dedicated lights never sampled on GPU → black.

## Fix direction (pick per existing engine conventions; note both in the PR)

- **Option A — default to `"path_tracer"` at construction.** Matches CPU behavior and
  the principle of least surprise; `set_integrator` remains the override. Check the
  `clear()`/reset sites (`:2233`, `:2499`) — they must reset to the default, not to
  empty, or the footgun returns after a scene reset.
- **Option B — fail loudly on empty** (throw/assert when `render()` runs with no
  integrator set on GPU). Safer if the empty-name legacy path is load-bearing for
  some caller; grep for deliberate empty-name uses before choosing A.

Decide by call-site sweep: if nothing depends on the empty-name legacy branch,
prefer A (and consider deleting the branch as a follow-up note, not in this package).

## Acceptance gate

- GPU dedicated-light scene renders **non-black at default construction** (per-channel
  mean well above black floor), RTX-verified; CPU==GPU on the same default-constructed
  scene within the usual parity band.
- A binding-level test pinning the default (`get_integrator`/capabilities reflect
  `path_tracer`, or the loud-failure behavior if Option B) so the default cannot
  silently regress to empty.
- Existing integrator-selection tests (`test_integrator_capabilities.py` etc.)
  unchanged.

## Non-goals

- No integrator behavior changes — this is purely the default/failure-mode plumbing.
