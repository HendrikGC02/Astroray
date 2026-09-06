# pkg254 — Spectral path_tracer feature parity (the deferred bindings xfails)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg14, pkg87, pkg195

---

## Goal

Before: six features that the pre-pkg14 RGB path tracer supported are still
"not ported to the spectral path_tracer — deferred" and live as `strict=True`
xfails in `tests/test_python_bindings.py` with no owner. After: each feature
either works on the spectral `path_tracer` (CPU and GPU) with its xfail marker
removed, or is retired with a recorded owner decision; no unowned xfail remains.

---

## Context

pkg14 deleted the legacy RGB integrator and made `path_tracer` spectral-first.
Ten integration tests were parked as `strict=False` xfails, which silently
swallowed fixes: on 2026-09-07 four of them XPASSed (per-closure bounce limits
and caustics flags already work) and their markers were removed (PR #720). The
remaining six are real gaps a Blender user hits through native Cycles panels
(transparent alpha, filter glossy, cryptomatte passes, HDR/linear output,
gamma toggle). Owning them here keeps the coverage gate honest.

---

## Evidence

- 2026-09-07 — `python -m pytest tests/test_python_bindings.py -k "alpha or filter_glossy or cryptomatte or hdr or gamma"`: six xfails remain at lines ~516, ~546 (transparent alpha), ~1018 (filter_glossy), ~1279 (cryptomatte/render passes), ~1425 (HDR/linear output pass), ~1519 (gamma toggle); markers now `strict=True` (PR #720).
- 2026-09-07 — the four bounce-limit / caustics-flag tests XPASS on `build_cuda/Release` (main `bd59652`) and had their markers removed.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Spectral path tracer`
- pkg14 (legacy RGB path deletion), pkg87 (cryptomatte), pkg195 (spectral node system), pkg253 (Principled Alpha is the addon-side consumer of transparent alpha).

---

## Prerequisites

- [ ] pkg253 G1 (Principled Alpha) decides whether transparent alpha is a closure or a shadow-only feature.
- [ ] Build passes on main; `tests/test_python_bindings.py` collected with the six xfails present.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `tests/test_python_bindings.py` | remove each xfail marker as its feature lands; no test body changes |
| `plugins/integrators/path_tracer.cpp` | transparent alpha, filter_glossy, gamma toggle honoured on the spectral path |
| `module/blender_module.cpp` | expose/route the settings if a binding is missing |
| `src/gpu/wavefront/*.cu` | GPU twin of each honoured setting (register-neutral) |

### Key design decisions

- One feature per PR, CPU and GPU together, each removing exactly its xfail marker(s).
- Retirement is allowed only with an owner note in `## Progress` and the test deleted, never re-xfailed.
- Follow the Cycles semantics already mapped in `blender_addon/settings_map.py`.

---

## Acceptance criteria

- [ ] Zero `xfail` markers in `tests/test_python_bindings.py` whose reason contains "not ported to the spectral path_tracer".
- [ ] Each landed feature has a CPU/GPU parity assertion in its test.
- [ ] Full `tests/test_python_bindings.py` green on the RTX 5070 Ti.

---

## Non-goals

- Do not re-introduce an RGB integrator.
- Do not relax any test threshold to flip an xfail.

---

## Progress

- [x] 2026-09-07 — filed; four XPASS markers removed in PR #720; six remain.

---

## Lessons

*(Fill in after the package is done.)*
