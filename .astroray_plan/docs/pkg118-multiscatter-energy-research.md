# pkg118 — rough-dielectric energy: forced-TIR pdf fix + corrected root-cause

**Date:** 2026-06-08
**Author:** Claude (Opus 4.8)
**Spec:** `packages/pkg118-rough-dielectric-multiscatter-energy.md`
**Outcome:** Part A (forced-TIR pdf) landed; **Part B (Kulla-Conty compensation table)
is a DEAD-END — the spec's diagnosis is incomplete.** pkg118 stays OPEN, re-scoped.

## Baseline (256 spp, ior 1.5, reproduced 2026-06-08)

| R | 0.05 | 0.10 | 0.30 | 0.60 | 1.00 |
|---|------|------|------|------|------|
| CPU furnace | 0.771 | 0.815 | 0.921 | 0.967 | 0.962 |
| GPU furnace | 0.905 | 0.956 | 1.000 | 1.000 | 1.000 |

Gate (`test_disney_rough_glass_furnace_energy_cpu`, xfail) wants ∈[0.95,1.02] for
R∈{0.1,0.3,0.6,1.0}. The deficit is **worst at LOW roughness** — the OPPOSITE of
single-scatter GGX masking (which worsens with roughness).

## Part A — forced-TIR delta pdf (CPU + GPU) — LANDED, correct, gate-neutral

`disney.cpp` sample() (and the GPU `gpu_disney_sample` mirror) set the forced-TIR
delta-reflect `pdf = fresnel * transmission_`. When `cannotRefract` (TIR) forces the
reflection, its selection probability is 1, so `pdf = transmission_`; only a
Fresnel-roulette-selected reflection keeps the `fresnel` factor. Just past the
critical angle the geometric Schlick `fresnel` ≈ 0.04–0.07 while the true reflectance
→ 1, so the old pdf over-counted forced-TIR throughput by ~1/fresnel (~14–24× firefly).
**Cite:** PBRT-v4 §9.5 `DielectricBxDF::Sample_f` (pdf = pr/(pr+pt); TIR ⇒ pt=0 ⇒ 1).

**Measured: this is a no-op on the furnace centre-patch gate** (0.815→0.815): the
forced-TIR events fire near the critical angle on *exit* and scatter to edge pixels,
not the centre patch the gate samples. It IS a correct firefly/variance fix and is
kept. It does NOT close the gate on its own.

## Part B — Kulla-Conty multi-scatter table — REJECTED (does not address the deficit)

The spec prescribes a precomputed `E_glass(alpha,mu,eta)` table and a
`1 + Fms(1-E)/E` factor on the rough-transmission throughput, mirroring the opaque
GGX lobe's `ggxCompensationFactor`. This was implemented and tested; it does NOT work:

1. **The deficit is not single-scatter masking.** Masking loss worsens with
   roughness; the furnace deficit is worst at LOW roughness (R=0.05: 0.77). A
   Kulla-Conty masking compensation (`1/E[G1]`) compensates MORE at high roughness —
   the wrong direction.
2. **Two albedo-table estimators both fail.** Brute-force sphere integration of
   `f·cosI` underflows at low alpha (the sharp transmission lobe is missed → E≈0). An
   importance-sampled MC of the renderer's `sample()` throughput returns the RADIANCE
   expectation (incl. the `1/η²` radiance factor and the `1/fresnel` firefly), which
   is >1 and is not an energy albedo to invert.
3. **Even compensating the right code path barely moves the gate.** A furnace-calibrated
   table (`E=F0^0.5` ⇒ `C=F0^−0.5` per bounce) applied to `roughTransmissionEval`
   moved R=0.1 by **+0.003**. Adding the same factor to the rough→delta **fallthrough**
   refract (which carries ~80% of low-R transmission energy — at R=0.05 the spec's own
   instrumentation shows ~1.3M fallthroughs vs 330K rough refractions) moved R=0.1 only
   **0.815 → 0.823**. The transmission throughput is simply not where the energy leaks.

## Corrected root cause (the real lead for the next attempt)

The decisive datum: at R=0.1 the **GPU spectral closure-graph path is already
energy-conserving (0.956)** while the **CPU bespoke RGB `disney_sample` is 0.823**.
The closure path uses `makeDielectricTransmissionClosure` (a proper energy-conserving
microfacet dielectric); the CPU RGB Disney glass is a hand-rolled VNDF-rough +
smooth-delta **hybrid** whose fallthrough/threshold handling at low alpha loses ~13%
that the closure formulation does not.

**So pkg118 is not a multi-scatter-table problem — it is a CPU-RGB-path formulation
problem.** The fix is to make the CPU rough Disney glass match the energy behaviour of
the GPU closure path (or route disney glass through the same dielectric closure on
CPU), not to bolt a compensation table onto a leaky hybrid. The leak must be localized
with per-event energy instrumentation (rough-reflect / rough-refract / delta-reflect /
delta-refract / fallthrough), comparing each event's expected vs realized throughput
against the closure path.

## Recommendation

- Keep Part A (correct).
- Re-scope pkg118 around the CPU-RGB-vs-closure-path divergence; the Kulla-Conty table
  is removed from scope. Keep the `test_disney_rough_glass_furnace_energy_cpu` xfail.
- Only `disney` rough glass is affected; the prism / glass-sphere / dielectric-furnace
  scenes use the separate `dielectric` plugin and are untouched by any of this.

## PRECISE LOCALIZATION (2026-06-08, instrumented — the actionable lead)

Added DISNEY_DBG per-event instrumentation to `disney.cpp::sample()` (gated by env
`DISNEY_DBG`, near-zero cost off) + `scripts/diag_disney_dbg.py` (single-roughness
furnace + depth sweep). Findings at R=0.05 (furnace 0.771, ior 1.5, 256 spp):

```
rough_refl  count=359       avg_tp=0.19
rough_refr  count=330210    avg_tp=0.50
delta_refl  count=581425    avg_tp=2.24
delta_refr  count=719513    avg_tp=1.81
fallthrough count=1300938                 (= delta_refl + delta_refr)
```

1. **Not truncation.** Depth sweep R=0.05: furnace = 0.749 / 0.759 / 0.755 / 0.768 at
   depth 4 / 16 / 64 / 256. The loss saturates by depth ~4 — a genuine per-bounce leak,
   not rays trapped inside the sphere.
2. **alpha is CLAMPED at 0.0064 for R≤0.08** (`alpha = max(R², 0.0064)`), so the rough
   microfacets at R=0.05 are *near-flat* — yet the rough path furnaces 0.77 while the
   smooth-delta path (R=0.03) furnaces 0.97. So the rough VNDF path itself leaks ~20% vs
   the delta path at essentially-identical (near-flat) microfacet geometry.
3. **The leak is the rough→delta fallthrough mis-weighting.** 80% of rough samples fall
   through (1.3M of 1.63M). The dominant fallthrough trigger is the **rough-reflection
   side-check** (`disney.cpp` `if (s.wi.dot(rec.normal) * wo.dot(rec.normal) > 0)`): on
   the curved sphere, grazing/TIR microfacet reflections land *below* the macro surface,
   the check rejects them, and they fall through to the **macro-delta path** (geometric-
   normal reflection with `pdf = fresnel·transmission`). That macro-delta is sampled
   AFTER the VNDF + R/(R+T) randoms were already drawn, so its pdf does not account for
   the VNDF sampling that preceded it → energy mis-weighted (the delta avg_tp 1.8–2.2
   are η²-amplified exit events whose contribution does not balance the entering side).

**The fix (next attempt):** replace the bespoke VNDF-rough + smooth-delta hybrid +
fallthrough with a clean **PBRT-v4 `DielectricBxDF::Sample_f`** (BSD-3-Clause): sample
wm via VNDF, `pr=F, pt=1−F`, reflect or transmit *within the microfacet framework* with
matching `f` and `pdf` (`f_reflect = D·F·G/(4|cosO||cosI|)`, `pdf_reflect =
VNDF·pr/(4|wo·wm|)`; transmit via the existing `roughTransmissionEval/Pdf` scaled by
`pt`). NO macro-delta fallthrough for rough glass — invalid micro-samples return f=0
(unbiased VNDF). Validate: furnace ∈[0.95,1.02] for R∈{0.1,0.3,0.6,1.0} AND no
regression to `test_glass_sphere_caustic`, the prism gates, and the disney-sweep SSIM
(disney glass is in that scene). The GPU `gpu_disney_sample` mirror must be updated in
lockstep. Mirror Cycles `bsdf_microfacet.h` (Apache-2.0) for cross-check.

### ATTEMPT 2026-06-08 — "remove the fallthrough" TANKS (the fallthrough is load-bearing)

Implemented exactly the above (clean PBRT-v4 reflect/transmit, correct dielectric
microfacet reflection `f = D·F·G/(4·cosO)`, NO macro-delta fallthrough, invalid micro
returns f=0). **Result: the CPU furnace collapsed to 0.000 at every roughness.** Built +
measured; reverted.

Why: removing the fallthrough kills the glass entirely. The deficit's 80% "fallthrough"
is dominated by **EXIT** interactions (ray inside the sphere hitting the curved surface
at grazing → micro-TIR / micro-reflection below the surface → invalid). Without the
fallthrough those exit samples return f=0 and the path DIES inside the sphere before it
can escape to the white environment → no light returns. The macro-delta fallthrough was
keeping those rays alive (giving them a valid continuation direction).

**So the next attempt must NOT just delete the fallthrough.** Two viable directions:
1. **Fix WHY exit micro-samples are invalid.** On a curved exit at grazing the VNDF
   microfacet reflection often lands below the geometric surface and the same-hemisphere
   check rejects it. PBRT-v4 keeps these alive because micro-TIR reflects *off the
   microfacet* and stays in the lobe; the disney port rejects them. Make the rough
   reflection produce a valid in-medium TIR reflection (so few samples are invalid),
   THEN the no-fallthrough estimator conserves.
2. **Keep the fallthrough but make it energy-CONSISTENT.** The fallthrough's macro-delta
   pdf must account for the VNDF + R/(R+T) randoms already drawn (MIS-weight it against
   the rough lobe), instead of the bare `fresnel·transmission`. This is the lower-risk
   path — it preserves the working ray continuation and only fixes the mis-weighting.

This is a careful multi-step microfacet-dielectric rewrite (instrument exit vs enter
separately first — the 2026-06-08 DISNEY_DBG `entering` flag was the macro `cosTheta`
sign, which mislabels exits; use `rec.frontFace`). Best done as a focused session.
