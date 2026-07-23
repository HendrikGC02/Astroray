# pkg138 — Disney dielectric rough-reflection eval: research + measurements

**Spec:** `.astroray_plan/packages/pkg138-disney-dielectric-rough-reflection-eval.md`
**Status:** PARTIAL — the spec's diagnosed defect (Cspec0 collapse in `eval()`) is
fixed and verified; the acceptance gate (`test_chi2_disney_glass[0.3-45]`) is
**still red**, root-caused to two further, out-of-spec-scope defects (below).

---

## Citations

- **pbrt-v4** `src/pbrt/bxdfs.cpp` `DielectricBxDF::f` / `DielectricBxDF::Sample_f`
  reflection branch (BSD-3-Clause), https://github.com/mmp/pbrt-v4 — the
  reflection-lobe BRDF form and the `Sample_f` reflect-then-`SameHemisphere`
  discard convention.
- **Walter, Marschner, Li, Torrance 2007**, "Microfacet Models for Refraction
  through Rough Surfaces" (EGSR), §5.1 Eq. 20:
  `f_r(wo,wi) = D(wm)*G(wo,wi)*F(wo.wm,eta) / (4*cosThetaO*cosThetaI)`.
  https://www.graphics.cornell.edu/~bjw/microfacetbsdf.pdf
- **Heitz 2018**, "Sampling the GGX Distribution of Visible Normals", JCGT 7(4)
  — already in-tree (`sampleGgxVNDF`), unmodified.
- License: pbrt-v4 is BSD-3-Clause, compatible with Astroray's Apache-2.0.

---

## Fix #1 (spec's diagnosed defect) — SHIPPED, verified

**Mechanism (as diagnosed by the spec, confirmed):** `sample()`'s VNDF
reflection candidate calls `eval(rec, wo, s.wi)` to get its throughput. For a
transmissive (glass) material, `eval()`'s only reflection term was the OPAQUE
Schlick term `spec = Ds * F * Gs` with `F0` built from `Cspec0 = specular_*0.08`
(a plastic-highlight approximation) — not related to the dielectric's own
`ior_`. `pdf()`, on the transmission side, independently reports a continuous
VNDF reflection density (`microfacetReflectionPdf`, added by pkg123) using the
correct dielectric Fresnel. The two lobes disagreed in *magnitude and shape*.

**Fix:** added `roughReflectionEval()` (CPU: `plugins/materials/disney.cpp`;
GPU: `include/astroray/gpu_materials.h::gpu_disney_roughReflectionEval`,
reached via `GCLOSURE_DIELECTRIC_TRANSMISSION -> GMAT_DISNEY` in
`gpu_closure_as_material`, confirmed by reading `scene_upload.cu` +
`gpu_materials.h`), computing the bare (untinted) Walter Eq. 20 BRDF:

```
f_r = D_GTR2(NdotH,alpha) * smithG1_GGX(cosO)*smithG1_GGX(cosI)
      * fresnelDielectric(HdotO, 1, ior_) / (4*cosO*cosI)
```

reusing the in-tree `D_GTR2`, `smithG1_GGX` (true Smith G1, not the combined
visibility form the opaque `spec` term uses), and `fresnelDielectric`. In
`eval()`, blended with the opaque Schlick term by the same
`(1-transmission_)` / `transmission_` mixture weights `pdf()` already uses
(`mixScale` in `pdf()`), so `eval()`'s reported value matches the mixture
`sample()`/`pdf()` actually implement:

```cpp
if (transmission_ > 0.0f && roughness_ > kDeltaTransmissionRoughness) {
    float dielectricWeight = (1.0f - metallic_) * transmission_;
    spec = spec * (1.0f - dielectricWeight) +
           dielectricWeight * roughReflectionEval(rec, wo, wi);
}
```

**Verification (direct query, bypassing the chi2 harness):** glass
(metallic=0, transmission=1, roughness=0.3, ior=1.5), `wo` at 45°, `wi` at the
mirror direction: `eval()` now returns `[0.6946, 0.6946, 0.6946]` with
`pdf()=0.6961` (ratio 0.9976, consistent) — pre-fix this candidate would have
been rejected by `sample()`'s `s.f.length2() > 0` check (Cspec0-collapsed
value near the 0.060 sample/eval ratio the pkg123 review measured).

This fix is real and does move OTHER (roughness, theta) configurations where
the VNDF reflection candidate is actually accepted (roughness>=0.5 at
theta>=60, measured acceptance rates below) — it does **not**, however, move
`glass[0.3-45]` (see Root cause #2).

---

## Root cause #2 (measured, NOT fixed) — `sample()`'s VNDF reflection is masked 100% of the time at this config

Measured directly via `debug_bsdf_sample_batch` (N=100,000-200,000 samples
per config), counting how often the VNDF-branch `sampleReflection==true` path
survives its own `s.wi.dot(rec.normal) * wo.dot(rec.normal) > 0` (same-
hemisphere) check, for glass (metallic=0, transmission=1, ior=1.5):

| theta | roughness=0.3 | roughness=0.5 |
|-------|---------------|----------------|
| 0     | 0.0%          | 0.0%           |
| 30    | 0.0%          | 0.0%           |
| 45    | 0.0%          | 0.0%           |
| 60    | 0.0%          | 12.76%         |
| 75    | 20.59%        | 64.58%         |

At `glass[0.3-45]` (the exact acceptance-criterion config), **every** VNDF
reflection candidate is rejected — `eval()`'s fix is never exercised for this
config, so the chi² statistic is bit-identical before/after Fix #1:
`143140779.145224` both times (`d.o.f=1025`, `p=0.000000`).

**Mechanism:** the Fresnel roulette `dist(gen) < R/(R+T)` (`R=F(HdotO)`,
`T=1-F`, `R+T=1`) selects reflection roughly proportionally to `F(HdotO)`.
Since `F(HdotO) -> 1` as `HdotO -> 0` (grazing-microfacet Fresnel), the
population that gets selected as "reflection" is disproportionately the
small-`HdotO` (near-orthogonal) tail of the VNDF distribution. But
`reflect(wo,wm) = 2*HdotO*wm - wo -> -wo` as `HdotO -> 0`, and since
`wo.dot(n) > 0` implies `(-wo).dot(n) < 0`, **exactly the half-vectors the
roulette prefers are exactly the ones whose reflection crosses the macro
surface**. This is not a rare grazing-tail edge case at moderate
roughness/incidence — it is the dominant (100%) outcome.

**pbrt-v4's own convention** for this case (`DielectricBxDF::Sample_f`) is to
return **no sample** (`return {}`), not to substitute a delta event — this
package's `sample()` instead falls through to the smooth-mirror delta
(`disney.cpp`'s pre-existing "Extremely grazing sampled microfacets can fail
both reflection and refraction. Fall through to the smooth event instead of
treating that as absorption" comment), reproducing the exact symptom the
xfail describes (100% delta reflection, constant analytic pdf).

**Tried:** matching pbrt-v4 exactly — return a dead (`pdf=0,f=0`) sample
instead of the delta fallback, in both `disney.cpp::sample()` and
`gpu_materials.h::gpu_disney_sample`.

**Measured result — REVERTED, energy-conservation regression:**

| roughness | furnace CPU before | furnace CPU after (dead-sample) | furnace GPU before | furnace GPU after |
|-----------|--------------------|-----------------------------------|---------------------|---------------------|
| 0.1       | ~0.94 (passing)    | **0.0**                           | ~0.96 (passing)     | **0.0**             |
| 0.3       | ~1.00 (passing)    | **0.0**                           | ~1.00 (passing)     | **0.0**             |
| 0.6       | ~1.00 (passing)    | **0.0**                           | ~1.00 (passing)     | **0.0**             |
| 1.0       | ~1.00 (passing)    | 0.0006                            | ~1.00 (passing)     | 0.0018              |

`test_disney_rough_glass_furnace_energy_cpu`/`_gpu` both failed catastrophically.
Chi² itself only improved marginally with this change present (143.1M ->
142.8M — the sameHemi rejection rate for `glass[0.3-45]` specifically stayed
effectively unchanged; most of the "dead" mass shows up elsewhere in the
domain and does not resolve the reflection-lobe peak/shape either).

**Why:** the existing `pdf()`/`microfacetReflectionPdf` do not yet contain a
term compensating for this masking probability (no joint Smith
`G(wo,wi)=1/(1+Lambda(wo)+Lambda(wi))`, no Turquin/Kulla-Conty multiscatter
term on this lobe) — so a large fraction of the analytic-density mass at
"masked" configurations is not actually reachable by `sample()`, and simply
discarding those samples is not an unbiased operation without a compensating
correction. This needs its own dedicated pass (see Non-goals below); reverted
and kept as the pre-existing (if type-inconsistent) energy-conserving
behavior pending that follow-up.

---

## Root cause #3 (measured, explicitly out of pkg138 scope) — rough transmission lobe sample/pdf shape mismatch

Independent of #2 above (which only affects the ~4-8% reflection fraction),
the **transmission** lobe (`roughTransmissionEval`/`roughTransmissionPdf`,
which the spec's Non-goals section explicitly marks "correct and untouched")
has its own substantial sample/pdf mismatch, measured directly:

- `roughTransmissionPdf`, swept over `theta_from_normal` in the exact
  incidence plane (`wo` at 45°, ior=1.5), peaks sharply at **152°**
  (pdf=191.5, dropping below 1.0 outside 143-160°) — this is *exactly* the
  smooth Snell's-law refraction angle
  (`180 - asin(sin(45)/1.5) = 151.87°`), as expected for a correctly-derived
  rough-transmission density.
- The **actual** `sample()`-generated transmission directions (VNDF `wm` +
  `refractThroughMicroNormal`), restricted to the same incidence plane
  (`|z|<0.03`, correct refraction-bend side), peak at **168-170°**
  (N=173,891 live transmission samples in-plane) — a genuine **~16-18°**
  angular discrepancy between where `pdf()` says the energy is and where
  `sample()` actually puts it.
- This lobe carries ~92-96% of this material's total sampled weight at this
  Fresnel (`transmission=1`, low reflectance at moderate incidence), and
  appears to be the dominant chi² contributor — Fix #1 + reverting the
  Root-cause-#2 experiment leaves chi² completely unchanged
  (`143140779.145224`, bit-identical), consistent with the transmission lobe
  dominating the statistic regardless of what happens to the (comparatively
  small) reflection lobe.

This is a **pre-existing** defect, not introduced by pkg138 or by pkg145 —
`roughTransmissionEval`/`roughTransmissionPdf`/`sampleGgxVNDF` were not
touched this session. It appears nobody previously ran a sample-vs-pdf
*positional* check on this lobe (prior investigation, per
`.astroray_plan/docs/vndf-microfacet-dielectric-research.md`, focused on
energy magnitude/furnace values, which this positional bug does not
necessarily show up in if the *total* integrated energy over the lobe happens
to be conserved despite the wrong shape).

**Not investigated further** (explicit spec Non-goal); flagging for a
dedicated follow-up spec.

---

## Net measured effect on the acceptance gate

| | chi² (`glass[0.3-45]`) | furnace (R=0.1/0.3/0.6/1.0, CPU) |
|---|---|---|
| Baseline (pre-pkg138) | 143,140,779 (FAIL) | ~0.94/1.00/1.00/1.00 (PASS) |
| + Fix #1 only (shipped) | 143,140,779 (FAIL, bit-identical) | ~0.94/1.00/1.00/1.00 (PASS, unchanged) |
| + Fix #1 + Root-cause-#2 experiment (reverted) | 142,832,581 (FAIL, ~0.2% better) | 0.0/0.0/0.0/0.0006 (CATASTROPHIC REGRESSION) |

## Recommendation / open question for follow-up

Fix #1 (this PR) is real, cited, tested, and non-regressing — it should ship.
It does **not**, by itself, close `test_chi2_disney_glass[0.3-45]`. Closing
that gate needs BOTH:

1. A masking/multiscatter compensation term for the rough dielectric
   reflection lobe (so the "return dead sample, not delta" pbrt-v4 fix can be
   applied without an energy-conservation regression) — Root cause #2.
2. A re-derivation of the rough transmission lobe's sample/pdf consistency
   (`roughTransmissionEval`/`Pdf` vs. the actual VNDF+refract sampling
   process) — Root cause #3, explicitly out of pkg138's stated scope.

Both are themselves non-trivial, cite-and-borrow-worthy algorithm changes
(candidates: Kulla & Conty 2017 / Turquin 2019 multiscatter compensation for
#2; a fresh pbrt-v4/Mitsuba cross-check of the transmission VNDF sampling
frame for #3) and are being left for a follow-up package rather than folded
into this PR silently.
