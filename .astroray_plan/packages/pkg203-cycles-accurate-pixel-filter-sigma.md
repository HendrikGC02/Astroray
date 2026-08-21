# pkg203 — Cycles-accurate pixel-filter width→σ (CPU+GPU parity, closes pkg200 `pixel_filter_type` honour row)

**Pillar:** Integration Milestone (Blender/DCC integration — reconstruction-filter parity)
**Track:** A
**Status:** done (PR #624, 2026-08-19 — CPU+GPU byte-mirrored Cycles mapping σ=width/4, Gaussian support ±1.5·width, BH ±1.0·width; closes pkg200's `pixel_filter_type` honour row).
**Estimated effort:** S–M.
**Depends on:** **pkg201 Stage 2** (the GPU wavefront reconstruction-filter code this package modifies — pkg201-S2 adds the GPU pixel-filter weighting: `pixelFilterType`/`pixelFilterWidth` applied in the primary-ray/splat stage, Gaussian branch). Do NOT start until pkg201-S2 has landed on main. Cross-links: **pkg200** (the honour-matrix that measured the finding — the `pixel_filter_type` row is the acceptance gate here), **pkg119-B** (numeric Cycles parity — orthogonal).

## Goal

The pixel reconstruction filter's Gaussian width→σ mapping is `σ = filterWidth / 6` and is shared by BOTH backends:
- CPU — `Renderer::filterSample` (`include/raytracer.h:2427`, `float sigma = pixelFilterWidth / 6.0f`), Box-Muller jitter clamped to `[0,1]`.
- GPU — the primary-ray/splat filter stage added by **pkg201-S2** (Gaussian branch), which mirrors the same mapping.

This mapping does not match Cycles' reconstruction-filter spread. Empirically, on pkg200's honour-matrix run (PR #616, RTX-reverified), the `pixel_filter_type` row (BOX@1 vs GAUSSIAN@3, predicate `p_grad_sharper` needs the Gaussian ≥1% sharper) reads **0.83% sharper** — correct *direction* but below threshold — so the row stays **HONEST-FAIL** even though the GPU (post-pkg201-S2) genuinely honours the filter. Note the sibling `filter_width` row DID flip to PASS under pkg201-S2, so the plumbing is live; only the *shape* of the mapping is off.

**Adopt a Cycles-accurate width→σ mapping** for the Gaussian reconstruction filter (and correct the Blackman-Harris width mapping while in the same code) so the reconstruction filters match Cycles' actual spread. This is a **CPU+GPU parity change** — both backends read the same mapping — and the two must stay byte-mirrored.

## Specification

1. **Invoke the `cite-algorithm` skill BEFORE writing code** (CLAUDE.md §6). Cite the canonical width→σ / filter-table definitions:
   - Cycles `intern/cycles` kernel/scene film filter tables (`scene/film.cpp` `filter_table` — Gaussian and Blackman-Harris cases; `kernel/film` reconstruction weighting) — the reference for how `filter_width` maps to the Gaussian falloff and the Blackman-Harris support.
   - PBRT filter widths (`GaussianFilter`, `BlackmanHarrisFilter` / `MitchellFilter` support conventions) as the corroborating textbook source.
   Save research notes to `.astroray_plan/docs/` and cite the source inline in both the CPU and GPU code (the exact formula/constant, with the paper/impl reference).

2. **Replace the `σ = filterWidth / 6` mapping** with the cited Cycles-accurate mapping in `Renderer::filterSample` (`include/raytracer.h:2427`). While there, align the **Blackman-Harris** branch (`raytracer.h:2434–2442`, currently rejection-sampled over `[0,1]`) to the cited Cycles support/width so its spread matches Cycles too. Preserve the existing `[0,1]` sub-pixel-jitter contract unless the cited mapping requires wider support — if it does, state that scope change explicitly and gate it on the same acceptance below (do not silently change splat topology).

3. **CRITICAL — byte-mirror CPU and GPU in the SAME PR** (memory: CPU/GPU material/filter work is byte-mirrored, never split). The GPU filter stage added by pkg201-S2 must adopt the identical mapping/constants in the same commit. Locate the GPU site at implementation time (per pkg201-S2's landed code — `src/gpu/wavefront/` primary-ray/splat/init stage, Gaussian branch); do NOT assume the file path from this spec, verify against the merged pkg201-S2 diff. Add a comment on each side pointing at the other as the mirror.

4. **Re-baseline any CPU filter tests that assert the current σ.** Grep the test suite for tests pinning `σ = width/6`, the `filterSample` distribution, or a specific Gaussian/Blackman-Harris jitter spread, and update their expected values to the new mapping. Un-xfail nothing that wasn't already gated on this. Existing anti-alias / convergence tests must still pass unchanged.

## Acceptance

- [ ] `cite-algorithm` invoked; a research note lands in `.astroray_plan/docs/` and the CPU + GPU code both cite the Cycles/PBRT source inline.
- [ ] The pkg200 `pixel_filter_type` honour row flips **HONEST-FAIL → PASS** on a **verbatim** re-run of the pkg200 driver (`scripts/verify_pkg200_honour_matrix_run.py`, or the canonical driver name at run time) on **real Blender 5.1 AND 5.2**, RTX hardware, LINEAR EXRs, seed-pinned, sentinel-gated (not exit code). Record the measured `grad`/sharpness A/B numbers next to the flip. `.pyd` mtime stated next to the render leg (memory `stale_pyd_locations`).
- [ ] The pkg200 `filter_width` row stays **PASS** (no regression) on the same verbatim re-run.
- [ ] CPU↔GPU filter parity preserved: a same-scene, same-seed CPU-vs-GPU comparison of the filtered output shows the two mappings agree (per-channel mean-ratio band, memory `ssim-wrong-gate-for-independent-rng`; NOT SSIM). The mapping constants are byte-identical between the two code sites (show both snippets in the PR).
- [ ] Re-baselined CPU filter tests pass with the new expected values; existing anti-alias and convergence tests pass unchanged.
- [ ] CI green on all matrix jobs (`gh run view` on HEAD — memory `mingw_local_vs_gcc_ci_divergence`) AND the RTX leg above (CI has no GPU — memory `ci_has_no_gpu_runtime_blindspot`).

## Non-goals

- **No numeric Cycles parity** beyond matching the reconstruction-filter spread (pkg119-B owns absolute pixel parity; the known ~3× light-energy factor is not in scope).
- **No new filter types** and no change to which settings are plumbed (pkg201-S2 owns the GPU plumbing; this package only corrects the shape of an existing mapping).
- **No splat-topology rewrite** to full cross-pixel reconstruction unless the cited mapping strictly requires wider-than-pixel support — if so, that is called out explicitly under §2, not slipped in.

## Provenance

Filed by the architect 2026-08-15 from a pkg201 Stage 2 finding (surfaced in the PR being opened for pkg201-S2). Grounded in live code: CPU mapping `include/raytracer.h:2427` (`σ = filterWidth/6`) + Blackman-Harris `:2434–2442`; empirical motivation from the pkg200 honour matrix (`.astroray_plan/docs/pkg200-honour-matrix-results.md` / spec §"Hardware verification 2026-08-14 (PR #616)", `pixel_filter_type` row = 0.83% sharper, HONEST-FAIL). Depends on pkg201-S2 landing the GPU filter code this modifies.
