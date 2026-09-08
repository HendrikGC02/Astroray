# pkg264 — Rough glass transmission energy: Cycles parity for the Glass BSDF (limb darkening + roughness loss)

**Pillar:** 5
**Track:** A
**Status:** done — PR #771 merged 2026-09-08 (scoped fix delivered; the ±5 % Cycles-parity criterion is NOT met and is re-scoped to #770): the native Principled transmission sampler returned absorbing dead microfacet samples (no delta fallback, unlike disney.cpp); rerouted to the delta glass event CPU+GPU. White furnace r0.85 0.645 → 0.958 (= Disney); pkg263 harness r0.85 centre 0.525 → 0.742, limb 0.342 → 0.556 of Cycles; 289 regression pass; REG 254; cycles-parity-reviewer MERGE ("pragmatic patch, not the Cycles reject + energy_scale mechanism") + cpp-abi-guard MERGE. Residual (both lobes, engine-wide) + the run_parity glass scene → #770
**Estimated effort:** 2–3 sessions (~8 h; CPU fix + GPU closure-graph mirror under the GPU lock; gated by the pkg263 harness)
**Depends on:** pkg263, pkg179, pkg169, pkg118

---

## Goal

Before: a Glass BSDF sphere (IOR 1.45) under a studio light + grey world renders
darker than Cycles everywhere except the background — limb-annulus ratio
Astroray/Cycles 0.81 at roughness 0, 0.67 at 0.2, 0.44 at 0.5, 0.34 at 0.85;
centre-disc 0.96 → 0.53 — while two Cycles seeds agree to 1.4 %. Rough glass
looks like a dark grey ball instead of a bright frosted one. After: the Glass
BSDF (delta and rough, reflection and transmission) matches Cycles'
`bsdf_microfacet_ggx_glass` within ±5 % per ROI at every roughness in the
pkg263 sweep on CPU and GPU, with no furnace regression (pkg118/pkg169 gates
stay green) and the pkg263 harness row as the acceptance gate.

---

## Context

The owner reported the limb darkening on 2026-09-08; pkg263 quantified it the
same day and showed two regimes: a grazing-only loss at roughness 0 (Fresnel /
TIR / limb handling of the delta lobe) and a whole-silhouette loss that grows
sharply with roughness (rough transmission lobe energy — the pkg179 Phase 2
territory: dead-sample redistribution, furnace in-band at r 0.3/0.6/1.0 CPU and
GPU, all unticked). Every earlier glass fix was gated on Astroray's own furnace,
never on Cycles. Gate (c) (material zoo) and the pkg259 materials-hall Alcove C
depend on this. `cite-algorithm` applies: Cycles `bsdf_microfacet.h`
(`bsdf_microfacet_ggx_glass_setup`, `bsdf_microfacet_sample/eval` transmission
branch, `microfacet_ggx_preserve_energy` glass tables in `kernel/tables.h`),
PBRT-v4 §9.7 dielectric BSDF. Serves Pillar 5.

---

## Evidence

- 2026-09-08 (pkg263, `.astroray_plan/docs/pkg263-rough-glass-ab-2026-09.md`,
  256², 128 spp, CPU both engines, linear): per-ROI Astroray/Cycles R/G/B —
  r 0: centre 0.963, limb 0.815, background 0.999; r 0.2: 0.950 / 0.673; r 0.5:
  0.809 / 0.443; r 0.85: 0.525 / 0.342. Raw limb means r 0.85: Cycles 0.510 vs
  Astroray 0.174. Cycles limb/centre 1.60–1.92 vs Astroray 1.05–1.36.
- 2026-09-08: Cycles seed 7 vs seed 1234 noise floor ≤ 1.4 % on every ROI.
- Contact sheets `.astroray_plan/docs/pkg263/glass_r{000,020,050,085}__contact_sheet.png`
  (lead-inspected: r 0.85 Astroray sphere is dark grey; Cycles bright frosted).
- pkg179 Phase 1 (2026-08-09): smooth-delta fallback reroutes below-horizon
  reflection energy into transmission (energy-correct in the furnace); the
  pkg150 dead-sample removal dropped the furnace 0.997 → 0.788 and was reverted.
  Memory `rough-glass-residual-is-multiscatter`: the 2026-06 furnace deficit was
  the albedo-LUT η² clamp (#423).

---

## Reference

- Harness: `benchmarks/cycles-parity/metal_ab/harness.py --material glass`
  (pkg263), ROI definitions in its `scenes.py`; `tests/test_pkg129_metal_ab_harness.py`.
- Astroray: `plugins/materials/disney.cpp` glass branch (sample/eval/pdf,
  delta fallback, `ggxGlassComp`), `include/raytracer.h` `Material::sampleSpectral`
  (η² factor handling, #423), GPU closure-graph glass lowering in
  `include/astroray/gpu_materials.h` (`GMAT_CLOSURE_GRAPH` dielectric, memory
  `gpu-dielectric-lowers-to-closure-graph`), `include/astroray/energy_compensation.h`
  (`ggxGlassE`, `ggxGlassEavg`).
- Cycles (Apache-2.0): `intern/cycles/kernel/closure/bsdf_microfacet.h`,
  `kernel/tables.h` (`table_ggx_glass_E`, `table_ggx_glass_Eavg`,
  `table_ggx_glass_inv_E`), `svm/closure.h` glass node; PBRT-v4 `DielectricBxDF`.
- Specs pkg179 (Phase 2 leads), pkg169 (Fresnel common factor + |N·wi|),
  pkg124 (VNDF reflection lobe), pkg118 (furnace history).
- Memories: `dielectric-dead-sample-needs-transmission-redistribution`,
  `chi2-glass-gate-quadrature-dominated`, `general-photon-loop-needs-solid-glass`.

---

## Prerequisites

- [x] pkg263 harness + first measurement (PR #764).
- [ ] Build passes on main; `.pyd` newer than HEAD before any GPU number.
- [ ] GPU lock held for the CUDA build and GPU sweep.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/pkg264-glass-energy-research.md` | `cite-algorithm` note: Cycles' glass sample/eval/pdf and energy-preservation tables vs Astroray's, term by term; a per-(roughness, θ) table of transmitted+reflected energy from a Monte-Carlo oracle of the exact dielectric microfacet BSDF vs Astroray's lobe, isolating which regime (delta grazing vs rough transmission) each term explains. |
| `tests/test_pkg264_glass_cycles_parity.py` | White-furnace mechanism gate for the native `principled` rough-transmission lobe (IOR 1.45, target [0.95,1.05], CPU+GPU) + disney regression guard; RED on main (0.645@r0.85), GREEN after. The furnace (absolute ground truth 1.0) replaces an in-process render-vs-Cycles ROI assertion because the render's absolute scale depends on Blender area-light watt→radiance units; the pkg263 Blender-harness ROI re-run is the acceptance evidence (results doc / PR). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/principled.cpp` | **Scope correction (lead 2026-09-08 Q1): `principled.cpp`, NOT `disney.cpp`.** The pkg263 acceptance render routes `ShaderNodeBsdfGlass` → native `principled` (`use_native_principled` default ON), so `disney.cpp` is never exercised by the gate. The research note (§7) isolated the defect to `principled.cpp`'s rough-transmission sampler `chooseAndSampleDir`, which drops dead microfacet samples (no smooth-delta fallback) — the below-horizon fallback routing candidate. Fix mirrors disney's proven fallback; no compensation/formula change. `disney.cpp` untouched. |
| `include/astroray/gpu_materials.h` | Mirror the same dead-sample fallback in the GPU native-principled twin `gpu_pr_chooseAndSampleDir`; REG 254 must hold; report STACK. |
| `include/astroray/energy_compensation.h` | Only if the glass tables/lookup are the defect (clamps, parameterisation, η-branch). |
| `tests/test_disney_energy_conservation.py` | Furnace/chi² gates that pinned the old behaviour are re-derived with the derivation in a comment, never relaxed to pass. |
| `.astroray_plan/packages/pkg179-dielectric-transmission-energy-redistribution.md` | Progress: Phase 2 leads resolved here (or what remains). |
| `.astroray_plan/packages/pkg124-vndf-sampling.md` | Evidence: what pkg264 found about the reflection lobe. |

### Key design decisions

- **Two regimes, measured separately.** Roughness 0 (delta lobe only; the limb
  loss is Fresnel/TIR/limb handling) is fixed and gated before touching the
  rough lobe; then the rough transmission energy. The MC oracle decides which
  term is wrong before any formula changes (pkg261 pattern).
- **Cycles-shaped, cited.** No invented compensation; if Astroray lacks a Cycles
  table (as pkg261 found for Schlick), port it with its generator.
- **Furnace stays green.** A change that fixes the Cycles ratio but breaks the
  white furnace is wrong; both gates run every step.
- **CPU then GPU in one PR** (the closure-graph glass mirror; parity test runs
  both).

---

## Acceptance criteria

- [x] `tests/test_pkg264_glass_cycles_parity.py` red on main, green after, CPU
      and GPU — **as a white-furnace energy gate** (0.645→0.958 @r0.85; disney
      guard green). The ±5 % render-ROI form was NOT achievable: the residual gap
      is engine-wide (affects disney too), so the furnace is the mechanism gate and
      the harness re-run is the parity evidence. See §7.5.
- [x] pkg263 harness sweep re-run headless after the fix; before/after +
      contact sheets under `.astroray_plan/docs/pkg264/postfix_harness/`
      (r0.85 centre 0.525→0.742, limb 0.342→0.556; r0.85 sphere now bright frosted,
      inspected). Full ±5 % parity not reached — residual is a follow-up.
- [x] Furnace gates green (289 regression pass incl. pkg118/pkg169/pkg179 furnaces,
      dielectric/disney glass, caustic, pkg178 GPU furnace); REG 254 held.
- [ ] `cycles-parity-reviewer` pass (pending); call-site sweep clean (no signature
      changed — only `chooseAndSampleDir`/`gpu_pr_chooseAndSampleDir` bodies).

---

## Non-goals

- No dispersion / spectral changes; no caustic (SMS/photon) changes.
- No relaxation of any furnace or parity band to pass.
- Principled transmission (metallic/transmission lobes in `principled.cpp`)
  only if the note proves it shares the defect; otherwise a follow-up.

---

## Progress

- [ ] 2026-09-08 — filed by the lead from pkg263; not started.
- [~] 2026-09-08 — research note + MC flux-furnace oracle committed
      (`.astroray_plan/docs/pkg264-glass-energy-research.md`,
      `.astroray_plan/docs/pkg264/glass_energy_oracle.py`). **Diagnosis
      contradicts the spec's premise on two axes; escalated to the lead, no
      engine edit made.** (1) The pkg263 gate renders through
      `plugins/materials/principled.cpp`'s Transmission lobe, NOT `disney.cpp`
      (native-principled ON by default; `blender_addon/__init__.py:4079→4234`).
      (2) The dead-sample fraction is 0–4 % (not the mechanism; corroborates
      pkg179 Phase 1's "measurement artifact" finding). (3) A single glass
      interface is 77–100 % flux-efficient uncompensated (comp_needed ≤ 1.29),
      far too small for pkg263's ~2× render deficit — the 2× must be compounding
      over the sphere's internal bounces and/or a render-integration effect, not
      a per-interface BSDF formula error. Blocked on lead answers to Q1 (fix
      target = principled.cpp?), Q2 (authorize the single-vs-multi-bounce render
      A/B before any formula change), Q3 (scope of a comp-application fix). See
      the research note §6.
- [x] 2026-09-08 (continuation; lead answered Q1–Q3) — mechanism found and fixed.
      Render-level A/B **refuted** bounce caps + filter_glossy (byte-identical);
      white furnace **isolated** the defect: native `principled` rough transmission
      lost energy (0.909@r0.5 / 0.645@r0.85 / 0.524@r1.0) while `disney` conserved.
      Root cause = the sampler returned an **absorbing dead sample** on grazing
      microfacets that failed both reflect and refract (high on the sphere's exit
      interface), with no smooth-delta fallback (disney has one). **Fix** (CPU
      `principled.cpp` + GPU `gpu_pr_chooseAndSampleDir`): reroute dead rough samples
      to the delta glass event. Furnace → 0.958@r0.85 CPU+GPU (= disney); test
      GREEN; **289 regression pass**; **REG 254 held**. pkg263 harness re-run
      (native-principled, this branch): r0.85 centre 0.525→0.742, limb 0.342→0.556;
      r0.5 centre 0.809→0.873 (contact sheets under
      `.astroray_plan/docs/pkg264/postfix_harness/`, r0.85 now bright frosted).
      **Residual gap to full ±5 % Cycles parity is engine-wide** (post-fix
      `principled` ≥ trusted `disney`; the residual affects disney equally and both
      furnace-conserve) — filed as a follow-up (multiscatter angular lobe vs Cycles),
      out of pkg264's principled=disney scope. Research note §7. PR #771.

---

## Lessons

- The pkg263 acceptance gate renders native-`principled`, not `disney`; a spec that
  names the wrong plugin as the fix target cannot be validated by its own gate.
  Escalate the file mismatch before coding (this lane did).
- Energy conservation (white furnace) is necessary but NOT sufficient for Cycles
  render parity: a furnace-conserving rough glass can still be dimmer than Cycles in
  a directional-lit scene because the *angular* distribution differs. Gate the
  mechanism on the furnace; gate parity on the lit harness.
- The oracle's single-front-interface dead-sample measurement (0–4 %) under-counted
  the loss; the dominant dead samples are on the solid's *exit* interface (dense→rare,
  near the critical angle). Measure both interfaces before concluding "not the
  mechanism."
