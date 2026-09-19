# pkg273 — `Astroray Cloud Volume`: a spectral cloud-microphysics volume material (Lorenz–Mie / ice-habit tables, tabulated phase)

**Pillar:** 3
**Track:** A
**Status:** paused — owner: horizon item until the cloud simulation is complete (filed 2026-09-15)
**Estimated effort:** 3 weeks across 4 phases (P1 ~1 week, P2 ~1 week, P3 ~3 sessions, P4 ~3 sessions); TBD until the sim's export format is fixed
**Depends on:** pkg270, pkg269, pkg271

---

## Goal

Before: cloud VDBs render through Principled Volume — an artist `density`
scaled by a colour, a grey/RGB σ_t, and a Henyey–Greenstein phase — so the
coefficients have no physical units, r_eff has no effect, and fogbow / glory /
corona / silver-lining structure cannot appear. After: an `Astroray Cloud
Volume` node consumes the sim's physical grids (LWC, IWC, r_eff, optional
v_eff / T / rain), derives σ_s(λ, x) and σ_a(λ, x) per hero wavelength from
Lorenz–Mie (water) and Yang/Baum (ice) tables, scatters through a tabulated,
importance-sampled bulk Mie/ice phase function on CPU and GPU, and passes
analytic single-scatter gates (efficiencies, fogbow angle, glory, Rayleigh
limit) with Cycles `Volume Scatter + Mie` recorded as a cross-check band.

---

## Context

The owner's separate cloud-simulation project will emit physically based VDBs
(LWC, droplet number / r_eff, IWC, T, possibly rain / graupel). A physics-first
material for them serves both production renders and the north-star science
lane (physically meaningful radiance / instrument observables) — clouds are the
canonical spectral radiative-transfer test case. It is a **horizon** item:
`paused` until the sim exists and the owner answers the three open questions;
it must not be dispatched autonomously. It sits on the volumes track: pkg270
(per-λ σ, spectral tracking), pkg269 (GPU hetero stage) and pkg271 (passes,
corpus) must be done first. Opus-tier implementation when it opens (physics +
CUDA, memory `delegate-tier-stalls-on-hard-packages`). Research:
`docs/cloud-volume-material-research-2026-09-15.md`.

---

## Reference

- Design doc: `.astroray_plan/docs/cloud-volume-material-research-2026-09-15.md` (§1–§10)
- Volumes track: `.astroray_plan/docs/volumes-track-research-2026-09-12.md`;
  `include/astroray/volume/{grid_medium,phase,principled_volume,volume_transport}.h`
- External (physics): Bohren & Huffman 1983 (BHMIE); Wiscombe 1980 (MIEV0);
  Frisvad, Christensen, Jensen 2007 (SIGGRAPH, bulk Mie for rendering);
  Hansen & Travis 1974 (r_eff/v_eff); Hu & Stamnes 1993 (r_eff
  parameterisation); Hale & Querry 1973 / Segelstein 1981 (water n,k);
  Warren & Brandt 2008 (ice n,k); Yang et al. 2013 (Zenodo 5348402,
  CC-BY-4.0) + Baum et al. 2014 (ice bulk models); Jendersie & d'Eon 2023
  (analytic Mie approx = Cycles `Mie` phase); Kutz et al. 2017 (spectral
  tracking); Novák et al. 2018 STAR.
- External (code, licences): miepython (MIT) for the table builder;
  pbrt-v4 `PiecewiseConstant1D` (Apache-2.0) for the inverse-CDF sampler
  pattern; Cycles `node_shader_volume_scatter.cc` `SHD_PHASE_MIE` (Diameter
  µm, default 20) for the cross-check tree.
- `cite-algorithm` must run per algorithm before code (CLAUDE.md §6).

---

## Prerequisites

- [ ] Owner's cloud simulation exports VDBs; the grid contract below is
      confirmed or amended by the owner (open question 1).
- [ ] pkg270 done (per-λ σ_t and spectral tracking exist on CPU).
- [ ] pkg269 done (GPU `HasGridVolume` stage exists); pkg271 done (volume
      passes + `volumes` corpus family to extend).
- [ ] Owner answers open questions 2 (mixed-phase policy) and 3 (Cycles
      fallback tree).
- [ ] `cite-algorithm` notes saved for: Lorenz–Mie tabulation, bulk-phase
      integration + inverse-CDF sampling, hero-λ spectral MIS for phase
      sampling, ice bulk models.
- [ ] Licence check recorded for any vendored Baum 2014 bulk files (fallback:
      re-integrate from the CC-BY-4.0 Yang v2 single-particle data).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/cloud_mie_tables.py` | Table builder: miepython (MIT) over (r_eff × v_eff × λ) for water; loads/re-integrates ice bulk tables; caches `.npz` under the addon data dir; validated against BHMIE reference rows |
| `blender_addon/nodes/cloud_volume_node.py` | `Astroray Cloud Volume` custom node (sockets below) + exporter lowering to the engine cloud medium |
| `include/astroray/volume/cloud_medium.h` | `CloudMedium`: per-voxel LWC/IWC/r_eff → σ_s(λ), σ_a(λ) via the tables (fast path 3·LWC/(2ρ·r_eff) with tabulated ω0); majorant from max(LWC/r_eff) |
| `include/astroray/volume/tabulated_phase.h` | Tabulated bulk phase: eval/sample/pdf by inverse CDF on a non-uniform θ grid, per (r_eff bin, v_eff bin, λ bin); hero-λ spectral MIS weights; optional HG-after-order-k hybrid flag |
| `src/gpu/wavefront/cloud_phase_tables.cu` | Upload phase/coefficient tables to texture memory + `__constant__` side-table of handles; consumed only inside the pkg269 `HasGridVolume` stage |
| `data/cloud/README.md` | Attribution + licence text for the shipped ice tables (CC-BY-4.0) and the water n,k tables (CC0 via refractiveindex.info) |
| `tests/test_pkg273_mie_tables.py` | Q_ext/Q_sca/g vs BHMIE reference rows; Rayleigh limit; Q_ext→2 for x ≫ 1; β/LWC = 3/(2ρ r_eff) within 5 % for r_eff ≥ 5 µm at 550 nm |
| `tests/test_pkg273_phase_sampling.py` | ∫p dΩ = 1; chi² sample-vs-pdf; fogbow maximum at 138–140° (r_eff 10 µm, 550 nm); glory maximum at 180°; hero-λ MIS unbiased vs per-λ sampling |
| `tests/test_pkg273_cloud_render.py` | Single-scatter slab vs a numpy Mie-phase oracle (linear, floor+ceiling); CPU↔GPU ROI mean ratio; Cycles Volume Scatter+Mie cross-check band recorded |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/volume/volume_transport.h` | Accept a medium whose σ_t(λ, x) and phase come from `CloudMedium` / `tabulated_phase.h` (same delta/ratio/spectral-tracking estimators; phase sampler is a call-through) |
| `include/astroray/volume/grid_medium.h` | Register the additional named grids (LWC, IWC, r_eff, v_eff, rain) as passthrough `DenseGrid` handles; majorant grid built from the cloud σ_t field |
| `src/gpu/wavefront/stage_volume_hetero.cu` | Phase sample/eval via the table textures when the medium is a cloud medium (inside the existing `HasGridVolume` axis; no shared shade-kernel change) |
| `blender_addon/exporter.py` | Lower `Astroray Cloud Volume` → engine cloud medium; degradation-report rows for unsupported inputs; optional Cycles fallback tree (fork (c)) |
| `blender_addon/volume_export.py` | Export the extra cloud grids by name per the grid contract |
| `module/blender_module.cpp` | Bind cloud-medium construction, table upload, and test hooks (efficiencies / phase eval for the gates) |
| `benchmarks/reference_corpus/scenes/manifest.json` | Add a `volumes_cloud` scene (owner cumulus VDB or a synthetic LWC/r_eff blob) with CPU/GPU rows and the Cycles band |

### Key design decisions

#### VDB grid contract (what the sim should export; v1 proposal)

All grids float, index-aligned on one transform, SI units; names are the
Blender/Cycles attribute-name convention (lower case). "Required" = the
material refuses to build without it.

| Grid name | Unit | Required | Notes |
|---|---|---|---|
| `lwc` | kg m⁻³ | one of `lwc` / `iwc` | liquid water content (sim may export g m⁻³; the node has a unit multiplier) |
| `iwc` | kg m⁻³ | one of `lwc` / `iwc` | ice water content |
| `r_eff` | µm | optional (constant socket fallback) | droplet effective radius; if the sim exports number concentration `n_d` (m⁻³) instead, r_eff is derived from LWC and n_d with the gamma-distribution moments (research §2) |
| `n_d` | m⁻³ | optional | droplet number concentration (alternative to `r_eff`) |
| `v_eff` | — | optional (constant default 0.1) | effective variance of the size distribution |
| `d_eff_ice` | µm | optional (constant default 60) | ice effective diameter (Yang/Baum definition (3/2)V/A) |
| `temperature` | K | optional | mixed-phase heuristics only if the sim gives no explicit ice split; blackbody emission is irrelevant in the visible |
| `rain` / `graupel` / `snow` | kg m⁻³ | optional | extra particle populations; v1 treats rain as a large-drop Mie population (r ~ 0.5 mm), graupel/snow as the roughened-aggregate ice model |
| `density` | — | not used | kept so the same VDB still works with Principled Volume |

Open question 1 (bin-resolved spectrum export) may replace `r_eff`/`v_eff`
with a per-voxel size-class id; the table axis then becomes the class id.

#### The node: `Astroray Cloud Volume`

Inputs: `LWC Grid` (name, default `lwc`), `IWC Grid` (name, default `iwc`),
`LWC Units` (kg/m³ | g/m³), `Effective Radius` (grid name or constant µm,
default 10), `Effective Variance` (constant, default 0.1), `Ice Habit`
(enum: General Habit Mixture (Baum 2014) | Solid Columns | Aggregates |
Pristine Hexagonal (smooth, halo-capable) | Sphere (Mie ice, for A/B)),
`Ice Effective Diameter` (grid name or constant µm), `Phase` (enum:
Tabulated Mie/Ice | HG (tabulated g) | HG after order k (biased hybrid)),
`Hybrid Order k` (int, default 3, only for the hybrid), `Spectral Coefficients`
(bool, default on: per-λ σ via spectral tracking; off = grey σ_t at the hero
λ for perf A/B), `Rain Grid` (optional). No emission sockets — clouds do not
emit in the visible; the thermal-IR case reuses pkg270's Planck path with the
temperature grid when the band widens, not a new socket. Output: Volume.

#### Precomputation (tables)

- Water: built at addon level with miepython (MIT) on first use, cached as
  `.npz` (r_eff 2–40 µm log-spaced 16 bins; v_eff {0.03, 0.1, 0.2, 0.3};
  λ 0.2–5 µm, ≥ 32 bins with the 360–830 nm band resolved at ≥ 16 bins;
  n,k from Hale & Querry / Segelstein via refractiveindex.info, CC0).
  Stored: Q_ext, Q_sca, g, and the bulk phase pdf+CDF on a non-uniform
  θ grid (log-spaced near 0°, dense at 135–145° and 175–180°). Build time
  budget: < 5 min single-threaded; validated against BHMIE reference rows in
  `test_pkg273_mie_tables.py`.
- Ice: ship the Baum 2014 GHM / solid-column / aggregate bulk tables
  (attribution in `data/cloud/README.md`) or re-integrate from the Yang v2
  CC-BY-4.0 single-particle data — decided at licence-check time.
- Engine receives tables as flat float arrays (CPU) and `cudaArray` textures
  (GPU) through one upload call; the tables are version-stamped so a stale
  cache cannot silently mismatch the sampler's θ grid.

#### Transport changes

- σ_t(λ, x): `CloudMedium::sigma(λ, x)` = Σ_populations (σ_ext/LWC)(r_eff(x), λ)
  · LWC(x); fast path 3/(2 ρ r_eff) × LWC with tabulated ω0 when
  `r_eff ≥ 5 µm` and λ in the visible (research §3), full table otherwise.
- Free flight and NEE transmittance: unchanged pkg268/pkg270 estimators
  (delta + ratio + spectral tracking); the majorant grid is built from the
  cloud σ_t field (max over λ, supervoxel), so all pkg267/268 gates still hold.
- Phase: `tabulated_phase.h` sample with the hero λ's CDF; evaluate the
  secondaries' pdf ratios (single-sample spectral MIS, Wilkie 2014); collapse
  to hero only when the ratio bound exceeds a threshold (corona regime).
  Per-collision r_eff bin from the grid; population choice ∝ σ_s for mixed
  phase.
- GPU: everything lives inside the pkg269 `template<bool HasGridVolume>`
  volume stage — tables via texture fetches, handles in a `__constant__`
  side-table (memory `shade-axis-side-table-avoids-spill`). **The shared shade
  kernel gains no live state; REG:254 is a HARD gate** (memory
  `wavefront-shade-kernels-register-saturated`). The volume stage's own REG /
  STACK is reported on the PR; grid-free scenes stay byte-identical.

#### Phases

- **P1 — tables + oracle (CPU-only, addon + tests).** `cloud_mie_tables.py`,
  BHMIE-reference gates, numpy single-scatter oracle with the tabulated phase.
- **P2 — CPU material + transport.** `cloud_medium.h`, `tabulated_phase.h`,
  transport hookup, node + exporter lowering, render gates.
- **P3 — GPU leg.** Table upload, phase in `stage_volume_hetero.cu`, CPU↔GPU
  parity, REG gate, RTX sweep.
- **P4 — ice + corpus + Cycles band.** Ice presets, mixed phase,
  `volumes_cloud` corpus scene, Cycles Volume Scatter+Mie A/B band, visual
  inspection (fogbow/glory contact sheet at the antisolar view).
- Optional later: a multi-scatter accelerator (pkg272 fork or an NRC-style
  learned MS, research §7) — separate package, not here.

#### Fork (c): Cycles fallback tree

If the owner wants scenes to stay Cycles-renderable, the exporter also emits a
Cycles `Volume Scatter` (Phase = Mie, Diameter = 2·r_eff µm, Density from
LWC·3/(2ρ r_eff)) + `Volume Absorption` node group behind the Astroray node —
approximate by construction (Jendersie–d'Eon fit, RGB σ). Off unless chosen.

---

## Acceptance criteria

- [ ] `test_pkg273_mie_tables.py`: Q_ext, Q_sca, g match BHMIE/miepython
      reference rows to 1e-3 relative; Rayleigh limit (x = 0.05) p ∝ 1+cos²θ
      within 1 %; Q_ext → 2 ± 0.05 for x ≥ 200; β/LWC vs 3/(2ρ r_eff) within
      5 % for r_eff ∈ [5, 30] µm at 550 nm.
- [ ] `test_pkg273_phase_sampling.py`: ∫p dΩ = 1 ± 1e-3 for every table row;
      chi² sample-vs-pdf passes (pkg121 gate style); fogbow maximum in
      [138°, 140°] and glory maximum at 180° for r_eff 10 µm / 550 nm; hero-λ
      MIS estimator mean equals the per-λ estimator within noise on a
      100-sample-per-bin sweep.
- [ ] `test_pkg273_cloud_render.py`: single-scatter slab radiance vs the numpy
      Mie oracle within 3 % (linear, floor AND ceiling, `apply_gamma=False`);
      GPU↔CPU per-channel ROI mean ratio within ±5 %; grid-free scenes
      byte-identical; shared shade kernel REG unchanged (`cuobjdump`).
- [ ] A cumulus VDB (owner's, or synthetic) renders CPU+GPU from the node with
      a visible fogbow/glory at the antisolar view and a silver lining at the
      forward view; contact sheet inspected by Astra or Claude; Cycles Volume
      Scatter+Mie A/B recorded as a cross-check band (not a gate).
- [ ] `volumes_cloud` corpus scene registered; full CPU + GPU suites green;
      RTX sweep at closeout; `data/cloud/README.md` carries the CC-BY-4.0 / CC0
      attributions.

---

## Non-goals

- Do not implement oriented ice crystals (sun dogs, pillars, arcs) — needs an
  anisotropic medium; out of scope for every phase.
- Do not add a multiple-scattering accelerator here — pkg272 fork or a later
  package; this package is the unbiased reference plus an explicit
  HG-after-order-k hybrid flag only.
- Do not make the spectral sky handoff (per-λ Nishita radiance) part of this
  package — separate item; the material must work with the current RGB sky.
- Do not change pkg267–271 estimators or the Principled Volume mapping.
- Do not grow the shared GPU shade kernel's register footprint.
- Do not treat Cycles Volume Scatter+Mie as the acceptance oracle.
- Do not widen `kLambdaMin/Max`; the tables cover 0.2–5 µm so the IR band
  works later, but the band change is pkg251/pkg133 territory.

---

## Progress

- [x] 2026-09-15: research note + spec filed; `paused` pending the owner's
      cloud simulation and open questions 1–3.
- [ ] Owner confirms the grid contract + mixed-phase policy + Cycles fallback.
- [ ] P1 tables + oracle. P2 CPU material. P3 GPU leg. P4 ice + corpus + band.

---

## Lessons

*(Fill in after the package is done.)*
