# Half-implemented package triage — 2026-09-12

Owner directive (2026-09-11 evening, item 7): "Don't forget about older packages that
were half implemented but dropped along the way." The fact sheet
`half-implemented-audit-2026-09-12-facts.md` (delegated grunt read of the 17 specs,
verified by the lead against the spec text) is the evidence; this note is the lead's
verdict per package. Each verdict is also written into the spec's `**Status:**` line
(prefix `Triage 2026-09-12`), so `project_index.py whatis <pkg>` shows it.

Buckets: **finish in a batch** (bounded, user-visible, goes into a batched lane),
**re-scope** (delivered part closed, remainder named and deferred with a trigger),
**close** (done or superseded — nothing left to build), **park** (explicitly paused
with the condition that resumes it).

| pkg | title | verdict | remaining item / trigger |
|---|---|---|---|
| pkg88 | Motion blur | **close** (done: A/B/C.0) | C.1 perf-gated, D deferred (owner 2026-08-03) |
| pkg136 | Path guiding | **park** (Stage 1 landed) | Stage 2 GPU leg — rank in the optimisation session vs sampler / light tree / adaptive |
| pkg241 | Cancellation / viewport response | **close** (done: 0–2.2) | P2.3 gates → pkg266 |
| pkg253 | Principled advanced inputs | **finish in a batch** | GPU alpha shadows in the deferred shadow stage (strict xfail `test_alpha0_casts_no_shadow_gpu`) |
| pkg127 | Specular polynomials (sphere) | **close** (done: Phase 1) | Phases 2/3 live in pkg227 |
| pkg227 | General specular polynomials | **re-scope** (2a/2b landed) | 2c/2d wait on owner Open Decision #1; Phase 3 = future GPU caustic package |
| pkg201 | GPU settings-honour | **finish in a batch** | pkg200 driver closeout on 5.2 once; parked rows stay parked with evidence (filter_glossy, transparent_max_bounces, volume_bounces → pkg268, pixel_filter σ → pkg203) |
| pkg179 | Dielectric dead-sample Part 2 | **close** (done by diagnosis) | owner OPTION 2, 2026-08-09 |
| pkg121 | χ² sampler gates | **re-scope** (fill) | Phase B gallery campaign, no gate value |
| pkg119 | Blender parity program | **close** (superseded) | pkg260 matrix, pkg259 corpus (gate c), pkg176/#564 degradation |
| pkg126 | Mesh-emitter unification | **park** | user-visible part = #776 (textured emitters in NEE/light tree) → batch on its own |
| pkg130 | Light groups | **park** (Cycles parity) | queue after the volumes track (pkg267–271) |
| pkg133 | SRF spectral sensors | **park** | resumes with pkg51 (Pillar 4) |
| pkg134 | Light path expressions | **park** | after pkg130 |
| pkg242 | Procedural transformed-p Phase 2 | **finish in a batch** | real-Blender parity + the two #737 follow-ups |
| pkg245 | Normal/bump provenance | **re-scope** (fill) | architect review first, then a batch |
| pkg254 | Spectral path_tracer parity | **finish in a batch** | six xfails in `tests/test_python_bindings.py`, after pkg253's GPU alpha item |

## Batch candidates that fall out of this

- **Batch "GPU shade-stage items"**: pkg253 GPU alpha shadows + pkg254 xfails (they share
  the shadow-stage / transparent-alpha decision) + #776 textured emitters in NEE.
- **Batch "addon parity fill"**: pkg242 Phase 2 + pkg201 driver closeout + pkg245 (after
  its architect review).
- The optimisation session (owner decision 2) decides pkg136 Stage 2's fate.

## Nothing here changes the roadmap sequencing

All four "finish in a batch" packages are fill-tier behind Batches A–E of the
2026-09-11 handoff; the closes/supersedes only stop them from showing as open work in
`STATUS`/`KNOWN_ISSUES`.
