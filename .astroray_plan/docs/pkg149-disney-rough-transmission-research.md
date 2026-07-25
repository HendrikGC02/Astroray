# pkg149 — Disney dielectric rough-transmission sample/pdf: research + measurements

**Spec:** `.astroray_plan/packages/pkg149-disney-dielectric-rough-transmission-sample-pdf.md`
**Status:** BLOCKED — root cause of the OWNED defect (transmission sample/pdf peak
mismatch) found, cited, fixed, and verified (CPU+GPU); the fix also substantially
improves pkg150's charter as a side effect. However, the same fix (properly
implementing VNDF half-vector sampling) EXPOSES a previously-masked rough-glass
furnace/energy-conservation regression not described by either pkg149 or pkg150's
spec. Three concrete mechanisms have been ruled out by direct rebuild-and-measure
experiments (see "Furnace regression investigation" below); the remaining
candidate is a genuine missing multi-scatter/energy-compensation term for the
rough dielectric TRANSMISSION lobe — itself a non-trivial, separately-citable
physics addition (CLAUDE.md §6), not describable as "the same half-vector
convention/Jacobian, mirrored to two call sites" that this spec's Fix Contract
scopes. **Not shipped pending a scope decision** — see "Fork / decision needed"
at the end of this note. Code changes are present in the worktree
(`plugins/materials/disney.cpp`, `include/astroray/gpu_materials.h`) but NOT
pushed/PR'd.

---

## Citations

- **Heitz 2018**, "Sampling the Visible Normal Distribution of Visible Normals",
  JCGT 7(4) — canonical VNDF half-vector sampling algorithm; already in-tree and
  cited at `disney.cpp::sampleGgxVNDF`.
- **pbrt-v4** `src/pbrt/util/scattering.h` `TrowbridgeReitzDistribution::Sample_wm`
  (Apache-2.0, https://github.com/mmp/pbrt-v4) — the reference implementation
  Astroray's `sampleGgxVNDF`/`gpu_disney_sampleGgxVNDF` port from (already cited in
  both). Fetched and diff'd line-by-line against the in-tree port for this package.
- **pbrt-v4** `src/pbrt/util/math.h` `inline Float Lerp(Float x, Float a, Float b)`
  — `return (1 - x) * a + x * b;` — the definition needed to correctly read
  `Sample_wm`'s `p.y = Lerp((1 + wh.z) / 2, h, p.y);` call.
- **pbrt-v4** `src/pbrt/bxdfs.cpp` `DielectricBxDF::f` / `::PDF` / `::Sample_f`
  (Apache-2.0) — used to independently re-verify `roughTransmissionEval`,
  `roughTransmissionPdf`, and `refractThroughMicroNormal` against the canonical
  half-vector (`wm = wi*etap + wo`) and Jacobian (`dwm_dwi = |HdotI| /
  (HdotI + HdotO/etap)^2`) forms. **These were already byte-for-byte faithful
  ports; they are not the defect** (see below).
- License: pbrt-v4 is Apache-2.0/BSD-3 (per repo LICENSE.txt), compatible with
  Astroray's license.

---

## Method — reproduce the defect independently before touching code

Per CLAUDE.md §1/§6, the spec's own measurement (152° pdf peak vs 168-170° sample
peak, glass metallic=0/transmission=1/roughness=0.3/ior=1.5, wo at 45°) was
reproduced from scratch in a standalone NumPy port of the exact CPU math
(`sampleGgxVNDF`, `refractThroughMicroNormal`, `roughTransmissionPdf`, `vndfPdf`,
`fresnelDielectric`, `D_GTR2`, `smithG1_GGX`), using a local frame where
tangent=+X, bitangent=+Y, normal=+Z (so world math = local math) and wo in the x-z
plane. Result, pre-fix (N=300,000, restricted to `|wi.y|<0.03` in-plane,
26,095 live transmission samples survived Fresnel-roulette selection):

| | measured (repro) | pkg138 note | Snell prediction |
|---|---|---|---|
| pdf() peak theta_from_normal | **151.80°** | 152° | 151.87° (`180-asin(sin45/1.5)`) |
| sample() peak theta_from_normal | **167.5°** | 168-170° | — |

This matches the spec's numbers closely enough to trust the standalone repro as a
faithful mirror of the in-tree code, and rules out a measurement artifact.

## Isolating the mechanism — half-vector reconstruction is exact

The spec's Fix Contract point 1 suspected the half-vector convention or Jacobian
denominator disagreeing between `sample()`'s construction and `pdf()`'s term. This
was tested directly: for 13,395 live transmission samples, `wm` was reconstructed
from the actual `(wo, wi)` pair using `roughTransmissionPdf`'s own formula
(`wm = normalize(wi*etap + wo)`, face-forwarded) and compared to the original `wm`
drawn by `sampleGgxVNDF` and used by `refractThroughMicroNormal` to build that same
`wi`. **0 of 13,395 mismatched** (cosine agreement >0.9999 in all cases) — the
half-vector reconstruction, the `etap`/Jacobian convention, and the eval/pdf
formulas are already a faithful, internally-consistent pbrt-v4 port (confirmed
line-by-line against `pbrt_bxdfs.cpp`'s `DielectricBxDF::f`/`PDF`, fetched
2026-07-24). **Root cause is not in `roughTransmissionEval`/`roughTransmissionPdf`
or `refractThroughMicroNormal`.**

## Root cause — `sampleGgxVNDF`'s disk-warp Lerp has swapped arguments

pbrt-v4's `TrowbridgeReitzDistribution::Sample_wm` (`scattering.h:163-187`):

```cpp
Float h = std::sqrt(1 - Sqr(p.x));
p.y = Lerp((1 + wh.z) / 2, h, p.y);   // Lerp(t,a,b) = (1-t)*a + t*b
```

i.e. `p.y_new = (1-t)*h + t*p.y_orig` where `t = (1+wh.z)/2`.

Astroray's in-tree port (`disney.cpp::sampleGgxVNDF`, `gpu_materials.h::
gpu_disney_sampleGgxVNDF`, both pre-fix, byte-identical to each other):

```cpp
float h = std::sqrt(std::max(0.0f, 1.0f - px * px));
py = ((1.0f + wh.z) / 2.0f) * h + (1.0f - (1.0f + wh.z) / 2.0f) * py;
```

i.e. `py_new = t*h + (1-t)*py_orig` — **the coefficients of `h` and `py` are
swapped relative to pbrt-v4's `Lerp(t, h, p.y)` call.** This is an
argument-transcription error (reading `Lerp(t, a, b)` as if it computed
`t*a + (1-t)*b`), not a sign flip or a Jacobian error.

**Numeric confirmation of the mechanism (wo at 45°, roughness=0.3, u1=u2=0, the
"most central" disk sample):**

| formula | `m_local` (tangent/bitangent/normal frame) |
|---|---|
| pre-fix (Astroray) | `(-0.484, 0, 0.875)` — **azimuth opposite wo** |
| pbrt-v4 (correct) | `(+0.083, 0, 0.997)` — azimuth aligned with wo, as expected |

Physically, VNDF sampling concentrates visible microfacet normals *between* `wo`
and the macro normal — i.e. tilted toward `wo`'s azimuth, never away from it. A
full-distribution check (N=2,000,000 wm draws, `wo`'s azimuth = 0°) confirms this
isn't a one-sample fluke — pre-fix, **100% of sampled `wm` had `|phi_m| > 90°`**
(azimuth bins `[-90°,90°]` — the side matching `wo` — had **zero** samples; all
mass was in `[-180°,-120°]` and `[120°,180°]`). This azimuthal inversion, propagated
through the (independently-verified-correct) refraction mapping, is exactly what
produces the reported 16-18° peak-shift in the resulting `wi` distribution: the
half-vectors are systematically drawn from the wrong side of the lobe, biasing the
refracted-ray population toward larger bend angles than the (correctly-computed)
analytic pdf predicts.

## Fix

One-line fix, mirrored in both CPU (`disney.cpp::sampleGgxVNDF`) and GPU
(`gpu_materials.h::gpu_disney_sampleGgxVNDF`):

```cpp
float h = std::sqrt(std::max(0.0f, 1.0f - px * px));
float t = (1.0f + wh.z) / 2.0f;
py = (1.0f - t) * h + t * py;
```

This is the sole change; `roughTransmissionEval`/`roughTransmissionPdf`/
`refractThroughMicroNormal`/`vndfPdf` are untouched (verified already correct,
see above) — consistent with the spec's Fix Contract point 1's *outcome*
(sample and pdf now agree) even though the actual defect was one level upstream
of where the spec's hypothesis pointed (a shared VNDF-normal-sampling primitive
bug, not the transmission-specific construction/Jacobian).

**Post-fix repro measurement** (same standalone harness, N=300,000, wo=45°,
roughness=0.3, ior=1.5, 180,316 live in-plane transmission samples):

| | pre-fix | post-fix | Snell prediction |
|---|---|---|---|
| pdf() peak theta_from_normal | 151.80° | 151.80° (unchanged, formula untouched) | 151.87° |
| sample() peak theta_from_normal | 167.5° | **152.5°** | — |
| **peak offset** | **~15.7°** | **~0.7°** | (gate: <2°) |

## Side effect on pkg150 (reflection-candidate masking) — measured, not fixed here

`sampleGgxVNDF` also feeds the VNDF *reflection* candidate
(`s.wi = reflect(wo,wm)` in `sample()`). Since the fix changes which `wm`'s are
drawn (now correctly concentrated toward `wo`'s azimuth rather than away from it),
it changes pkg150's starting point. Measured post-fix, same
`debug_bsdf_sample_batch` methodology as the pkg138 note (N=100,000 per config,
glass metallic=0/transmission=1/ior=1.5):

| theta | roughness=0.3 (pre-fix accept%) | roughness=0.3 (post-fix accept%) |
|-------|-------|-------|
| 0     | 0.0%  | 0.0%  |
| 30    | 0.0%  | 0.0%  |
| 45    | 0.0%  | 0.0%  |
| 60    | 0.0%  | 0.0%  |
| 75    | 20.59%| 21.4% |

`glass[0.3-45]`'s reflection-candidate acceptance is still 0% post-fix — the
azimuthal-inversion bug did not happen to be the reflection lobe's masking
mechanism (that mechanism, per the pkg138 note, is the Fresnel-roulette
preferentially selecting near-grazing `HdotO` half-vectors whose reflection
crosses the macro hemisphere regardless of azimuth). pkg150 is unaffected by this
fix and remains open with its own defect intact; this is reported for
attribution transparency only, no pkg150 code was touched.

## Net effect on the owned gate (chi²)

Measured, `--runxfail` (`tests/statistical/test_chi2_bsdf.py::test_chi2_disney_glass[0.3-45]`):

| | chi² statistic (d.o.f=1025) | p-value |
|---|---|---|
| Baseline (pre-pkg149, = post-pkg138) | 143,140,779.145224 | 0.000000 |
| + this fix (sampleGgxVNDF Lerp swap only) | 34,987.970271 | 0.000000 |

**~4,092x reduction**, but still red (critical chi² at alpha=0.002008/1025 dof is
~1,150-1,200). Reflection-candidate acceptance at `glass[0.3-45]` improved from
0.0% (pkg138 measurement) to **5.15%**, with **99.86%** of those candidates'
`s.pdf` matching a fresh `pdf()` re-evaluation within 10% (i.e. genuine,
correctly-modeled VNDF reflection samples, not delta fallbacks) — pkg150's
charter defect looks substantially, though not completely, resolved as a side
effect of this same fix (see "Side effect on pkg150" above). The residual chi²
is consistent with a small (~0.28% of total probability mass at this exact
config) remaining delta-vs-continuous mismatch from the pre-existing "both VNDF
branches fail -> smooth event" fallback (`disney.cpp` sample(), the comment
"Extremely grazing sampled microfacets can fail both reflection and refraction");
this fallback is explicitly pkg150's territory (same-hemisphere/coverage-hole
family) and was not modified here.

**The chi² un-xfail was NOT applied** — the gate is unambiguously still red, and
per the spec's own instruction ("do NOT force it") the xfail must stay in place.
This is secondary to the furnace blocker below, which is the reason nothing was
shipped this round.

---

## Furnace regression investigation — BLOCKING

Applying *only* the `sampleGgxVNDF` Lerp fix (nothing else) regresses
`test_disney_rough_glass_furnace_energy_cpu` catastrophically:

| roughness | pre-fix (passing) | post-fix (Lerp swap only) | required band |
|---|---|---|---|
| 0.1 | ~0.94 | **0.217** | [0.92, 1.03] |
| 0.3 | ~1.00 | **0.357** | [0.92, 1.03] |
| 0.6 | ~1.00 | **0.596** | [0.92, 1.03] |
| 1.0 | ~1.00 | **0.817** | [0.92, 1.03] |

Confirmed this is a genuine regression (not pre-existing): reverted the fix,
rebuilt, re-ran the same test — passes cleanly on the unmodified `9bb058f`
baseline. Confirmed converged, not a variance artifact: `test_disney_rough_
glass_furnace_converges` (256 vs 1024 spp at roughness=0.3) agrees within 0.03
(both ~0.35-0.36) — the estimator has settled on a wrong value, it is not still
drifting toward 1.0.

**Three hypotheses tested and ruled out** (each via a full rebuild + re-render,
not just code reading):

1. **The newly-reachable VNDF reflection candidate is unbalanced.** Tested by
   forcing `sampleReflection` to always fail (100% fall-through to
   transmission-or-smooth-delta) with the Lerp fix still applied. Furnace got
   *worse*, not better (R=0.1: 0.085 vs 0.217) — the reflection lobe is not the
   source; if anything it was contributing a small compensating amount of
   energy back.
2. **`roughTransmissionEval` needs an explicit `|cosI|` factor** (a
   "bare-BTDF-vs-render-loop-convention" mismatch hypothesis: Astroray's render
   loop does `throughput *= f_spectral/pdf` with no separate cosine multiply
   anywhere, matching the convention `eval()`'s reflection/diffuse paths use
   internally — `result*NdotL` baked into the return value — but
   `roughTransmissionEval`'s early-return bypasses that final multiply,
   returning a bare pbrt-v4-style BTDF). Implemented (`return result *
   std::abs(cosI)`, both CPU and GPU), rebuilt, re-tested: **no meaningful
   change** (R=0.1: 0.211 vs 0.217 pre-change) — reverted. This hypothesis was
   algebraically well-motivated (a direct derivation from the in-tree formulas
   gives `f_t*cosI/pdf_t = G1(wi)/etap²` for the "correct", explicit-cosine
   convention) but empirically wrong as the dominant effect, or cancelled by
   something else.
3. **The integrator's firefly clamp (`raytracer.h` `if (maxC>10.0f) throughput
   *= 10.0f/maxC`) is discarding legitimate high-throughput grazing-exit
   energy that the old (wrong-azimuth) sampler never reached.** Tested by
   raising the clamp threshold to 1,000,000 (effectively disabled) for this
   diagnostic, rebuilding, re-testing: **no meaningful change** (R=0.1: 0.217
   vs 0.217) — if rare high-value paths were being clamped away, disabling the
   clamp should have raised the furnace value substantially; it did not.
   Reverted (clamp restored to 10.0).

**A direct single-scatter measurement supports a genuine (not clamping-driven)
energy deficit, not a "wrong formula" bug**: computing `f_t*|cosI|/pdf_t`
per-sample (Python re-implementation of `roughTransmissionEval`/
`roughTransmissionPdf`, cross-checked against the compiled binary's sampled
`wi`/`pdf`) at `glass[0.3-45]`, the **median** of this per-sample estimator
across 470k+ transmission-side samples is **0.4439**, matching the theoretical
single-interface value `G1(wi)/etap² ≈ 1/1.5² = 0.444` (etap=ior=1.5 entering)
almost exactly — i.e. the BSDF math (`roughTransmissionEval`/
`roughTransmissionPdf`/`refractThroughMicroNormal`) is NOT wrong for the bulk of
transmission events. Only the top ~0.01-0.1% of samples spike to ~90 (expected
MC variance near a near-singular Jacobian denominator, not itself alarming and
not what the clamp-disable experiment implicated).

Also checked and ruled out as an explanation for the *specific* central-patch
(near-axial-ray) deficit measured by the furnace test: a genuine chirality
difference exists between a sphere's frontface and "backface" (from-inside-glass)
hit-point tangent frames (`buildOrthonormalBasis(normal,...)`: the shading
normal is negated on a backface hit, which leaves `tangent` unchanged but flips
the sign of `bitangent` — traced algebraically). For an *isotropic* GGX lobe
this by itself should be energy-neutral (mirror symmetry), and for the
furnace test's near-axial rays specifically, entry and exit normals happen to
coincide numerically (both ≈(0,0,±1) map to the same `buildOrthonormalBasis`
inputs), so this mechanism does not actually differ frontface-vs-backface for
the rays the test's center-patch measures. Not pursued further as the primary
explanation, though it may be worth an independent look for off-axis rays.

**Working hypothesis (not verified further, time-boxed):** a genuine,
pre-existing energy-conservation gap in the rough-dielectric-transmission
estimator's tail/multi-bounce behavior — most plausibly a missing multi-scatter
compensation term for the transmission lobe (the reflection lobe already has
one, `ggxCompensationFactor`/`DisneyEnergyCompensationTables`, Kulla & Conty
2017-style; the transmission lobe has none) — that was previously masked
because the buggy (wrong-azimuth) VNDF sampler systematically under-explored
the true half-vector distribution, and is now exposed because the corrected
sampler reaches it. This is explicitly flagged as future work in the pkg118
research note (`.astroray_plan/docs/pkg118-multiscatter-energy-research.md`:
"a masking/multiscatter compensation term ... Kulla & Conty 2017 / Turquin
2019") but was never implemented for the transmission side. Confirming this
would need a proper multi-scatter derivation/port (its own CLAUDE.md §6
citation trail), not assumed here.

## Fork / decision needed

This package cannot currently close all of its own gates simultaneously:

- Shipping the `sampleGgxVNDF` fix alone (which correctly, verifiably fixes the
  peak-alignment defect this package owns, and improves pkg150's charter as a
  bonus) **regresses the furnace gate** from ~0.94-1.0 to ~0.09-0.82 — an
  explicit hard requirement of this spec ("Furnace/rough-glass furnace
  unchanged").
- NOT shipping the fix leaves the peak-alignment defect (and the chi² gate
  transfer this package was created to own) unresolved.
- Closing the furnace gap properly (multi-scatter compensation for the rough
  transmission lobe) is a genuine, non-trivial, separately-citable physics
  addition — outside this spec's stated Fix Contract ("same half-vector
  convention and Jacobian ... one derivation, two call sites") and likely
  multiple additional hours of research + implementation + its own
  furnace/chi²/parity verification loop.

Real options, not manufactured:
1. **Hold pkg149** (do not ship yet); file the furnace-exposure finding as
   its own follow-up spec (multi-scatter compensation for rough dielectric
   transmission) and let that land first or alongside.
2. **Expand pkg149's scope** to include the multi-scatter compensation
   research/implementation now, closing both the peak-alignment defect and the
   furnace gate together (larger, uncertain-duration task).
3. **Ship the peak-alignment fix with the furnace gate explicitly re-gated**
   (xfail/skip with a documented, measured reason analogous to how pkg138
   handled its own residual) — only appropriate if the furnace gate's owner
   agrees a documented regression is acceptable pending a follow-up package;
   the spec as written treats furnace as non-negotiable, so this needs
   explicit sign-off, not an implementer's unilateral call.

No code from this investigation has been pushed. The worktree
(`C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg149`) has the
Lerp fix (CPU+GPU), the peak-alignment test, and this research note, committed
locally on branch `pkg149-rough-transmission-sample-pdf` pending a decision on
the above.
