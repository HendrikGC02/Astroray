# pkg153 — wavefront_diff env-scene + perf gates: pre-existing FAIL on workstation main (disposition owner)

**Pillar:** 3 (GPU pipeline health / gate integrity)
**Track:** A (RTX-gated — CI is blind to every one of these gates)
**Codex-paste-ready:** no (disposition-first: decide recalibration vs real regression from the gate-failure-reviewer's evidence, then a small targeted PR either way)
**Status:** superseded — 2026-07 gate dossier is stale; the live baseline failures are owned by pkg237 (HDRI SSIM) and pkg238 (PostInit ULP) (2026-09-07 backlog triage)
**Estimated effort:** S (disposition) + unknown (if a real regression is behind it)
**Depends on:** none. **Blocks clean HW verdicts for every PR** until dispositioned — the full RTX sweep includes these gates, so every verifier run inherits the FAIL (see Interim protocol).

**Origin:** pkg141/PR #518 hardware verification (2026-07-25, RTX 5070 Ti). The verifier re-ran the failing gates on UNMODIFIED main @ `8c49bbb` with a fresh worktree `.pyd` and reproduced them bit-deterministically — pre-existing on main, not attributable to #518.

---

## Measured failures (main @ `8c49bbb`, RTX 5070 Ti, CUDA 12.8, OptiX 9.1.0)

1. `tests/wavefront_diff::test_gpu_wavefront_final_image_mean_ratio` — R-channel mean ratio ~12–15% over the 0.12 tolerance.
2. `tests/wavefront_diff::test_megakernel_open_env_scene_mean_ratio` — same signature. **Note: a megakernel test** — the common factor across the three ratio gates is the env/world scene + R channel, NOT the wavefront leg.
3. `tests/wavefront_diff::test_megakernel_world_max_bounces_env_gate` — same signature.
4. `tests/wavefront_diff::test_wavefront_contact_sheet_floor` — perf floor **0.90x vs required ≥1.30x** (the wavefront was 1.45–1.52× the megakernel on this same workstation in June).
5. `tests/test_pkg55_c5_photon_wavefront.py::test_wavefront_photon_caustic_parity` (isolated) — SSIM=-0.0000 vs gate ≥0.80, peak WF=1.208 MW=1.591; known pre-existing flake signature.

All bit-deterministic (fixed seed) and reproduced near-identically on the PR branch and on main. None of the scenes contain Disney metal.

## Candidate causes (for the gate-failure-reviewer to distinguish)

- **Stale machine-pinned thresholds/baselines from the travel-laptop round** (2026-07-18..20; memory `current-machine-rtx5070ti`: laptop-pinned observations need re-validation on the workstation; precedent `dd670b7` recorded exactly this class of machine-dependent gate drift). Most plausible for the perf floor; check whether the baseline JSON/threshold was re-pinned on the laptop.
- **A real env/world-scene R-channel regression from a recent merge window** (#497/#503 C6 ReSTIR, or the #513–#517 round). A stable per-channel ratio is the structural-bug signature (memory `mc-noise-vs-deterministic`) — if no threshold was ever re-pinned, bisect the merge window on the failing gate directly.
- **Environment/driver delta since the June workstation baselines** (CUDA 12.8-vs-12.6 on PATH, driver update). Cheap check: re-run the June-pinned refbank env scenes and compare stored numbers.
- The photon-caustic flake may be a distinct cause (it is a NEGATIVE SSIM — near-anticorrelation, not drift); disposition separately, do not force one root cause to cover all five.

## Disposition contract

**Bisect vehicle (2026-07-25): the combined pkg153+pkg155 protocol** —
`.astroray_plan/docs/pkg153-pkg155-combined-bisect-protocol-2026-07-25.md`. The
R-channel env-gate bisect shares ONE rebuild per point with pkg155's shade-reg
bisect (same #481→#524 window, same GPU). This spec owns signals 3 (R-channel
mean ratio + emitters→matte discriminator) and 4 (tables-loaded checksum) in that
protocol. Anchors carried over unchanged: #489/#500 (emitter-linked, suspect 1A),
#481 (spectral eval, suspect 1B), the a7f09d1^/41101a5^ decisive step, and #523
as a **compounding anchor only, never an origin candidate**. The photon-caustic
negative-SSIM flake is a distinct cause and is NOT part of this window bisect.

1. Consume the gate-failure-reviewer's report; convict ONE cause per gate (they need not share one).
2. If stale pins: one re-pin PR with fresh workstation measurements and the pinning provenance recorded in the test file; never widen a tolerance without a measured justification.
3. If a real regression: bisect to the merge, file a targeted fix spec, and leave the gate red and owned by that spec (never relax to green).
4. Either way, update this spec with the verdict and close.

## Interim protocol (binding for the rest of the 2026-07-24/25 run — set by the PR #518 adjudication)

Every HW verdict that hits these gates: re-run the failing gate on unmodified main @ a pinned SHA; PR-attributable failures block the PR; main-attributable failures are logged here with the repro numbers, and the PR is adjudicated on its own gates.

## Provenance

Filed by the architect during the PR #518 adjudication (2026-07-25). Full verifier evidence: pkg141 spec "Hardware verification 2026-07-25" section; verdict comment https://github.com/HendrikGC02/Astroray/pull/518#issuecomment-5071150211.

## pkg55-C7 day-arc findings (2026-07-25, RTX 5070 Ti, main @ e0185c8) — partial disposition

**Failure 4 (perf floor 0.90×): CONVICTED as measurement artifact — CLOSED.**
Median-of-5 isolated timing (GPU lock held, cool GPU, 48 C start): 1.528× @512spp
(spread 1.522–1.545), 1.539× @1024spp (spread ≤0.007 s both legs); the pytest
gate in isolation passes at 1.52× and XPASSES the 1.5× target; the full
`wavefront_diff` sweep in one process ALSO passes (xpass). The overnight 0.90×
(WF 0.647 s vs 0.356 s today; MK leg normal) was observed exactly once by the
single-sample harness during the contended overnight window, and the "rerun on
unmodified main" evidence file contains only the 3 ratio gates — the perf gate
was never re-run on main. Today's ratio is the all-time high of the recorded
history (1.38→1.46→1.50→1.53), so there is no regression to bisect. Fix shipped
with C7: the perf harness is median-of-N and the megakernel comparator is pinned
(`benchmarks/wavefront/megakernel_final_2026-07-25.json`) before deletion.
Note: the "wavefront accreted feature cost" hypothesis (2A) is real but applies
to BOTH pipelines — see pkg155 (GPU absolute ~5× slowdown since 2026-05); it
does not move the WF/MK ratio.

**Failures 1–3 (R-channel ratio drift): still OPEN, quarantined per the interim
protocol. New discriminator evidence:** re-rendering the open-env scene with
the emitters replaced by matte surfaces (env-only illumination), the MK/CPU
ratio moves [1.148, 1.007, 1.070] → [1.102, 0.996, 1.049]. ~4.6 pp of the
~5.7 pp R drift is therefore emitter-linked (the scene's warm [1.0, 0.8, 0.5]
emissive sphere) — this tilts toward the #489/#500 light-energy arc (suspect
1A) — but no June env-only pin exists, so #481 (spectral tables, suspect 1B) is
not excluded for the residual; the a7f09d1^/41101a5^ bisect remains the
decisive step. Reproduced today's failing ratios exactly on e0185c8 before any
C7 change ([1.148, 1.007, 1.069] open-env; [1.133, 1.008, 1.046] wmb=0).
C7 disposition of the gates themselves: the two megakernel-named env gates are
retargeted at the wavefront (plan §6-R10) with thresholds unchanged and remain
red-and-quarantined under this spec; `test_gpu_wavefront_final_image_mean_ratio`
likewise stays red and pkg153-owned.

**Post-#523 data point (C7 rebase, 2026-07-25):** after PR #523 (pkg152 gpu_disney_eval compensation-table mirror) the wavefront final-image R ratio moved [1.153, 1.007, 1.068] -> **[1.191, 1.007, 1.072]** on the same scene/seed (CPU oracle unchanged). A materials-eval PR moving the R residual by +3.8pp is direct evidence the drift lives in the GPU material/spectral eval arc (suspect 1B class) at least in part — useful bisect anchor. Quarantine unchanged.

**pkg168 cross-link (2026-08-02):** pkg156's residual decomposition (PR #537
round) independently convicted a CPU-`RGBAlbedoSpectrum`/`RGBIlluminant`-vs-
GPU-tables upsampling parity gap as its remaining ~1.4% channel-asymmetric
residual — the suspect-1B mechanism class. **pkg168**
(`pkg168-rgb-spectral-upsampling-parity.md`) now owns that fix; its Step-1
unit-level A/B and any fix are bisect anchors for this spec's failures 1–3.
Ownership unchanged: these gates stay quarantined and pkg153-owned (the
emitter-linked ~4.6 pp discriminator still points at a separate co-mechanism in
the light-energy arc), and this spec closes only via its own disposition
contract after consuming pkg168's result.

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: open — investigation IN FLIGHT (gate-failure-reviewer dispatched 2026-07-25 by the team-lead; this spec is the formal owner of the failures and receives its findings). **PRIORITY NOTE 2026-08-03 (owner-endorsed):** any remainder after the reviewer's disposition is sub-percent parity tail — DE-PRIORITIZED below the Integration Milestone alongside pkg173, unless the paper requires bit-level parity. The reviewer finishes its disposition; no new fix packages spawn from it ahead of the milestone. A disposition PR may ship during the 2026-07-24/25 overnight run ONLY if the root cause is proven to be stale machine-pinned baselines/thresholds (a re-pin with workstation evidence); if a real rendering regression is convicted, file a targeted fix spec — do NOT blind-fix or relax gates without conviction.
