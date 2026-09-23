# pkg280 — GR transfer & reference audit (Stage 1 groundwork lane)

**Pillar:** 4
**Track:** A
**Status:** done — fixed stop reached, 2026-09-24; report + follow-ups pkg281-283
**Estimated effort:** 2 sessions (~6 h), CPU
**Depends on:** none

---

## Goal

Before: `diskEmissionSpectral` evaluates `B(λ_obs, T)·g⁴` with no wavelength
shift and clamps emission at 20; GR bank render time grew ~10× since 2026-05;
no external cross-check; the GR bank has no per-channel baseline. After: the
thin-disk and volumetric emitters use the invariant transfer
`I_obs(ν_obs) = g³ I_em(ν_obs/g)`, the emission clamp is removed or justified by
a numeric test, the ~10× growth is attributed to a named component, one Kerr
frame is cross-checked against GYOTO/ipole, and the four GR bank scenes are
re-baselined — all recorded in one evidence report with a fixed stop.

**FIRST MEASURABLE DELIVERABLE.** A figure of `I_obs(ν)/ν³` versus
`B_ν(ν, g·T)/ν³` for a Planck emitter at several `g`. Literature invariant:
`I_ν/ν³` (Rybicki & Lightman 1979 §4.2; Cunningham 1975). Tolerance: the
recovered colour temperature equals `g·T` within **≤ 1 %**.

---

## Context

Stage 1b names this the one bounded CPU groundwork lane before Pillar 4 thaws.
Pretty GR images can hide observables that are physically wrong — clamps and a
missing frequency shift preserve appearance while corrupting spectra. The
science tracks (Track N nebula, Track L lensing/HMXB) depend on a GR transfer
path whose numbers can be trusted. Runtime is also unattributed, so any later
optimisation would be guesswork. Without this audit, pkg50 and pkg279 build on
an unverified path.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: `diskEmissionSpectral` (`include/astroray/black_hole.h:159-166`) evaluates `B(λ_obs,T)·g⁴`, caps `g` at 10, and clamps emission at 20.
- 2026-09-22: a second `g⁴·B(λ_em,T)` site exists in the visualization disk path (`include/astroray/black_hole.h:302-308`).
- 2026-09-22: `benchmarks/reference_bank/README.md` lists `~2 s` for `gr-schwarzschild` and `gr-kerr-94-faceon` (2026-05); measured 19.7–19.8 s at `604b03f0`, 512×512×64.
- 2026-09-22: pkg107 reconciled — `r_obs_M` is a constructor parameter (`include/astroray/black_hole.h:214-223`), forwarded by `addBlackHole`, and used by the bank scenes (`r_obs_M: 20.0`). Verification is folded into this package.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).
- 2026-09-22: Codex Terra review defects applied (planning session).
- 2026-09-22: Astra turn-4 sign-off discrepancies closed (planning session).

---

## Reference

- Design: `.astroray_plan/docs/stage-plan-2026-09-22.md §3 Stage 1b`, `§4`.
- `.astroray_plan/docs/astrophysics.md`; `.astroray_plan/docs/accretion-emission-research.md` (invariant `I/ν³` transfer; ipole `radiation.c::jnu_inv`).
- `.astroray_plan/packages/pkg107-blackhole-robs-parameterization.md`; `.astroray_plan/packages/pkg243-raw-band-output-provenance.md`; `.astroray_plan/packages/pkg251-spectral-band-parameter-reachability.md`.
- External: Rybicki & Lightman 1979, *Radiative Processes in Astrophysics*, §4.2; Cunningham 1975, ApJ 202, 788; Moscibrodzka & Gammie 2018, MNRAS 475, 43 (ipole); Luminet 1979, A&A 75, 228; Vincent et al. 2011, CQG 28, 225011 (GYOTO).

---

## Prerequisites

- [ ] Build passes on main; CPU backend only.
- [ ] Binary / `.pyd` rebuilt at the audit commit so matched-setting timings compare like with like.
- [ ] `include/astroray/black_hole.h:214-223` confirms `r_obs_M` is live before the shadow-radius check.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/gr-transfer-audit-2026-09.md` | Evidence report: the four numbers, method, raw logs, and the fixed-stop list. |
| `tests/test_gr_transfer_invariance.py` | Spectral-invariance and clamp tests for the disk, ADAF, and synchrotron emitters. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/black_hole.h` | `diskEmissionSpectral`, `volumetricEmissionSpectral`, and the visualization disk path: invariant `g³` transfer evaluated at `ν_obs/g`; remove the clamp or justify it with a numeric test. |
| `include/astroray/adaf.h` | `ADAF::emissivity` / `ADAF::integrateSegment`: audit the `g`-factor transfer (j_nu via `jnuThermalI` / `jnuBremsstrahlungI`); align it or record a no-op justification. |
| `include/astroray/synchrotron.h` | `SynchrotronJet::emissivity` / `SynchrotronJet::integrateSegment`: audit the `g`-factor transfer (j_nu evaluated at `ν_obs/D`, `D³` boost); align it or record a no-op justification. |
| `benchmarks/reference_bank/runner.py` | Add a per-channel mean-ratio metric for GR scenes, keeping SSIM as a diagnostic. |
| `benchmarks/reference_bank/scenes/gr-kerr-94-faceon/gates.toml` | New metric thresholds for the Kerr scene. |
| `benchmarks/reference_bank/scenes/gr-schwarzschild/gates.toml` | New metric thresholds for the Schwarzschild scene. |
| `benchmarks/reference_bank/scenes/adaf-sgrA-faceon/gates.toml` | New metric thresholds for the ADAF scene. |
| `benchmarks/reference_bank/scenes/synchrotron-jet-m87/gates.toml` | New metric thresholds for the synchrotron-jet scene. |
| `benchmarks/reference_bank/README.md` | Re-baselined GR render times and the new metric. |

### Key design decisions

Cite the published method; add no invented physics. Reuse existing volume
transport and the emission registry rather than new accumulators.

#### Phase 1 — Invariant intensity transfer

- Frequency domain: `I_ν,obs(ν) = g³ I_ν,em(ν/g)` with `g = ν_obs/ν_em`. Wavelength domain: `I_λ,obs(λ) = g⁵ I_λ,em(g·λ)`.
- The engine's `diskEmissionSpectral` works in the wavelength domain (per-λ `SampledSpectrum`); the Jacobian-exact form is `I_λ,obs(λ) = (c/λ²)·g³·B_ν(c/(g·λ), T) = g⁵·B_λ(g·λ, T)`. Applying `g³` to `B_λ`, evaluating `B` at the unshifted `λ`, or omitting the `(c/λ²)` Jacobian is wrong.
- Test bin-by-bin that the `(c/λ²)·g³·B_ν` and `g⁵·B_λ` evaluations agree on every sampled bin, so a missing Jacobian cannot pass.
- Keep the existing `exposureScale / span` normalisation unchanged.
- Remove the `min(20.0, ·)` clamp unless a numeric test shows a needed bound; if kept, state the affected pixel range and why unbiased sampling cannot replace it.
- Test: `g = 1` reduces to `B(λ, T)`; monotone `g` scaling; the invariant residual `I_ν/ν³` is preserved within **≤ 1 %**; recovered colour temperature `= g·T` within 1 %.
- Test: monochromatic shift — a delta emitter at `λ_em` appears at `λ_em/g`.
- Test: bolometric scaling `∫I_ν dν ∝ g⁴` — integration measure: trapezoidal integral over the sampled per-λ grid spanning ≥ 99.9 % of the Planck flux at both `T` and `g·T`; tolerance **≤ 1 %** `(frozen 2026-09-22, lead may adjust)`.
- Test (fluid-frame frequency): for a moving emitter with 4-velocity `u`, the emitted frequency used to evaluate `j_ν` MUST be `ν_em = -k·u` (Moscibrodzka & Gammie 2018, ipole), verified against an analytic boost case.
- Test (Doppler/redshift double-counting): the invariant `j_ν/ν²` and `α_ν·ν` transport MUST apply the `g`-factor exactly once (no separate Doppler multiply on top of the invariant transfer), verified by a static-vs-moving emitter pair whose ratio equals the analytic `g³` (frequency-domain) factor within **1 %**.

#### Phase 1b — Volumetric transfer convention (mandatory for science paths)

- Any path transporting emission or absorption through a moving medium transports the Lorentz-invariant `j_ν/ν²` (emissivity) and `ν·α_ν` (absorption), applying the `g³` intensity transfer at integration. Source: Rybicki & Lightman 1979 §4.2; ipole `radiation.c::jnu_inv`.
- Each volumetric path (ADAF, synchrotron) MUST pass the Phase 1 analytic tests under this convention before it is labelled science-ready; a path that cannot pass is unresolved and prohibited from science release.

#### Phase 2 — Render-time attribution (~10×, bounded)

- Bounded attribution only: matched-setting bisection to a named component. Recovering the old performance is NOT part of this package's acceptance.
- Matched settings: same scene SHA, build id, backend, 512×512×64.
- Bisect geodesic integrator only vs spectral sampling vs emission vs scene changes; use `runner.py` timers and `benchmarks/reference_bank/history.csv`.

#### Phase 3 — Cross-check one Kerr frame

- `gr-kerr-94-faceon`, `a = 0.94`: compare photon-ring image position and disk redshift asymmetry against a GYOTO or ipole reference, each within **5 %**.
- Any reference MUST supply frozen comparison metadata — matched geometry (`a`, `r_obs_M`, inclination, field of view, pixel resolution), emission model (disk temperature profile and emissivity index), spectral band, intensity normalization, and the measurement procedure for both extracted quantities — or it is rejected; a 5 % mismatch is only interpretable under matched metadata.
- If neither tool runs in-env, use one published frame that supplies all metadata above; a frame missing any item is rejected.

#### Phase 4 — Bank re-baseline and pkg107

- Primary metric: per-channel mean ratio; SSIM retained as a diagnostic.
- Re-baseline the GR scenes after Phase 1; record before/after ratios. Re-baselining requires attribution of every changed pixel region to the Phase 1 fix and an independent reviewer sign-off (Codex Terra or the cycles-parity-reviewer); passing newly captured references cannot validate the change that produced them.
- Verify `r_obs_M` scales the shadow radius as expected.

#### Scope boundary

- Mandatory analytic validation core: the Phase 1 tests above, on every path the report labels science-ready — the thin-disk path AND each volumetric path (ADAF, synchrotron) to be labelled science-ready. A path without passing analytic transfer validation MUST NOT be labelled science-ready.
- Volumetric paths additionally require the invariant emissivity/absorption transport of Phase 1b; absent it they are not science-ready.
- Plus ONE compatible external reference comparison (Phase 3, GYOTO or ipole), matching physical model and normalisation.
- Any path not validated in-lane is recorded as unresolved and explicitly prohibited from science release; the existence of the report does not authorise use of an unresolved path.

---

## Acceptance criteria

- [ ] Report exists with four numbers: invariance residual, render-time delta, cross-check mismatch, bank per-channel ratios.
- [ ] `tests/test_gr_transfer_invariance.py` passes on every path labelled science-ready; invariance residual ≤ 1 %.
- [ ] Fluid-frame frequency and double-counting tests pass for every path labelled science-ready.
- [ ] Emission clamp removed or justified by a numeric test.
- [ ] `gr-kerr-94-faceon`, `gr-schwarzschild`, `adaf-sgrA-faceon`, `synchrotron-jet-m87` PASS on the new per-channel metric; SSIM recorded.
- [ ] The ~10× growth is attributed to a named component (attribution only).
- [ ] Report lists validated vs unresolved paths explicitly; no unresolved path is labelled science-ready.
- [ ] pkg107 `r_obs_M` shadow-radius behaviour verified.
- [ ] Follow-up specs filed for anything not fixed in-lane.

---

## Non-goals

- Do not add or change GPU GR code.
- Do not add new emission models or disk/jet physics.
- Do not produce showcase renders.
- Do not implement pkg243 band output or pkg133 SRF sensors.
- Do not implement grating (#141) or cluster lensing.

---

## Progress

- [x] Phase 1: invariant transfer + clamp decision + tests. Thin-disk `g⁵·B_λ`/`(c/λ²)·g³·B_ν` helper landed; clamp-20 removed; analytic tests pass; GYOTO external-`g` checkpoint ≤1% (see Checkpoint 2026-09-24).
- [x] Phase 2: render-time attribution. ~15-16x scene re-authoring (PR #405), +4.8-6.7% code.
- [x] Phase 3: Kerr cross-check. FAILS both quantities against GYOTO a=0.94 (ring 94%, redshift asymmetry ~100%); root causes identified (spin ignored, momentum-free redshift). Filed pkg281/pkg282.
- [x] Phase 4: bank re-baseline + pkg107 verification. No reference.png replaced; all four scenes within ~1.5% of stored refs; pkg107 scaling law verified, 0.37x absolute offset unexplained (filed to pkg282).
- [x] Report written; follow-ups filed; stop. `.astroray_plan/docs/gr-transfer-audit-2026-09.md` has the four-numbers section; pkg281 (Kerr spin), pkg282 (momentum redshift + pkg107 offset), pkg283 (ADAF/synchrotron Phase 1b) filed.

---

## Lessons

- The Phase 1 analytic core (thin-disk transfer formula) and the Phase 3
  cross-check are separable: a formula can be internally self-consistent and
  match an external oracle at a controlled `g`, while the engine path that
  produces `g` in practice is still wrong (ignored spin, momentum-free
  redshift). "Analytically validated" and "science-ready" are different
  claims — keep the report explicit about which paths earn which label.
- Freezing the comparison procedure (rows/cols, edge threshold, tolerance)
  in `NOTES.md` *before* reading the 512² GYOTO output was load-bearing: it
  let a genuine 94%/100% failure stand without room to re-interpret the
  measurement after the fact.
- Render-time attribution and reference-bank re-baseline both need a
  matched-settings/matched-build bisection, not just before/after diffing;
  otherwise a scene-authoring change (PR #405) would have been misread as a
  10x code regression.
- Do not re-bless a reference image for a path known to be geometrically
  wrong (Kerr at a=0): a passing per-channel gate on a mislabeled scene is
  not evidence of correctness. Rebaseline only after pkg281 fixes the metric.
