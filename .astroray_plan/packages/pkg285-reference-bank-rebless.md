# pkg285 — Reference bank re-bless on the corrected engine (#898)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h) + one GPU-lock render window
**Depends on:** pkg280, pkg286

---

## Goal

Before: 13 bank scenes, references blessed 2026-05 on an engine with the W-1
pixel mapping (#845), the light-tree bias (#851), the clamp bounce error
(#860), the D⁴ jet transfer (pkg283) and the old photon scale (#914); five
scenes fail on main with references the lead calls visually identical, and two
gates (ADAF pHash 20 > 18, jet `bright_coverage` 0.0759 < 0.08) are stale
calibrations. After: every scene has a reference rendered on the corrected
engine, an attribution note (W shift vs physics) per scene, gates that are
either MC-robust (per-ROI mean ratio) or explicitly structural (dark_disk,
bright_coverage) with re-derived thresholds, and a `blessed_on` record.

---

## Context

pkg280 Phase 4 assigned the re-bless; Batch U (#893) then moved pixel mapping
and transport together, so the deltas need attribution before blessing (else a
re-bless could encode a regression). Owner 2026-09-26: tests calibrated on a
broken engine are corrected, never kept. The caustic scenes (prism-*, sms-*,
glass-*) depend on the photon scale, which pkg286 changes; bless those after it
lands or the bank is re-blessed twice.

---

## Evidence

- 2026-09-25 (#898): batchU vs main — gr-schwarzschild pHash 0 → 16 (thr 12), sms-reflective-metal-sphere 12 → 18 (thr 16); cornell-mini, prism SSIM, gr SSIM already fail on main.
- 2026-09-26: ADAF pHash 20 > 18 and jet bright_coverage 0.0759 < 0.08 fail before and after pkg283 → stale calibration.
- 2026-09-26: gr-kerr re-blessed in Batch Z (Bardeen D, 89/33 px vs GYOTO 87/34); pkg281 done.

---

## Reference

- `benchmarks/reference_bank/runner.py` (`--bless`, `compute_channel_mean_ratio`), `metrics/`, `scenes/*/gates.toml`.
- `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md` Phase 4; `pkg104-visual-reference-bank.md`.
- GYOTO 2.0.2 fixture (WSL `/home/hgcom/pkg280-external`) for the GR scenes' independent check.
- Memory: `ssim-wrong-gate-for-independent-rng`, `ssim-gate-baseline-can-encode-a-bug`, `verify-attribution-with-a-baseline-build`.

---

## Prerequisites

- [ ] Baseline build of main before Batch U (`Astroray-pkg280-may-baseline` or a fresh worktree at be340452) available for attribution renders.
- [ ] pkg286 merged before Phase 2 (caustic scenes).
- [ ] GPU lock window for the CPU bank (~6 min) plus GPU legs where a scene has one.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_bank/ATTRIBUTION-2026-09.md` | Per scene: reference vs main vs baseline deltas, which change moved it (W shift / #851 / #860 / pkg283 / pkg286), sign-off image links. |
| `benchmarks/reference_bank/metrics/roi_ratio.py` | Per-ROI per-channel mean ratio gate (thin wrapper over `runner.compute_channel_mean_ratio`) usable from `gates.toml`. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_bank/scenes/adaf-sgrA-faceon/gates.toml` | (and the other 12 scenes' `gates.toml`) Replace SSIM gates with `roi_ratio` (tolerance from 3 seeds); keep `dark_disk`/`bright_coverage`/`hue_spread` with thresholds re-derived from the new reference (threshold = measured × 0.9 for `ge`, /0.9 for `le`); drop pHash where the scene is noise-limited (cornell-mini, prism-*, sms-*), keep it for GR silhouettes. Add `blessed_on`. |
| `benchmarks/reference_bank/scenes/adaf-sgrA-faceon/reference.png` | (and the other 12) Re-blessed on the merge build (canonical MSVC/NMake `build_cuda`). |
| `benchmarks/reference_bank/scenes/adaf-sgrA-faceon/notes.md` | (and the other 12) One line: what changed and why the new image is right. |
| `benchmarks/reference_bank/README.md` | Status table + the re-bless rule (same as pkg284). |
| `tests/test_reference_bank_smoke.py` | Smoke stays cornell-mini; add a `roi_ratio` self-test. |

### Key design decisions

- **Attribute before blessing.** Render each scene on baseline (be340452), main, and the candidate; a scene may be re-blessed only when its delta is explained by a landed, cited fix. Unexplained deltas become issues, not references.
- **Two phases:** Phase 1 now — GR (schwarzschild, kerr, adaf, jet), cornell-mini, disney-sweep. Phase 2 after pkg286 — prism-bk7/sf11, prism-tilted, sms-*, glass-*.
- **Gate choice:** structural metrics stay because those scenes are Astroray-only (no Cycles reference); MC-noisy scenes move to per-ROI ratios. Thresholds are derived from the blessed render, not typed.
- **Independent sign-off:** a Sonnet or Terra reviewer reads the side-by-side PNGs and the attribution note before `--bless` runs (pkg280 Phase 4 wording).

---

## Acceptance criteria

- [ ] `python -m benchmarks.reference_bank.runner` exits 0 on the merge build; `history.csv` shows 13/13.
- [ ] `ATTRIBUTION-2026-09.md` names a landed PR for every scene whose reference changed, with baseline/main/candidate numbers.
- [ ] No `gates.toml` keeps an SSIM gate on a noise-limited scene; every threshold has a derivation line.
- [ ] GR scenes still pass their GYOTO fixture checks (pkg280) after re-bless.

---

## Non-goals

- Do not add scenes (pkg284 owns new parity scenes).
- Do not change engine code; if attribution finds a regression, file it and leave that scene's reference untouched.
- Do not bless caustic scenes before pkg286.

---

## Progress

- [ ] Phase 1: baseline/main/candidate renders + attribution, six scenes re-blessed.
- [ ] Phase 2: seven caustic scenes after pkg286.

---

## Lessons

*(Fill in after the package is done.)*
