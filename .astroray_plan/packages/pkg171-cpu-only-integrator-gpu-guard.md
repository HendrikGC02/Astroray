# pkg171 — CPU-only integrators render silently near-black on GPU: explicit guard + the light_tracer_caustic known-state record

**Pillar:** 3 (dispatch honesty / GPU pipeline health)
**Track:** A (small; the guard is CPU-side dispatch logic, CI-testable; one RTX repro leg)
**Status:** open — backlog (S, gap-filler tier — no user-facing defect today; the value is failing LOUDLY instead of silently black)
**Estimated effort:** S
**Depends on:** nothing.

**Origin:** PR #540 hardware verification (2026-08-02, RTX 5070 Ti). The
verifier, out of thoroughness, forced `light_tracer_caustic` onto GPU and got
a near-black frame — **peak 0.019 vs CPU 0.500**. NOT a regression (the
integrator is CPU-only by its own docstring; pkg169 did not touch it) — but
the failure mode is SILENT: it renders, it's just black. This is the same
silent-black class that hid the pre-pkg89 dedicated-lights gap and the
pre-pkg80 `'auto'`-dropdown crash family.

## Known-state record (the citable fact)

`plugins/integrators/light_tracer_caustic.cpp` (pkg106, forward light tracer)
has NO GPU implementation. Requesting it on a GPU device produces a near-black
frame (peak 0.019 vs CPU 0.500, #540 verifier run), not an error. **If GPU
support for `light_tracer_caustic` is ever claimed, this is the known starting
state** — a "port" that merely stops being black is not parity; gate against
the CPU render.

## Deliverable — the cheap guard

1. Enumerate integrators by backend capability (grep the registry — any other
   CPU-only integrators get the same treatment; do not hardcode one name).
2. When a CPU-only integrator is requested with a GPU device: raise an
   explicit error (preferred) or, if the call site is the Blender addon's
   auto-fallback path, a visible warning + documented CPU fallback — match
   the existing device-selection UX (pkg37/pkg80 conventions), do not invent
   a third behaviour.
3. Test: requesting `light_tracer_caustic` + GPU asserts the error/warning
   (CI-runnable, no GPU needed for the dispatch-logic leg); one RTX leg
   confirms no silent black remains reachable.

## Non-goals

- Porting `light_tracer_caustic` to GPU (own package if ever wanted; caustics
  on GPU are pkg113's photon-map path).
- Any change to the integrator itself.

## Provenance

Filed by the architect 2026-08-02 from the #540 HW-verification finding
(team-lead bookkeeping request). Class precedent: silent-black GPU gaps
(pkg89 dedicated lights, pkg159 cryptomatte drop) cost real diagnosis time
whenever they surface inside an unrelated package's verification.
