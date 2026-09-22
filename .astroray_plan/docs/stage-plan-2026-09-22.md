# Stage plan to the north star — 2026-09-22

Planning session (Claude Fable 5.1 lead + GPT-6 Astra co-planner, Luna fact-checks).
Supersedes §4 "Sequencing" of `north-star-and-integration-gate-2026-09-07.md`; the north
star (§1) and the exit gate (§2) of that document stay authoritative. Facts below are
sourced in the session fact sheets (`state_facts.md`, `p4_audit.md`, Astra turn 1/2, all
in `reports/2026-09-22-planning/`).

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
weeks (volumes, observer fix, env NEE, viewport worker, lamp radiometry, op-VM) all
serves it. The drift is procedural, not directional: packages are marked done when
implemented rather than validated, and the exit gate has never been scored with its own
ratified instruments. Corrections adopted from Astra turn 1 (each verified in code):

| Claim in circulation | Verified fact |
|---|---|
| pkg107 is the cheapest Pillar 4 package to thaw | Already implemented (`black_hole.h:214`, `blender_module.cpp:1530`); status reconciled to done. |
| pkg259 corpus is done | Assets done; Phase 4 (`coverage_report.py`, harness join) never built — gate (b) cannot be scored. |
| Gate (c) trio is undecided | Owner chose gallery / workshop / terrace-with-hair on 2026-09-08 (`reference-corpus-design-2026-09.md` answer 9). |
| GR path renders correctly | Renders stably (pHash 0, shadow + ring present) but `diskEmissionSpectral` evaluates B(λ_obs,T)·g⁴ with no wavelength shift and a hard clamp at 20 — spectra are not yet trustworthy. |

## 2. Exit gate scoreboard (2026-09-22)

| Row | State | Instrument that must exist | Owner |
|---|---|---|---|
| (a) viewport latency | AMBER: real-Blender p95 64–224 ms on one config; #721/#854/#855/#857 open | end-to-end table: event → first CORRECT presented frame, cancel ack, stale-frame exclusion, both pinned scenes × camera/material edits | pkg278 + Stage 0c |
| (b) socket coverage | UNMEASURED: raw 403/586 DROPPED-SILENT; weighted score never computed | `coverage_report.py`: Σwᵢsᵢ/Σwᵢ, wᵢ = min(distinct scenes, 3); exercised sockets, not manifest labels; silent drops reported separately; #823 scanner fix first | pkg278 |
| (c) reference trio parity | AMBER: assets exist, no consolidated CPU+GPU report; trio = gallery/workshop/terrace-with-hair | one parity report with pinned SHAs, ±5 % ROI ratio, SSIM ≥ 0.95, non-vacuity checks | pkg278 |
| (d) native adaptive + denoise | AMBER: landed both backends; no output-effect smoke | one smoke: sample-count AOV differs and flat-region noise falls at a declared budget; denoise residual falls; CPU + GPU | pkg278 |
| (e) zero high-severity addon bugs | RED: #721 open P1; #859/#846/#845/#833/#860 unrated | independent triage of all open issues under the published rubric, not by label | pkg278 + Stage 0b |
| (f) one-command install | AMBER: dev loop one-command; no clean-machine artifact | fresh-profile, no-toolchain ZIP install + F12 with evidence | pkg278 |

Baseline hygiene that is NOT a thaw condition unless adopted: reference bank `cornell-mini`
self-test failing since 2026-09-06; GR bank scenes fail SSIM only (0.93 / 0.85 vs 0.96,
identical to 2026-09-03, visually indistinguishable).

## 3. Stages

Each stage lists steps, the verifiable exit, and the package that owns it. "Batch" means
one worktree / build / RTX sweep / CI cycle with per-item tests (owner 2026-09-11).

### Stage 0 — Wrap-up: make the gate green and measurable (now)

**Exit:** every row of §2 GREEN from its own instrument, recorded in one acceptance
manifest (scene SHAs, build id, backend, settings, metrics, thresholds, evidence paths).

- 0a **Instrument the gate first** (pkg278, CPU-only lane, dispatch first): acceptance
  manifest schema; `coverage_report.py` + weighted scorer (after the #823 scanner fix);
  corpus-trio parity report; gate (d) smoke; gate (f) clean-machine run; gate (e) rubric
  triage of all 33 open issues; reference-bank re-baseline (per-channel mean-ratio, keep
  SSIM diagnostic). Exit: a scoreboard with numbers in every row.
- 0b **Light-transport correctness batch:** #859 (GPU loses the sun with a mesh emitter),
  #851/#763 (light-tree importance clamp; test a temporary default rollback before new
  samplers), #852 (area spread), #860/#833/#842 (mesh-bounded volumes), #845 (ortho /
  panoramic cameras). Exit: each issue's measured number inside its gate; no new xfails.
- 0c **Viewport batch:** #857 render border, #854/#855/#856 measurements, then #849
  in-place updates only to the extent the gate (a) table demands; real-navigation owner
  try-out (#858) before any default flip; close #721 on the measured table.
- 0d **Coverage batch:** #823 scanner (gate (b) validity), #846 silent op-VM drops (a
  silent drop is a gate violation), pkg277 (#822), #847. Nodes outside the frozen corpus
  that neither drop silently nor block 95 % can slide.
- 0e **Speed / noise session with Astra** (owner-owed, starts as soon as 0a has a
  manifest): equal-spp AND equal-time error vs Cycles, time-to-target-error; attribute
  export/upload, tracing, presentation and denoise costs separately; light-tree
  regression first, new samplers only after attribution. Uses pkg262 rows as the A/B
  record.

### Stage 1 — Pillar 4 groundwork, overlapping Stage 0 (allowed by the thaw rule)

**Exit:** every Pillar 4 spec lint-clean and current; one evidence report on the GR path;
the band-output contract landed.

- 1a **Spec amendment (this session):** see §4. All rewrites carry an explicit
  first-science-deliverable with a literature number.
- 1b **The one bounded groundwork lane = pkg280 GR transfer & reference audit** (CPU):
  invariant-intensity transfer (I_ν/ν³, wavelength shift by g) in `diskEmissionSpectral`
  and the ADAF/synchrotron paths, removal or justification of the emission clamp,
  attribution of the ~10× GR render-time growth (2 s → 20 s per bank scene) on matched
  settings, GYOTO/ipole cross-check of one Kerr frame, bank scenes green. Fixed stop: an
  evidence report plus scoped follow-ups. No GPU GR work enters through this lane.
- 1c **Science-foundational lane (behind gate-critical work):** pkg251 → pkg243 raw band
  output with provenance. Both nebula and instrument deliverables depend on it.

### Stage 2 — Pillar 4 thaw round 1 (after Stage 0 exit; two tracks in parallel)

**Track N — emission nebula.** pkg45 (validated line tables, physical contract) →
pkg46 (line emission inside the existing volume transport; dust scattering staged
separately) → Blender end-to-end quantitative render.
First science deliverable: a dust-free Case-B hydrogen slab at Tₑ = 10⁴ K,
nₑ = 100 cm⁻³ whose rendered integrated Hα/Hβ ≈ 2.86 agrees with the pinned table within
2 % (with stated MC uncertainty) and scales linearly with path length.

**Track L — lensing / HMXB.** pkg280 report → pkg50 weak-field lensing → pkg279 HMXB
Phase 1 (prescribed orbital geometry + explicit emission model; no hydrodynamics).
First science deliverables: (L1) deflection vs impact parameter with α·b·c²/(GM) → 4 in the
weak-field limit within ≤ 1 % over a declared validity range, plus image-geometry and
surface-brightness checks; (L2) a normalised HMXB orbital light curve reproducing the
eclipse/phase shape of a prescribed geometry before any X-ray microphysics is chosen.

**Exit:** both deliverable figures produced from Blender-driven renders, numbers inside
their tolerances, CPU oracle; one showcase render per track.

### Stage 3 — Instrument pipeline and simulation ingest

- pkg251/pkg243 (trusted spectral output) → pkg133 response-weighted accumulation (QE ×
  filter SRF) → pkg51 chromatic optics (per-band PSF, spectral information preserved per
  band, not recovered from one broadband image) → detector statistics (collecting area,
  pixel solid angle, exposure, photon-energy conversion, Poisson/read/dark). One design
  document, separate bounded implementation packages.
- pkg48/49 ingest: dense NumPy density/temperature arrays already reach the engine
  (`set_volume_grid`); the packages become conversion tooling (HDF5/yt/SPH → arrays or
  `.vdb`) with units, transforms, field provenance, conservation and
  resolution-convergence evidence. An engine-side reader needs a demonstrated gap.
- #799 Phase 2 per-wavelength Nishita sky (owner: stretch goal, not a priority).

**Exit:** one synthetic observation of the Track N nebula through a declared instrument
with a photon-count image whose statistics match the declared exposure.

### Stage 4 — Research-grade validation and figures

Validation lives inside each package from Stage 2 on; this stage extends it to research
use: ipole/GYOTO frame comparison across spin and inclination, published line-ratio
grids, journal-figure production (pkg130 light groups, per-mechanism AOVs), deferred
candidates (diffraction grating #141, cluster/NFW lensing) only when a science case names
them.

### Stage 5 — Platform (conditional)

Hydra/USD delegate (#398) only if a second real DCC caller appears.

## 4. Pillar 4 package disposition (Stage 1a, executed this session)

| Package | Disposition | Rewrite content |
|---|---|---|
| pkg45 CLOUDY tables | keep, rewrite the data contract | integrated-line vs per-λ quantities, units, solid-angle normalisation, air/vacuum λ, abundance + ionising-spectrum assumptions, interpolation validity, wavelength grid tied to `kLambdaMin/Max` 360–830 nm (CIE 1931 is the observer, not the emissivity grid) |
| pkg46 HII region + #144 | merge, rewrite on existing volume transport | line emission through `GridMedium` + pkg270 spectral emission; explicit unbiased line-sampling strategy (narrow lines vs hero-wavelength MIS) with energy-conservation tests; dust scattering as a later phase; Case-B slab deliverable |
| pkg48 HDF5/NumPy loader | rewrite as conversion tooling | retire bespoke `DensityGrid`; use `set_volume_grid` / Blender-native OpenVDB; provenance + resampling-loss evidence |
| pkg49 SPH-to-volume | rewrite after pkg48 | Wendland C4 kernel stays; output retargeted; mass conservation + resolution convergence |
| pkg50 weak lensing | keep, strengthen model + validation | deflection-vs-b figure, image geometry, surface-brightness conservation; CPU pass |
| pkg51 telescope + pkg133 SRF | one design, separate implementations | dependency order per Stage 3; photon-count model beyond SRF weighting; gated on pkg243 |
| pkg107 r_obs_M | done (reconciled) | verification folded into pkg280 |
| pkg278 exit-gate instrumentation | NEW | §3 Stage 0a |
| pkg279 HMXB Phase 1 | NEW, bounded | orbital geometry + light-curve observable |
| pkg280 GR transfer & reference audit | NEW, the groundwork lane | §3 Stage 1b |
| Grating #141, cluster lensing | deferred candidates | no spec until a science case names them |

## 5. Risks (Astra + lead)

1. False green: stale statuses, missing instruments, label-dependent triage. Mitigation: pkg278 manifest.
2. Biased coverage: a corpus authored around supported features. Mitigation: exercised-socket counting, disclosed omissions, owner ratification (§6).
3. Spectral/science mismatch: line sampling, GR frequency transfer, clamps preserve pretty images while corrupting observables. Mitigation: pkg280 first, literature numbers in every science deliverable.
4. Unattributed performance: the 10× GR slowdown and the Cycles noise gap. Mitigation: matched-build attribution in pkg280 and Stage 0e.
5. Scope: two science tracks + instruments + ingest on one RTX lane. Mitigation: Stage 2 runs only after Stage 0 exit; Stage 3 waits for Stage 2 exit.

## 6. Open owner decision

Ratify that the frozen nine-scene corpus (with disclosed omissions and independent
exercised-socket checks) replaces the original "~50 Blender scenes" population for gate
(b). Until ratified, pkg278 scores both and reports the difference.
