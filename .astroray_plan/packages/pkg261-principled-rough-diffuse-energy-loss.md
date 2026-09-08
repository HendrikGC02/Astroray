# pkg261 — Principled diffuse energy loss at high specular roughness (Cycles parity)

**Pillar:** 5
**Track:** A
**Status:** in-progress — CPU+GPU fix implemented and verified (sweep +-2.2-2.7% vs Cycles CPU/GPU, REG:254 held, furnace floors re-derived 0.85->0.97); PR pending
**Estimated effort:** 1–2 sessions (~4–6 h; CPU fix + GPU closure-graph mirror under the GPU lock)
**Depends on:** pkg178, pkg253, pkg258

---

## Goal

Before: a Principled dielectric (metallic 0, transmission 0) loses ~6–7 % of
its diffuse energy at specular roughness 0.85 relative to Cycles under the same
light (sun lamp or HDRI), while roughness 0 matches Cycles to 1 %; every
diffuse-dominant Blender surface with a rough specular layer therefore renders
darker than Cycles, and the pkg178 furnace tests tolerate a 15 % diffuse loss
at roughness 0.5 against an Astroray-internal reference. After: the Principled
diffuse/specular layering reproduces Cycles' `closure_layering_weight` +
microfacet albedo estimate numerically across roughness 0…1 on CPU and GPU, the
`hdri_exterior_hair` ground strip and the `metal_sweep` floor blocks land
within the ±5 % gate-(c) band, and the furnace floors are re-derived against
Cycles rather than against Astroray itself.

---

## Context

The pkg258 residual (Astroray ground rows 7–17 % under Cycles with env NEE on)
was diagnosed on 2026-09-08 (`pkg258-ground-residual-diagnosis-2026-09-08.md`,
#756): not env NEE, not the firefly clamp, not occlusion — the deficit is gated
by Principled specular roughness alone and reproduces under a plain Sun lamp.
This is a Pillar 5 BSDF-parity defect on the most common Blender material and a
direct gate-(c) blocker (material zoo floor blocks 1.06, HDRI ground 0.925).
`cite-algorithm` applies: the layering is Cycles' `closure_layering_weight`
(`bsdf_util.h`) fed by `bsdf_microfacet_estimate_albedo` (`bsdf_microfacet.h`);
nothing is invented.

---

## Evidence

- 2026-09-08: ground-only `hdri_exterior_hair` variants, 160×90, 32 spp, CPU,
  Astroray/Cycles ground-strip ratio (R/G/B): Principled roughness 0 → 0.989
  (1.006/0.984/0.975); roughness 0.85 → 0.926 (0.946/0.919/0.913); Sun lamp
  only, no HDRI: roughness 0 → 1.000, roughness 0.85 → 0.936 (0.952/0.936/0.921);
  grey albedo, roughness 0.85 → 0.936 (channel spread narrows to 1.5 pp).
- 2026-09-08: firefly clamp forced 0 → 0.925 (no change); Hair hidden → 0.921;
  all other objects hidden → 0.926 (no change).
- 2026-09-08: `tests/test_principled_bsdf.py:83-86` and
  `tests/test_pkg178_principled_gpu_furnace.py:70` assert only `floor=0.85`
  (15 % loss tolerated) for Principled diffuse at roughness 0.5 vs a white
  Lambertian — a self-referential tolerance never checked against Cycles.
- 2026-09-08: the addon maps `BSDF_DIFFUSE` to Principled (`blender_addon/__init__.py:4059-4064`)
  with the default specular layer, so the "plain Diffuse" control in the
  diagnosis carried a 4 % dielectric specular Cycles' Diffuse BSDF lacks
  (+11 % overshoot on a sky-lit ground) — tracked separately as an addon issue,
  not part of this package.

---

## Reference

- Diagnosis: `.astroray_plan/docs/pkg258-ground-residual-diagnosis-2026-09-08.md`
  (experiment table E0–E5, evidence PNGs under `pkg258-ground-residual/`).
- Astroray: `plugins/materials/principled.cpp` — `ggxCompFactor` (~L625),
  `ggxDirectionalAlbedo` (~L638), `layeringWeightAfter` (~L663), the specular
  layer site (~L965-966), coat (~L865-866), sheen (~L846);
  `include/astroray/energy_compensation.h` (`DisneyEnergyCompensationTables`,
  `ggxDarkeningChannel`); GPU closure-graph mirror in
  `include/astroray/gpu_materials.h` (Principled lowering) and the
  `HasPrincipled` shade path in `src/gpu/wavefront/stage_advance.cu`.
- Cycles (Apache-2.0): `intern/cycles/kernel/closure/bsdf_util.h`
  (`closure_layering_weight`), `bsdf_microfacet.h`
  (`bsdf_microfacet_estimate_albedo`, `microfacet_ggx_preserve_energy`,
  the `ggx_E`/`ggx_Eavg` tables in `kernel/tables.h`),
  `svm/closure.h` (Principled specular layer placement and `bsdf_albedo` use),
  `bsdf.h` (`bsdf_albedo`).
- Memories: `spectral-upsample-nonlinearity-scaled-bsdf` (the secondary blue
  skew), `rough-glass-residual-is-multiscatter` (a previous albedo-LUT clamp bug
  in the same table family), `closure-graph-lobe-count-spills-fused-kernel`.

---

## Prerequisites

- [x] #756 merged (diagnosis + evidence).
- [ ] Build passes on main; `.pyd` newer than HEAD before any GPU number.
- [ ] GPU lock held for the CUDA build and the GPU furnace/parity runs.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg261_principled_rough_diffuse.py` | Roughness sweep (0, 0.3, 0.5, 0.85, 1.0) of a Principled dielectric under a sun lamp on CPU and GPU: per-roughness mean vs a pinned Cycles reference (rendered headless, numbers + provenance in the test docstring) within ±3 %; directional-albedo unit check — `ggxDirectionalAlbedo(F, r, mu)` vs an independent Monte-Carlo estimate of the GGX+dielectric-Fresnel albedo at the same (r, mu) within 2 % over a grid. |
| `.astroray_plan/docs/pkg261-principled-layering-research.md` | `cite-algorithm` note: Cycles' layering formula, albedo estimate, table lookup and clamps, with line pointers; what Astroray computes today; the numeric diff per (roughness, mu). |
| `data/disney_compensation/ggx_gen_schlick_ior_s.bin` | **[lead-approved scope widening 2026-09-08]** Cycles' `table_ggx_gen_schlick_ior_s[4096]` 16^3 LUT (Apache-2.0, `blender/blender@eaa5f63b`), extracted verbatim — the layering-albedo table Astroray did not previously ship. |
| `data/disney_compensation/README.md` | **[lead-approved]** provenance note for the extracted LUT. |
| `scripts/data/extract_ggx_gen_schlick_ior_s.py` | **[lead-approved scope widening]** generator that parses the Cycles `shader.tables` C initializer and writes the `.bin` (registered in `scripts/README.md`). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/principled.cpp` | Make the specular-layer albedo used by `layeringWeightAfter` match Cycles' `bsdf_microfacet_estimate_albedo` for the dielectric GGX (single-scatter E·F with Cycles' compensation, not the current `E·F·darkening` product if that is the error); apply the same correction to the coat and sheen layering sites if the research note shows they share it; cite lines. |
| `include/astroray/gpu_materials.h` | Mirror the corrected albedo in the GPU Principled lowering so CPU/GPU stay at parity (REG on `stageShadeBucketedKernel` must stay 254; report STACK). |
| `include/astroray/energy_compensation.h` | pkg261: add the `ggxGenSchlickIorS(roughness, mu, z)` accessor + the 16^3 table storage + the GPU-upload data accessor (the missing table was the defect, not a clamp bug). |
| `src/energy_compensation.cpp` | **[lead-approved]** load `ggx_gen_schlick_ior_s.bin` and implement `ggxGenSchlickIorS` (trilinear, same axis order as the glass tables). |
| `include/astroray/gpu_ggx_tables.cuh` | **[lead-approved]** device twin `gpu_ggxLayeringAlbedo` + `gpu_gen_schlick_sample3D` (mirrors the pkg151 `ggx_glass_E` device lookup). |
| `src/gpu/gpu_ggx_tables.cu` | **[lead-approved]** upload the 16^3 table to the `g_ggxGenSchlickIorS` device symbol in `uploadGgxTables()`. |
| `scripts/README.md` | **[lead-approved]** register the new table generator in the per-task index. |
| `tests/test_principled_bsdf.py` | Re-derive the diffuse-energy `floor` from the Cycles reference (expect ≈ 0.97 at roughness 0.5, not 0.85); keep the energy-GAIN ceiling. |
| `tests/test_pkg178_principled_gpu_furnace.py` | Same floor re-derivation for the GPU twin. |
| `.astroray_plan/packages/pkg258-hdri-environment-nee-importance-sampling.md` | Lessons: the ground residual is owned here. |

### Key design decisions

- **Find the number before the formula.** Step 1 is the research note with a
  per-(roughness, mu) table: Astroray's `ggxDirectionalAlbedo` vs Cycles'
  estimate vs an independent MC albedo. The fix targets whichever term
  disagrees; no re-tuning of tolerances to make a gate pass.
- **Layering stays Cycles-shaped.** `closure_layering_weight` is
  `weight * (1 - saturate(max_channel(albedo)))`-style; keep the existing
  per-channel form only if the note shows it is equivalent for the tested cases.
- **CPU first, GPU mirror second**, both gated by the same sweep test; the
  closure-graph lowering must not add lobes (memory
  `closure-graph-lobe-count-spills-fused-kernel`).
- **Secondary blue skew is out of scope** unless the corrected layering removes
  it; otherwise record the residual per channel in Lessons.

---

## Acceptance criteria

- [x] `tests/test_pkg261_principled_rough_diffuse.py` green on CPU and GPU:
      every roughness in the sweep within ±3 % of the pinned Cycles reference
      (CPU 2.20-2.71 %, GPU 2.19-2.72 %, sha d28394da). Albedo unit check: the
      Cycles `s`-table fit deviates from the raw VNDF MC oracle up to 3.25× at
      high roughness (research note §5), so the gate asserts the port reproduces
      the **Cycles reference** `mix(f0,1,s)` within 0.002 — the parity target —
      and records the MC comparison as documentation (lead-surfaced deviation).
- [~] `hdri_exterior_hair` ground-strip ratio (ground-only, roughness 0.85,
      160×90, 32 spp, CPU) rises **0.926 → 0.962** (Astroray 0.11188 / Cycles
      0.11634, Cycles matches pkg258 E2b 0.11634 exactly); sky strip unchanged at
      1.002. **Short of the ≥0.97 target by ~0.8 pp.** Per-channel A/C = R 0.982
      / G 0.954 / B 0.947 — the residual is blue-dominated, i.e. the **secondary
      spectral-upsampling skew** the Non-goals scope OUT of pkg261 (memory
      `spectral-upsample-nonlinearity-scaled-bsdf`), not a layering-albedo
      shortfall: the controlled normalised sweep (grey material, black world,
      sun) matches Cycles within ±3 % on both backends. Before/after PNGs:
      `.astroray_plan/docs/pkg261/ground_strip_*.png` (ROIs drawn + inspected).
      Flagged for the lead: whether the remaining ~3.8 % blue skew warrants a
      follow-up or the ≥0.97 target is relaxed given it is out of scope here.
- [ ] `metal_sweep` floor-reflection blocks — NOT re-measured this lane
      (the `metal_ab` harness spawns 3 subprocess Blender legs incl. a GPU leg;
      deferred to the on-hardware verifier). pkg261 changes only the dielectric
      specular/coat layering albedo; the metallic lobe path is untouched, so no
      metal_sweep regression is expected. Recorded as outstanding for the lead.
- [x] Furnace floors re-derived from Cycles with the derivation next to the
      constant (diffuse/Lambert 0.85→0.97, measured 0.9988 CPU / 0.9974 GPU);
      pkg178 GPU furnace + `test_principled_bsdf` Principled suites green; every
      `stageShadeBucketedKernel<…>` fleet variant REG:254 (cuobjdump).
- [ ] `cycles-parity-reviewer` pass on the diff; call-site sweep for any changed
      signature.

---

## Non-goals

- Do not touch the addon's `BSDF_DIFFUSE` → Principled mapping (separate issue).
- Do not change the GGX sampling, Fresnel, or the multiscatter tables' data.
- Do not relax any parity band to make the sweep pass.
- No Pillar 4 work; no metallic/transmission layering changes unless the note
  proves they share the defect.

---

## Progress

- [ ] 2026-09-08 — filed by the lead from #756; not started.
- [~] 2026-09-08 — research note landed
      (`.astroray_plan/docs/pkg261-principled-layering-research.md`). A VNDF
      Monte-Carlo directional-albedo oracle proves the disagreeing term is **not**
      the multi-scatter darkening (spec hypothesis) — that term is ≤3 %. The
      defect is that `ggxDirectionalAlbedo` multiplies `E` by the **view-angle**
      Fresnel `Fview`, which matches the true albedo within 2–3 % at mu≥0.8 but
      overestimates the specular layer albedo by 1.2–5.5× at grazing (mu≤0.5),
      over-attenuating the diffuse below exactly on the grazing near-ground band.
      Cycles avoids this via the lobe-averaged `ggx_gen_schlick_ior_s` 16³ LUT
      (`bsdf_microfacet_estimate_albedo`) that Astroray does not ship. **SCOPE
      FORK surfaced to the lead:** the faithful fix needs a new LUT + its GPU
      upload path (precedent: pkg151 `ggx_glass_E`), which is outside this spec's
      Files-to-modify; a closed-form alternative risks a §6 invention. Awaiting
      the lead's decision on the widened surface / CPU-first split before writing
      the fix.
- [x] 2026-09-08 (cont2) — **Option A landed (lead-approved widening): faithful
      port of Cycles `bsdf_microfacet_estimate_albedo` (`mix(f0, f90=1, s)`, `s`
      from the 16^3 `ggx_gen_schlick_ior_s` LUT) at the Principled specular
      (`ior_`) and coat (`coat_ior`) layering sites, CPU + GPU in one PR.** Built
      from HEAD under the GPU lock (sha d28394da, sm_120, BUILD OK). Verified:
      the normalised roughness sweep vs the pinned Cycles reference is within
      +-3% at every roughness on **both backends** (CPU: r0.3 2.38%, r0.5 2.20%,
      r0.85 2.47%, r1.0 2.71%; GPU: 2.37/2.19/2.45/2.72%); the table-reference
      unit gate reproduces Cycles' `mix(f0,1,s)` within 0.002 and shows the
      pre-fix `E*Fview*darkening` over-shoots the reference by >3x at grazing
      (the removed defect); `stageShadeBucketedKernel<...>` **REG:254 held on all
      128 fleet variants** (cuobjdump `--dump-resource-usage`); pkg55
      oracle/production/ssim + pkg178 GPU furnace + principled_bsdf all green (24
      + 7 re-verify). Furnace floors re-derived 0.85->0.97 (measured 0.9988 CPU /
      0.9974 GPU). **Note (research-note deviation, lead-surfaced):** Cycles' `s`
      table is a lobe-averaged Schlick fit that deviates from the raw VNDF MC
      oracle by up to 3.25x at high roughness, so the unit gate asserts against
      the Cycles reference (the parity target), not the MC oracle at 2%.
- [~] 2026-09-08 (cont2) — Blender-level ground-strip A/B on `hdri_exterior_hair`
      (ground-only, roughness 0.85, CPU addon built from this branch): ground
      ratio 0.926 → **0.962**, sky 1.002 unchanged. Improves in the correct sign
      and locus but is ~0.8 pp short of ≥0.97; the residual is the out-of-scope
      blue skew (per-channel R 0.982 / G 0.954 / B 0.947). PNGs under
      `.astroray_plan/docs/pkg261/`.

---

## Lessons

- **The grazing view-Fresnel, not the multiscatter darkening, was the defect.**
  The spec hypothesised `E·F·darkening`; the VNDF MC oracle proved the darkening
  term is ≤3 % and the real error is multiplying `E` by the view-angle Fresnel
  `Fview` (→1 at grazing). Find-the-number-before-the-formula caught a wrong
  hypothesis before any code.
- **Cycles' `s`-table is a clamped lobe-averaged fit, not the true albedo.**
  Because `s∈[0,1]` and `f90=1`, `mix(f0,1,s)` cannot fall below f0, so it
  over-estimates the true MC albedo up to 3.25× at high roughness / normal
  incidence while correcting the large grazing error. Parity target is Cycles,
  not the MC oracle — the unit gate asserts against the extracted table.
- **A residual ~3.8 % blue-skewed ground deficit survives the layering fix.**
  The HDRI ground strip lands at 0.962 (R 0.982 / G 0.954 / B 0.947), not ≥0.97.
  Blue-dominated ⇒ the spectral-upsampling nonlinearity (memory
  `spectral-upsample-nonlinearity-scaled-bsdf`), explicitly out of pkg261 scope.
  The controlled sweep (achromatic, black world) is within ±3 %, isolating the
  residual to the HDRI/colour path. Candidate follow-up package.
