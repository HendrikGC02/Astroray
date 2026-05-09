# pkg60 — Disney v2 Energy Compensation (No-Glow Materials)

**Pillar:** 5
**Track:** A or E (well-defined port — strong Codex fit)
**Status:** **done** (PR #178, 2026-05-09)
**Estimated effort:** 1-2 sessions (~6 h)
**Depends on:** none — pure port of well-known math

---

## Goal

**Before:** Astroray's Disney BRDF (`plugins/materials/disney.cpp`) has no energy compensation between its lobes. Stacking high roughness + sheen + clearcoat or driving roughness above ~0.6 makes the closure return more energy than the incoming radiance, and surfaces visibly *glow* — the project-owner-reported "materials seem to glow" bug from the 2026-05-08 triage.

**After:** Disney closures are energy-conserving across the (roughness, metallic, sheen, clearcoat) parameter grid, matching Cycles' Principled BSDF v2 behavior to within a small tolerance. A regression test integrates the BSDF over the hemisphere on a Halton grid and asserts the directional-hemispherical reflectance is ≤ 1.0 across the parameter range.

---

## Context

This is the most user-visible material bug after pkg59. Cycles ran into the same problem and shipped energy-compensation tables in the v2 Principled BSDF (Burley 2015 + Kulla & Conty 2017 directional-albedo tables, integrated into Cycles by Brecht Van Lommel circa Blender 4.0). The compensation is per-lobe: each microfacet lobe (GGX rough metal, GGX rough dielectric, sheen, clearcoat) gets a 32×32 LUT of `(cosTheta_o, alpha)` → directional albedo, and the sampler multiplies in `(1 - albedo) / albedo` to recover the energy lost to multiple scattering.

The Cycles tables are CC0 / Apache-2.0 (Blender Foundation), so we can ship them directly under our license.

---

## Reference

- **Math:** Kulla & Conty, "Revisiting Physically Based Shading at Imageworks", SIGGRAPH 2017 Course (open access). §"Energy Compensation".
- **Cycles reference implementation** (CC0 / Apache-2.0):
  - LUT generation: `intern/cycles/kernel/closure/bsdf_microfacet.h`, function `microfacet_ggx_E`.
  - LUT data: `intern/cycles/kernel/data_template.h` and the corresponding `.bin` files in `intern/cycles/kernel/closure/precomputed_tables/`.
  - Sheen compensation: `intern/cycles/kernel/closure/bsdf_sheen.h` (Conty & Kulla 2017 sheen + compensation).
- **Burley 2015** "Extending the Disney BRDF to a BSDF with Integrated Subsurface Scattering" (proceedings).
- Existing Astroray Disney code: [plugins/materials/disney.cpp](plugins/materials/disney.cpp).

The implementer must do a fresh WebSearch + WebFetch pass (per CLAUDE.md §6) to confirm the exact Cycles file paths, license headers, and table dimensions before porting.

---

## Prerequisites

- [x] Existing Disney BSDF tests pass (`tests/test_disney*.py`) — establishes the no-regression baseline.
- [x] Confirm Cycles table license is compatible (Apache-2.0 / BSD-3-Clause, not CC0). Save findings to `.astroray_plan/docs/disney-energy-compensation-research.md`.
- [x] Identify which Astroray Disney lobes need compensation: GGX rough metal/dielectric, sheen attenuation, clearcoat, plus a local diffuse furnace normalization found during the pkg60 numerical gate.
- [x] Decide table format: Cycles static arrays were converted to `.bin` files under `data/disney_compensation/`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `data/disney_compensation/ggx_E.bin` | 32×32 LUT for GGX rough metal/dielectric directional albedo. |
| `data/disney_compensation/sheen_E.bin` | Sheen lobe directional albedo. |
| `data/disney_compensation/clearcoat_E.bin` | Clearcoat (fixed alpha=0.25) 1D LUT. |
| `include/astroray/energy_compensation.h` | Loader + bilinear sample helpers for the LUTs. |
| `src/energy_compensation.cpp` | Implementation; lazy-load on first use; `ASTRORAY_DATA_DIR` resolution. |
| `tests/test_disney_energy_conservation.py` | Halton-grid hemisphere integration; asserts directional-hemispherical reflectance ≤ 1.0 across the parameter range. |
| `.astroray_plan/docs/disney-energy-compensation-research.md` | WebSearch findings + license confirmation + math derivation. |

### Files to modify

| File | What changes |
|---|---|
| [plugins/materials/disney.cpp](plugins/materials/disney.cpp) | In each lobe's `eval()` and `sample()`, multiply by the compensation factor `1 + (1 - E(cosTheta_o, alpha)) / E(cosTheta_o, alpha)` for metallic/dielectric. Sheen lobe gets its own compensation per Conty & Kulla. |
| `CMakeLists.txt` | Install rule for `data/disney_compensation/` next to existing data files. |
| [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md) | Mark pkg60 active/done. |

### Key design decisions

1. **Port, do not derive.** Use the Cycles LUTs directly (license permitting). Generating new LUTs from scratch would require running a high-spp ground-truth Monte Carlo integration over the parameter grid — exactly the kind of work CLAUDE.md §6 says to borrow rather than redo.
2. **CPU first.** Apply compensation only on the spectral CPU integrator. GPU compensation is a follow-up package — do not extend `gpu_materials.h` here.
3. **LUTs are 32×32 (or whatever Cycles ships).** Bilinear interpolation. ~12 KB per LUT total. Embed as binary, not constexpr — easier to swap.
4. **Cite in code.** Each multiplication site must cite "Kulla & Conty 2017 §X" and "Cycles `bsdf_microfacet.h:microfacet_ggx_E`". Per CLAUDE.md §6.
5. **Energy-conservation test is the hard gate.** Render is not enough; we need a numerical proof that the BRDF integrates to ≤ 1.0 over the upper hemisphere across at least the parameter grid `(roughness ∈ {0.1, 0.3, 0.5, 0.7, 0.9}, metallic ∈ {0, 1}, sheen ∈ {0, 0.5, 1}, clearcoat ∈ {0, 0.5, 1})` at incident angles `cosTheta ∈ {0.1, 0.5, 0.9}`. 60 parameter combos × 3 angles = 180 integrations. 4096-sample Halton hemisphere integration each.
6. **Visual regression on the contact sheet.** `scripts/diagnostics/material_contact_sheet.py` should still produce visually-similar images at low roughness (where compensation is small); high-roughness rows should look slightly brighter (recovered multi-scatter energy) but never blown out.

---

## Acceptance criteria

- [x] `.astroray_plan/docs/disney-energy-compensation-research.md` exists with paper citations + Cycles file paths + license confirmation.
- [x] Per-lobe directional-hemispherical reflectance ≤ 1.0 + ε (ε = 0.02) at every grid point.
- [x] No grid point has reflectance > 1.05 (loose upper bound — anything greater is a real bug).
- [x] Cornell-box reference render at 256 spp shows no visible glow on any object's high-roughness configuration.
- [x] Existing `tests/test_disney*.py` pass with within-noise differences (SSIM ≥ 0.95) at low roughness.
- [x] Material contact sheet (`scripts/diagnostics/material_contact_sheet.py`) regenerated and saved to `tests/reference/disney_contact_sheet_post_compensation.png`.

---

## Non-goals

- Do not port to GPU. Separate package after pkg54 is in.
- Do not change the Disney BRDF parameter set (no new sliders).
- Do not implement subsurface compensation (separate Burley 2015 chapter).
- Do not touch the spectral pipeline beyond what's needed for the compensation factor.

---

## Progress

- [x] Research note (WebSearch + WebFetch) — Codex fetched Kulla/Conty,
      Cycles, and Burley references with license headers and table
      dimensions before any code was written.
- [x] Owner sign-off on research note.
- [x] Port LUTs from Cycles (Apache-2.0 / CC0 — confirmed compatible).
- [x] Loader + bilinear sample with `ASTRORAY_DATA_DIR` resolution.
- [x] Wired into Disney lobes (GGX rough metal, GGX rough dielectric,
      sheen, clearcoat top-layer attenuation, local diffuse furnace
      normalization). Replaces the previous additive roughness boost.
- [x] Hemisphere-integration test: 90 parameter combos × 3 outgoing
      cosines × 4096 Halton samples each. Worst-case
      directional-hemispherical reflectance **1.0159** — under the 1.02
      gate. No grid point exceeded 1.05.
- [x] Material contact sheet regenerated; combined-sampler PDF
      regression caught during owner review and fixed.
- [x] STATUS.md update (2026-05-09 changelog entry).

---

## Lessons

- **The hard gate caught a pre-existing bug.** The 4096-sample furnace
  test at 90 parameter combinations × 3 incident angles surfaced a
  Smith-G denominator bug in Disney's specular/clearcoat lobes that
  predated this package. Worth keeping the test as a permanent
  regression gate; cheap to run.
- **Visual review caught what the furnace test didn't.** A
  combined-sampler PDF regression slipped past the eval-only
  hemisphere integration (mixed Disney diffuse/specular returned the
  selected lobe's PDF while carrying the full Disney `eval` in `f`).
  The bug manifested only in mixed-metallic glossy scenes during
  visual review. Numerical gates are necessary but not sufficient —
  the visual contact sheet is part of the acceptance set, not a
  nice-to-have.
- **Cycles' LUT format is portable.** 32×32 GGX + 32×16 sheen LUTs
  loaded directly from binary; no regeneration needed.
- **GPU compensation is the obvious follow-up.** This package is CPU-only
  by design. When pkg54 megakernel lands, port the same LUTs to a
  device-side texture lookup. ~1 session of additional work.
- Current Cycles did not match the package's quoted filenames/functions:
  the GGX entry point is `microfacet_ggx_preserve_energy`, GGX data lives in
  `src/scene/shader.tables`, and the current sheen path is the 2022 LTC sheen,
  not a Conty/Kulla 2017 Charlie table.
- The package spec says "60-point parameter grid" but lists 90 parameter
  combinations. The implemented test covers all listed values: 90 combinations
  × 3 outgoing cosines = 270 integrations.
- The first hard-gate run exposed an existing Astroray Disney bug: the Disney
  Smith-G helper already contains the denominator used by the Burley Disney
  formula, but the specular and clearcoat lobes divided by `4*NdotL*NdotV`
  again. Fixing that removed the grazing-angle glow before LUT compensation
  was judged.
- Final measured worst-case directional-hemispherical reflectance:
  **1.015891** at roughness=0.9, metallic=0, sheen=0, clearcoat=0,
  cosThetaO=0.1, using 4096 Halton samples.
- Project-owner visual review exposed a second no-glow bug outside the eval-only
  furnace grid: mixed Disney lobes returned the selected branch PDF from
  `sample()` even though `f` contained the full Disney eval. A glossy
  metallic=0.7, roughness=0.05 sphere therefore over-brightened a gray furnace.
  The sampler now returns the combined `pdf()` for diffuse/specular mixtures,
  and `tests/test_disney_energy_conservation.py` includes a gray-furnace render
  regression for that exact case.
- Visual smoke: `test_results/pkg60_disney_cornell_256spp.png` rendered at
  128x128, 256 spp, max pixel 0.928315, no visible high-roughness glow.
