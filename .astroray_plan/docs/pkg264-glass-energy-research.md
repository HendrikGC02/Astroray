# pkg264 — Glass BSDF energy research + MC oracle (cite-algorithm note)

**Date:** 2026-09-08
**Author lane:** package-implementer pkg264 (Opus 4.8), worktree `../Astroray-pkg264`,
branch `fix/pkg264-rough-glass-energy`.
**Status of this note:** research/diagnosis only. **No engine formula was changed.**
The oracle contradicts the spec's stated fix target *and* its stated mechanism;
this note is the evidence for the escalation in the lane report. See §6.

---

## 0. TL;DR (read this first)

1. **Wrong file.** The pkg263 render (and the pkg264 acceptance gate that re-runs
   it) does **not** exercise `plugins/materials/disney.cpp`. A Blender
   `ShaderNodeBsdfGlass` is translated to `kind:'principled'`
   (`blender_addon/__init__.py:4079`) and, with `use_native_principled` **ON by
   default** (`:290`, `:3862`, routed at `:4234`), renders through
   `plugins/materials/principled.cpp`'s `LobeKind::Transmission` lobe. `disney.cpp`
   is only reached with the flag OFF. The spec's "Files to modify → `disney.cpp`"
   and its "Non-goals → principled.cpp only if the note proves it shares the
   defect" are therefore inverted: the measured defect lives *entirely* in
   `principled.cpp`.

2. **Not dead samples.** The shipped `principled.cpp` glass sampler discards
   dead microfacet samples (`chooseAndSampleDir` `ds.ok==false` → `sample()`
   returns `f=0,pdf=0`, `principled.cpp:1986`) with **no fallback** (unlike
   `disney.cpp:855-909` which reroutes to a delta glass event). But the measured
   dead fraction is only **0–4 %** across the whole (roughness, θ) sweep — the
   estimator is essentially unbiased. This independently reproduces **pkg179
   Phase 1's own conclusion** (`.astroray_plan/docs/pkg179-…-research.md`): the
   "dead-sample" gap is a ~2–7 % measurement artifact, *not* a sampler
   regression, and Phase 2 was deliberately not started. The spec's "regime 2 =
   pkg179 Phase 2 dead-sample redistribution" premise is refuted twice.

3. **Per-interface energy is fine.** In a flux furnace (radiance 1/etap² undone)
   the shipped sampler delivers **0.77–1.00** of the incident flux with **zero**
   multi-scatter compensation; the boost needed to reach 1.0 is only
   **comp ≤ 1.29** at the worst cell (r 0.85, θ 60–75°). The shipped code already
   applies `ggxGlassComp ≥ 1` on top of this. A single glass interface therefore
   cannot be the source of pkg263's ~2× render deficit (Astroray/Cycles 0.34 at
   r 0.85 limb). The 2× must arise from **compounding over the many internal
   interface interactions inside the solid rough sphere**, and/or a
   **render-integration** effect (bounce-budget accounting, Russian roulette, or
   the compensation not reaching the render), **not** a per-interface BSDF
   formula error. Distinguishing these needs a render-level A/B (build + GPU
   lock), not a blind formula edit.

**Recommendation:** do not change any BSDF formula on the spec's current premise.
Escalate to the lead for a fix-target + mechanism decision (§6).

---

## 1. cite-algorithm — canonical sources (all already ported, license-compatible)

The glass path is a faithful port; every term already carries an in-code citation.
No new algorithm is required for diagnosis.

| Term | Canonical source | License | In-repo |
|---|---|---|---|
| GGX NDF D | Walter et al. 2007 "Microfacet Models for Refraction through Rough Surfaces" (EGSR) Eq. 33; PBRT-v4 §9.6 | — | `principled.cpp:132 D_GTR2` |
| Height-correlated Smith G2 / Λ | Heitz 2014 "Understanding the Masking-Shadowing Function…" JCGT 3(2) §3.2 Eq.72; Cycles `bsdf_microfacet.h` `bsdf_lambda` (BSD-3) | BSD-3 | `principled.cpp:153 smithLambda/:161 smithG2` |
| VNDF sampling | Heitz 2018 "Sampling the GGX Distribution of Visible Normals" JCGT 7(4); PBRT-v4 `TrowbridgeReitz::Sample_wm` (BSD-3) | BSD-3 | `principled.cpp:724 sampleGgxVNDF` |
| Dielectric transmission BTDF + Jacobian | Walter 2007 Eq. 21; PBRT-v4 `DielectricBxDF::f/PDF` (BSD-3) | BSD-3 | `principled.cpp:1287-1317 transmissionEvalRGB`, `:1445-1455 transmissionPdf` |
| Unpolarized dielectric Fresnel | PBRT-v4 §9.5; Cycles `bsdf_util.h fresnel_dielectric_cos` | BSD-3 | `principled.cpp:285 fresnelDielectric` |
| GGX multi-scatter energy preservation (glass) | Kulla & Conty 2017 "Revisiting PBS at Imageworks" Eq. 6-9; Cycles `microfacet_ggx_preserve_energy` + `table_ggx_glass_{E,Eavg,inv_E}` (BSD-3) | BSD-3 | `energy_compensation.h:38 ggxDarkeningChannel`, `principled.cpp:649 ggxGlassComp`, tables in `data/disney_compensation/ggx_glass_*.bin` |
| dielectric Fss (hemispherical-avg Fresnel) | Kulla & Conty 2017; Cycles `bsdf_util.h fresnel_dielectric_Fss` | BSD-3 | `disney.cpp:104 fresnelDielectricFss` (principled reuses tables) |

Cycles reference tree (Blender 5.2-era): `intern/cycles/kernel/closure/bsdf_microfacet.h`
(`bsdf_microfacet_ggx_glass_setup`, `bsdf_microfacet_sample/eval` transmission branch,
`microfacet_ggx_preserve_energy`), `kernel/tables.h` glass tables. PBRT-v4
`src/pbrt/bxdfs.h` `DielectricBxDF`. Both are Apache-2.0 / BSD-3 — compatible.

## 2. Term-by-term: Cycles vs `principled.cpp` vs `disney.cpp` (transmission lobe)

Structurally identical (both are the Walter/PBRT-v4 microfacet dielectric). The
only substantive differences:

| Term | Cycles combined glass closure | `principled.cpp` Transmission | `disney.cpp` glass branch |
|---|---|---|---|
| Masking G | height-correlated G2 = 1/(1+ΛO+ΛI) | **G2 height-correlated** (`smithG2`, :161) | separable **G1·G1** (`smithG1_GGX`, :70) |
| dead sample at grazing | reflect/refract both kept; combined closure | **`ds.ok=false` → f=0,pdf=0, NO fallback** (:1986) | reroute to **delta glass event** (:855-909) |
| multi-scatter comp | ONE factor on the combined closure | `ggxGlassComp` on eval only (:1305/1314) | `ggxGlassCompensationFactor` on eval only (:373/450) |
| radiance factor | `/etap²` on transmission | `/ (etap*etap)` (:1304/1313) | `/(etap*etap)` (:432) |

The `disney.cpp` delta-fallback is an *unintentional energy patch* (pkg150/pkg179):
it happens to return dead-sample energy to the path, which nudges its render
*toward* Cycles by accident. `principled.cpp` has no such patch. This means the
two plugins are **not** interchangeable for a "glass energy" fix and the spec's
disney-centric plan would not move the acceptance gate at all.

## 3. MC oracle — method

`test_results/2026-09-08-pkg264/glass_energy_oracle.py` reimplements the exact
`principled.cpp` transmission-lobe math and importance sampler in vectorized numpy
(every function line-cited to the shipped source), IOR 1.45, single front-facing
interface, white base. For roughness {0, 0.2, 0.5, 0.85} × θ {0, 30, 60, 75, 85}°:

- **True single-scatter albedo** R, T: for r ≤ 0.03 (delta) analytic (R=F, T=1−F,
  R+T=1 exactly — verified); for r > 0 by uniform-sphere MC of the exact BSDF
  (comp=1), split by hemisphere. **N_INT = 600 k**.
- **Realized estimator albedo**: simulate the shipped sampler (VNDF wm → Fresnel
  reflect/refract split → dead-sample `ds.ok`), average `eval·|cosI| / pdf` with
  dead samples counted as 0. **N_EST = 300 k**. This is the energy the renderer
  actually delivers per interface.
- **Flux furnace**: the transmission sub-lobe's `/etap²` radiance compression is
  undone (×etap²) so a lossless smooth interface integrates to **1.0** and a
  rough interface integrates to its single-scatter **flux efficiency E_ss** — the
  quantity Cycles' `preserve_energy` tables restore toward 1.

The single-interface *radiance* albedo (~0.5 for rough) is **not** an energy
metric — it entangles physical radiance compression (1/etap², undone at the exit
interface over a round trip) with single-scatter loss. Only the flux furnace
isolates the loss. This is the subtlety behind memory
`dielectric-dead-sample-needs-transmission-redistribution` and the #423 η² LUT
clamp; the oracle is built to avoid it.

## 4. MC oracle — results (flux furnace, comp = 1, IOR 1.45)

`flux_smooth` = 1.0 lossless reference. `E_ss` = shipped sampler flux efficiency
(single-scatter, uncompensated). `dead%` = dead-sample fraction. `comp_needed` =
1/E_ss = the multi-scatter boost to reach 1.0.

| r | θ | E_ss (flux, comp=1) | dead % | comp_needed |
|---|---|---|---|---|
| 0.00 | all | 1.000 | 0 | 1.000 |
| 0.20 | 0–60 | 1.000 | 0 | 1.000 |
| 0.20 | 75 | 0.996 | 0 | 1.004 |
| 0.20 | 85 | 0.946 | 2 | 1.057 |
| 0.50 | 0 | 0.993 | 1 | 1.007 |
| 0.50 | 30 | 0.989 | 1 | 1.011 |
| 0.50 | 60 | 0.962 | 2 | 1.039 |
| 0.50 | 75 | 0.924 | 2 | 1.082 |
| 0.50 | 85 | 0.920 | 1 | 1.087 |
| 0.85 | 0 | 0.944 | 4 | 1.059 |
| 0.85 | 30 | 0.919 | 4 | 1.088 |
| 0.85 | 60 | 0.825 | 3 | 1.213 |
| 0.85 | 75 | 0.773 | 2 | 1.294 |
| 0.85 | 85 | 0.801 | 1 | 1.249 |

**Reading:** worst per-interface single-scatter loss is ~23 % (r 0.85, θ 75°),
comp_needed 1.29. The shipped `ggxGlassComp` already applies a ≥1 boost on top, so
the shipped per-interface efficiency is ≥ these numbers. Dead-sample fraction
never exceeds 4 %.

**pkg263 measured render deficit for comparison** (Astroray/Cycles, linear):
r 0.85 limb **0.34**, centre **0.53**; r 0.5 limb 0.44, centre 0.81. These are
**far** below the ≤ 1.29× single-interface headroom. A single interface cannot
produce them.

## 5. What the oracle does and does NOT establish

**Establishes (robust):**
- The pkg263 render path is `principled.cpp`, not `disney.cpp`.
- The `principled.cpp` glass sampler is ~unbiased (dead ≤ 4 %); dead-sample
  redistribution is not the mechanism (corroborated by pkg179 Phase 1).
- One glass interface is 77–100 % flux-efficient uncompensated; ≥ that
  compensated. Not a 2× source.

**Does NOT establish (needs a render-level A/B under the GPU lock):**
- Whether the ~2× render deficit is (a) **compounding** of ~10–20 % per-interface
  losses over the many internal interactions in the solid rough sphere (a real,
  Cycles-vs-Astroray-differential effect *if* Astroray's per-interface
  compensation under-performs Cycles' combined-closure comp across a chain), or
  (b) a **render-integration** artifact — transmission-bounce budget accounting,
  Russian-roulette termination of long internal glass paths, or `ggxGlassComp`
  tables not loaded/applied at render time (`DisneyEnergyCompensationTables::
  instance().loaded()` must be verified in the actual render build), or (c) the
  reflection sub-lobe / limb Fresnel handling specific to the sphere geometry.
- The correct fix (if any) and its file. The measured gate is `principled.cpp`.

The decisive next experiment is a **single-vs-multi-bounce render A/B**: render the
pkg263 glass sphere capping transmission bounces at 1, 2, 4, 12 in both engines. If
Astroray tracks Cycles at low bounce caps and diverges only as the cap rises, the
deficit is compounding (BSDF/comp); if it diverges even at cap 1–2, it is
integration/config. This is ~30 min under the GPU lock and should precede any
formula change.

## 6. Recommendation / questions for the lead

The spec's fix target (`disney.cpp`) and mechanism (rough-transmission dead-sample
energy loss, pkg179 Phase 2) are both contradicted by the oracle and by pkg179's
own Phase 1 finding. Per CLAUDE.md §1 and the brief's "before I sink hours" rule I
am stopping before any engine edit and asking:

- **Q1 (target).** Confirm the fix target is `principled.cpp`'s Transmission lobe
  (what the gate renders), not `disney.cpp`. If `disney.cpp` is genuinely wanted,
  the acceptance criterion "re-run the pkg263 harness" cannot validate it (harness
  uses native-principled by default) — the spec would need the harness pinned to
  `use_native_principled=False`.
- **Q2 (mechanism).** Authorize the single-vs-multi-bounce render A/B (§5) as the
  first engine-level step, so the fix targets the measured mechanism rather than
  the spec's assumed one. Only after that should any formula/comp change be made.
- **Q3 (scope).** If the A/B shows compounding per-interface comp under-performance,
  the fix is the `ggxGlassComp`/`table_ggx_glass_*` application in `principled.cpp`
  (and its GPU twin), not a new dead-sample term. Confirm this is in scope for
  pkg264 or should be re-filed.

Until Q1–Q2 are answered I have not modified any `.cpp/.h`. The oracle and this
note are committed as the package's first deliverable.

---

## 7. CONTINUATION (2026-09-08 15:20, lead answers Q1–Q3) — mechanism found, fixed

The lead answered: Q1 target = `principled.cpp` transmission lobe + its GPU twin
(`disney.cpp` out of scope). Q2 = run the render-level A/B first. Q3 = fix whatever
(a)–(d) isolates in principled.cpp (+ GPU mirror). This section records the A/B and
the fix.

### 7.1 Render-level A/B — bounce caps and filter_glossy REFUTED

In-process reproduction of the pkg263 scene through the raw engine binding
(`test_results/2026-09-08-pkg264cont/ab_harness.py`, build_cuda .pyd, CPU, 128 spp,
200²), sweeping ONE integrator lever at a time. Centre disc (<0.35R) / limb annulus
(0.80–0.98R) means vs the pinned pkg263 Cycles numbers:

| r | cfg | c/Cyc | l/Cyc |
|---|---|---|---|
| 0.0 | baseline d4/g4/t12 | 0.948 | 0.954 |
| 0.0 | high_all_64 | 0.948 | 0.952 |
| 0.2 | baseline | 0.934 | 0.719 |
| 0.5 | baseline | 0.809 | 0.502 |
| 0.85 | baseline | 0.520 | 0.366 |

Lever (a) transmission/glossy/total bounce cap (12 vs 64, and each per-type
isolated) and filter_glossy (0 vs 1) are **byte-identical at r=0 and move the
ratio by <0.5% at r=0.85** — REFUTED as the mechanism. The lead's prediction (a)
is wrong. The pattern is instead a **roughness-driven whole-silhouette energy
loss**: both centre and limb fall increasingly below Cycles as roughness rises,
while r=0 already matches Cycles (0.95). (b) Russian roulette has no engine setter
and r=0 already matches Cycles so RR is not implicated. (c) is the answer — see 7.2.

A second, smaller effect: the pkg263 **addon** r=0 limb (0.232) is ~15% below both
Cycles (0.284) and this in-process engine render (0.271). So a minor r=0 limb loss
is introduced by the addon render path (not the core engine BSDF/integrator, which
matches Cycles at r=0). It is dominated by the roughness loss below and is left as a
separate, small follow-up.

### 7.2 White-furnace isolation — principled rough transmission LOSES ENERGY

`test_results/2026-09-08-pkg264cont/furnace_probe.py`, IOR 1.45, clear glass in a
uniform white field (invisible ⇒ target 1.0), CPU 256 spp; GPU leg
`gpu_furnace_check.py` under the GPU lock:

| r | principled CPU | principled GPU | disney CPU | disney GPU |
|---|---|---|---|---|
| 0.0 | 0.997 | — | 0.997 | — |
| 0.2 | 0.993 | 0.994 | 0.992 | 0.996 |
| 0.5 | 0.909 | 0.908 | 0.967 | 1.015 |
| 0.85 | 0.645 | 0.642 | 0.962 | 1.033 |
| 1.0 | 0.524 | 0.526 | 0.957 | 1.005 |

The native `principled` transmission lobe is **not energy-conserving** at high
roughness on **either backend**, while `disney` glass **is**. The ~0.20
per-interface loss compounds over the sphere's two interfaces (0.8²≈0.64) to match
the ~0.5× render deficit. This furnace is now the mechanism gate
(`tests/test_pkg264_glass_cycles_parity.py`).

### 7.3 Root cause — dropped dead microfacet samples (no delta fallback)

`principled.cpp chooseAndSampleDir` (and its GPU twin `gpu_pr_chooseAndSampleDir`)
returns an **absorbing dead sample** (`ds.ok=false` ⇒ `sample()` `f=0,pdf=0`) when a
grazing VNDF microfacet fails BOTH reflection (wi below the surface) and refraction
(below-horizon / micro-TIR). On the solid sphere's **exit** interface (dense→rare,
near the critical angle) this dead rate is high and rises with roughness — the
entering-interface dead rate is only 0–4% (research note §4, corroborated by
`deadrate.py`), which is why §4's single-front-interface oracle under-counted it.

`disney.cpp` does NOT lose this energy because on a dead rough sample it **falls
through to a smooth delta glass event** (disney.cpp:844-912; its own comment: a
"return a dead (pdf=0) sample instead of this delta fallback … MEASURED to regress
energy conservation severely — white-furnace collapsed … to ~0.0"). The GPU
`gpu_disney_sample` has the same fallback. The native-principled samplers lacked it.

### 7.4 Fix

On a dead rough transmission sample, fall through to the existing smooth delta glass
event instead of returning black — `if (ds.ok) return ds;` then let control reach the
delta block (which sets `ds.isDelta=true` and the Fresnel-cancelling f/pdf the delta
`sample()`/`sampleSpectral()` branch already handles). Two lines mirrored, byte-for-
byte across the CPU/GPU twins:
- `plugins/materials/principled.cpp` `chooseAndSampleDir`
- `include/astroray/gpu_materials.h` `gpu_pr_chooseAndSampleDir`

No compensation invented; no formula changed; disney untouched. The comp factor
(`ggxGlassComp`) and the tables were confirmed to LOAD and apply (disney uses the
same math and conserves) — they were never the defect.

**Spec scope correction:** the fix is `principled.cpp` (+ GPU twin), NOT `disney.cpp`
as the spec's Files-to-modify originally listed; the acceptance render (pkg263
harness) renders native-principled by default. Recorded per the lead's Q1 decision.

### 7.5 Verification — furnace fixed, harness before/after, residual is engine-wide

**White furnace (IOR 1.45, target 1.0), worktree build (sha 459ab63, sm_120):**

| r | principled CPU before → after | GPU after | disney (guard) |
|---|---|---|---|
| 0.5 | 0.909 → 0.968 | 0.968 | 0.967 |
| 0.85 | 0.645 → 0.958 | 0.956 | 0.962 |
| 1.0 | 0.524 → 0.955 | 0.955 | 0.957 |

`tests/test_pkg264_glass_cycles_parity.py`: 3 passed (CPU+GPU). Regression suite
(furnace/caustic/energy/pkg178 GPU furnace/rough-glass): **289 passed**.
`stageShadeBucketedKernel` **REG:254** held (STACK 7968–8672); the delta fallback
reuses existing code, register-neutral.

**pkg263 Blender harness re-run (256², 128 spp, CPU addon from this branch,
native-principled), Astroray/Cycles per-ROI (before = pkg263 PR #764):**

| ROI | r | before | after | Cycles |
|---|---|---|---|---|
| centre | 0.5 | 0.809 | 0.873 | 1.0 |
| centre | 0.85 | 0.525 | 0.742 | 1.0 |
| limb | 0.5 | 0.443 | 0.490 | 1.0 |
| limb | 0.85 | 0.342 | 0.556 | 1.0 |

r=0/0.2 unchanged (delta/near-delta, no dead samples). Contact sheets
`.astroray_plan/docs/pkg264/postfix_harness/glass_r085__contact_sheet.png`:
the r=0.85 Astroray sphere is now a **bright frosted glass**, not the pkg263
dark-grey ball (visually inspected).

**Residual (NOT the pkg264 defect).** After the fix, `principled` in the same
in-process lit scene equals the trusted `disney` sibling (r=0.85 centre 0.767 vs
disney 0.751; limb 0.650 vs 0.565 — principled now ≥ disney). The remaining gap to
Cycles (centre ~0.74×, limb ~0.56× at r=0.85, growing with roughness) is present in
**disney too**, and the furnace conserves for both (~0.96). So it is an
**engine-wide rough-glass angular-appearance gap vs Cycles** (multiscatter angular
lobe / VNDF distribution / reflection-lobe roughness response — Cycles adds a
diffuse-like multiscatter lobe, Astroray applies a scalar comp boost), NOT the
principled-specific energy loss pkg264 scoped. Recommend a follow-up package for the
engine-wide gap; pkg264 delivers the principled=disney energy fix (CPU+GPU).
