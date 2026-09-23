# GR thin-disk invariant transfer — Research

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
