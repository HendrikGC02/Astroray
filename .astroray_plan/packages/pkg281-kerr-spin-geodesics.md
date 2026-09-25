# pkg281 — Honour spin in BlackHole geodesics (CPU)

**Pillar:** 4
**Track:** A
**Status:** done
**Estimated effort:** 1 session (~3 h), CPU
**Depends on:** pkg280

---

## Goal

Before: `addBlackHole` never reads the scene's `spin` parameter and `BlackHole`
hardcodes `SchwarzschildMetric(1.0)`, so `gr-kerr-94-faceon` (a=0.94) renders
identical to Schwarzschild. After: `BlackHole` selects `KerrMetric` with the
declared `spin` when nonzero, `gr-kerr-94-faceon` renders true a=0.94
geodesics, and the photon-ring position matches GYOTO within the audit's
gate.

---

## Context

pkg280 Phase 3 found the root cause of the Kerr cross-check failure: the
engine silently discards `spin` and always integrates Schwarzschild. Against
GYOTO a=0 the ring already agrees within 1.5 %, so the geodesic solver and
measurement procedure are trustworthy — only the metric selection is wrong.
Without this fix no Kerr-labelled render in the reference bank is science-valid.

---

## Evidence

- 2026-09-24: `addBlackHole` (`module/blender_module.cpp`) never reads `spin`; `BlackHole` ctor hardcodes `SchwarzschildMetric(1.0)` (`include/astroray/black_hole.h:291`).
- 2026-09-24: `KerrMetric::geodesic_rhs` (`kerr.cpp:126`) throws — not currently reachable from any live path.
- 2026-09-24: Phase 3 cross-check (`astra_run/batchB-phase3/RESULT.md`, `NOTES.md`): Astroray ring edges 67/66/67/66 px vs GYOTO a=0.94 87/34/61.5/61.5 px (max mismatch 94 %, mean radius +9.0 %); vs GYOTO a=0 66/66/66/66 px (1.5 % match, quantisation-bound). GYOTO a=0.94 edges independently match the analytic Bardeen equatorial critical impact parameters (34.0 / 88.8 px).

---

## Reference

- `.astroray_plan/docs/gr-transfer-audit-2026-09.md` §Phase 3, §Four numbers (fixed stop).
- `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md`.
- Frozen comparison metadata and procedure: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase3/NOTES.md`.
- External: Rybicki & Lightman 1979, *Radiative Processes in Astrophysics* §4.2; Cunningham 1975, ApJ 202, 788; Vincent et al. 2011, CQG 28, 225011 (GYOTO, GPL-3.0 — external executable oracle only, no code copied or linked); Bardeen 1973 (Kerr equatorial photon orbits, critical impact parameter).

---

## Prerequisites

- [ ] pkg280 is done; the audit report and its four numbers exist.
- [ ] Build passes on main. CPU backend only.
- [ ] GYOTO 2.0.2 (pinned `94863d06`) available as an external process for re-running the Phase 3 comparison, or the frozen `astra_run/batchB-phase3/gyoto/*.fits` outputs are reused unchanged.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/black_hole.h` | Constructor selects `KerrMetric(spin)` when `spin != 0`, `SchwarzschildMetric(1.0)` when `spin == 0`; forward the constructor's `spin` argument instead of hardcoding. |
| `plugins/metrics/kerr.cpp` | Fix `KerrMetric::geodesic_rhs` (currently throws, reserved for pkg41/pkg67) so it integrates real Kerr geodesics; cite the equations of motion used. |
| `module/blender_module.cpp` | `addBlackHole` reads and forwards the scene's `spin` parameter to `BlackHole`'s constructor. |
| `benchmarks/reference_bank/scenes/gr-kerr-94-faceon/gates.toml` | Add/adjust the ring-edge gate once the new render is measured. |

### Key design decisions

Follow the pattern already validated in pkg280: cite the published geodesic
equations (do not invent), reuse the existing Schwarzschild integrator
structure rather than a parallel one. CPU only — no GPU GR code (matches
pkg280's non-goals).

---

## Acceptance criteria

- [ ] `gr-kerr-94-faceon` (a=0.94) renders using `KerrMetric`, not `SchwarzschildMetric`.
- [ ] Re-run the pkg280 Phase 3 procedure (frozen metadata in `astra_run/batchB-phase3/NOTES.md`) against GYOTO a=0.94: ring edges L/R/T/B each within **≤ 5 %**.
- [ ] a=0 regression check: setting `spin=0` still matches GYOTO a=0 within 1.5 % (no regression from the metric-selection change).
- [ ] `gr-kerr-94-faceon` reference bank rebaselined once the gate passes, with independent reviewer (Codex Terra or cycles-parity-reviewer) sign-off per pkg280 Phase 4 rules.

---

## Non-goals

- Do not fix the redshift asymmetry (pkg282).
- Do not add GPU GR code.
- Do not implement ADAF/synchrotron invariant transport (pkg283).

---

## Progress

- [x] Wire `spin` through `addBlackHole` into `BlackHole`.
- [x] Fix `KerrMetric::geodesic_rhs`.
- [x] Re-run GYOTO a=0.94 ring comparison; confirm ≤5 % (2026-09-25: 89/33/62.5/61.5 px vs GYOTO 87/34/61.5/61.5, max 2.9 %; a=0 unchanged at 1.5 %).
- [ ] Rebaseline `gr-kerr-94-faceon` reference with reviewer sign-off.

---

## Lessons

*(Fill in after the package is done.)*
