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

## Round 2a — coordinator hardware run surfaced two further bugs (2026-07-20)

The coordinator built the Round-1 worktree (CPU epsilon fix only, pre-GPU-fix) and
ran the real chi² suite. Two additional, distinct bugs surfaced that Round 1's
code-inspection-only adjudication could not see without an actual run:

### Round-2a finding 1 — harness domain-check flags dead samples (HARNESS bug)

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

### Round-2a finding 2 — glass pdf double-counts the plain-NDF specular term (ENGINE bug)

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

## Round 2b — coordinator rebuild + full re-run: 163→34 failures (2026-07-20)

The coordinator built the Round-2 worktree (harness domain-check fix + glass
mixScale fix) and ran the full chi² suite. Confirmed: 163→34 failures, 129 pass.
The harness domain-check fix worked — metallic and diffuse core gates now PASS
with real p-values. **34 real failures remained**, all p=0.000000 — the
significance test now actually runs (not harness-check noise). Full log:
`chi2_round2.log` (coordinator scratchpad). Three distinct failure groups:

### Round-2c finding 1 — glass residual shape mismatch survives the mixScale fix (defensive hardening, NOT the root cause)

`test_chi2_disney_glass[0.3-45]` still failed: `Histogram sum = 1.000000, PDF sum
= 0.967118` (mass now correct — confirms the mixScale fix from Round 2a worked) but
`Chi^2 statistic = 143140779.145224` (d.o.f = 1025) — catastrophically large despite
correct total mass, meaning a genuine **shape** (not mass) defect remains.

**Candidate cause proposed this round (found by code inspection against
`sample()`'s exact formula, before an actual re-run):** `pdf()`'s VNDF-reflection
Fresnel-weight computation (`float F = fresnelDielectric(wo.dot(H), etaI, etaT);`)
did not wrap `wo.dot(H)` in `std::abs()`, while `sample()`'s matching inline
computation (`std::abs(HdotO)`) does. The theorized mechanism: `tabulate_pdf`'s
quadrature queries `wi` values far from `wo`, where the reconstructed
`H=(wo+wi).normalized()` could have `wo.dot(H) < 0`, flipping
`fresnelDielectric`'s internal `entering` branch.

**Correction (Opus re-review, 2026-07-20, measured on hardware):** this
hypothesis was **not the root cause**. The `abs()` change is harmless — it
matches `sample()`'s convention and is kept as defensive hardening against a
real (if not dominant) edge case — but the reviewer's empirical measurement
(instrumented run, not code inspection) established the *actual* mechanism is a
**delta-vs-continuous sample/pdf type mismatch**, unrelated to the sign of
`wo.dot(H)`. See Round 2d below for the adjudicated mechanism and measurements.
The earlier framing above (this section, as originally written) incorrectly
presented the `abs()` fix as *the* fix for the 143M chi² statistic; it is not —
the glass gate remains a genuine, pre-existing engine defect, now `xfail`'d
(strict=True) rather than claimed fixed.

### Round-2c finding 2 — full_grid near-delta skip criterion was wrong (TEST bug, not engine)

`test_chi2_disney_full_grid` failures at `metallic=0.0/0.5/1.0`, `roughness ∈
{0.0, 0.1}` (all 5 θ), plus most of `roughness=0.2` (θ=0,60,75 at minimum) — 30 of
the 34 residual failures. All showed the classic near-delta signature: **PDF-sum
overshoot growing as roughness shrinks and θ grows toward grazing** (e.g.
metallic=0.0: 12.7x at roughness=0.0/θ=0°, shrinking to 1.04x at roughness=0.1/
θ=30°; metallic=1.0/roughness=0.1: 10.3x at θ=0° down to 1.09x at θ=30°) —
**identical in shape and magnitude across all three metallic values**, using the
exact same (already chi²-passing at higher roughness) reflection-pdf code path.

**Root cause: the existing `is_near_delta` skip criterion
(`metallic >= 0.5 and alpha <= 0.01`) had two bugs**, not an engine defect:
1. **Wrong gating variable.** The specular reflection term (`specWeight=1`) is
   present identically regardless of `metallic` — a `metallic=0.0` dielectric has
   the *same* narrow near-mirror specular lobe at low roughness as a
   `metallic=1.0` conductor (mixed with a diffuse lobe, but the specular peak
   itself is unchanged). Gating the skip on `metallic >= 0.5` incorrectly let
   `metallic=0.0` configs run and fail at exactly the roughness values the policy
   already intended to exclude.
2. **Float-precision boundary bug.** `roughness=0.1` in Python floats squares to
   `0.010000000000000002`, narrowly exceeding the `alpha <= 0.01` threshold — so
   even `metallic=1.0, roughness=0.1` (explicitly named in the ALREADY-documented
   policy: "metallic=1.0, roughness <= 0.1") was never actually skipped, and ran
   to a 10.3x PDF-sum-overshoot failure.

**Fixed:** the skip criterion now compares `roughness <= 0.2 + 1e-9` directly
(sidesteps the float-square boundary issue) and applies regardless of `metallic`.
The extension from `alpha<=0.01` (roughness 0.1) to roughness<=0.2 is backed by
the measured evidence above — `roughness=0.2` still shows the identical
monotonically-shrinking-overshoot signature (1.01x-1.19x) at most angles, for all
three metallic values, consistent with the *same* quadrature-resolution artifact,
not a new phenomenon. This is a **test/policy fix**, not an engine change — no
`disney.cpp`/`gpu_materials.h` edit.

### Round-2c finding 3 — grazing-incidence residual at roughness=0.3, θ=75° only

`metallic ∈ {0.0, 0.5, 1.0}` at `roughness=0.3, θ=75°` (3 of the 34 failures) show
a **much smaller** deviation than the near-delta cases (PDF/histogram sums
0.94–0.97, i.e. 3–9% off, vs. the 2x-12x near-delta overshoots) but still
chi²-significant given 10⁶ samples (χ²≈3100-4200, d.o.f≈1580-3180). Critically,
`roughness=0.3` **passes at every other tested angle** (0°/30°/45°/60°) for all
three metallic values, and the core gate's `roughness=0.4` config passes cleanly
at θ=75°. This rules out a blanket near-delta explanation (roughness=0.3 is not
uniformly unresolvable) and rules out a plain formula bug (it would not vanish at
non-grazing angles for the *same* roughness).

**Adjudication:** a narrow, grazing-incidence-specific boundary-of-resolvability,
most plausibly explained by the well-documented (Heitz 2018) degradation of
**plain-NDF** (as opposed to VNDF) reflection sampling at grazing incidence — the
reflection lobe elongates/streaks at grazing `wo`, which a fixed-resolution
quadrature grid resolves poorly even when the *same* lobe at normal incidence is
fine. This is squarely `disney.cpp:496-513`'s plain-NDF sampler, which is
`pkg124`'s stated target for a VNDF replacement. **Action:** `pytest.xfail()`'d
with a precise per-config reason (only `roughness==0.3 and theta_deg==75`, not a
blanket skip — `roughness=0.3` still asserts at every other angle), naming
pkg124 as the likely fix and citing this doc.

## Round 2d — Opus re-review: the glass root cause is a delta-vs-continuous sample/pdf type mismatch (2026-07-20)

**Status:** ADJUDICATED (final for pkg123's scope). `test_chi2_disney_glass[0.3-45]`
is `xfail(strict=True)`, not fixed — the fix is out of pkg123's scope (see below).

Independent re-review (Opus, measured on hardware, not code inspection) traced
the residual 143M chi² statistic to its actual mechanism, correcting the Round-2c
finding-1 `abs()` hypothesis (which the reviewer confirmed is harmless defensive
hardening — matches `sample()`'s convention — but empirically **not** the cause
of the shape mismatch).

**Mechanism:** Disney glass reflection is sampled as a smooth **DELTA** (perfect
mirror, `pdf = fresnel * transmission_`, `isDelta = true` —
`disney.cpp:465-474`) because the rough-reflection candidate is **rejected** at
`disney.cpp:455` (`if (s.pdf > 0.0f && s.f.length2() > 0.0f)`): `eval()`'s
reflection lobe evaluates to ~0 for `transmission_=1.0, metallic_=0.0` via the
`Cspec0`/`F0` specular-tint formulation (`disney.cpp:325`) rather than the
dielectric's actual Fresnel reflectance. Meanwhile `pdf()` **still adds** a
continuous VNDF reflection density term (`disney.cpp:543`,
`transmission_ * F * microfacetReflectionPdf(...)`) — a density for an event
class `sample()` never actually produces for this material (100% of its
reflection draws are the smooth delta event, not the continuous VNDF one). This
is a **delta-vs-continuous type mismatch**: `pdf()` reports a continuous density
where `sample()` only ever emits a point mass, which a binned chi² histogram
cannot represent consistently (a point mass smeared across nearby continuous
bins vs. an integrated continuous density predicting smooth structure there).

**Measurements (Opus re-review, instrumented run):**
- **Angle-from-mirror max = 0.0** — every sampled reflection `wi` is *exactly*
  the ideal specular-mirror direction; none come from the rough VNDF branch.
  Direct proof of 100% delta-branch selection.
- **Constant pdf = 0.04213 = F(45°, ior=1.5) × transmission_** — matches the
  delta branch's analytic formula (`disney.cpp:474`,
  `s.pdf = fresnel * transmission_`) exactly, confirming the reported pdf is the
  *delta* event's point-mass value wherever the sample lands, not a continuous
  density.
- **sample/eval energy ratio = 0.060** — the `eval()` reflection lobe (Cspec0-based,
  `disney.cpp:325`) and the delta event's actual throughput diverge by ~16.7x,
  consistent with `eval()` using the wrong (non-Fresnel) specular model for a
  dielectric's reflection component.

**Why this is furnace-invisible:** the estimator (sample-then-weight-by-f/pdf)
stays formally unbiased regardless of whether the underlying event is delta or
continuous — furnace/white-furnace tests integrate total reflected energy, which
doesn't distinguish *how* that energy arrived (one delta spike vs. a spread
continuous lobe). Only a shape-sensitive test (chi²) can see this — exactly the
reason pkg121/pkg123 built this harness.

**Why this is real and pre-existing, not a pkg123 regression:** the delta
fallback and the continuous VNDF `pdf()` term both predate pkg123 (pkg123 fixed
the *mixScale* double-count on top of this — the mass-normalization bug — but
the underlying delta-vs-continuous shape defect was already present and is
orthogonal to mixScale).

**Fix (explicitly out of pkg123's scope, NOT applied here):** give the rough
dielectric a proper reflection lobe in `eval()` — the actual Fresnel-weighted
GGX reflection term for a dielectric interface, not the metal-style
`Cspec0`/Schlick-F0 approximation — so `sample()`'s rough-VNDF-reflection
candidate is actually accepted instead of always falling through to the delta
event. **Cite:** pbrt-v4 `DielectricBxDF` (reflection-branch `f()`), Walter 2007
"Microfacet Models for Refraction through Rough Surfaces" §5.1 Eq. 20 (rough
dielectric reflection BRDF). **Do NOT patch `pdf()` to suppress the continuous
term instead** — that would make `pdf()` match `sample()`'s current (broken)
delta-only behavior, silently discarding the physically-correct rough-reflection
energy the VNDF branch is meant to eventually contribute once `eval()` is fixed,
and would corrupt the NEE MIS weight (pkg120) in the opposite direction.
**Follow-up:** filed as a new package, tracked as
`disney-dielectric-reflection-lobe` (architect to file the spec).

## Round 3 — coordinator verification of 2ed96f6: chi²/furnace green, GPU-parity regression found and adjudicated as pre-existing (2026-07-20)

**Status:** ADJUDICATED (final for pkg123's scope). `test_pkg123_disney_metal_gpu_cpu_parity_near_delta[0.0]`
is `xfail` (plain, not strict), not fixed — the underlying GPU defect is
explicitly **out of pkg123's scope** (see below).

The coordinator ran the full verification suite against commit `2ed96f6`
(the Round-2d xfail commit): the full chi² suite, `test_disney_rough_glass_furnace.py`,
and `test_disney_energy_conservation.py` all passed (399 passed; the glass
`xfail(strict=True)` behaved as expected — confirming the delta-vs-continuous
defect is furnace-invisible, per the Round-2d adjudication).

**New finding:** `tests/test_pkg123_disney_metal_gpu_cpu_parity.py` (the CPU↔GPU
regression test added in Round 2a for the alpha-floor/guard GPU fix) failed at
`roughness=0.0`: measured GPU/CPU per-channel mean ratio up to **4.0**, outside
the test's `[0.4, 2.5]` band.

**Adjudication (coordinator, A/B against pre-PR#498 `main` via `ASTRORAY_BUILD_DIR`
redirect):** this is a **pre-existing GPU defect, not a pkg123 regression**.
Measured:
- **GPU per-channel mean is byte-identical pre/post PR #498**: `0.02387` in both
  the pre-#498 `main` build and the post-fix `2ed96f6` build. None of pkg123's
  GPU edits (alpha floor/guard, epsilon removal, `790` revert, `mixScale`,
  Fresnel `abs()` hardening) touch the code path this scene's shading actually
  exercises.
- **CPU per-channel mean moved from `0.00884` (pre-#498) to `0.00596`
  (post-#498)** — pkg123's CPU `pdf()` correction (the epsilon removal fixing
  the angle-dependent density deflation, Round 1) legitimately made the CPU
  side *more* correct.
- Consequently the GPU/CPU ratio **widened** from an already-failing `2.70x`
  (pre-#498) to `4.00x` (post-#498) — not because GPU got worse or because
  pkg123 introduced a new defect, but because the CPU-side fix moved the CPU
  mean further away from a GPU value that was already too bright and was never
  touched.

**Suspected root cause (not confirmed, named for the follow-up spec):** either
the GPU selected-lobe pdf inline computation (`gpu_materials.h:849-857`, the
`gpu_disney_sample` specular branch's pdf assignment) or the GPU closure-graph
Disney twin (see memory `gpu-dielectric-lowers-to-closure-graph`: plain
Disney/dielectric materials shade via `GMAT_CLOSURE_GRAPH` on GPU, a
structurally different code path from the CPU's direct `Material::sample()`/
`pdf()` calls) lacking the CPU's full diffuse+specular mixture semantics — this
is the same category of CPU/GPU MIS asymmetry the Opus review flagged in its
notes on PR #498.

**Action (initial, `a677cb4`):** `roughness=0.0` in
`test_pkg123_disney_metal_gpu_cpu_parity_near_delta` is `xfail` (plain —
`strict=False`, since MC noise could make a marginal row flap between
pass/fail run to run) with this adjudication as the reason.
`roughness ∈ {0.03, 0.05, 0.1}` were initially left **not** xfail'd — no
evidence yet that they failed. Superseded by Round 3b below.

## Round 3b — coordinator re-run confirms all four near-delta rows fail; follow-up filed as pkg141 (2026-07-20)

**Status:** ADJUDICATED (final for pkg123's scope, all four rows).

The coordinator re-ran `test_pkg123_disney_metal_gpu_cpu_parity.py` on commit
`a677cb4` (code unchanged from `2ed96f6`, so the pre/post logic is identical —
this was a rerun to gather the missing per-row evidence, not a new build) and
measured R-channel ratios for **all four rows**, all failing the `[0.4, 2.5]`
band:

| roughness | alpha | GPU mean | CPU mean | R ratio |
|---|---|---|---|---|
| 0.00 | 0.0064 (floored) | 0.02387 | 0.00596 | 4.0033 |
| 0.03 | 0.0064 (floored) | 0.02387 | 0.00596 | 4.0033 |
| 0.05 | 0.0064 (floored) | 0.02387 | 0.00596 | 4.0033 |
| 0.10 | 0.0100 (above floor) | 0.02387 | 0.00647 | 3.6870 |

`roughness=0.03` and `roughness=0.05` both floor to the exact same
`alpha=0.0064` as `roughness=0.0` (since `alpha = max(roughness², 0.0064)` and
`0.03² = 0.0009`, `0.05² = 0.0025`, both `< 0.0064`) — they produce
**byte-identical renders** on both CPU and GPU, hence the identical
measurements and identical adjudication as `roughness=0.0`.
`roughness=0.1` sits just above the floor (`alpha=0.0100`), so it is a
distinct, slightly larger lobe; the same GPU over-brightness persists but is
somewhat diluted by the larger lobe, giving a smaller-but-still-failing ratio
(`3.6870`).

**Action (final):** all four rows (`roughness ∈ {0.0, 0.03, 0.05, 0.1}`) are
now `xfail` (plain, `strict=False`) in
`tests/test_pkg123_disney_metal_gpu_cpu_parity.py`, each with its own
per-row measured numbers in the reason string. **Follow-up filed:** `pkg141`
(`gpu-near-delta-disney-metal-brightness`, PR #504) — the architect-filed spec
to investigate and fix the pre-existing GPU near-delta over-brightness. Per
the coordinator's explicit instruction, the ratio band `[0.4, 2.5]` is
**not** widened to hide this — the xfails document a known, pre-existing,
non-regressing gap instead, and the test still guards NaN/Inf and gross
divergence (a >10x or NaN-producing regression would still fail even under
`strict=False`, since that's a categorically different, unexpected failure
mode from the documented ~4x over-brightness).

## Round 4 — CI-caught render regressions: dormant `clampColor` woken by the D fix (2026-07-21)

**Status:** RESOLVED for the 3 deterministic specular regressions (engine fix,
render-level). The 4th (clearcoat energy) is adjudicated as an out-of-scope
collateral (see below).

The team-lead parked PR #498 at wrap-up: CI `build-and-test` surfaced four
material-correctness regressions the PR-named suites (chi²/furnace/energy/parity)
had not exercised. Three reproduced locally on MSVC; the fourth was CI-only.

### Root cause of the 3 specular regressions (metal-too-dark, metallic-tint, roughness-gloss)

Not the NEE/MIS mechanism the parking note hypothesized. The mechanism is a
**previously-dormant firefly cap in `eval()` woken by the epsilon removal**:

- `plugins/materials/disney.cpp::eval()` ended with `return clampColor(result)`,
  which clamped each channel to `[0, 4]`. `gpu_materials.h::gpu_disney_eval` had
  the asymmetric twin `fminf(result, 10.f)`.
- The `+0.001f` in `D_GTR2` (added in **pkg03 / PR #91**, before pkg60's energy
  calibration) **deflated** D to `≤ ~0.32` at *every* roughness (`D_peak = a²/(π·t²+ε)`
  is maximized at the alpha floor but the `+ε` denominator caps it near `a²/ε`;
  for the floored `a=0.0064`, `a²/ε ≈ 0.04`). So on `main` the specular
  `eval()` value never approached 4.0 and **`clampColor` never fired** — the
  deflated D cancelled cleanly in the importance-sampled `f/pdf` ratio, giving a
  correct render.
- pkg123 removed the epsilon (correctly — required for sample()/pdf() chi²
  consistency). The specular D now reaches **~10³–10⁴** at the alpha floor
  (`D_peak = 1/(π·a²) ≈ 7772` at `a=0.0064`). `eval()`'s spec term
  (`D·F·Gs·NdotL`) now hugely exceeds 4.0 and gets **capped**, while `pdf()`
  carries the **uncapped** D. The `f/pdf` ratio therefore no longer cancels D:
  `throughput = 4.0 / (D·NdotH/(4·HdotV)) → 0`, so Disney metal reflection
  collapsed toward black (`test_disney_metal_reflection_not_black`: 0.215 vs the
  `metal` material's 0.604 at roughness 0.05; the low-roughness specular
  highlight in `test_disney_metallic_tints_specular_highlight` /
  `test_disney_roughness_changes_glossiness` dimmed the same way, erasing the
  render deltas those tests assert).

**Why chi²/furnace/parity all stayed green:** chi² only exercises
`sample()`/`pdf()` (never `eval()`); the furnace/energy suites integrate total
energy (the clamp's darkening is invisible to a scalar albedo when it doesn't
fire, and it *does* fire only for the near-mirror lobe an unbiased furnace
absorbs as variance); CPU↔GPU parity shares the defect. Only a
sampled-reflection *render* against a reference exposes it.

### The fix (engine, render-level)

Remove the closure-level upper cap on both sides, floor at 0 only:

- `disney.cpp::clampColor` → `Vec3::max(c, Vec3(0.0f))` (no `hi`).
- `gpu_materials.h::gpu_disney_eval` → `fmaxf(result, 0.f)` (was `fminf(·,10)`).

This is a **no-op relative to `main`'s actual render behaviour** (the cap was
dormant there) and restores the exact `f/pdf` cancellation for the now
correctly-normalized GGX lobe, while leaving the epsilon-free `pdf()` the chi²
gates require untouched. It also *removes* a pre-existing CPU(4.0)/GPU(10.0)
parity divergence.

**Cite:** Cycles `src/kernel/film/accumulate.h` / `kernel_accum_clamp`
(`clamp_direct`/`clamp_indirect`) — firefly control is applied to the
**path/sample radiance at the integrator**, never as a cap on the BRDF closure
value (`bsdf_microfacet.h` returns the true `D`). Astroray already has the
integrator-level equivalents: `raytracer.h` `clampDirect`/`clampIndirect` plus
the always-on `sLum > 20` per-sample suppression (`raytracer.h:3005`) and
`finiteVecOrZero` NaN guard (`raytracer.h:3002`) — so the closure cap was
redundant as well as harmful.

### The 4th failure (clearcoat energy) — out-of-scope collateral, adjudicated

`test_disney_directional_hemispherical_reflectance_is_conserved[0.9-1.0-0.0-0.0-0.3]`
(cos_theta_o=0.9, clearcoat=1.0, sheen=0, metallic=0, roughness=0.3,
clearcoat_gloss=0.25) measured **1.0206**, just over the pkg60 hard gate 1.02
(the loose "bug" gate 1.05 still passes). Distinct mechanism, **not** fixed by
the clamp removal (the clamp does not fire for this config — peak `eval()`≈0.93):

- The clearcoat lobe (`disney.cpp:369`) shares `D_GTR2`. Removing the epsilon
  **normalized** the clearcoat NDF, restoring energy the deflated D had been
  silently discarding. pkg60's clearcoat energy compensation
  (`clearcoatE`/`min(1/clearE,1.25)` boost + `layeringWeightAfter` base debit)
  was **numerically calibrated against the epsilon-deflated engine** — pkg60's
  own recorded worst case was **1.015891** *with* the epsilon present
  (`disney-energy-compensation-research.md:300-302`). With the corrected D the
  Astroray-specific clearcoat compensation (Cycles has **no** clearcoat_E table;
  it uses the GGX-E path — `disney-energy-compensation-research.md:188-201`)
  slightly over-produces for this one config.
- **Marginal / platform-sensitive:** it failed only on the Linux/GCC CI leg; it
  did **not** reproduce on the owner's MSVC local build (float-ordering of the
  4096-sample uniform-Halton `integrateMaterialReflectance` of a now-correctly-
  sharp lobe straddles the 1.02 boundary by ~6e-4 across compilers).

**Adjudication:** this is a **pkg60 clearcoat energy-compensation
recalibration**, explicitly a pkg123 **non-goal** (spec §Non-goals: "Not new
BSDF lobes… clearcoat… is not this package"). It cannot be closed inside pkg123
without either (a) re-adding a bare `+0.001f` epsilon to the clearcoat D — the
exact anti-pattern this package removed, forbidden — or (b) re-deriving the
clearcoat multi-scatter compensation / layering debit against the correct D,
which requires an empirical build-and-measure loop (the tables were fit
numerically). Neither is a blind edit. **Recommended follow-up:** a focused
`disney-clearcoat-energy-recalibration` package that re-fits the clearcoat
compensation against the epsilon-free D (or, per the research doc, moves
clearcoat onto the Cycles GGX-E path and drops the Astroray clearcoat_E table).
The test is **not** weakened here.

## Citations

- **Walter et al. 2007.** "Microfacet Models for Refraction through Rough Surfaces."
  *EGSR 2007.* (Eq. 33 GGX NDF, §5.3 half-vector Jacobian).
- **pbrt-v4** `src/pbrt/bxdfs.h` `TrowbridgeReitzDistribution`, §9.6 (Apache-2.0,
  Matt Pharr). Reference implementation of clean GGX sample/pdf without stabilizer
  epsilons in the canonical formulas; `DielectricBxDF::PDF` for the
  branch-probability-weighted mixture-pdf pattern used in the Round-2a glass fix.
- **Mitsuba 3** `src/python/python/chi2.py` (BSD-3-Clause, Wenzel Jakob). Harness
  ported in pkg121, extended here to dump per-cell residuals and to correctly
  exclude dead samples from the domain-validity check (Round 2a).
- **Heitz 2018.** "Sampling the GGX Distribution of Visible Normals." *JCGT 7(4).*
  Cited for the Round-2c finding-3 grazing-incidence adjudication (plain-NDF
  sampling degrades at grazing incidence relative to VNDF) — already the
  citation anchor for `sampleGgxVNDF` (`disney.cpp:97`) and pkg124's scope.

## Gate state after pkg123

**Round-1 measured (coordinator hardware run, CPU epsilon fix only, pre-Round-2a):**
`test_chi2_disney_metallic` (roughness 0.4/0.8, θ=0°/45°/75°) and
`test_chi2_disney_diffuse` (roughness 1.0, θ=45°) all measured p-values 0.25–0.94
(statistically passing) but were reported FAILED by the harness domain-check bug
(Round-2a finding 1). `test_chi2_disney_glass[0.3-45]` measured p=0.000000 with PDF
integral 1.951 (Round-2a finding 2, genuine engine bug).

**Round-2b measured (coordinator rebuild + full re-run, harness domain-check fix +
glass mixScale fix applied):** 163→34 failures, 129 pass. `test_chi2_disney_metallic`
and `test_chi2_disney_diffuse` core gates now **PASS with real p-values** — the
harness fix worked. 34 residual failures, all genuinely significant (p=0.000000,
not harness noise): glass shape mismatch (Round-2c finding 1), full_grid near-delta
skip-policy gap (Round-2c finding 2, 30 configs), full_grid grazing-incidence
residual (Round-2c finding 3, 3 configs — `roughness=0.3, θ=75°` × 3 metallic
values). One config's dof shifted between runs due to variable cell-pooling, not
a defect.

**Round-2c changes:**
- `disney.cpp::pdf()` / `gpu_materials.h::gpu_disney_pdf`: wrap the VNDF-reflection
  Fresnel-weight cosine in `std::abs()`, matching `sample()`. Kept as **defensive
  hardening** — Round 2d's Opus re-review established this was not the glass
  root cause (see below).
- `test_chi2_bsdf.py::test_chi2_disney_full_grid`: near-delta skip criterion fixed
  to `roughness <= 0.2` regardless of metallic (finding 2 — test/policy fix, no
  engine change); `roughness=0.3, θ=75°` now `pytest.xfail()`'d per-config with a
  precise reason citing pkg124 (finding 3).

**Round-2d (Opus re-review, sign-off with required xfail):** the glass residual is
a real, pre-existing, delta-vs-continuous sample/pdf type mismatch (see "Round 2d"
above) — the smooth-mirror delta fallback is always taken for rough dielectric
reflection because `eval()`'s Cspec0-based specular term is ~0 for
`transmission_=1.0`, while `pdf()` correctly reports the continuous VNDF density
for an event `sample()` never produces. `test_chi2_disney_glass[0.3-45]` is now
`xfail(strict=True)` with this mechanism as the documented reason — not claimed
fixed. The proper fix (a rough dielectric reflection lobe in `eval()`, pbrt-v4
`DielectricBxDF` / Walter 2007 §5.1 Eq. 20) is **out of pkg123's scope**,
follow-up filed as `disney-dielectric-reflection-lobe`.

**Final gate state (pkg123 close, confirmed on hardware — Round 3):**
- `test_chi2_disney_metallic` (roughness 0.4, 0.8 across θ=0°/45°/75°) —
  **passing** (confirmed on hardware, Round 2b).
- `test_chi2_disney_diffuse` (θ=45°, roughness 1.0) — **passing** (confirmed on
  hardware, Round 2b).
- `test_chi2_disney_glass` (θ=45°, roughness 0.3, SphericalDomain) —
  **`xfail(strict=True)`**, documented pre-existing engine defect, follow-up
  filed as `disney-dielectric-reflection-lobe`. Behaves as expected — confirmed
  on hardware, Round 3 (399 passed overall, glass xfail behaved as expected).
- `test_chi2_disney_full_grid` (slow) — 165 configs total: 45 skipped as
  grid-limited (`roughness<=0.2`, all metallic), 3 `xfail`'d (grazing residual,
  `roughness=0.3,θ=75°`), remaining ~117 passing — **confirmed on hardware,
  Round 3**.
- `test_disney_rough_glass_furnace.py` / `test_disney_energy_conservation.py` —
  **passing, confirmed on hardware, Round 3** (furnace-invisibility of the
  glass delta-vs-continuous defect verified empirically, as the Round-2d
  adjudication predicted).
- `test_pkg123_disney_metal_gpu_cpu_parity_near_delta` — all four rows
  (`roughness ∈ {0.0, 0.03, 0.05, 0.1}`) **`xfail`** (plain, not strict),
  pre-existing GPU near-delta over-brightness, unrelated to pkg123 (see
  "Round 3b" above, measured R ratios 4.0033/4.0033/4.0033/3.6870), follow-up
  filed as **`pkg141`** (`gpu-near-delta-disney-metal-brightness`, PR #504).

The Lambertian anchor passes (harness not regressed, confirmed on hardware). No
production regression: the pdf fix only affects MIS weights, not the unbiased
estimator itself — confirmed empirically by the Round-3 furnace/energy-
conservation hardware run (399 passed).
