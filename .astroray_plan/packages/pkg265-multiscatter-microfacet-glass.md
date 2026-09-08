# pkg265 — Multiple-scattering microfacet dielectric (Heitz 2016) replaces the delta reroute for rough glass

**Pillar:** 5
**Track:** A
**Status:** open — filed 2026-09-09 by the lead from #770 (owner: physics first, 2026-09-08 evening)
**Estimated effort:** 3 sessions (~10 h; Python oracle + directional gate, CPU BSDF on both lobes, GPU mirror under the lock, harness re-runs)
**Depends on:** pkg264, pkg263, pkg179, pkg124

---

## Goal

Before: the rough dielectric transmission lobe in both `principled.cpp` and
`disney.cpp` conserves energy in the white furnace only because a dead
microfacet sample (grazing VNDF normal that fails both reflection and
refraction) is rerouted into the smooth delta glass event (pkg264 #771,
pkg138). The flux is right but the direction is a Dirac the rough lobe does not
contain, `eval()`/`pdf()` never see that branch, and the pkg263 harness still
reads Astroray/Cycles centre 0.742 / limb 0.556 at roughness 0.85 (0.873 /
0.490 at 0.5). After: the rough dielectric (reflection + transmission, entering
and exiting) implements the physically correct multiple-scattering Smith
microfacet BSDF of Heitz et al. 2016 — an unbiased stochastic random walk on
the microsurface with no dead samples and no delta fallback — on CPU and GPU,
for both the native Principled transmission lobe and the Disney glass lobe. A
Python random-walk oracle of the same model is the directional reference; the
engine matches it per (roughness, μ, η) in energy and angular distribution; the
white furnace stays in band; the Cycles A/B becomes a recorded cross-check band
with the divergence explained.

---

## Context

The owner's named complaint (rough glass renders as a dark ball) survived
pkg264. The cycles-parity review of #771 called the reroute "a pragmatic
patch, not the mechanism" and the residual is engine-wide (Principled ==
Disney). The owner's 2026-09-08 evening rule (north-star doc §7) makes the
target explicit: where Cycles is approximate — its `energy_scale = 1/E`
single-scatter compensation (Turquin/Kulla–Conty style tables) is one —
Astroray implements the published physically correct model, records the
divergence with oracle evidence, and uses the Cycles A/B as a cross-check band,
not the criterion. Gate (c) material zoo and the pkg259 materials-hall Alcove C
depend on this. `cite-algorithm` is mandatory before any code. Serves Pillar 5.

---

## Evidence

- 2026-09-08 (pkg264 research note §7.2, IOR 1.45): native Principled furnace 0.645 → 0.958 after the reroute; Disney 0.962; both backends within 0.005.
- 2026-09-08 (pkg264 §7.5 harness, 256², 128 spp, CPU): Astroray/Cycles centre 0.873 / limb 0.490 at r 0.5; 0.742 / 0.556 at r 0.85; r 0 unchanged (0.963 / 0.815); Cycles seed-to-seed floor ≤ 1.4 %.
- 2026-09-08 (pkg264 §7.1): bounce caps, filter_glossy, RR refuted as the mechanism (byte-identical / < 0.5 %); the addon r 0 limb (0.232) is ~15 % below the in-process engine render (0.271) and Cycles (0.284) — a separate addon-side residual.
- 2026-06-08 (`pkg118-multiscatter-energy-research.md`): a Kulla–Conty multi-scatter table was tried and rejected — that deficit was the η² albedo-LUT clamp (#423), not multi-scatter; a table alone does not fix directionality.

---

## Reference

- Paper: Heitz, Hanika, d'Eon, Dachsbacher, "Multiple-Scattering Microfacet BSDFs with the Smith Model", ACM TOG 35(4) (SIGGRAPH 2016), DOI 10.1145/2897824.2925943 — §5 (random walk on the Smith microsurface: height sampling, G1/Λ, conductor/dielectric/diffuse phase functions), §6 (stochastic evaluation, MIS with a stochastic `eval`). Reference code: the paper's supplemental (`MicrosurfaceScattering.cpp`, Beckmann + GGX, dielectric `samplePhaseFunction`/`evalPhaseFunction`, `eval` with `scatteringOrderMax`) and its Mitsuba 0.5 plugin — the lane records the exact URL, commit and licence in the research note and stops if the licence is not compatible.
- Astroray: `plugins/materials/principled.cpp` (`chooseAndSampleDir` transmission branch, the #771 reroute), `plugins/materials/disney.cpp:844-912` (delta fallback since pkg138), `include/astroray/gpu_materials.h` (`gpu_pr_chooseAndSampleDir`, `gpu_disney_sample`), `include/astroray/energy_compensation.h` (`ggxGlassE`/`ggxGlassEavg`, `ggxGlassComp`), `pkg264/glass_energy_oracle.py` (single-interface MC oracle to extend), `module/blender_module.cpp` `debug_bsdf_sample_batch` / `debug_bsdf_pdf_batch` (chi²-style BSDF-level test hooks, used by `tests/test_pkg178_alpha.py`), `tests/chi2_data.py`.
- Harness: `benchmarks/cycles-parity/metal_ab/harness.py --material glass` (pkg263); `scripts/run_parity.py` + `benchmarks/cycles-parity/scenes/manifest.toml` (today only `cornell`).
- Cycles (Apache-2.0, cross-check only): `intern/cycles/kernel/closure/bsdf_microfacet.h` (`microfacet_ggx_preserve_energy`, reject on invalid sample), `kernel/tables.h` glass tables.
- Docs: `pkg264-glass-energy-research.md`, `pkg263-rough-glass-ab-2026-09.md`, north-star doc §7 (2026-09-08 evening), issue #770.
- Memories: `rough-glass-residual-is-multiscatter`, `dielectric-dead-sample-needs-transmission-redistribution`, `chi2-glass-gate-quadrature-dominated`, `wavefront-shade-kernels-register-saturated`, `noinline-runtime-flag-avoids-shade-spill`.

---

## Prerequisites

- [x] pkg264 merged (#771); pkg263 harness available.
- [ ] `cite-algorithm` research note written and the reference code's licence confirmed compatible BEFORE engine code.
- [ ] Build passes on main; `.pyd` newer than HEAD before any GPU number; GPU lock held for the CUDA build and GPU gates.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/pkg265-multiscatter-microfacet-research.md` | `cite-algorithm` note: the Heitz 2016 random walk term by term (height distribution, Λ, G1, dielectric phase function with Fresnel + refraction on the microsurface, escape test, MIS-compatible stochastic `eval`), the supplemental code mapping, licence, and what Astroray reproduces vs simplifies; a Divergence section: why Cycles' `1/E` single-scatter compensation differs in angular shape from the multiple-scattering solution, with the oracle tables. |
| `benchmarks/cycles-parity/glass_ms_oracle/heitz_random_walk.py` | The Python (numpy) random-walk oracle: given (α, μ_o, η, side) returns the reflected/transmitted albedo and an angular histogram (θ bins, φ-averaged) of the multiple-scattering dielectric, single-scatter-only variant switchable for the divergence table. Registered in `scripts/README.md`. |
| `tests/test_pkg265_ms_glass_directional.py` | The directional gate: for α ∈ {0.3, 0.5, 0.85, 1.0} (roughness → α by the engine's mapping), μ_o ∈ {0.1, 0.3, 0.5, 0.7, 0.9}, η 1.45 entering and 1/1.45 exiting: (a) sampled-direction θ histogram from `debug_bsdf_sample_batch` vs the oracle within ±5 % per bin holding ≥ 2 % of the mass (chi²-style, seeded, ≥ 2e5 samples), (b) total reflected + transmitted albedo within ±2 % of the oracle, (c) `debug_bsdf_pdf_batch` consistent with the sampled histogram; RED on main (delta reroute puts mass in a Dirac bin), GREEN after; CPU, plus the GPU variant through the closure-graph sample hook if one exists (else the GPU furnace + render parity below is the GPU gate). |
| `benchmarks/cycles-parity/scenes/glass_sphere.blend` | run_parity glass scene: native-Principled sphere IOR 1.45 at roughness 0.5 / 0.85 / 1.0 (three objects or three rows), area light + grey world as in pkg263, manifest row(s) so the CI parity table carries a Cycles cross-check for glass. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/principled.cpp` | Transmission lobe sample/eval/pdf become the Heitz multiple-scattering dielectric random walk (bounded `scatteringOrderMax`, cited); the #771 delta reroute is removed; `ggxGlassComp` is no longer applied to this lobe (the walk conserves energy by construction — record the furnace before/after). |
| `plugins/materials/disney.cpp` | Same on the Disney glass lobe (dead-sample delta fallback at 844-912 removed); the reflection lobe of the dielectric follows the same walk so reflection and transmission are one consistent model. |
| `include/astroray/gpu_materials.h` | GPU twins (`gpu_pr_chooseAndSampleDir`, `gpu_disney_sample` + eval/pdf) mirror the walk; `stageShadeBucketedKernel` REG must stay 254 — use the `__noinline__` + `__constant__` runtime-flag pattern (memory `noinline-runtime-flag-avoids-shade-spill`) if the walk spills; report REG/STACK before and after. |
| `include/astroray/energy_compensation.h` | Glass compensation entry points are left for other callers; document which lobes no longer use them. |
| `scripts/run_parity.py` | Register the glass scene with a recorded (not gating) ratio band until the divergence is explained; the cornell gate unchanged. |
| `benchmarks/cycles-parity/scenes/manifest.toml` | Manifest row(s) for the glass scene. |
| `tests/test_pkg264_glass_cycles_parity.py` | Furnace gates stay; add the linear upper bound (≤ 1.02, memory `gamma-furnace-cannot-detect-energy-gain`); any pin re-derived with its derivation in a comment, never relaxed to pass. Same for `test_disney_rough_glass_furnace.py` and `test_dielectric_glass_furnace.py`. |
| `.astroray_plan/packages/pkg264-rough-glass-transmission-energy-cycles-parity.md` | Progress line: reroute superseded here. Same for pkg179 (Phase 2 leads closed) and pkg124 (reflection-lobe finding). |
| `.astroray_plan/docs/external-references.md` | Pointer to the research note. |

### Key design decisions

- **Oracle first, then the engine.** Phase 1 = research note + Python oracle + the divergence table (oracle multi-scatter vs single-scatter vs Cycles' `1/E` compensation at the same grid) + the RED directional test against the current engine. Post a WIP commit + a short summary for the lead, then continue into Phase 2 CPU unless the table contradicts the premise (in which case stop and report).
- **Full random walk in-engine, not a fitted table.** The physically correct model is the stochastic walk (paper §5–6); a compensation table fitted to the oracle would reproduce Cycles' shape problem with different numbers. Stochastic `eval` is unbiased in expectation and MIS-safe (paper §6.1); document the variance cost and the `scatteringOrderMax` bound (start at 10, measure the truncated energy).
- **Both lobes, one model.** Principled transmission and Disney glass share the walk; the smooth-delta path (α → 0) keeps its analytic branch. Threshold for the delta branch stays where it is.
- **CPU then GPU in one PR** if REG 254 holds; if the GPU leg spills even behind the `__noinline__` flag, land CPU + a GPU stub that keeps the #771 reroute, file the GPU leg as a phase with the spill numbers, and say so in the PR body — never a silent CPU/GPU divergence.
- **Cycles is a band, not a gate.** The pkg263 harness is re-run after; the ratio is recorded per ROI with the physical explanation from the oracle table (expected: Astroray brighter at the limb than the single-scatter model, at or near Cycles; either direction is acceptable if the oracle agrees).

---

## Acceptance criteria

- [ ] Research note complete, licence recorded, code headers cite paper + reference file.
- [ ] `tests/test_pkg265_ms_glass_directional.py` RED on main, GREEN after, CPU (+ GPU where a hook exists).
- [ ] White furnace (IOR 1.45) for principled + disney at r 0.5 / 0.85 / 1.0 within [0.97, 1.02] linear, CPU and GPU; pkg118/pkg169/pkg178 furnace suites green.
- [ ] `stageShadeBucketedKernel` REG 254 on all shade specialisations; STACK reported.
- [ ] pkg263 harness re-run (256², 128 spp) with the per-ROI ratio recorded in the research note and the divergence explained from the oracle table; contact sheet saved and lead-inspected.
- [ ] Glass scene registered in `run_parity.py` and the manifest; CI parity table shows the row.
- [ ] cycles-parity-reviewer + cpp-abi-guard MERGE; #770 closed by the PR.

---

## Non-goals

- Do not fit or port Cycles' `energy_scale` tables as the mechanism (owner rule).
- Do not touch the addon-side r 0 limb residual (~15 %, pkg264 §7.1) — file it as its own issue if not already.
- Do not change the delta (smooth) glass branch, the thin-film lobe, or the conductor lobes.
- Do not relax any furnace or parity pin to pass.

---

## Progress

- [ ] 2026-09-09 — filed by the lead; dispatched to Opus 4.8 (`package-implementer`) as the first item of the session.

---

## Lessons

- (none yet)
