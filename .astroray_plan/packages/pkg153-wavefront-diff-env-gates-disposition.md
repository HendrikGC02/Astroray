# pkg153 — wavefront_diff env-scene + perf gates: pre-existing FAIL on workstation main (disposition owner)

**Pillar:** 3 (GPU pipeline health / gate integrity)
**Track:** A (RTX-gated — CI is blind to every one of these gates)
**Codex-paste-ready:** no (disposition-first: decide recalibration vs real regression from the gate-failure-reviewer's evidence, then a small targeted PR either way)
**Status:** open — investigation IN FLIGHT (gate-failure-reviewer dispatched 2026-07-25 by the team-lead; this spec is the formal owner of the failures and receives its findings). A disposition PR may ship during the 2026-07-24/25 overnight run ONLY if the root cause is proven to be stale machine-pinned baselines/thresholds (a re-pin with workstation evidence); if a real rendering regression is convicted, file a targeted fix spec — do NOT blind-fix or relax gates without conviction.
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

1. Consume the gate-failure-reviewer's report; convict ONE cause per gate (they need not share one).
2. If stale pins: one re-pin PR with fresh workstation measurements and the pinning provenance recorded in the test file; never widen a tolerance without a measured justification.
3. If a real regression: bisect to the merge, file a targeted fix spec, and leave the gate red and owned by that spec (never relax to green).
4. Either way, update this spec with the verdict and close.

## Interim protocol (binding for the rest of the 2026-07-24/25 run — set by the PR #518 adjudication)

Every HW verdict that hits these gates: re-run the failing gate on unmodified main @ a pinned SHA; PR-attributable failures block the PR; main-attributable failures are logged here with the repro numbers, and the PR is adjudicated on its own gates.

## Provenance

Filed by the architect during the PR #518 adjudication (2026-07-25). Full verifier evidence: pkg141 spec "Hardware verification 2026-07-25" section; verdict comment https://github.com/HendrikGC02/Astroray/pull/518#issuecomment-5071150211.
