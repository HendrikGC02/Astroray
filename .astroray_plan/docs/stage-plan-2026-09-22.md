# Stage plan to the north star — 2026-09-22

Planning session (Claude Fable 5.1 lead + GPT-6 Astra co-planner, Luna fact-checks,
Codex Terra spec reviews). Supersedes §4 "Sequencing" of
`north-star-and-integration-gate-2026-09-07.md`; the north star (§1) and the exit gate
(§2) of that document stay authoritative and are imported here in full (viewport p95/p99,
repetitions, cancellation thresholds, native-panel activation, the four mandatory shader
families). Facts are sourced in `reports/2026-09-22-planning/` (fact sheets, Astra turns
1–3, Terra reviews). Revision 2 after Astra turn 2 (REVISE → exits made executable).

## 0. Owner decisions recorded today

- Agent policy: Opus 5 is the Claude judgment tier; DeepSeek V4.1 Flash is the open-model
  implement + grunt primary; Codex Terra reviews and implements bounded work (no cap);
  Astra only in this session (≤4 turns) and the render-speed session; Fable subagents
  stay banned; Haiku summarises short files; project index before grep. (CLAUDE.md §5.)
- Thaw rule: the measurable gate (a)–(f) stays the formal trigger. Pillar 4 spec
  amendment and ONE bounded groundwork lane may run now, in overlap with the wrap-up.
- Pillar 4 first stage builds BOTH the emission-nebula track and the relativistic
  lensing / HMXB track.
- Outputs land directly on main (docs and policy only).

## 1. Course check (Astra verdict: ON-COURSE)

The two-track science destination is intact and the integration work of the last six
weeks (volumes, observer fix, env NEE, viewport worker, lamp radiometry, op-VM) serves
it. The drift is procedural: packages are marked done when implemented rather than
validated, and the exit gate has never been scored with its own ratified instruments.
Corrections adopted from Astra turn 1 (each verified in code):

| Claim in circulation | Verified fact |
|---|---|
| pkg107 is the cheapest Pillar 4 package to thaw | Already implemented (`black_hole.h:214`, `blender_module.cpp:1530`); status reconciled to done. |
| pkg259 corpus is done | Assets done; Phase 4 (`coverage_report.py`, harness join) never built — gate (b) cannot be scored. |
| Gate (c) trio is undecided | Owner chose gallery / workshop / terrace-with-hair on 2026-09-08 (`reference-corpus-design-2026-09.md` answer 9). |
| GR path renders correctly | Renders stably (pHash 0, shadow + ring present) but `diskEmissionSpectral` evaluates B(λ_obs,T)·g⁴ with no wavelength shift and a hard clamp at 20 — spectra are not yet trustworthy. |

## 2. Exit gate scoreboard (2026-09-22)

| Row | State | Instrument that must exist | Owner |
|---|---|---|---|
| (a) viewport latency | AMBER: real-Blender p95 64–224 ms on one config; #721/#854/#855/#857 open | end-to-end table: event → first CORRECT presented frame p95/p99, cancel ack, stale-frame exclusion, both pinned scenes × camera/material edits, real Blender session | pkg278 + Stage 0c |
| (b) socket coverage | UNMEASURED: raw 403/586 DROPPED-SILENT; weighted score never computed | `coverage_report.py` per backend: S_b = Σ min(nᵢ,3)·sᵢ,b / Σ min(nᵢ,3); frozen manifest before scoring; exercised sockets from node trees; zero silent drops as a separate Boolean; #823 first | pkg278 |
| (c) reference trio parity | AMBER: assets exist, no consolidated CPU+GPU report; trio = gallery/workshop/terrace-with-hair | one parity report with pinned SHAs, ±5 % ROI ratio, SSIM ≥ 0.95, non-vacuity checks | pkg278 |
| (d) native adaptive + denoise | AMBER: landed both backends; no output-effect smoke | one smoke: sample-count AOV differs and flat-region noise falls at a declared budget, checked against a converged reference with mean-error and detail-preservation checks; CPU + GPU | pkg278 |
| (e) zero high-severity addon bugs | RED: #721 open P1; #859/#846/#845/#833/#860 unrated | independent triage of the LIVE open-issue population under the published rubric, not by label | pkg278 + Stage 0b |
| (f) one-command install | AMBER: dev loop one-command; no clean-machine artifact | fresh-profile, no-toolchain ZIP install + F12 with evidence, in its own execution slot | pkg278 |

Baseline hygiene that is NOT a thaw condition: reference bank `cornell-mini` self-test
failing since 2026-09-06; GR bank scenes fail SSIM only (0.93 / 0.85 vs 0.96, identical
to 2026-09-03, visually indistinguishable). Reference-bank repair is attributed and
independently approved (pkg280 Phase 4); it never redefines a gate.

## 3. Stages

Each stage lists steps, the verifiable exit, and the owning package. "Batch" means one
worktree / build / RTX sweep / CI cycle with per-item tests (owner 2026-09-11). Every
issue dispatched in Stage 0 carries, before dispatch, a named observable, fixture,
threshold and evidence owner; "no new xfails" is necessary, never sufficient.

### Stage 0 — Wrap-up: make the gate green and measurable (now)

**Exit:** every row of §2 GREEN under the full ratified gate, from its own instrument,
recorded in one acceptance manifest (scene SHAs, build id, backend, settings, metrics,
thresholds, evidence paths), with GPU parity, the real-Blender viewport table and the
clean-machine install each produced in their own execution slot.

- 0a **Instrument the gate first** (pkg278; CPU-only for the scripts, separate RTX and
  clean-machine slots for the measurements). #823 lands before gate (b) is scored.
  Exit of 0a: validated instruments, reproducible commands and evidence for every row;
  measured RED is an acceptable 0a result; rows without an instrument stay UNMEASURED.
- 0b **Light-transport correctness batch:** #859 (GPU loses the sun with a mesh emitter),
  #851/#763 (light-tree importance clamp; test a temporary default rollback before new
  samplers), #852 (area spread), #860/#833/#842 (mesh-bounded volumes), #845 (ortho /
  panoramic cameras). Exit: each issue's named observable inside its threshold with
  evidence; independent severity re-rating under the rubric.
- 0c **Viewport batch:** #857 render border, #854/#855/#856 measurements, then #849
  in-place updates only to the extent the gate (a) table demands; real-navigation owner
  try-out (#858) before any default flip; close #721 on the measured table.
- 0d **Coverage batch:** #846 silent op-VM drops (a silent drop is a gate violation),
  pkg277 (#822), #847. Nodes outside the frozen corpus that neither drop silently nor
  block 95 % can slide.
- 0e **Speed / noise session with Astra** (owner-owed, starts as soon as 0a has a
  manifest): equal-spp AND equal-time error vs Cycles, time-to-target-error; attribute
  export/upload, tracing, presentation and denoise costs separately; light-tree
  regression first, new samplers only after attribution. pkg262 rows are the A/B record.

### Stage 1 — Pillar 4 groundwork, overlapping Stage 0 (allowed by the thaw rule)

Three separate exits:

- 1a **Spec amendment (this session):** the named set in §4 is lint-clean, Terra-reviewed
  and current. Exit: Terra verdicts recorded per spec; no open "REVISE".
- 1b **The one bounded groundwork lane = pkg280 GR transfer & reference audit** (CPU):
  mandatory analytic core (invariant transfer in both domains: I_ν,obs = g³ I_ν,em(ν/g),
  I_λ,obs = g⁵ I_λ,em(gλ); monochromatic-shift and bolometric-scaling tests; clamp removed
  or justified) plus ONE compatible external comparison (GYOTO or ipole, matched model and
  normalisation); bounded attribution of the ~10× GR render-time growth (attribution
  only, recovery is not an exit); bank re-baseline with attribution and independent
  sign-off. Exit: the report lists validated-for-science paths vs unresolved paths; only
  validated paths feed Stage 2. No GPU GR work enters through this lane.
- 1c **Science-foundational lane (behind gate-critical work):** pkg251 → pkg243 raw band
  output with provenance. Exit: pkg243 acceptance met; it is an explicit prerequisite for
  every quantitative Stage 2 output.

### Stage 2 — Pillar 4 thaw round 1 (after Stage 0 exit; two tracks in parallel)

**Track N — emission nebula.** pkg45 (validated line tables, physical contract) →
pkg46 (line emission inside the existing volume transport; dust scattering staged
separately) → Blender end-to-end quantitative render.
First science deliverable: a dust-free Case-B hydrogen slab at Tₑ = 10⁴ K,
nₑ = 100 cm⁻³; measured quantity = integrated energy radiance per line; rendered Hα/Hβ
equals the pinned pkg45 table row (Storey & Hummer 1995, ≈ 2.86) within 2 % with ≥ 5
seeds and a 95 % CI inside the tolerance; independent single-line normalisation check
I_line = j_line·L (solid-angle convention explicit); linear in path length in the
optically-thin Balmer regime.

**Track L — lensing / HMXB.** pkg280 report → pkg50 weak-field lensing and pkg279 HMXB
Phase 1 (independent of each other; prescribed orbital geometry + explicit emission
model; no hydrodynamics).
First science deliverables: (L1) deflection vs impact parameter with Q = α·b·c²/(GM),
|Q/4 − 1| ≤ 0.01 for b ≥ 1000 r_g (the second-order term ≈ 2.945 r_g/b is budgeted), α in
radians, b the asymptotic impact parameter, validated on rendered image positions,
magnification/Jacobian and surface brightness against geodesic deflection, never against
the pass's own formula; (L2) a normalised HMXB orbital light curve whose eclipse duration
fraction matches f = arcsin(R★/a)/π (edge-on, spherical donor, point emitter) within 2 %
RELATIVE error, with phase-resolution convergence, ingress/egress phases, eclipse depth
and a non-eclipsing control. L2 validates occultation geometry only, not an HMXB spectrum.

**Exit:** both deliverable figures produced from Blender-driven renders, numbers inside
their tolerances on the CPU oracle, plus one showcase render per track that passed the
qualitative inspection required by CLAUDE.md §5c.

### Stage 3 — Instrument pipeline and simulation ingest

- Physical normalisation bridge first: pkg243 Phase 2 fixes scene-length units, observer
  pixel solid angle and physical radiance normalisation; exposure and collecting area
  cannot calibrate an arbitrary scalar.
- pkg51 (design merges pkg133; separate bounded implementation phases): trusted spectral
  output → response-weighted accumulation (QE and throughput kept separate) → per-band
  chromatic PSF applied BEFORE spectral integration with a spectral-bin convergence test →
  detector statistics distinguishing incident photons, detected electrons and ADU.
  μ_e(x) = t·A·Ω_pix ∫ [I_λ ∗ P_λ](x)·T(λ)·QE(λ)·λ/(hc) dλ.
- pkg48/49 ingest as conversion tooling (dense arrays already reach the engine through
  `set_volume_grid`; Blender-native OpenVDB): units, transforms, field provenance, mass
  conservation and resolution convergence. An engine-side reader needs a demonstrated gap.
- #799 Phase 2 per-wavelength Nishita sky (owner: stretch goal).

**Exit:** ensemble statistics, not one image: over ≥ 20 realisations of the Track N slab
through a declared instrument, the electron histogram matches the declared
Poisson + read + dark model (χ²/dof in [0.8, 1.25]) and the Hα/Hβ recovery holds as a
mean with CI.

### Stage 4 — Research-grade validation and figures

Validation lives inside each package from Stage 2 on; this stage extends it to research
use with a bounded matrix: ipole/GYOTO frames across ≥ 3 spins × ≥ 2 inclinations,
line-ratio grids across ≥ 3 (Tₑ, nₑ) points, journal-figure production (pkg130 light
groups, per-mechanism AOVs). Deferred candidates (diffraction grating #141, cluster/NFW
lensing) only when a science case names them.
**Exit:** a reproducible figure bundle (one script, pinned inputs) whose every panel
carries its reference value and residual.

### Stage 5 — Platform (conditional, unscheduled)

Hydra/USD delegate (#398) only if a second real DCC caller appears.

## 4. Pillar 4 package disposition (Stage 1a, executed this session)

| Package | Disposition | Rewrite content |
|---|---|---|
| pkg45 CLOUDY tables | keep, rewrite the data contract | integrated-line vs per-λ arrays, units, solid-angle convention flag, air/vacuum λ, Case-B regime, Storey & Hummer 1995 pinned, no extrapolation, grid on 360–830 nm |
| pkg46 HII region + #144 | merge, rewrite on existing volume transport | line emission through `GridMedium` + pkg270 spectral emission; unbiased line-mixture MIS with an unbiasedness test; single-line normalisation check; dust scattering Phase 2; Case-B slab deliverable |
| pkg48 HDF5/NumPy loader | rewrite as conversion tooling | retire bespoke `DensityGrid`; provenance + resampling-loss evidence |
| pkg49 SPH-to-volume | rewrite after pkg48 | Wendland C4 stays; mass conservation + resolution convergence |
| pkg50 weak lensing | keep, strengthen model + validation | independent observable (geodesic deflection, image positions, Jacobian, surface brightness), b ≥ 1000 r_g budget; CPU pass |
| pkg51 telescope + pkg133 SRF | one design, separate implementation phases | normalisation bridge, chromatic-before-integration, photons/electrons/ADU, ensemble acceptance |
| pkg107 r_obs_M | done (reconciled) | verification folded into pkg280 |
| pkg278 exit-gate instrumentation | NEW | §3 Stage 0a; omission-resistant scorer rules |
| pkg279 HMXB Phase 1 | NEW, bounded | occultation geometry + light-curve observable, analytic control |
| pkg280 GR transfer & reference audit | NEW, the groundwork lane | §3 Stage 1b |
| Grating #141, cluster lensing | deferred candidates | no spec until a science case names them |

Every rewrite carries an independent reference observable: a literature number for the
science packages, conservation and convergence for the conversion tooling.

## 5. Risks (Astra + lead)

1. False green: stale statuses, missing instruments, label-dependent triage. Mitigation: pkg278 manifest; live-population triage.
2. Biased coverage: a corpus authored around supported features. Mitigation: frozen manifest before scoring, exercised-socket denominator, provisional score until the owner ratifies (§6).
3. Spectral/science mismatch: line sampling, GR frequency transfer, clamps, normalisation preserve pretty images while corrupting observables. Mitigation: pkg280 first; independent single-line and monochromatic-shift checks; normalisation bridge before counts.
4. Unattributed performance: the 10× GR slowdown and the Cycles noise gap. Mitigation: matched-build attribution in pkg280 and Stage 0e.
5. Scope: two science tracks + instruments + ingest on one RTX lane. Mitigation: Stage 2 runs only after Stage 0 exit; Stage 3 waits for Stage 2 exit.

## 6. Open owner decision

Ratify that the frozen nine-scene corpus (with disclosed omissions and independent
exercised-socket checks) is the gate (b) population. Until ratified, pkg278 publishes the
nine-scene score as PROVISIONAL; the original "~50 scenes" population was never frozen,
so its score is UNDEFINED rather than computed.
