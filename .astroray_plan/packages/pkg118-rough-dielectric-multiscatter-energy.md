# pkg118 — Rough-dielectric multiple-scattering energy compensation (CPU)

**Pillar:** 2 (materials / BSDF correctness)
**Track:** A (CPU-gated; furnace test runs on CI — no GPU needed)
**Codex-paste-ready:** no (numerical precompute + furnace verification)
**Status:** open — proposed 2026-05-31. Root cause fully diagnosed (this spec).
**Depends on:** none. Extends the existing `DisneyEnergyCompensationTables` (pkg60).
**Estimated effort:** M (a precompute pass + apply + furnace re-gate)

---

## Goal

**Before:** CPU Disney **rough** glass (`transmission=1`, `roughness>0.03`) loses
energy in the white furnace, worst at LOW roughness:

| R | 0.05 | 0.10 | 0.30 | 0.60 | 1.00 |
|---|------|------|------|------|------|
| CPU furnace @256spp | 0.771 | 0.815 | 0.921 | 0.967 | 0.962 |

Gate wants ∈ [0.95, 1.02] for R∈{0.1,0.3,0.6,1.0}. R=0.1 and R=0.3 FAIL.
Tracked by the non-strict xfail `test_disney_rough_glass_furnace_energy_cpu`.

**After:** CPU rough-glass furnace ∈ [0.95, 1.02] for all R∈{0.1,0.3,0.6,1.0},
smooth glass unaffected (R≤0.03 stays ~0.97), no caustic/prism gate regressions,
xfail removed (becomes a hard pass).

---

## Root cause (diagnosed 2026-05-31, instrumented)

The current `plugins/materials/disney.cpp` rough-glass path is a **hybrid** of a
single-scattering microfacet model plus a delta fallthrough, and it is NOT
energy-conserving. Two opposing bugs partially cancel — they balance at high
roughness and diverge at low roughness:

1. **Single-scattering masking loss (under-count).** The rough microfacet
   transmission/reflection use the single-scattering Smith G (separable
   `G1(wo)·G1(wi)`). Like all single-scattering GGX, this loses the energy that
   physically scatters via multiple microfacet bounces. The loss grows with
   roughness. The reflection lobe already gets Kulla-Conty multi-scatter
   compensation (`ggxCompensationFactor`, pkg60) but the **transmission lobe does
   not**.

2. **Delta-TIR over-count (gain).** When a VNDF-sampled rough reflection lands
   below the surface (common for grazing exit/TIR rays — PBRT discards these),
   the code **falls through to the smooth delta path**. Instrumentation (env
   `DISNEY_DBG=1`, see the diag scripts) shows at R=0.05 **~1.3M fallthroughs**
   vs 330K successful rough refractions. The delta-reflect branch then assigns a
   forced-TIR reflection `f=1, pdf=Fresnel·transmission` → throughput **≈21×**
   (= 1/Fresnel) instead of the physically-correct **1.0** for a deterministic
   total reflection.

At high roughness the over-count (2) roughly cancels the masking loss (1) → ~0.96.
At low roughness there are fewer grazing-TIR fallthroughs, so (2) under-compensates
(1) and the furnace sags to 0.77. The fix is to make BOTH terms correct, not to
keep relying on their accidental cancellation.

### Evidence (instrumented furnace, R=0.05)
```
rough-reflect      count=359        avg_throughput=0.19
rough-refract      count=330210     avg_throughput=0.50
delta-reflect      count=581425     avg_throughput=21.27   <-- forced-TIR over-count
delta-refract      count=719513     avg_throughput=1.81
rough-fallthrough  count=1300938                            <-- dominant at low R
```
- Loss saturates by path depth 4 (per-transmission-event leak, not truncation).
- `rec.normal` is already face-forwarded to `wo` by the integrator (a faceforward
  of the VNDF sampling frame was verified a no-op — do NOT re-attempt that).
- The GPU furnace test passes because `set_use_gpu(True)` routes to the spectral
  multiwavelength closure path, NOT `gpu_disney_sample`; the bespoke RGB
  `disney_sample` BSDF has the same defect on both backends.

Diag scripts (keep): `scripts/diag_rough_glass_furnace.py`,
`scripts/diag_rough_glass_depth.py`,
`scripts/prototypes/rough_glass_albedo_probe.py`.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

Two correct, independently-verifiable changes:

### A. Correct the forced-TIR delta throughput (small, unblocks the gain bug)
In the delta reflect branch, when `cannotRefract` (TIR) forced the reflection,
the selection probability is 1 (deterministic), so `pdf = transmission_`
(NOT `Fresnel·transmission_`). Only the *Fresnel-selected* reflection keeps
`pdf = Fresnel·transmission_`. This removes the non-physical ~21× firefly.
Mirror in `gpu_materials.h`. **Cite:** PBRT-v4 §9.5 specular dielectric
(`Sample_f` reflection branch sets `pdf = pr/(pr+pt)`; for TIR `pt=0` ⇒ `pdf=1`).

### B. Multiple-scattering energy compensation for the rough dielectric
After (A) the furnace will read the true single-scattering albedo (below 1, sagging
with roughness). Compensate the missing multi-scatter energy:
- Precompute the rough-dielectric directional albedo table
  `E_glass(alpha, mu, eta)` by MC-integrating the single-scattering rough-dielectric
  BSDF (reuse the numpy BSDF in the prototype script; generate per-IOR slices or a
  3D table keyed on the common IOR set). Store alongside the existing
  `DisneyEnergyCompensationTables`.
- Apply the Kulla-Conty multi-scatter factor `1 + F_avg·(1-E)/E` to the rough
  transmission+reflection throughput, exactly as `ggxCompensationFactor` already
  does for the opaque GGX reflection lobe.
- **Cite:** Kulla & Conty 2017 "Revisiting Physically Based Shading at Imageworks"
  (SIGGRAPH course); Heitz et al. 2016 "Multiple-Scattering Microfacet BSDFs with
  the Smith Model" (the stochastic alternative if a table is undesirable); Cycles
  `intern/cycles/kernel/closure/bsdf_microfacet.h` `microfacet_ggx_preserve_energy`
  (Apache-2.0) — the reference the reflection lobe already mirrors.

Verification: rebuild, run `scripts/diag_rough_glass_furnace.py`; the CPU column
must read ∈[0.95,1.02] for R∈{0.1,0.3,0.6,1.0}. Then remove the xfail. Re-run the
prism/glass-sphere caustic gates (`test_glass_sphere_caustic.py`, the prism
hue/coverage gates) to confirm no regression.

---

## Acceptance criteria
- [ ] `test_disney_rough_glass_furnace_energy_cpu` passes (xfail removed).
- [ ] Smooth glass furnace unchanged (R≤0.03 ~0.97).
- [ ] No regression: prism hue/coverage gates, `test_glass_sphere_caustic.py`,
      `test_dielectric_glass_furnace.py`, `test_disney_reflection_not_black.py`.
- [ ] CPU and GPU `disney_sample` kept in lockstep (mirror both changes).
- [ ] Research note: `E_glass` table generation method + Kulla-Conty citation in
      `.astroray_plan/docs/vndf-microfacet-dielectric-research.md`.

## Non-goals
- The GPU spectral closure path (already energy-conserving) — untouched.
- pkg64-gpu SMS caustics (frozen/legacy per owner 2026-05-30).
- A full Heitz-2016 stochastic multi-scatter rewrite (table approach preferred;
  the stochastic path is the documented fallback if the table proves insufficient).

## Filed by
Claude (Opus 4.8), 2026-05-31, after a full instrumented root-cause pass on
NEXT_STAGE_REPORT §2 open item 1. Supersedes the "low-alpha residual" framing —
the real defect is missing multi-scatter compensation + a forced-TIR over-count.
