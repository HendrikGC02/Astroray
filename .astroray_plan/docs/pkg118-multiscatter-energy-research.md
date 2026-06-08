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
