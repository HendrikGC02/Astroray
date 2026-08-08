# pkg179 — Phase 1 diagnosis: the "3× dead-sample-rate" discrepancy

**Scope:** Phase 1 ONLY (steps 1–3). No Phase-2 redistribution term built.
**Date:** 2026-08-09
**Main SHA under test:** `d0db581` (post-#562/#571).
**Engine used:** `build_cuda/astroray.cp313-win_amd64.pyd` (pkg181 build, `d896c1b`).
  - `plugins/materials/disney.cpp` is **byte-identical** between `d896c1b` and
    `d0db581` (`git diff` empty), so the CPU dead-fraction measurement is valid
    for current main. `gpu_materials.h` differs (pkg181's own changes) but the
    dead-fraction quantity here is CPU-only (`debug_bsdf_sample_batch` is a
    CPU-serial binding, `blender_module.cpp:601`).
**Config:** Disney glass, `metallic=0`, `transmission=1`, `ior=1.5`, LINEAR
  (this is a sampler-geometry measurement; no render/energy gate involved).
  N = 300k (engine) / 500k (analytic) per cell.

---

## Verdict (step 3)

**The 3× gap is a MEASUREMENT-METHODOLOGY / DEFINITION artifact — candidate (b).
It is NOT a sampler regression (a) and NOT new physics (c).**

- pkg150's documented **7.1% at r=1.0, θ=0** is *correct and current*. It
  reproduces on main to two decimals across the **entire** pkg150 grid.
- pkg167's **22.9% at r=1.0** is a *different quantity*: the raw, un-gated VNDF
  below-horizon **reflection** rate (before the Fresnel branch-selection knocks
  it down ~5–7×), and/or a grazing-incidence reading. It is not the realized
  dead-sample rate that the furnace actually experiences.

The physically load-bearing number — the fraction of *paths* that lose their
fallback energy when the dead-sample fix removes the smooth-delta reroute — is
**~7% at r=1.0, θ=0** (falling to ~2.8% at θ=75), exactly as pkg150 documented.

**Per the spec fork: methodology artifact ⇒ no sampler fix implemented, Phase 2
NOT started.** Recommendation on whether Phase 2 is still needed is below (it
turns on a design fork that is the lead's to adjudicate, not mine).

---

## Step 1 — reproduce & localize the rate

Two independent measurements of the realized below-horizon **fallback** rate
(the fraction of `sample()` calls that reach the smooth-delta fallback at
`disney.cpp:812`, i.e. the VNDF reflection candidate landed below the geometric
hemisphere or — never, see below — the microfacet refraction failed):

### (i) Analytic replication of `sample()`'s transmission-branch geometry

A faithful NumPy port of `sampleGgxVNDF` (Heitz 2018 / pbrt-v4 form on main) +
the Fresnel branch split + the same-hemisphere check + `refractThroughMicroNormal`.
`totalfb%` = fraction of all samples reaching the fallback:

| r \\ θ | 0 | 30 | 45 | 60 | 75 |
|---|---|---|---|---|---|
| 0.3 | **0.086** | 0.110 | 0.153 | 0.360 | 1.265 |
| 0.6 | 1.266 | 1.408 | 1.774 | 2.382 | 2.532 |
| 1.0 | **7.026** | 5.529 | 4.839 | 4.088 | 2.789 |

This matches **pkg150 Finding 1** (r=0.3 row: 0.08/0.11/0.16/0.35/1.25) and
**Finding 2** (7.1% @ r=1.0-θ0) to two decimals — validating both the port and
pkg150's figures as current.

Decomposition (same run): `refrfail% = 0.000` in **every** cell. The microfacet
refraction never fails geometrically (front-face entering a denser medium,
`eta=1/1.5<1`, so no microfacet TIR). **100% of the fallback is below-horizon
reflection.** The Fresnel branch is entered only `reflbr% ≈ 4–9%` of the time,
which is what gates the raw below-horizon reflection rate down to the realized
~7%.

### (ii) Engine corroboration (`debug_bsdf_sample_batch`, detector = wi within
0.25° of the smooth mirror/refract direction)

| r \\ θ | 0 | 30 | 45 | 60 | 75 |
|---|---|---|---|---|---|
| 1.0 | **7.057** | 5.482 | 4.836 | 4.068 | 2.761 |

At high roughness the engine detector agrees with the analytic replication
(7.057 vs 7.026 at r=1.0,θ0). At low roughness the direction-detector
over-counts (e.g. r=0.3,θ0 reads 2.1% vs true 0.086%) because legitimate
microfacet-refraction samples cluster within 0.25° of the exact smooth-refract
direction — a detector-tolerance false positive, not a real fallback. **The
analytic replication is the authoritative grid; the engine confirms it where the
detector is reliable (wide lobe / high roughness).**

`pdf<=0` fraction is **0.000 in every cell on main** — confirming that WITHOUT
the dead-sample fix, no sample is actually dead: the below-horizon reflection
reroutes through the fallback's second Fresnel roulette to a *live* smooth event
(pdf>0), overwhelmingly a smooth **transmission** (f = `baseColor·eta²·(1−F)`,
pdf = `(1−F)·transmission`). See the Phase-2 insight below.

### Where does 22.9% come from? (localizing the gap)

Candidate quantities in the "below-horizon" family, measured on the same
unchanged sampler:

| quantity (r=1.0) | θ=0 | θ=30 | θ=45 | θ=60 | θ=75 |
|---|---|---|---|---|---|
| realized fallback `totalfb%` (pkg150's metric) | 7.03 | 5.53 | 4.84 | 4.09 | 2.79 |
| **raw** VNDF below-horizon reflect % (ignores Fresnel split) | 50.1 | 46.3 | 41.5 | 33.4 | **20.5** |
| below-horizon **among reflection-branch** samples % | 76.5 | 69.4 | 62.6 | 51.9 | 33.3 |
| reflection-branch selection % | 9.2 | 8.0 | 7.7 | 7.9 | 8.4 |

22.9% is **not reproducible for the realized fallback at any r=1.0 cell** (max
7.03%). It sits squarely in the *raw* below-horizon reflection family (20.5% at
r=1.0, θ=75; ~23% at θ≈73), i.e. the per-microfacet below-horizon rate **before**
the Fresnel branch selection removes ~90% of would-be reflection events. (For
reference, the reflection-branch *selection* rate hits exactly 22.96% at
r=0.3,θ=75 — another quantity that could be mislabeled "22.9%".) Either reading
is a different statistic than pkg150's realized fallback; the gap is definitional.

---

## Step 2 — bisect the cause

**(a) Sampler regression between pkg150's `d02fe07` and main — RULED OUT.**
`git diff d02fe07..d0db581 -- plugins/materials/disney.cpp` shows **no change**
to `sampleGgxVNDF`, `refractThroughMicroNormal`, the Fresnel branch split
(`sampleReflection = ... F/(R+T)`), or the same-hemisphere check
(`s.wi.dot(rec.normal)*wo.dot(rec.normal) > 0`). The only two commits touching
the file since (`ee1e735` pkg167 reflection multiscatter; `b1da65f` pkg169
delta-Fresnel + rough |cosI|) altered eval/pdf *magnitudes* and the delta
fallback's f/pdf, none of which change **which** samples reach the fallback. The
dead-fraction geometry is invariant since pkg150 — and my reproduction confirms
7.03% is unchanged. The GPU twin (`gpu_disney_sample`, `gpu_materials.h:1073`)
byte-mirrors the same VNDF/split/hemisphere/fallback structure, so there is no
GPU-specific divergence in the below-horizon accounting either.

**(b) Measurement-methodology difference — CONVICTED.** pkg150 measured the
realized fallback rate (Fresnel-gated), = 7.03% @ r=1.0,θ0. pkg167's 22.9% is the
raw/un-gated below-horizon reflection rate (and/or a grazing reading). Same
sampler, different statistic → the entire 3× gap.

**(c) Genuine VNDF azimuth / hemisphere-orientation bug (pkg149 class) — RULED
OUT.** The pkg149 Lerp-argument fix is present and correct:
`t=(1+wh.z)/2; py=(1-t)*h + t*py` with `h=sqrt(1-px²)` (disney.cpp:231-233),
matching pbrt-v4 `p.y = Lerp((1+wm.z)/2, sqrt(1-Sqr(p.x)), p.y)`,
`Lerp(t,a,b)=(1-t)a+t b`, exactly. The raw below-horizon rate varies smoothly and
symmetrically with θ (50→20% as θ:0→75 at r=1.0), with no azimuth anomaly; ~50%
below-horizon at α=1, normal incidence is the expected, Smith-G-accounted VNDF
masking, not a defect. No oriented-normal/geometric-normal enter/exit mix-up in
the below-horizon path (front-face `etaI=1,etaT=ior` throughout).

---

## Step 3 — fork & recommendation

Because the finding is **methodology, not a sampler bug**, I did not implement a
sampler fix and did not start Phase 2. Two things the lead must decide:

### The furnace regression is real regardless of the 3× label
0.997→0.788 (CPU) / 1.000→0.918 (GPU) at r=1.0 when the dead-sample fix removes
the fallback (pkg150 Finding 2), and reflection compensation recovers only
+0.009 (pkg167 escalation). That is unchanged by this diagnosis — it is driven
by the realized **7%** per-bounce fallback compounding over the depth-32
integral, not by a phantom 23%.

### New mechanistic insight for Phase 2 (and pkg178)
**The existing smooth-delta fallback already redistributes the below-horizon
reflection energy into the TRANSMISSION lobe.** On main, a below-horizon VNDF
reflection candidate is not dead — it re-enters the fallback's second Fresnel
roulette and, because `F≈0.04–0.09` for this dielectric, ~95% of the time exits
as a smooth **transmission** event carrying `baseColor·eta²·(1−F)`. This is
*exactly* the physical routing the spec's Phase-2 premise calls for
("the masked energy belongs in the transmission lobe"), already happening — just
as a smooth-delta instead of a rough event. The dead-sample fix deletes this
redistribution, which is *mechanistically why* the furnace drops and why
reflection-lobe compensation cannot recover it (the energy was never in the
reflection lobe — it was being handed to transmission).

Consequently, **if the dead-sample fix must ship** (a binding pkg179 acceptance
criterion), Phase 2's transmission-lobe redistribution IS required — it is the
principled (rough, sample/pdf-consistent) replacement for what the smooth-delta
fallback does crudely today. The realized budget to redistribute is ~7% of
transmission-branch paths at r=1.0,θ0, not 23%.

### The fork I surface for the lead (do not resolve unilaterally)
There is a real question of whether the dead-sample fix is *worth* shipping at
all. The only defect it removes is the sample()/pdf() *type* mismatch (a delta
event where pdf() reports continuous density), and pkg150 Finding 3 showed that
chi² residual is **~90% an ires=4 quadrature artifact** (raw chi² 35107→3942
from ires 4→8 on the identical sampler). The current fallback is arguably
already doing the physically-right thing (routing below-horizon reflection
energy to transmission) and keeping the furnace at 0.99. So the choice is:

1. **Ship the dead-sample fix + build Phase 2 transmission redistribution** (the
   spec's default path) — structurally cleaner, informs pkg178's combined
   closure, but a genuine M–L effort to hold the furnace at all roughnesses.
2. **Do not ship the dead-sample fix** — keep the fallback's existing (crude but
   energy-correct) transmission reroute, and close the chi² concern as the
   documented quadrature artifact it is. Cheaper; risks leaving the split-lobe
   sample/pdf type-consistency imperfect (cosmetic at ires=4).

This is an architecture/scope call (the "one combined closure vs split lobes"
fork the spec itself raises), and it is the lead's to make. My Phase-1 evidence
narrows it to exactly this choice; I recommend the lead weigh option 2 seriously
given that the 23% that motivated "the energy is large and must be rebuilt" was a
measurement artifact and the realized rate is a modest 7%.

---

## Artifacts / reproduction
- `scratchpad/measure_dead.py` — engine `debug_bsdf_sample_batch` dead-detector grid.
- `scratchpad/vndf_below.py` — NumPy port of `sampleGgxVNDF`; raw below-horizon rate.
- `scratchpad/vndf_full.py` — full branch-logic replication; all candidate
  dead-rate definitions (the authoritative grid, matches pkg150).

## Citations (forms verified, not modified)
- **Heitz 2018**, "Sampling the GGX Distribution of Visible Normals," JCGT 7(4)
  — VNDF sampler; below-horizon reflections are an explicit implementation
  decision, not guaranteed upper-hemisphere.
- **pbrt-v4** `TrowbridgeReitzDistribution::Sample_wm` / `DielectricBxDF`
  (Apache-2.0) — the Lerp warp (verified against disney.cpp:231-233) and the
  dead-sample `pdf=0` semantics preserved at
  `.astroray_plan/docs/pkg150-deadsample-fix.patch`.
- **Cycles** `bsdf_microfacet.h` (BSD-3-Clause) — the combined-closure routing
  that makes the transmission reroute "free" (the Phase-2 design target).
