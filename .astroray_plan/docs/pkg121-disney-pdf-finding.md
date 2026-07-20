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

---

# pkg123 adjudication — epsilon-contaminated pdf denominators (2026-07-20)

**Status:** RESOLVED (engine fix).
**Root cause:** Spurious epsilon stabilizers in `D_GTR2` and the specular reflection
pdf denominator created angle-dependent density inflation that violated the
sample/pdf consistency invariant chi² tests.

## Evidence trail

### The suspects (from pkg123 spec §Root cause posture)

Four candidate suspects were named in the spec:
1. **Denominator epsilon asymmetry** — `pdf()` divides by `4·HdotV + 0.001f` while
   `sample()` reflects with no matching epsilon.
2. Half-vector density vs reflected-direction density Jacobian application.
3. Lobe-mixture weight leakage at `specular=0`.
4. Roughness→α mapping consistency.

### Adjudication

**Comparison against pbrt-v4 and Walter 2007:**

The canonical GGX reflection pdf (Walter 2007 §5.3, pbrt-v4 §9.6 Eq. 9.24) is:

```
p(wi) = D(wm) · |wm·n| / (4 · |wo·wm|)
```

where the GGX NDF is (Walter 2007 Eq. 33, pbrt-v4 TrowbridgeReitzDistribution):

```
D(wm) = α² / (π · (1 + (α²-1)·cos²θm)²)
```

**Engine code before pkg123:**

```cpp
// disney.cpp line 16 (D_GTR2):
return a2 / (float(M_PI) * t * t + 0.001f);

// disney.cpp line 535 (pdf):
p += (D * NdotH / (4 * HdotV + 0.001f)) * (specWeight / total);
```

**The bug:** Both denominators carried spurious `+0.001f` epsilons. These were
**numerical stabilizers** meant to prevent division by zero, but adding a positive
epsilon to a denominator **deflates** (reduces) the quotient — not "inflates" as an
earlier draft of this note incorrectly claimed — and they violated the mathematical
identity between `sample()` and `pdf()`:

- `t = 1 + (α²-1)·cos²θm` is **not** bounded below by 1. For any roughness < 1.0
  (α < 1), `α²-1 < 0`, so `t` **decreases** from 1 (at NdotH=0) to its minimum `α²`
  (at NdotH=1, the lobe's peak/near-mirror direction). So `t ∈ [α², 1]` — **t ≤ 1**,
  minimized at NdotH=1 — not "t ≥ 1 always" as an earlier draft claimed.
  Consequently `t²` shrinks toward `α⁴` at the peak; for grid-tested roughnesses
  (e.g. α=roughness²=0.16 at roughness=0.4), `π·t²≈0.002` at NdotH≈1 is comparable
  in magnitude to the `0.001` epsilon, so the epsilon **deflates** `D_GTR2` by tens
  of percent exactly at the lobe's peak density — where `pdf()` most needs to be
  accurate.
- The pdf denominator epsilon `4·HdotV + 0.001f` similarly **deflates** the
  reported density whenever `HdotV` is small. Because `HdotV → 0` at grazing
  angles, the fixed `+0.001f` epsilon becomes proportionally larger against the
  shrinking `4·HdotV` term, so the deflation is **angle-dependent** — worse at
  oblique incidence than at normal incidence. This matches the observed pattern
  (diffuse passes at θ=0° but fails at θ=45°; metallic fails more severely at
  oblique incidence) — though the *sign* of the effect is `pdf()`
  **under-reporting** density in the affected region, not over-reporting.

**Why the other suspects were ruled out:**

- Jacobian: The `D * NdotH / (4 * HdotV)` structure matches the reference exactly;
  the epsilon was the contaminant, not a missing factor.
- Lobe weights: Both `sample()` and `pdf()` compute `diffWeight` and `specWeight`
  identically; the diffuse-gate failure came from the epsilon leaking through the
  specular term (which still has nonzero mixture weight even at `specular=0`).
- Roughness mapping: `a = max(roughness² , 0.0064f)` is byte-identical on both sides.

### The fix (pkg123, disney.cpp)

**Removed both epsilons:**

```cpp
// D_GTR2 (now clean, cites Walter 2007 Eq. 33):
float D_GTR2(float NdotH, float a) const {
    float a2 = a * a;
    float t = 1 + (a2 - 1) * NdotH * NdotH;
    return a2 / (float(M_PI) * t * t);  // epsilon removed
}

// Specular reflection pdf (cites Walter 2007 §5.3, pbrt-v4 §9.6 Eq. 9.24):
p += (D * NdotH / (4.0f * HdotV)) * (specWeight / total);  // epsilon removed
```

**Also cleaned `microfacetReflectionPdf`** (line 158, used for transmission):

```cpp
return vndfPdf(rec.normal, wo, wm) / (4.0f * HdotO);  // was + 1e-10f
```

This ensures transmission lobes (tested via SphericalDomain in the glass gate) also
have clean pdf denominators.

**Numerical safety:** The guard `if (NdotH > 0.0f && HdotV > 0.0f)` at line 535
already prevents true division by zero — `D_GTR2` and the pdf term are only
evaluated when both dot products are positive. The epsilons were **redundant** and
actively harmful to statistical correctness.

### Harness extension: full-sphere domain and residual maps

**SphericalDomain for glass/transmission** (pkg123 §C):
- `test_chi2_disney_glass` now uses `SphericalDomain` instead of
  `HemisphericalDomain`, enabling chi² validation of transmission into the lower
  hemisphere.
- The BSDFSamplerAdapter already handled negative-y `wi` correctly (no adapter
  changes needed).

**Per-cell standardized residuals** (pkg123 §A):
- Extended `chi2.py::_dump_tables()` to compute and dump
  `residual[i,j] = (observed - expected) / sqrt(expected)` alongside the existing
  difference map, enabling spatial localization of mismatch (the original residual
  maps were used during investigation but are not archived — the fix was identified
  via code inspection against the reference before needing empirical heatmaps).

### Grid-limited configs documented (pkg123 §D)

Near-delta lobes that an 80×160 grid cannot resolve are now **skipped with
pytest.skip()** and a documented reason, rather than xfailed as "engine defect":

- `metallic >= 0.5` and `α = max(roughness², 0.0064) <= 0.01` triggers
  `pytest.skip("Grid-limited: ... produces near-delta lobe (α=...) that 80×160
  cannot resolve.")`.
- This keeps the gate's pass/fail map honest about what is validated vs what is
  grid-unresolvable.

## Round 2 — coordinator hardware run surfaced two further bugs (2026-07-20)

The coordinator built the Round-1 worktree (CPU epsilon fix only, pre-GPU-fix) and
ran the real chi² suite. Two additional, distinct bugs surfaced that Round 1's
code-inspection-only adjudication could not see without an actual run:

### Round-2 finding 1 — harness domain-check flags dead samples (HARNESS bug)

**Measured:** `test_chi2_disney_metallic` (roughness 0.4/0.8, θ=0°/45°/75°) and
`test_chi2_disney_diffuse` (roughness 1.0, θ=45°) all had **good p-values (0.25 to
0.94)** — the CPU pdf fix from Round 1 works statistically — but pytest still
reported FAILED, because `ChiSquareTest.run()` printed `"Not running the test for
reasons listed above"` and returned `False` regardless of the p-value. The
preceding log line was `"Encountered N samples outside of the specified domain!"`.

**Root cause:** `chi2.py::tabulate_histogram()`'s domain-validity check inspected
**every** sampled direction, including **dead** samples (weight=0; the
pkg121-established failed-sample convention — an NDF-sampled specular reflection
that lands below the horizon still returns the geometrically-computed `wi`, just
with `pdf=0`). For `HemisphericalDomain` (`bounds()` restricts `cos_theta ∈
[0,1]`), a dead sample's `wi` legitimately has `cos_theta < 0` (it's a
lower-hemisphere direction by construction of the convention) — this is **not** a
bug, it's the convention working as designed, but the domain check flagged it
as "outside the domain" and set `self.fail = True` anyway, short-circuiting the
test before the p-value gate could execute. This is a harness bug the pkg121
"validity weights" fix (commit 06ad4c9, histogram binning) didn't fully close —
it fixed weighting the *histogram*, but not this separate *domain-validity* check.

**Fix (`tests/statistical/chi2.py::tabulate_histogram`):** restrict the
domain-validity check to **live** (`weight > 0`) samples only:

```python
live = weights_out > 0
if not np.all(in_domain[live]):
    self._log(f'Encountered {np.sum(~in_domain[live])} live samples outside of the specified domain!')
    self.fail = True
```

Dead samples still get clamped into a bin by the existing `np.clip(...)` and
contribute weight 0 — this change only stops them from tripping the unrelated
`self.fail` short-circuit. A genuine bug that produces a **live** out-of-domain
sample (e.g. a real NaN or a sampler that emits directions outside its stated
domain) is still caught.

### Round-2 finding 2 — glass pdf double-counts the plain-NDF specular term (ENGINE bug)

**Measured:** `test_chi2_disney_glass[0.3-45]` failed hard: `p-value=0.000000`,
and critically `"Failure: PDF integrates to a value greater than 1.0: 1.951..."`
— roughly **2x** over unity.

**Root cause:** In `sample()`, the top-level transmission roulette
(`if (transmission_ > 0 && dist(gen) < transmission_) { ...glass branch...; return
s; }`) means that for `transmission_ = 1.0` (pure glass), `dist(gen) < 1.0` is
**always true** — the plain-NDF specular branch further down (the
`diffWeight`/`specWeight` mixture used by metals, reached only when the
transmission roulette does **not** fire) is **provably unreachable**. But `pdf()`
computed `specWeight`/`diffWeight` **without any transmission-branch gating** —
it unconditionally added the plain-NDF specular pdf term
(`D*NdotH/(4*HdotV) * specWeight/total`) on top of the already-correct VNDF
reflection term (`transmission_ * F * microfacetReflectionPdf(...)`), which is
the term that actually matches `sample()`'s glass-branch reflection sub-case.
Two density models were being summed for the same reflection event —
double-counting, consistent with the measured ~2x integral.

Since `sample()`'s diffuse/specular branch is only entered with probability
`(1 - transmission_)` (the complement of the top-level roulette), `pdf()` must
gate that whole block by the same `(1 - transmission_)` factor. Note `sample()`
never computes its own pdf inline — every branch calls `pdf(rec, wo, s.wi)` — so
`sample()` needed **no change**; fixing `pdf()` alone restores consistency.

**Fix (`disney.cpp::pdf()`, mirrored in `gpu_materials.h::gpu_disney_pdf`):**

```cpp
float mixScale = 1.0f - transmission_;
if (diffWeight > 0) p += (... ) * (diffWeight / total) * mixScale;
if (specWeight > 0) { ... p += (...) * (specWeight / total) * mixScale; }
```

For `transmission_ = 0` (metals, already-passing gates) `mixScale = 1` — no
change, no regression risk. For `transmission_ = 1` (pure glass) `mixScale = 0` —
the plain-NDF specular term is fully and correctly excluded, leaving only the
VNDF reflection term (matches `sample()`) plus `roughTransmissionPdf` (matches
`sample()`'s refraction sub-case, unaffected by this change — it's an early
return at the top of `pdf()`).

**Cite:** general mixture-pdf consistency principle — each additive term in a
multi-lobe `BxDF::PDF` must be weighted by its own branch's actual selection
probability in `Sample_f`, matching pbrt-v4's pattern for mixed
reflection/transmission BxDFs (e.g. `DielectricBxDF::PDF`,
`src/pbrt/bxdfs.h`, Apache-2.0) where the reflection-vs-transmission split
uses the same `pr/(pr+pt)` weights as `Sample_f`'s roulette.

**Status:** fixed in this round; **unverified locally** (no CUDA build on the
implementer's machine) — pending team-lead re-run.

## Citations

- **Walter et al. 2007.** "Microfacet Models for Refraction through Rough Surfaces."
  *EGSR 2007.* (Eq. 33 GGX NDF, §5.3 half-vector Jacobian).
- **pbrt-v4** `src/pbrt/bxdfs.h` `TrowbridgeReitzDistribution`, §9.6 (Apache-2.0,
  Matt Pharr). Reference implementation of clean GGX sample/pdf without stabilizer
  epsilons in the canonical formulas; `DielectricBxDF::PDF` for the
  branch-probability-weighted mixture-pdf pattern used in the Round-2 glass fix.
- **Mitsuba 3** `src/python/python/chi2.py` (BSD-3-Clause, Wenzel Jakob). Harness
  ported in pkg121, extended here to dump per-cell residuals and to correctly
  exclude dead samples from the domain-validity check (Round 2).

## Gate state after pkg123

**Round-1 measured (coordinator hardware run, CPU epsilon fix only, pre-Round-2):**
`test_chi2_disney_metallic` (roughness 0.4/0.8, θ=0°/45°/75°) and
`test_chi2_disney_diffuse` (roughness 1.0, θ=45°) all measured p-values 0.25–0.94
(statistically passing) but were reported FAILED by the harness domain-check bug
(Round-2 finding 1). `test_chi2_disney_glass[0.3-45]` measured p=0.000000 with PDF
integral 1.951 (Round-2 finding 2, genuine engine bug).

**Expected after Round 2 (harness domain-check fix + glass mixScale fix) —
unverified locally, pending team-lead re-run:**
- `test_chi2_disney_metallic` (roughness 0.4, 0.8 across θ=0°/45°/75°)
- `test_chi2_disney_diffuse` (θ=45°, roughness 1.0)
- `test_chi2_disney_glass` (θ=45°, roughness 0.3, SphericalDomain)
- `test_chi2_disney_full_grid` (slow) — 165 configs exercised (45 skipped as
  grid-limited).

The Lambertian anchor is expected to still pass (harness not regressed). No
production regression is *expected* — the pdf fix only affects MIS weights, not
the unbiased estimator itself; furnace tests the latter, chi² tests the former —
but this is **expected, unverified locally**: the team lead must confirm by running
the furnace/white-furnace and CPU↔GPU parity suites alongside the chi² gates.
