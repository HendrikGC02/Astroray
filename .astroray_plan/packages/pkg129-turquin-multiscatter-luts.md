# pkg129 — Reflection multiscatter energy compensation via Turquin albedo-scaling LUTs (CPU+GPU parity)

**Pillar:** 2 (materials / BSDF energy correctness)
**Track:** A (CPU-gated rough-metal furnace + chi² gates on CI; GPU spectral-closure leg RTX-verified against the CPU result, with a live-Cycles A/B on rough metals)
**Codex-paste-ready:** no (a LUT port that must be reconciled against two existing compensation implementations of different heritage, replace a GPU placeholder, and hold chi² gates that depend on a sibling pdf adjudication — needs judgment, not a mechanical patch)
**Status:** open — closes the *reflection* multiscatter gap (the counterpart to pkg118's transmission fix), and gives the GPU spectral path its first physically-based reflection multiscatter term
**Estimated effort:** M (port 7 verified LUTs with a CUDA backend + apply on both paths + reconcile with the existing CPU compensation + re-gate furnace/chi²; the LUTs are pre-baked and license-clean, so the work is integration and validation, not derivation)
**Depends on:** **pkg123** (Disney spec-lobe sample/pdf adjudication — the residual finding from pkg121). The multiscatter factor **multiplies the single-scatter GGX lobe throughput**; if the underlying lobe's `sample()`/`pdf()` shape is still mismatched (pkg121 localised a spec-lobe shape bug that fails chi² on every metallic config), the furnace and chi² interpretation of this compensation is confounded. pkg123 must land the corrected single-scatter baseline first so pkg129 is measured against, and gated by, a correct lobe. **Composes with** pkg60 (CPU Kulla-Conty GGX reflection compensation, DONE) and pkg118 (rough-*dielectric*/transmission multiscatter, DONE) — see Root cause for how the three relate.

---

## Goal

**Before:** Reflection multiscatter energy compensation is **inconsistent across the
two backends and of mixed heritage**:

- **CPU** Disney reflection uses **Kulla-Conty** albedo compensation
  (`ggxCompensationFactor`, `plugins/materials/disney.cpp:43-51`, applied at
  `:381-385`) off the pkg60 `ggxE` LUT
  (`include/astroray/energy_compensation.h`) — a working, physically-based term.
- **GPU** wavefront metal shade has **no working reflection multiscatter**:
  `ggxMultiScatterCompensation` in `src/gpu/wavefront/stage_shade_metal.cu:114-116`
  is a **placeholder that returns 0** (comment: *"Simplified placeholder: return 0
  for now"*), and the actual multiscatter energy is a hand-tuned, non-physical hack
  `albedo · (Fms · roughness·(2-roughness) · 1.3)` (`stage_shade_metal.cu:211-214`).
  So GPU rough metals lose (or mis-add) energy at high roughness with no LUT behind it.

Modern Cycles has moved past both: Blender commit `888bdc1` **deleted** its
Heitz-2016 stochastic multiscatter GGX and replaced it with **Turquin-style
albedo scaling of the single-scatter lobe via precomputed LUTs** (PR
blender/blender#107958), on the rationale that *"having the exact correct
directional distribution is not that important as long as the overall albedo is
correct."*

**After:** Reflection multiscatter compensation is a **single Turquin-style
albedo-scaling LUT set, ported once and applied identically on CPU and GPU**. The
GPU placeholder/hack is replaced by a real device-side LUT lookup; the CPU path is
reconciled onto the same tables (or a documented equivalence between Kulla-Conty and
Turquin scaling is recorded). Rough-metal white-furnace at high roughness moves
**toward unity on both backends**, the chi² sampler gates stay green (compensation
scales throughput, not the sampling distribution), and a live-Cycles A/B on rough
metals confirms parity with the reference that made the same Turquin switch.

---

## Root cause / relationship to pkg60, pkg118, pkg123

The pass-2 research answered this axis directly
(`.astroray_plan/docs/2026-07-pbr-advances-research-pass2.md` Axis B, two claims
✅-VERIFIED by direct fetch):

- Cycles' current (4.x-era) energy conservation **is** Turquin albedo scaling, not
  Heitz stochastic multiscatter and not the Kulla-Conty second lobe — commit
  `888bdc1`, PR #107958. Generator `intern/cycles/app/cycles_precompute.cpp`, tables
  in `intern/cycles/scene/shader.tables`.
- **`adobe/openpbr-bsdf` is Apache-2.0** and ships **7 precomputed multiscatter
  energy LUTs** (ideal/opaque dielectrics, ideal metals) + an LTC fuzz table,
  portable across **C++/GLSL/CUDA/MSL/Slang** with LUTs embeddable as arrays or GPU
  textures — a directly portable CUDA-compatible reference. This is the port pair.

How this sits with the shipped energy work:

- **pkg60** added Kulla-Conty reflection compensation **on CPU only** (its non-goal:
  *"Do not port to GPU"*). pkg129 is the deferred GPU counterpart the pkg60 Lessons
  explicitly flagged (*"GPU compensation is the obvious follow-up… port the same LUTs
  to a device-side texture lookup"*) — but done with the **Turquin LUTs that modern
  Cycles actually uses**, and with the CPU path reconciled so both backends share one
  table set instead of the current Kulla-Conty(CPU)/placeholder(GPU) split.
- **pkg118** fixed *transmission* (rough-glass) multiscatter energy. Its research
  note is explicit that this axis is the **reflection** counterpart at high roughness
  (`2026-07-pbr-advances-research-pass2.md`: *"pkg118 fixed transmission energy — this
  axis is reflection multiscatter at high roughness"*).
- **pkg123** (dependency) fixes the Disney spec-lobe sample/pdf shape mismatch. Since
  Turquin scaling multiplies the single-scatter lobe, a wrong lobe underneath would
  make both the furnace ratio and the chi² gate un-interpretable. Land pkg123 first.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### A. Port the Turquin multiscatter LUTs (the port pair)

- Port the multiscatter energy LUTs from **`adobe/openpbr-bsdf` (Apache-2.0)** — the
  metal/dielectric reflection tables — using its **CUDA backend** so the same table
  data serves the GPU path directly (embed as device arrays or textures, as the
  reference supports). Store alongside the existing pkg60 tables
  (`data/disney_compensation/`, loaded via
  `include/astroray/energy_compensation.h`); extend
  `DisneyEnergyCompensationTables` rather than adding a parallel loader.
- Apply **Turquin albedo scaling**: scale the single-scatter GGX reflection lobe so
  the total directional albedo integrates to the multiscatter-complete value
  `ρ_ms = F_ms · k_ms · ρ_ss` (Turquin's `E`-scaling form). This trades exact
  reciprocity for energy preservation — the documented Turquin tradeoff, and the one
  Cycles accepted in #107958.
- **Cite:** Turquin 2019, "Practical multiple scattering compensation for microfacet
  models" (blog.selfshadow.com/publications/turquin/ms_comp_final.pdf);
  `adobe/openpbr-bsdf` (Apache-2.0) as the LUT + CUDA-backend source; Cycles
  `intern/cycles/app/cycles_precompute.cpp` + `intern/cycles/scene/shader.tables`
  (Apache-2.0, PR #107958, commit `888bdc1`) as the production cross-check.

### B. Replace the GPU placeholder with the real lookup

- Delete the `stage_shade_metal.cu:114-116` return-0 placeholder and the
  `:211-214` ad-hoc `roughness·(2-roughness)·1.3` hack; apply the ported LUT-based
  Turquin scaling to the GPU single-scatter metal lobe. This is the concrete
  correctness win — the GPU had **no** physically-based reflection multiscatter
  before.

### C. Reconcile the CPU path onto the same tables

- Either (i) switch the CPU `ggxCompensationFactor`
  (`disney.cpp:43-51`, `:381-385`) to the Turquin LUTs so CPU and GPU are bit-for-bit
  the same scaling, or (ii) keep pkg60's Kulla-Conty on CPU **only if** a documented
  furnace-equivalence to Turquin scaling is established within tolerance. Prefer (i)
  for single-source-of-truth; the research recommendation is Turquin as the target
  model. Record the choice and its furnace evidence in the research note. Note the
  `metal.cpp` lobe currently references an Fdez-Agüera fit
  (`stage_shade_metal.cu:111` comment "Mirrors metal.cpp ggxMultiScatterCompensation")
  — fold that onto the same tables too, so no third heritage survives.

### D. Furnace + chi² + Cycles A/B gates

- **Rough-metal white-furnace:** high-roughness rough-metal furnace ratio moves
  **toward unity** on **both** CPU and GPU (reuse the pkg60/pkg118 furnace harness;
  gate e.g. ∈ [0.97, 1.03] at R ∈ {0.6, 0.8, 1.0} for metallic=1). Assert the GPU
  column matches the CPU column (the placeholder made them diverge).
- **chi² gates stay green:** compensation multiplies throughput, not the sampling
  pdf, so `tests/statistical/test_chi2_bsdf.py` metal configs must not regress —
  **this is why pkg123 is a dependency**: the chi² gate is only meaningful once the
  spec-lobe shape is adjudicated. Un-xfail nothing here that pkg123 owns; just prove
  no regression.
- **Live-Cycles A/B on rough metals:** render a rough-metal sweep in headless Cycles
  (which uses the same Turquin LUTs) and confirm image-plane radiance parity within
  tolerance — the strongest external check, since we are matching the exact model
  Cycles ships.

---

## Acceptance criteria

- [ ] Turquin multiscatter LUTs ported from `adobe/openpbr-bsdf` (Apache-2.0) with
      its CUDA backend; tables loaded via `DisneyEnergyCompensationTables`
      (`energy_compensation.h`), one table set for both backends.
- [ ] GPU placeholder (`stage_shade_metal.cu:114-116`) and ad-hoc hack
      (`:211-214`) removed and replaced by the real LUT-based Turquin scaling; GPU
      rough-metal furnace has physically-based compensation for the first time.
- [ ] CPU path reconciled onto the same tables (option i preferred), or a documented
      furnace-equivalence recorded (option ii); no third compensation heritage left.
- [ ] Rough-metal furnace ∈ tolerance toward unity at R ∈ {0.6, 0.8, 1.0},
      metallic=1, **on both CPU and GPU**, and the two columns agree.
- [ ] chi² sampler gates (`tests/statistical/test_chi2_bsdf.py`) stay green — no
      regression from the throughput scaling (validated on the pkg123-corrected lobe).
- [ ] Live-Cycles A/B on a rough-metal sweep within tolerance.
- [ ] Research note `.astroray_plan/docs/reflection-multiscatter-turquin-research.md`:
      Turquin 2019 + `adobe/openpbr-bsdf` (Apache-2.0, pinned commit) + Cycles
      #107958 (`cycles_precompute.cpp` / `shader.tables`, commit `888bdc1`); the
      CPU reconciliation decision with furnace evidence; CLAUDE.md §6 citations at
      every scaling call site.

---

## Non-goals

- **Not transmission multiscatter.** pkg118 fixed rough-dielectric/transmission
  energy; this package is **reflection** multiscatter only. Do not re-touch the
  transmission lobe.
- **Not the sheen/clearcoat lobes.** Their compensation is pkg60 (sheen LTC,
  clearcoat slice). This package is the GGX metal/dielectric **reflection** lobe.
- **Not a Heitz-2016 stochastic multiscatter rewrite.** The research (and Cycles
  #107958) explicitly chose albedo-scaling LUTs over stochastic evaluation
  (7–15× slower for minimal visual difference); do not port the stochastic path.
- **Not the Disney spec-lobe pdf fix.** That is pkg123 (this package's dependency);
  pkg129 does not adjudicate the sample/pdf shape, it consumes the corrected lobe.
- **Not fuzz / LTC.** The `adobe/openpbr-bsdf` fuzz LTC table is out of scope; port
  only the metal/dielectric reflection multiscatter LUTs.
- **No LUT regeneration from scratch.** The tables are pre-baked and license-clean
  (CLAUDE.md §6: borrow, don't re-derive) — port them, don't run a new ground-truth
  MC bake.

---

## Provenance

Filed from the **2026-07-18 PBR-advances follow-up pass**
(`.astroray_plan/docs/2026-07-pbr-advances-research-pass2.md` Axis B — the two
load-bearing claims verified by direct fetch: Blender commit `888bdc1` /
PR #107958 replacing stochastic multiscatter with Turquin albedo scaling, and
`adobe/openpbr-bsdf` Apache-2.0 with 7 CUDA-portable multiscatter LUTs). Grounded
against the live compensation code: CPU Kulla-Conty in `disney.cpp` (pkg60) and the
**GPU placeholder returning 0** in `stage_shade_metal.cu` — the concrete reflection
multiscatter gap this closes, and the GPU follow-up the pkg60 Lessons flagged.
Reflection counterpart to pkg118's transmission fix. Owner context: rough metals at
high roughness reading dark is part of the standing Cycles-parity story; matching the
exact Turquin model Cycles ships is the cleanest way to close it, and the A/B on
rough metals is a journal-article parity figure.

---

## Progress

- [ ] A — Turquin LUTs ported from `adobe/openpbr-bsdf` (Apache-2.0) + CUDA backend;
      loaded via `DisneyEnergyCompensationTables`.
- [ ] B — GPU placeholder/hack replaced by the real LUT lookup.
- [ ] C — CPU path reconciled onto the same tables (decision recorded).
- [ ] D — rough-metal furnace toward unity on both backends; chi² green; Cycles A/B.
- [ ] Research note written.

---

## Lessons

*(Fill in after the package is done.)*
