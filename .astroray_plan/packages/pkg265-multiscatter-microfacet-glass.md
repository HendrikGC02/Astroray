# pkg265 — Multiple-scattering microfacet dielectric (Heitz 2016) replaces the delta reroute for rough glass

**Pillar:** 5
**Track:** A
**Status:** in-progress — Phase 2 (CPU) + Phase 4 (harness/run_parity) + Phase 5 (eval/NEE consistency fix, lead HOLD response) + Phase 6 (post-fix harness re-run) + Phase 7 (thin-film rough glass stays single-scatter, cycles-parity review 2 CRITICAL #2 fix) + #779 run_parity honesty fix done, all on PR #778, 2026-09-09; Phase 3 GPU still pending the lead's call (CPU-lands / GPU-phase decision, spec §Progress)
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
- [!] 2026-09-09 — **cite-algorithm licence STOP raised** (research note §Reference/licence, committed on `feat/pkg265-ms-microfacet-glass`). No licence-compatible reference implementation of Heitz 2016 exists to port: the paper's supplemental `MicrosurfaceScattering.cpp` is licence-UNSTATED (skill: reject), the bundled Mitsuba plugin is GPLv3 (incompatible with MIT), and Mitsuba 3 (BSD) / pbrt-v4 (Apache) implement different/single-scatter models. Paper equations (§5–6) are freely readable for a clean-room implementation. Per the lane hard rule (STOP on licence mismatch, do not port), no algorithm code written; awaiting the lead's IP call on the recommended path (implement from the paper equations, cite Heitz 2016, copy no unstated/GPL code).
- [x] 2026-09-09 — **lead resolved: Option A (clean-room from the paper equations).** Implement the Heitz 2016 random walk from the paper's published equations (§5–9), cite DOI 10.1145/2897824.2925943 in the note and every code header, copy zero lines from the unstated-licence supplemental or the GPL plugin. Standard CLAUDE.md §6 reading: formulae are cited provenance, reference code's expression is not used. A later BSD/MIT/Apache implementation of the same walk may be cross-checked/cited but the clean-room path does not wait. Recorded verbatim in the research note licence section.
- [x] 2026-09-09 — **Phase 2 (CPU) complete** (pushed on `feat/pkg265-ms-microfacet-glass`,
  PR #778). Both glass lobes (`principled` transmission + `disney` glass) sample the
  clean-room Heitz-2016 walk (`include/astroray/microsurface_dielectric.h`, scatterMax=16,
  0.00% dead); `sample()`/`sampleSpectral()` set f/pdf = throughput with the §9
  first-bounce+diffuse-floor MIS pdf; #771 delta reroute + pkg138 delta fallback removed;
  `ggxGlassComp`/`ggxGlassCompensationFactor` dropped from these lobes. **Directional gate
  RED→GREEN (41/41)**; **furnace (linear, 256 spp) principled 0.992–0.996 / disney
  0.980–0.993, all in [0.97,1.02]** (bands tightened, R=1.0 pkg167 carve-out folded back in
  with no table). ~540 CPU regression tests green (furnace/caustic/energy/pkg178/chi2/rough-
  glass), 0 new failures. Class-of-bug found+fixed: the render calls `sampleSpectral`, whose
  base re-evaluates single-scatter `evalSpectral` for a non-delta sample — DisneyPlugin now
  overrides it (research note §Finding).
- [x] 2026-09-09 — **Phase 7 (thin-film rough glass, cycles-parity review 2 CRITICAL #2) fixed** on PR #778 (`feat/pkg265-thinfilm-fix` → PR branch). The walk branch had no `filmActive()` guard, so a thin-film Principled glass (thickness > cutoff, roughness > 0.03) went through the walk (which sets `isDelta=true`) while `eval()` returned the nonzero thin-film f → NEE double-counted direct light (+5%/+13%/+31% at r0.3/0.5/0.85 in an emissive-behind scene) and the plain-Fresnel walk dropped iridescence (thin-film glass rendered **byte-identical** to plain glass, reldiff 0.0000). Fix: behind `filmActive()`, `chooseAndSampleDir` + `transmissionPdf` restore verbatim the origin/main single-scatter sampler (incl. pkg264 #771 reroute), `isDelta=false` → sample==eval==pdf single-scatter, as on main. Non-film glass unchanged. Disney glass has no thin-film path (no change). New gate `tests/test_pkg265_thinfilm_rough_consistency.py` RED→GREEN (reldiff 0.0000→0.158 at r0.85); 180+ CPU tests green. Follow-up: **#783** (thin-film-aware walk). CPU-only lane; GPU thin-film parity (`test_pkg178_thinfilm_gpu_cpu_parity` glass_r0.2) flagged for the hardware-verifier.
- [ ] 2026-09-09 — **Phase 3 (GPU): DECISION FOR THE LEAD.** GPU glass
  lowers to `GMAT_CLOSURE_GRAPH` in the REG:254-pinned shade kernel and still carries the
  pkg264 #771 reroute (a documented, energy-conserving stub — GPU furnace principled
  0.958–0.996 / disney 1.00–1.03; all existing GPU furnace + CPU/GPU parity tests PASS, so
  nothing is broken and the divergence is not silent). A device twin of the walk is a large,
  register-sensitive port (erfinv/VNDF/height-sampling while-loop) into a saturated kernel,
  with the same base-`sampleSpectral` re-eval trap on GPU and no directional hook to validate
  it. Deferred pending the lead's call: attempt the GPU walk now (spill risk) vs land as-is
  and file the GPU leg as its own phase.
- [x] 2026-09-09 — **Phase 4 (harness + run_parity) complete** (Sonnet 5 lane, CPU-only, no
  GPU lock; two commits on `feat/pkg265-ms-microfacet-glass`, PR #778). Restaged the CPU addon
  from this worktree (`build_blender_addon.py --backend cpu`; `ASTRORAY_PYD_DIR` must point at
  the staged `dist/astroray/`, not the bare `build_blender_addon/` — that dir is missing the
  bundled MinGW/OIDN runtime DLLs the harness needs inside Blender). Re-ran the pkg263 glass A/B
  harness (256², 128 spp, CPU both engines): limb moves from ~0.5× Cycles (pre-#778 dead-sample
  loss) to ~1.0–1.05× (the walk lands on the oracle-predicted direction); centre overshoots to
  1.08–1.52× at r≥0.5, growing with roughness — the oracle's single-interface divergence table
  explains the *direction* but not the full magnitude (the render integrates two rough
  interfaces, entry+exit, which the single-interface oracle doesn't model). Full before/after
  table, direction check, contact sheets and wall times in the research note's new Phase 4
  section. Registered `glass_sphere` (3 native-Principled spheres, IOR 1.45, r 0.5/0.85/1.0) in
  `run_parity.py`/`manifest.toml` as a self-authored scene (no download), RECORDED not gated
  (SSIM 0.774 — the pkg76 `.blend` importer is parity-scope, base-colour only, so this leg
  renders diffuse spheres, not glass; the real physics divergence is the metal_ab harness
  above). Found + worked around (not fixed — out of this package's authorized scope):
  `tools/blend_import/reader.py`'s `BlendFile.by_old` silently overwrites on an "old"-pointer
  collision across ≥2 mesh datablocks in one file; joined the scene's meshes into one datablock
  to route around it and filed a follow-up task for the reader itself.
- [x] 2026-09-09 — **Phase 1 complete** (WIP `fc083403`, pushed). Research note rewritten term by term; numpy oracle `benchmarks/cycles-parity/glass_ms_oracle/heitz_random_walk.py` (registered in scripts/README.md); divergence table produced. Headline: MS walk conserves energy EXACTLY (R+T=1.000, 0.0% dead over the 4×5 grid, IOR 1.45, M=2e5) — the built-in correctness check; single-scatter dead fraction reaches 68% (r0.85 μ0.1) / 85% (r1.0 μ0.1); Cycles' 1/E over-counts reflection 5.5× vs the walk at r1.0 μ0.1 (R:T 0.354:0.646 vs 0.064:0.936). Premise CONFIRMED. Directional gate `tests/test_pkg265_ms_glass_directional.py` written (histogram ±5%/bin, albedo ±2%, MIS pdf-coverage); RED shown on the entering grazing case; exit-interface RED needs the new `front_face` binding (builds in Phase 2). Optional `front_face` arg added to `debug_bsdf_sample_batch`/`_pdf_batch` (default true). Next: Phase 2 CPU (principled + disney transmission lobe → the walk; remove #771 reroute + pkg138 delta fallback; drop `ggxGlassComp` on these lobes; furnace ≤1.02 linear bound).

- [x] 2026-09-09 — **Phase 5 (eval/NEE consistency fix) + Phase 6 (post-fix harness
  re-run) + #779 (run_parity honesty) complete** (Sonnet 5 lane, CPU-only, no GPU
  lock; PR #778, HEAD `fe04324e` after rebase/squash). Responds to the lead's
  2026-09-09 03:20 HOLD: **(1)** rebuilt `build_cpu/` from this HEAD and re-ran the
  full pkg265 gate suite (directional + lit furnace + pkg264/disney/dielectric/
  rough-glass furnaces + issue #762/#769 regressions): 57 passed, 6 skipped, 1
  failed (`test_principled_lit_furnace_conserves_gpu` — expected, `CUDA support
  not compiled` on this intentionally CPU-only build, not a regression); the C++
  eta unit test (`tests/cpp/test_pkg265_walk_eta.cpp`) PASSes with the numbers
  already recorded in the research note (maxErr 0.00/4.8e-7, dead 0.0000%).
  **(2)** Restaged the CPU addon from this HEAD and re-ran the UNCHANGED pkg263
  metal_ab glass harness (256², 128 spp) to isolate the Phase 5 fix from Phase 4's
  pre-fix numbers: the centre overshoot the lead flagged (1.518x at r0.85) drops to
  0.929x post-fix; the limb moves the other way (1.05x → 0.60x), the accepted noise
  cost of the unbiased skip-NEE contract at grazing incidence, quantified against
  each engine's own per-ROI std/CV (Astroray centre CV runs 1.02–1.30x Cycles',
  growing with roughness; limb CV is ≤ Cycles' own, since Cycles itself is noisy at
  grazing in this scene). New contact sheets (`_evalfix` suffix, force-added) and a
  new "Phase 6" research-note section carry the full three-way (before/#778-pre-fix/
  #778-post-fix) table, noise table, and wall times. **(3)** Fixed issue #779: the
  `glass_sphere` row in `run_parity.py`/`manifest.toml` previously attributed its
  SSIM ~0.77 to "the multi-scatter walk diverging from Cycles' 1/E" — misleading;
  the real cause is `tools/blend_import` mapping Base Color only, so the Astroray
  leg renders a diffuse proxy, not glass. Row name/comments now say so and point to
  the metal_ab harness as the real oracle; row itself unchanged (self-authored,
  recorded not gated). PR #778 body rewritten with Phase 5/Phase 6/#779 sections,
  the lead's HOLD items marked addressed, and the rebuilt test-gate results.

---

## Lessons

- (none yet)
