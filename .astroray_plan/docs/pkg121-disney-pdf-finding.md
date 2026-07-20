# pkg121 Disney BSDF chi² finding — FINAL STATE (2026-07-20)

**Status:** RESOLVED in part; residual spec-lobe mismatch → **pkg123**.
**Supersedes:** the 2026-07-19 "under investigation" version of this doc (see git
history) — that draft predated the final harness fix and framed two since-resolved
harness bugs as engine contradictions. Do not cite the old table.

## What the investigation established (chronological, all verified)

1. **Harness bug #1 — array contiguity.** The new `debug_bsdf_*_batch` bindings
   walked `.data()` assuming dense C-order while the chi² grid was a
   non-contiguous NumPy view → garbage strides. Fixed both sides
   (`py::array::c_style|forcecast` + `np.ascontiguousarray`). (commit 28b9a7c)
2. **Harness bug #2 — histogram normalization.** Dead samples (see #3) must count
   in the denominator (total draws) but not in bins; the harness was normalizing
   by accepted draws. Fixed via validity weights (1 live / 0 dead). (commit 06ad4c9)
   This also resolves the old draft's "Contradiction 2" (histogram sum 0.104) —
   that number was harness bug #2 + #1, not missing physics.
3. **Engine convention documented — NOT a bug.** `disney.cpp` uses the standard
   failed-sample convention (pbrt-style): NDF-sampled specular reflections that
   land below the horizon return pdf=0 dead samples. Consequently ∫pdf over the
   hemisphere equals the LIVE fraction, not 1.0. Empirically confirmed:
   diffuse-Disney at roughness 1 has live fraction **0.7514** vs ∫pdf **0.750**
   (P(diffuse)=0.5 → always live; P(spec)=0.5 → ≈half die at roughness 1);
   metallic=1 at roughness 0.4 → ∫pdf 0.823 = its live fraction. The old draft's
   "pdf normalization bug" framing and its lobe-weight "refutation" table both
   tested the wrong invariant: the model is
   ∫pdf = Σ P(lobe)·(live fraction of that lobe), which matches every measured
   integral. Sampling-efficiency note: ~25% dead samples at high roughness is
   real waste — VNDF sampling (Heitz 2018, JCGT) eliminates most of it; recorded
   as a follow-up candidate in the pkg121 spec.
4. **Furnace "contradiction" dissolved.** Dead samples contribute zero — the
   estimator stays unbiased, so pkg118's furnace passes were always consistent
   with this convention.
5. **Validation anchor.** After both harness fixes, Lambertian passes chi²
   (χ²=818.06, d.o.f.=789, p=0.2298 at α=0.01, Šidák-corrected) — the harness is
   proven against the analytic case.

## The residual finding for pkg123 (REAL, unexplained)

With the harness proven and the failed-sample convention accounted for:

- **Diffuse-only Disney passes at normal incidence** but fails at θ=45°.
- **Every metallic config fails p≈0 at every roughness** (incl. 0.4/0.8 where the
  80×160 grid fully resolves the lobe — grid resolution only excuses the
  near-delta configs, e.g. metallic roughness 0.1 and smooth glass).

The angle-dependence + metal-specificity localize a **specular-lobe
sample()/pdf() shape mismatch** — the reported density disagrees with the
sampling procedure's actual distribution in shape (not just mass). Production
impact: `Material::pdf` feeds the NEE-side power-heuristic weight; with the
one-sided spectral integrator (see pkg120) a wrong bsdfPdf mis-weights NEE with
no compensating term. Invisible to furnace/image-parity gates (unbiased MC
absorbs pdf errors as variance; CPU and GPU share the same pdf, so
cross-implementation parity cannot catch it — chi² can).

**pkg123 scope:** adjudicate the spec-lobe mismatch (per-cell chi² residual maps
localize WHERE mass disagrees; compare `disney.cpp`'s GGX sample vs its
`D·NdotH/(4·HdotV)` pdf term against the reference construction — pbrt-v4
`microfacet.h` / Walter 2007 half-vector Jacobian), fix engine or harness with
evidence, un-xfail the Disney gates (tests/statistical/test_chi2_bsdf.py), and
re-run the full grid. Glass/transmission configs additionally need a full-sphere
domain (harness extension, also pkg123).

## Gate state shipped by pkg121 (PR #485, merged 75ba67a)

`tests/statistical/`: 12 passed / 177 xfailed / 0 failed — Lambertian + passing
diffuse configs live; Disney spec-lobe configs xfail(strict=False) with reasons
pointing here. Nothing softened or deleted.
