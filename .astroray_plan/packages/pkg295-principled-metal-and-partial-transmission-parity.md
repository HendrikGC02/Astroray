# pkg295 — Principled metal −15 % vs Cycles on both backends (#934) and GPU partial-transmission Disney lowering (#933)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h) + one GPU build; one Opus 5.5 lane, sequential
**Depends on:** pkg292, pkg123

---

## Goal

Before: Disney/Principled `metallic=1` under a sun reads 0.476 on CPU and
GPU vs Cycles 0.563 (−15 %) while the dielectric rungs match within 3–6 %;
and on the GPU any Disney with `0 < transmission < 0.999` still lowers to the
pre-#876 multi-lobe closure graph (a base-tinted GGX conductor forced to
metallic 1, averaged with diffuse), so partially transmissive Principled
materials carry the #876 class of brightening. After: the metal lobe follows
Cycles' Principled conductor (F82-tint Fresnel with base colour as F0 and
specular tint as F82, multiscatter GGX energy preservation) on both backends
within ±5 % of Cycles per rung; the single-closure `gpu_disney_eval` path
covers partial transmission; the pkg292 ladder gains metal-Fresnel and
partial-transmission rungs and `test_pkg123` keeps its band.

---

## Context

Metals are on every showcase tile (gold/copper/titanium, `v2_thin_film_metals`)
and Principled is the default Blender material; a −15 % metal is visible in
every parity number and would be blessed into pkg284/pkg285 references if
not fixed first. #933 is the unfinished half of #876. Both live in
`plugins/materials/disney.cpp` / `include/astroray/gpu_materials.h`
(`gpu_disney_eval`), so one lane does #934 then #933 and pkg293 rebases on it.
Physics + shade-kernel register risk: Opus 5.5 with a Terra review;
`cite-algorithm` for the Fresnel model.

---

## Evidence

- 2026-09-27 (pkg292 #876 ladder, `astra_run\batchU\ah1\`): metallic=1 rung 0.476 CPU = GPU vs Cycles 0.563; dielectric rungs 3–6 %.
- `plugins/materials/disney.cpp:77` `fresnelSchlick(cosθ, F0, scale=0.8)` and `:724` `schlickScale`; `include/astroray/gpu_materials.h:974` `schlickScale = 0.8 + 0.2·metallic` — Schlick with a damped grazing term, not Cycles' F82-tint.
- `include/astroray/gpu_materials.h:927` `gpu_disney_eval` (single closure, #876) is selected only for opaque Disney; partial transmission falls back to the closure-graph lowering (`disneyMetalConductor`, `disney.cpp:592-595` comment).

---

## Reference

- Kutz, Hašan, Edmondson 2021, "Novel aspects of the Adobe Standard Material" (F82-tint conductor Fresnel); Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h` (`fresnel_f82_tint`, `bsdf_microfacet_setup_fresnel_f82_tint`, `microfacet_ggx_preserve_energy`) and `kernel/svm/closure.h` Principled metal branch — Apache-2.0.
- Kulla & Conty 2017 (multiscatter compensation; in-repo `energy_compensation.h`, `table_ggx_E`).
- Burley 2015 lobe mixing for transmission: `(1−metallic)·transmission·glass`.
- pkg292 ladder method and `docs/pkg292-gpu-cpu-ladders.md`; `tests/test_pkg292_disney_sun_parity.py`, `tests/test_pkg123_disney_metal_gpu_cpu_parity.py`.
- Memory: `closure-graph-lobe-count-spills-fused-kernel`, `wavefront-shade-kernels-register-saturated`, `gpu-dielectric-lowers-to-closure-graph`, `verify-attribution-with-a-baseline-build`.

---

## Prerequisites

- [ ] pkg292 #876 merged (yes, #935); ptxas register report of the current main build saved.
- [ ] Cycles 5.2 headless available for the metal rungs (Principled metallic=1, roughness 0.5 and 0.1, base 0.8 grey and copper, one sun).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg295_metal_fresnel_parity.py` | Metal rungs (grey/copper × roughness 0.1/0.5, sun and env) vs Cycles headless: CPU and GPU per channel within ±5 %; a `specular_tint` rung (F82 ≠ 1); white furnace on `metallic=1, base=1`, `apply_gamma=False`, linear mean in [0.98, 1.005] (energy preserved, never gained; memory `gamma-furnace-cannot-detect-energy-gain`). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/disney.cpp` | Metal lobe Fresnel: F82-tint (F0 = base colour, F82 = specular tint) replacing the damped Schlick for `metallic`; multiscatter preservation as Cycles (`microfacet_ggx_preserve_energy` semantics via `energy_compensation.h`). Dielectric lobes untouched. |
| `include/astroray/gpu_materials.h` | (#934) `gpu_disney_eval` metal Fresnel twin, same constants; (#933) extend the single-closure path to `0 < transmission < 0.999` (glass lobe weight `(1−metallic)·transmission`, MIS/pdf consistent with `disney.cpp::eval/pdf`), retire the multi-lobe fallback for that range. |
| `tests/test_pkg292_disney_sun_parity.py` | Add rungs: metal F82 (grey/copper), transmission 0.3 / 0.7 with roughness 0.05 / 0.4; GPU/CPU ±5 % per rung. |

### Key design decisions

- **#934 first, attributed against a baseline build** (which term: Fresnel at normal incidence, grazing term, or missing compensation). Do not change roughness remapping unless the ladder convicts it; the dielectric rungs already match.
- **Cycles' Principled, not Burley 2012**: the target is Cycles parity; cite the Cycles functions in code.
- **#933 reuses `gpu_disney_eval`**: no new closure lobes in the graph (memory `closure-graph-lobe-count-spills-fused-kernel`); if the transmission branch spills the shade kernel, gate it behind the `__noinline__` runtime flag rather than widening the band.
- **pkg293 rebases on this** (same file); the lead merges pkg295 first.

---

## Acceptance criteria

- [ ] `test_pkg295_metal_fresnel_parity.py` green CPU and GPU; metallic=1 sun rung within ±5 % of Cycles (was 0.476/0.563 = 0.846).
- [ ] `test_pkg292_disney_sun_parity.py` partial-transmission rungs GPU/CPU within ±5 %; `test_pkg123` at its original band; `test_pkg292` opaque rungs unchanged.
- [ ] Showcase metals tile re-rendered and inspected by the lead (gold/copper/titanium vs Cycles ratios recorded).
- [ ] Shade kernel REG ≤ 254 with STACK delta reported; `HasProgram=false` SASS hash change explained (metal Fresnel constants) in the PR.
- [ ] Moved references re-pinned in the same PR with attribution.

---

## Non-goals

- No per-hit lobe-weight programs (pkg293).
- No thin-film changes (#902 done; pkg265 follow-ups #783/#789 paused).
- No change to `plugins/materials/metal.cpp` (dedicated conductor) unless the ladder shows it shares the damped-Schlick term; then file, do not fix here.

---

## Progress

- [ ] #934 ladder + fix (CPU, then GPU twin).
- [ ] #933 single-closure partial transmission on GPU + rungs.
- [ ] Showcase metals re-render; register audit.

---

## Lessons

*(Fill in after the package is done.)*
