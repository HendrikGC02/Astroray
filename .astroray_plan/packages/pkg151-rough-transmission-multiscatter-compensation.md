# pkg151 — Rough-transmission multi-scatter energy compensation (unmasked by the pkg149 sampler fix)

**Pillar:** 2 (materials / BSDF energy conservation)
**Track:** A
**Codex-paste-ready:** no (an energy-compensation port with an ior-dimensioned table and a furnace calibration loop)
**Status:** open — dispatchable (**day queue, heads it as a stack with pkg149** — pkg149's corrected sampler is HELD unpushed until this lands; ship as one PR chain: pkg151 → pkg149 rebased on it, furnace + peak-alignment green together)
**Estimated effort:** M
**Depends on:** pkg149's worktree fix (`Astroray-pkg149`, local commit `670e583` — the corrected `sampleGgxVNDF`). Distinct from **pkg129** (Turquin *reflection* LUTs for metals + the GPU placeholder) — same technique family, different lobe, different table dimensionality (transmission needs an **ior axis**); do NOT fold them: pkg129 is coupled to the metal/GPU-placeholder work and would drag pkg149's ship date.

**Origin:** pkg149 root-cause session (2026-07-24). The azimuth-swapped
`sampleGgxVNDF` (pbrt-v4 `Lerp` args transposed) was inflating apparent
rough-transmission energy; with the corrected sampler the rough-glass furnace
drops to **0.09–0.82** (was 0.94–1.0), and the single-scatter estimator median
matches **`G1(wi)/ior²` theory almost exactly** — the textbook signature of
missing multiple-scattering energy, not a sampler or radiometry bug. Three
alternative hypotheses were ruled out by rebuild-and-measure; full trail:
`.astroray_plan/docs/pkg149-disney-rough-transmission-research.md` (worktree,
lands with the pkg149 PR).

---

## ⚠️ Supersession — pkg118 Part B is confounded

pkg118 (DONE, PR #423) concluded "the deficit was NOT missing multi-scatter
(Part B Kulla-Conty correctly REJECTED)" — but that measurement ran on the
**azimuth-swapped sampler**, which was over-delivering transmission energy.
The rejection is therefore confounded and is **superseded for the
corrected-sampler world**: re-measure on `670e583` before assuming anything
from pkg118 Part B. (pkg118's actual fix — the Jakob-Hanika albedo-LUT eta²
clamp — remains valid and untouched.)

## Fix contract (port, don't invent — CLAUDE.md §6)

Add a Turquin-style multiple-scattering energy compensation for the rough
**transmission** lobe, applied to the single-scatter GGX BTDF throughput,
matching what production engines ship:

1. **Canonical references:**
   - **Turquin 2019, "Practical multiple scattering compensation for
     microfacet models"** (Imageworks tech report) — the albedo-scaling
     formulation for dielectrics **including transmission**, with `E_ss`
     parameterized by (roughness, cos_theta, **ior**) — the ior axis is what
     distinguishes this from the reflection-only pkg60/pkg129 tables; both
     eta and 1/eta directions are needed.
   - **Cycles** `intern/cycles/kernel/closure/bsdf_microfacet.h`
     `microfacet_ggx_preserve_energy` + the **glass** E/Eavg albedo tables it
     consumes for `CLOSURE_BSDF_MICROFACET_GGX_GLASS` (Apache-2.0; Blender
     replaced stochastic multiscatter-GGX with exactly this in commit
     `888bdc1` / PR blender/blender#107958). **Confirm the exact table
     symbols/dimensions against the live source at port time** — prefer
     porting Cycles' pre-baked glass tables outright (D-independent, proven)
     over re-deriving.
   - **adobe/openpbr-bsdf** (Apache-2.0) — carries 7 CUDA-ready multiscatter
     energy LUTs incl. dielectric transmission (verified in
     `2026-07-pbr-advances-research-pass2.md`); a second license-clean table
     source if the Cycles extraction is awkward.
2. Apply on the CPU Disney rough-transmission path first (where the furnace
   gate lives); mirror on the GPU dielectric/closure-graph path (memory
   `gpu-dielectric-lowers-to-closure-graph`) with RTX parity.
3. Validate the estimator identity the research doc establishes: post-fix,
   single-scatter + compensation should integrate the furnace to ~1.0 where
   the theory predicted `G1(wi)/ior²` for single-scatter alone.
4. Table provenance + license recorded in `data/` README per the pkg60/pkg145
   precedent.

## Gates

- **Rough-glass furnace restored:** [0.92, 1.03] (the pkg118 gate band) across
  R ∈ {0.05, 0.1, 0.3, 0.6, 1.0} **on the corrected sampler** (`670e583`
  stacked) — the 0.09–0.82 regression is the package's reason to exist.
- **pkg149's peak-alignment stays green** (<2°, N≥100k) — compensation scales
  throughput magnitude, it must not touch sampled direction shape.
- chi² glass[0.3-45]: report the number on the stacked pair; the un-xfail is
  owned by pkg149 and may only flip with both packages' gates green
  (`--runxfail` verified).
- White-furnace + smooth-glass + caustic/prism refbank unchanged; **visual
  check mandatory** on the rough-glass and caustic renders (memory
  `general-photon-loop-needs-solid-glass`).
- CPU==GPU parity per-channel mean-ratio on a rough-glass scene; build
  evidence per CLAUDE.md.

## Non-goals

- Reflection multiscatter LUTs / GPU metal placeholder (pkg129).
- Re-opening pkg118's albedo-LUT clamp fix (valid, untouched).
- Any further sampler-shape changes (pkg149/pkg150 own those).
