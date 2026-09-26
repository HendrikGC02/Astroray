# GR thin-disk invariant transfer — Research

## Four numbers (fixed stop)

| # | Quantity | Result |
|---|---|---|
| 1 | Invariance residual | `2.41577546934435e-5` max spectral relative residual; `0.0033140826922287703` max bin residual; bolometric error `8.282559041994375e-5`; external-control ratio/`g⁴` error `8.946660117103988e-5` — all ≤ 1 % at externally measured `g = 0.8205396856615398` (Checkpoint 2026-09-24 below). PASS at this external `g`; not a claim about Astroray's own geodesics or redshift. |
| 2 | Render-time delta (~10x growth) | Attributed: scene-setting delta (same build) **15.45x–15.73x**; build/code delta (same settings) **+4.8% to +6.7%**. Root cause is the 2026-05-30 scene re-authoring (PR #405: 256²×16 → 512²×64, +1 bounce, generated env maps), not code. Source: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase24/RESULT.md` §Phase 2. |
| 3 | Cross-check mismatch (Kerr vs GYOTO) | **FAILS both quantities.** Photon-ring position: max per-edge mismatch 94 % (prograde edge, 34 px GYOTO vs 66 px Astroray), mean radius +9.0 %. Disk redshift asymmetry δ: Astroray ≈0 vs GYOTO +0.203 (a=0.94, i=90) — ~100 % mismatch. Against GYOTO a=0 (diagnostic), the ring agrees within 1.5 %. Source: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase3/RESULT.md`, `NOTES.md`, `phase3_metrics.json`. |
| 4 | Bank per-channel ratios | All four scenes within ~1.5 % per channel of stored `reference.png` (Kerr 1.009/0.998/1.003, Schwarzschild 1.015/0.994/1.003, ADAF 1.000/1.000/1.000, synchrotron 1.001/1.001/1.001). Vs pre-Phase-1 baseline: Schwarzschild/ADAF byte-identical, Kerr 0.68 % px changed (disk-ring boundaries, expected from the Phase 1 thin-disk fix), synchrotron 2/65536 px (clamp-removal boundary). Source: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase24/RESULT.md` §Phase 4. |

## Phase 3 — Kerr cross-check (GYOTO 2.0.2, pinned `94863d06`)

Frozen matched geometry (both codes): 512², 45° tan-pinhole camera, disk seen edge-on (world xz plane, camera on +z), disk radii 6–18 M, distance 48 M. Measurement procedure frozen in `NOTES.md` before any 512² GYOTO output was read (edge = first 50 % mask crossing on fixed rows/cols; δ = (g_R−g_L)/(g_R+g_L) over rows 248–263).

**Both quantities FAIL against GYOTO a=0.94.**

- **Root cause 1 (spin):** `addBlackHole` (`module/blender_module.cpp`) never reads the scene's `spin` parameter; `BlackHole`'s constructor hardcodes `SchwarzschildMetric(1.0)` (`include/astroray/black_hole.h:291`). The `gr-kerr-94-faceon` scene therefore renders at a=0, not a=0.94. Against GYOTO a=0 the ring matches within 1.5 % (procedure validated: GYOTO a=0.94 edges match the analytic Bardeen equatorial critical impact parameters 34.0/88.8 px).
- **Root cause 2 (redshift):** `NovikovThorneDisk::redshiftFactor` (`include/astroray/accretion_disk.h`) computes `g` from `sin(i_param)·sin(φ_emit)` — a flat-space approximation using the *declared* inclination parameter, not the photon's actual momentum. It never reads `p_φ`/`p_t`. The scene's declared inclination (78°) only enters this formula; the rendered geometry is actually 90° (geometrically edge-on). At i=90° every ring pixel sees the same far-side disk point, so `g` comes out azimuthally uniform (δ≈0) instead of matching GYOTO's momentum-based asymmetry (δ=+0.203 at a=0.94, i=90; +0.216 at a=0, i=90).
- Side observation, not investigated: the Astroray capture mask shows a faint partial dark ring at 74–78 px that GYOTO does not show.

Conclusion: the `gr-kerr-94-faceon` frame is not science-valid as currently rendered. See pkg281 (spin) and pkg282 (momentum-based redshift) below.

## Phase 2 / Phase 4 / pkg107

- **Phase 2 (render time):** the ~10x-and-more growth (README's `~2 s` in 2026-05 vs 19.7–19.8 s measured at `604b03f0`) is **not** a code regression. Matched-settings bisection (same scene SHA, build, backend, 512×512×64) attributes **15.45x–15.73x** to the 2026-05-30 scene re-authoring (PR #405: `WIDTH/HEIGHT` 256→512, `SAMPLES` 16→64, `MAX_DEPTH` 4→5, generated env maps) and only **+4.8% to +6.7%** to code changes since. Recovering the old performance is out of scope (non-goal).
- **Phase 4 (bank re-baseline):** no `reference.png` was replaced. Schwarzschild and ADAF renders are byte-identical vs pre-Phase-1 baseline; synchrotron differs in 2/65536 px (an isolated clamp-boundary pixel from the shared finite/nonnegative clamp removal, not the disk transfer). Kerr differs in 0.68 % of pixels at disk-ring boundaries — the expected footprint of the Phase 1 `g⁵·B_λ` fix. All four scenes remain within ~1.5 % per channel of the stored `reference.png`. Re-blessing the Kerr reference is deferred: the engine still renders `gr-kerr-94-faceon` at a=0 (Phase 3), so a rebaseline now would bless a scene that isn't the Kerr geometry it claims to be. SSIM is recorded as a diagnostic only (0.934 Kerr, 0.850 Schwarzschild vs stored reference — pre-existing, not introduced by this package); it is not the pass/fail metric.
- **pkg107 (`r_obs_M` shadow-radius scaling):** verified. θ halves as `r_obs_M` doubles (measured ratios 0.483x, 0.475x vs ideal 0.5x, within small-`r_px` noise) — `r_obs_M` scales the shadow radius per the expected inverse-linear law. The absolute size is ≈0.37x of the idealized `3√3·M/r_obs` textbook formula; this fixed offset is **unexplained** (the lane's earlier "geometric factor" claim is unproven) and is deferred to pkg282 alongside the momentum-based redshift work, since both concern the camera/geodesic-to-image mapping.

Evidence: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase3/` (`RESULT.md`, `NOTES.md`, `phase3_metrics.json`, `phase3_comparison.png`, `astroray_*.{npy,json}`, `gyoto/`) and `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase24/` (`RESULT.md`, `render_bank.py`, `compare_bank.py`, `phase4_report.json`, `*_cand_vs_*.png`).

## Validated vs unresolved paths

- **Validated (analytically, at external `g` only):** thin-disk transfer helper `g⁵·B_λ(gλ, T)` / `(c/λ²)·g³·B_ν(ν/g, T)` in `diskEmissionSpectral` — passes all Phase 1 analytic tests and the GYOTO external-`g` checkpoint within 1 %. This validates the *formula*, not Astroray's own geodesics, redshift, or the matched Kerr image.
- **Unresolved — thin-disk *path* (not science-ready):** the disk render path as a whole. `BlackHole` ignores `spin` (always Schwarzschild) and `NovikovThorneDisk::redshiftFactor` ignores photon momentum. Both are required before any Kerr-labelled render can be trusted. Follow-up: pkg281 (spin), pkg282 (redshift + pkg107 offset).
- **Validated (analytically) — ADAF and synchrotron jet transport (pkg283, 2026-09-25):** both paths integrate `j_ν/ν²` and `ν·α_ν` at `ν_em = −k·u`, with `I = ν_obs³·ℐ`. The BlackHole chord march attenuates front-to-back. Tests in `tests/test_gr_transfer_invariance.py`: the fluid-frame frequency matches `−k·u` to ≤1e-6; the static-vs-moving ratio matches `g³`/`D³` within 1 %, which is the no-double-counting check (the old jet code gave `D⁴`); the invariant slab residual vs the frame-transformation oracle is ≤1 % at τ = 0.3 and 3; a 96-segment march matches the single-slab solution within 1 %. Research: `volumetric-invariant-transport-research.md`.
- **Still limited — volumetric emitters:** the chord is a straight flat-space line (no lensing and no gravitational redshift of volumetric emission). The ADAF fluid is static (`g = 1`); orbital/inflow kinematics would be new physics. This validates the *transport*, not a science-grade ADAF/jet image.
- No path in this audit is labelled science-ready except the isolated thin-disk transfer formula at a fixed external `g`. The bank scenes passing their per-channel gate does not authorize science use of any unresolved path.

---

## Paper
- **Title:** *Radiative Processes in Astrophysics*, §4.9, “Invariant Phase Volumes and Specific Intensity.”
- **Authors:** George B. Rybicki and Alan P. Lightman.
- **Year / Venue:** 1979, John Wiley & Sons.
- **DOI / arXiv:** ISBN 0-471-82759-2; current online edition DOI 10.1002/9783527618170.
- **Publisher record:** https://www.wiley-vch.de/en/areas-interest/natural-sciences/radiative-processes-in-astrophysics-978-3-527-41431-4
- **Thin-disk transfer context:** C. T. Cunningham, “The Effects of Redshifts and Focusing on the Spectrum of an Accretion Disk around a Kerr Black Hole,” *ApJ* 202, 788–802 (1975), DOI:10.1086/154033, https://adsabs.harvard.edu/pdf/1975ApJ...202..788C.

## Reference implementation
- **Repo:** https://github.com/AFD-Illinois/ipole
- **Commit / tag:** `7f7a482cf91125aeeeb9c431485bba680e8941d7`
- **License:** BSD-3-Clause — compatible with Astroray's MIT license because both are permissive licenses. No ipole source is copied.
- **Files we mirror:**
  - `src/radiation.c` — `Bnu_inv()` identifies the Planck-frequency convention; `get_fluid_nu()` evaluates the fluid-frame frequency from `-k.u`. This slice derives the published thin-disk wavelength identity independently and does not port ipole code.

## What we reproduce
- Equations: `I_nu,obs(nu) = g^3 B_nu(nu/g, T)` and its Jacobian-exact wavelength form `I_lambda,obs(lambda) = (c/lambda^2) g^3 B_nu(c/(g lambda), T) = g^5 B_lambda(g lambda, T)`, where `g = nu_obs/nu_em`.
- Data structures: none; the transfer is a header-only scalar helper used by both existing black-hole disk paths.
- Differences from the reference: Astroray stores sampled wavelength radiance, so the helper evaluates `B_lambda` at `g * lambda_obs`. It retains the existing disk-only `exposureScale / span` presentation normalisation at the callers.

## What we deliberately do NOT take
- No ipole code, dependency, or model fixture.
- No GYOTO code: its GPL-3.0 source remains an external executable oracle only.
- No ADAF or synchrotron invariant-emissivity/absorption implementation. Their current transport has not passed the required analytic checks and remains unresolved.
- No bank rebaseline, render-time attribution, or science-ready claim. The only external comparison is the narrow GYOTO checkpoint recorded below; it validates intensity transfer at external `g` only.

## Integration plan in Astroray
- Files to add/edit: `include/astroray/black_hole.h`, `module/test_helpers_module.cpp`, `tests/test_gr_transfer_invariance.py`.
- Package: `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md` Phase 1, narrowed to the thin-disk analytic core.
- Tests / parity check: the test-only pybind seam calls the production helper. The test compares the independent frequency and wavelength forms per bin, checks `g=1`, fitted `g*T`, monochromatic shift, `g^4` bolometric scaling on a >99.9% Planck-flux grid, and an unbounded finite value above the former 20 clamp.

## Validation boundary
- The analytic tests establish self-consistency of the formula and confirm the production helper is shared by the live CPU disk caller `diskEmissionSpectral`; the RGB `traceGR` base path is a dormant consistency edit, not a live disk caller. They are not an independent external validation.
- The three live CPU GR dispatches (the normal Renderer, the caustic Renderer, and registered `restir-di`) retain only finite/nonnegative samples. The Renderer paths then apply the normal user-selected direct/indirect contribution clamp; ReSTIR-DI has no corresponding user clamp mechanism. The former fixed 20 ceiling is removed. The disk's float storage rejects a nonrepresentable or overflowing addition while preserving the existing finite accumulated value; this is a numeric storage boundary, not a physical radiance cap.
- `BlackHole::traceGR` is a dormant RGB base-fallback consistency edit: production BlackHole dispatch overrides and calls `traceGRSpectral`; the base `Hittable::traceGRSpectral` fallback is its only caller. It is not a third live BlackHole route.
- GYOTO 2.0.2 (pinned `94863d06a36958e65074c632231c12f943b8d868`) has now run as a process-isolated GPL-3.0 executable oracle with no code copied or linked into Astroray; see the narrow checkpoint below. No geodesic, volumetric, or matched-image match is claimed.
- Volumetric ADAF and synchrotron paths remain unresolved and are prohibited from a science-ready claim until their own invariant-emissivity/absorption transport and analytic tests exist.

## Open questions
- The former `g <= 10` cap has no cited physical basis in the package or preflight. This narrow slice removes it together with the local and dispatch output ceilings; invalid or non-finite geodesic factors remain rejected, non-finite evaluated radiance remains rejected, and float-unrepresentable storage additions are skipped rather than producing infinity.

## Checkpoint 2026-09-24 — source `924ea7d7`

Source `924ea7d7`: parent CPU build and both module imports verified fresh; 16 native tests passed; lint zero new findings from 5 tools. Opus SOURCE APPROVE after removing the third fixed 20 cap and testing actual registered ReSTIR. CUDA/full-suite/RTX/CI still pending.

Parent GYOTO 2.0.2 pinned `94863d06a36958e65074c632231c12f943b8d868` ran an external GPL-3.0 executable, with no code copied or linked into Astroray. Six generated autotools files differ from upstream; patch retained. Fixed near-face-on constant-temperature thermal annulus, transfer, and NoRedshift control. Native `127199f4` helper compared at externally measured `g = 0.8205396856615398`: max spectral relative residual `2.41577546934435e-5`; max bin residual `0.0033140826922287703`; bolometric error `8.282559041994375e-5`; external control ratio/`g^4` error `8.946660117103988e-5`. All meet the frozen 1% limit with no fitted normalization. Independent Terra accepted the raw FITS/NPZ recomputation. This validates intensity transfer only at external `g`, NOT Astroray geodesics/redshift, matched 78-degree Kerr frame, or volumetric transport.

Four-number status: intensity residual measured above; causal timing delta unresolved; required matched Kerr-image mismatch unresolved; raw bank per-channel ratios/rebaseline unresolved. Matched display bank retains existing Kerr/Schwarzschild SSIM failures, no references blessed. Old ~2 sec README used 256²x16 versus current 512²x64, a 16x pixel-sample increase; matched timing attribution pending and prior concurrent-load timings are not attribution.

Evidence root `C:/Users/hgcom/OneDrive/Astroray/astra_run/`: `batchB-924e-analytic.log`, `batchB-924e-parent-lint.log`, `batchB-924e-opus-delta.log`, `batchB-gyoto-v2-analysis/` (raw evidence, result, arrays, figure, provenance), `pkg280-gyoto-v2-independent-review.md`, `batchB-gr-visual-inspection.md`, `pkg280-runtime-attribution-preflight.md`.

Package remains OPEN. ADAF/synchrotron invariant emissivity, fluid-frame tests, matched image validation, timing attribution, and bank rebaseline remain unfinished and prohibited from science release.
