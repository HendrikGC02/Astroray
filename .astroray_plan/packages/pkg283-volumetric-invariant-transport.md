# pkg283 — Volumetric invariant transport for ADAF and synchrotron (Phase 1b)

**Pillar:** 4
**Track:** A
**Status:** done — 2026-09-25: 59/59 invariance tests; D³/g³ within 1 %; jet linear +3.6× (old extra D removed); ADAF unchanged
**Estimated effort:** 2 sessions (~6 h), CPU
**Depends on:** pkg280

---

## Goal

Before: `ADAF::emissivity`/`integrateSegment` and
`SynchrotronJet::emissivity`/`integrateSegment` have no verified
Lorentz-invariant emissivity/absorption transport (pkg280 Phase 1b was
scoped but not implemented — no Phase 1 analytic tests exist for either
path). After: both paths transport the invariant `j_ν/ν²` (emissivity) and
`ν·α_ν` (absorption), apply the `g³` intensity transfer at integration using
a fluid-frame frequency `ν_em = -k·u`, and pass the same class of analytic
tests pkg280 wrote for the thin disk — making them eligible for a
science-ready label for the first time.

---

## Context

pkg280 validated the thin-disk transfer formula but explicitly left ADAF and
synchrotron unresolved: their current transport has not passed any analytic
check, so both are prohibited from science release. pkg279 (HMXB Phase 1)
and future nebula/lensing work depend on trustworthy volumetric transport;
without this package their outputs remain uninterpretable observables dressed
as physical ones.

---

## Evidence

- 2026-09-24: pkg280 report (`.astroray_plan/docs/gr-transfer-audit-2026-09.md`, Checkpoint 2026-09-24): "No ADAF or synchrotron invariant-emissivity/absorption implementation. Their current transport has not passed the required analytic checks and remains unresolved."
- 2026-09-24: pkg280 Phase 4 (`astra_run/batchB-phase24/RESULT.md`): ADAF bank render byte-identical vs pre-Phase-1 baseline (no volumetric transfer change made); synchrotron differs only at an isolated clamp-boundary pixel (shared clamp removal, not a transfer fix).

---

## Reference

- `.astroray_plan/docs/gr-transfer-audit-2026-09.md` §Validated vs unresolved paths.
- `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md` §Phase 1b, §Scope boundary.
- External: Rybicki & Lightman 1979, *Radiative Processes in Astrophysics* §4.2 (invariant `j_ν/ν²`, `ν·α_ν`); Moscibrodzka & Gammie 2018, MNRAS 475, 43 (ipole, BSD-3 — `radiation.c::jnu_inv`, `get_fluid_nu`; no code copied, external pattern only); GYOTO (Vincent et al. 2011, CQG 28, 225011, GPL-3.0 — external executable oracle only, not linked).

---

## Prerequisites

- [ ] pkg280 is done; its Phase 1 analytic test harness (`tests/test_gr_transfer_invariance.py`) exists and passes for the thin disk.
- [ ] Build passes on main. CPU backend only.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/adaf.h` | `ADAF::emissivity`/`integrateSegment`: transport invariant `j_ν/ν²` (via `jnuThermalI`/`jnuBremsstrahlungI`) and `ν·α_ν`; evaluate at fluid-frame `ν_em = -k·u`; apply `g³` intensity transfer once at integration (no double-counted Doppler multiply). |
| `include/astroray/synchrotron.h` | `SynchrotronJet::emissivity`/`integrateSegment`: same invariant transport, using the jet's Doppler factor `D` in place of `g` (`j_ν` at `ν_obs/D`, `D³` boost), fluid-frame frequency from `-k·u`. |
| `tests/test_gr_transfer_invariance.py` | Extend with Phase 1 analytic tests for both paths: static-vs-moving emitter pair, fluid-frame frequency check, no-double-counting check, invariant residual ≤1 %. |
| `benchmarks/reference_bank/scenes/adaf-sgrA-faceon/gates.toml` | Update metric thresholds once the new transport is measured. |
| `benchmarks/reference_bank/scenes/synchrotron-jet-m87/gates.toml` | Update metric thresholds once the new transport is measured. |

### Key design decisions

Reuse the exact test structure pkg280 built for the thin disk (Phase 1
tests: `g=1` reduction, monotone scaling, invariant residual ≤1 %,
fluid-frame frequency test, double-counting test) rather than inventing new
ones. Cite ipole's `jnu_inv`/`get_fluid_nu` as the pattern (no code copied,
same posture as pkg280).

---

## Acceptance criteria

- [x] ADAF and synchrotron each transport `j_ν/ν²` and `ν·α_ν` per Rybicki & Lightman §4.2.
- [x] Fluid-frame frequency test (`ν_em = -k·u`) passes for both paths.
- [x] Double-counting test (static-vs-moving ratio = analytic `g³`/`D³` within 1 %) passes for both paths.
- [x] Invariant residual ≤ 1 % for both paths, matching pkg280's thin-disk tolerance.
- [x] `adaf-sgrA-faceon` and `synchrotron-jet-m87` bank scenes re-measured on the new per-channel metric; any reference change goes through independent reviewer sign-off per pkg280 Phase 4 rules.
- [x] `.astroray_plan/docs/gr-transfer-audit-2026-09.md` §Validated vs unresolved paths updated to move ADAF/synchrotron out of "unresolved" once tests pass.

---

## Non-goals

- Do not add new emission models or jet/disk physics.
- Do not add GPU GR code.
- Do not touch the thin-disk path (already validated by pkg280) or the Kerr metric/redshift work (pkg281/pkg282).

---

## Progress

- [x] ADAF invariant transport + tests.
- [x] Synchrotron invariant transport + tests.
- [x] Bank re-measurement + reviewer sign-off.
- [x] Update pkg280 audit doc's validated/unresolved list.

---

## Lessons

- Per lab-frame path, the thin result is g²·j(ν/g). g³ multiplies the fluid-frame intensity, and L_fluid = ds_lab/g. The old jet code applied D³ to the lab path, one power of D too many (steady jet D^{2+α}, Lind & Blandford 1985).
- Bank display gates saturate on both scenes, so they cannot see transport. The jet changed ×3.6 in linear light and the display changed by only 2 px. No reference was changed, so no reviewer sign-off was needed. Pre-existing failures: ADAF phash 20 > 18 and jet bright_coverage 0.0759 < 0.08, the same before and after.
- ADAF +30 % CPU render time (Kirchhoff α per sample).
- MinGW: a by-value `std::optional<std::array<double,3>>` pybind argument crashed after an earlier call. Use `py::object`.
