# pkg123 — Disney specular-lobe sample()/pdf() chi² adjudication (un-xfail the merged gates)

**Pillar:** 3 (correctness / statistical BSDF validation)
**Track:** A (CPU-only chi² harness + CPU BSDF path; runs on CI, no GPU)
**Codex-paste-ready:** no (an open statistical adjudication — the residual root cause is *not yet known*; needs per-cell evidence and an engine-vs-harness judgement call, not a mechanical patch)
**Status:** open — **highest priority**; the xfail gates that reference this package are already merged (pkg121 PR #485)
**Estimated effort:** M (1–2 sessions — residual localization via per-cell chi² maps, one engine-or-harness fix with evidence, harness full-sphere extension, un-xfail + full-grid re-run)
**Depends on:** **pkg121 (landed, PR #485, merged 75ba67a)** — the chi² harness, the `debug_bsdf_sample_batch`/`debug_bsdf_pdf_batch` bindings, and the xfail(strict=False) Disney gates all exist and point here. No other package blocks this. **Related (not blocking):** **pkg120** — the one-sided spectral integrator is *why* a wrong `Material::pdf` has production impact (see Context); **pkg124** builds on this package's adjudication (its VNDF change must not reopen the mismatch).

---

## Context — why a chi²-only defect still matters for the journal

`tests/statistical/test_chi2_bsdf.py` currently ships three Disney gates as
`xfail(strict=False)` (metallic, oblique-diffuse, glass) plus the slow full grid.
They are **not** cosmetic: the pkg121 investigation proved the harness is correct
(Lambertian anchor passes χ²=818.06, d.o.f.=789, p=0.2298) and that the residual
Disney failures localize to a **specular-lobe sample()/pdf() shape mismatch** —
`Material::pdf` reports a density that disagrees with what `Material::sample`
actually draws. This is invisible to every other gate we have:

- **Furnace / white-furnace gates** stay green because unbiased Monte Carlo
  absorbs a wrong pdf as *variance*, not *bias* (dead samples contribute zero).
- **CPU↔GPU parity gates** stay green because CPU and GPU share the same pdf, so a
  common error cancels in the difference.
- Only a **goodness-of-fit test** (chi²) can see it, which is exactly why pkg121
  built the harness.

Production impact (this is the journal-relevant part): `Material::pdf` feeds the
NEE-side power-heuristic weight `wt = lightPdf²/(lightPdf²+bsdfPdf²)`. With the
**one-sided** spectral integrator (pkg120: the diffuse BSDF-ray-hits-emitter term
is dropped, so there is no compensating BSDF-side leg), a wrong `bsdfPdf`
**mis-weights NEE with nothing to cancel it** — a real, uncorrected error in
direct lighting, not just extra noise. Closing pkg123 makes the Disney BSDF a
statistically-validated closure the journal-article correctness section can cite,
and hardens the pdf that pkg120's MIS math depends on.

---

## Goal

**Before:** The Disney specular reflection lobe samples the **standard GGX NDF**
(`disney.cpp:496-513`: half-vector `h` from `cosθ = √((1−r₂)/(1+(a²−1)r₂))`, then
`wi = 2(wo·h)h − wo`) and reports density `D·NdotH/(4·HdotV)`
(`disney.cpp:529-536`). The `sample()` and `pdf()` were **already reconciled once**
during pkg121 — the code comment at `disney.cpp:496-500` records that a prior
VNDF-sample-against-NDF-pdf mismatch was reverted because it "darkened disney
metal/specular reflection." Despite that reconciliation, chi² still fails:

- **Diffuse-only Disney** (`specular=0`, roughness 1) **passes at normal incidence**
  but **fails at θ=45°** (`test_chi2_disney_diffuse`, xfail).
- **Every metallic config fails p≈0 at every roughness**, including 0.4/0.8 where
  the 80×160 grid fully resolves the lobe (so it is *not* a grid-resolution
  artifact), with a clear **angle dependence** (`test_chi2_disney_metallic`, xfail).
- **Glass/transmission** cannot even be tested correctly today — the gate uses a
  `HemisphericalDomain` for a lobe that emits into the lower hemisphere
  (`test_chi2_disney_glass:261-263`, xfail).

**After:** The residual specular-lobe shape mismatch is **adjudicated with per-cell
chi² residual evidence**, the responsible side (engine `sample()`/`pdf()` **or**
harness) is fixed with a documented reason, the chi² harness gains a **full-sphere
domain** so transmission lobes are testable, the **near-delta roughness floor** is
documented so grid-unresolvable configs are excused explicitly rather than
silently, and the merged Disney gates are **un-xfailed** and pass across the full
grid (or any genuine engine↔reference divergence is owner-adjudicated and recorded,
not suppressed).

---

## Root cause posture (what is known vs. what pkg123 must establish)

**Known (pkg121, all verified — see `.astroray_plan/docs/pkg121-disney-pdf-finding.md`):**

1. The harness is proven correct against the analytic Lambertian case.
2. The failed-sample convention is understood and is *not* a bug: NDF-sampled
   reflections below the horizon return pdf=0 dead samples, so `∫pdf` over the
   hemisphere equals the **live fraction**, not 1.0; the harness now counts dead
   samples in the denominator but not the bins (validity weights).
3. The obvious `sample`/`pdf` mismatch (VNDF-sample vs NDF-pdf) was already found
   and reverted; the current reflection lobe is a matched NDF-sample + NDF-pdf pair.

**Unknown (pkg123 must establish with evidence):** *why a matched NDF-sample /
NDF-pdf pair still fails chi² for metals at all roughness with angle dependence,
and for diffuse only at oblique incidence.* Candidate suspects to test with the
per-cell residual maps — **name them, do not assume one**:

- The **denominator epsilon asymmetry**: `pdf()` divides by `4·HdotV + 0.001f`
  (`disney.cpp:535`) while `sample()` reflects with no matching epsilon — a small
  but angle-dependent density bias that grows as `HdotV → 0` (grazing), consistent
  with the observed θ-dependence.
- **Half-vector density vs reflected-direction density**: confirm the
  `D·NdotH/(4·HdotV)` Jacobian is applied against the same `H`, `a`, and
  frame the sampler uses (Walter 2007 §5.3 half-vector→direction Jacobian
  `1/(4·|H·wo|)`); check the `NdotH>0 && HdotV>0` guard (`disney.cpp:533`) against
  the sampler's below-horizon rejection (`disney.cpp:509`) — a density that is
  nonzero on directions the sampler can never produce (or vice-versa) is a pure
  shape mismatch.
- **Lobe-mixture weight leakage**: the diffuse gate sets `specular=0` yet still
  fails at θ=45° — check whether the specular lobe retains nonzero mixture weight
  (`specWeight=1, total=diffWeight+specWeight`, `disney.cpp:524-526`) even when the
  specular *contribution* is meant to be suppressed, and whether `pdf()` and
  `sample()` compute that mixture weight identically.
- The **roughness→α mapping** (`a = max(roughness², 0.0064f)`, applied at both
  `disney.cpp:501` and `:530`) — verify it is byte-identical on both sides (it
  appears to be; confirm, don't assume).

pkg123's deliverable is the *answer*, backed by residual maps — not a guess.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### A. Localize with per-cell chi² residual maps

Extend the harness (or add a debug path) to dump the per-cell
`(observed − expected)/√expected` residual grid for a failing config, not just the
pooled scalar χ²/p-value. This shows **where** on the (θ,φ) hemisphere the sampled
histogram and the integrated pdf disagree — a ring at the specular peak vs. a
systematic tilt vs. a horizon artifact each implicate a different suspect above.
Mitsuba's `chi2.py` already retains the failure-dump mechanism (pkg121 §Phase B
note: "keep Mitsuba's `chi2_data.py` failure-dump"); reuse it, add the residual
heatmap. Start with **metallic roughness 0.4, θ=45°** (fully grid-resolved, clearly
failing) as the diagnostic anchor.

**Cite:** Mitsuba 3 `src/python/python/chi2.py` `ChiSquareTest` + `chi2_data.py`
(BSD-3-Clause, already ported in pkg121); pbrt-v4 `src/pbrt/bsdfs_test.cpp`
(Apache-2.0) for the residual-inspection convention.

### B. Compare `disney.cpp` GGX sample vs pdf against the canonical construction

Put the engine's three pieces side by side against the reference math:

- **Sampler** (`disney.cpp:496-513`) — standard GGX NDF half-vector sample.
- **Density** (`disney.cpp:529-536`) — `D_GTR2(NdotH,a)·NdotH/(4·HdotV)`.
- **Reference** — pbrt-v4 `src/pbrt/bxdfs.h`/`microfacet.h`
  `TrowbridgeReitzDistribution::Sample_wm` + `PDF`, and Walter 2007 "Microfacet
  Models for Refraction through Rough Surfaces" (EGSR 2007) §5.3 — the half-vector
  sampling and its `p(ωo) = p(ωm)/(4·(ωo·ωm))` Jacobian. The in-tree
  `smithG1_GGX` already cites Walter 2007 Eq. 34 (`disney.cpp:26-32`); reuse that
  citation anchor.

Determine whether the reported density is the correct pushforward of the sampling
procedure. Fix the side that is wrong **with the residual map as evidence**:

- If the **engine** density is wrong (e.g. the epsilon, a missing/extra Jacobian
  factor, or a guard mismatch), fix `disney.cpp` and cite the reference line.
- If the **harness** is wrong (e.g. the hemisphere integration doesn't account for
  the failed-sample live-fraction normalization the way the sampler does), fix the
  harness and record why the pkg121 Lambertian anchor didn't catch it.

Do **not** lower a tolerance or widen a bin to make the gate pass — pkg121 §Scope
and the merged xfail reasons both forbid it.

### C. Harness full-sphere domain (make transmission testable)

The glass gate uses `HemisphericalDomain` with a stale "reflection-only" comment
(`test_chi2_disney_glass:261-263`) even though transmission emits into the lower
hemisphere; its xfail reason already says it "needs full-sphere domain." The ported
harness **already imports `SphericalDomain`** (`test_chi2_bsdf.py:21`, from
`chi2.py`). Switch the glass/transmission gates to `SphericalDomain`, verify the
`debug_bsdf_sample_batch` adapter round-trips lower-hemisphere `wi` correctly
(the adapter transposes (N,3)↔(3,N) — confirm sign handling), and confirm the
sampler emits the full BTDF domain. Cite Mitsuba `SphericalDomain` (already ported).

### D. Document the near-delta roughness floor

pkg121 established that **near-delta configs** (metallic roughness 0.1, smooth
glass roughness 0.0) are excused from chi² **only** for grid-resolution reasons —
an 80×160 grid cannot resolve a near-mirror lobe — **not** because the engine is
wrong there. Document this explicitly: record the α-floor
(`a = max(roughness², 0.0064f)`, `disney.cpp:501,530`), state which configs the
80×160 grid cannot resolve, and mark them as grid-limited (skip/expected) rather
than leaving a bare xfail that reads as "engine defect." This keeps the un-xfailed
grid honest about *what is validated* vs *what is grid-unresolvable*.

### E. Un-xfail and re-run the full grid

Once the residual is fixed with evidence: remove the `xfail(strict=False)` markers
from the configs that now pass (`test_chi2_disney_metallic`,
`test_chi2_disney_diffuse`, `test_chi2_disney_glass`, and the slow
`test_chi2_disney_full_grid`), keeping only genuinely grid-limited near-delta
configs marked (per D). Run the full slow grid (`pytest -v -m slow`) and record the
pass/fail map. If any config exhibits a **genuine engine↔reference divergence**
that is physically correct but statistically flagged, surface it for **owner
adjudication** (do not silently suppress) — matching the pkg120 "or divergences
owner-adjudicated" acceptance pattern.

---

## Acceptance criteria

- [ ] Per-cell chi² residual maps produced for the diagnostic anchor(s) and
      archived (metallic 0.4/θ=45° at minimum); the residual localizes the mismatch.
- [ ] The responsible side (engine `disney.cpp` `sample()`/`pdf()` **or** the
      harness) is fixed **with the residual map as the cited evidence**; the fix
      cites pbrt-v4 `microfacet.h` / Walter 2007 §5.3 (engine) or the ported
      Mitsuba `chi2.py` invariant (harness). No tolerance/bin fudging.
- [ ] Harness gains a **full-sphere domain** path; glass/transmission gates use
      `SphericalDomain` and the adapter round-trips lower-hemisphere `wi`.
- [ ] Near-delta roughness floor documented; grid-unresolvable configs marked as
      grid-limited (not bare "engine defect" xfails).
- [ ] Merged Disney gates **un-xfailed** and passing:
      `test_chi2_disney_metallic`, `test_chi2_disney_diffuse`,
      `test_chi2_disney_glass`, and `test_chi2_disney_full_grid` (slow) — or any
      residual divergence explicitly owner-adjudicated and recorded.
- [ ] Lambertian anchor still passes (harness not regressed by the changes).
- [ ] No production regression: furnace/white-furnace and CPU↔GPU parity gates stay
      green (the fix, if in the engine pdf, must not perturb the unbiased estimator).
- [ ] Research/citation note in `.astroray_plan/docs/` recording the adjudication
      (which side was wrong, the residual-map evidence, the cited reference lines);
      extend `pkg121-disney-pdf-finding.md` rather than starting a new doc.

---

## Non-goals

- **Not VNDF sampling.** Replacing the reflection lobe's NDF-sample-then-reflect
  with visible-NDF sampling is **pkg124**. pkg123 adjudicates the *current* lobe's
  sample/pdf consistency; pkg124 changes the sampler afterward (and must re-pass
  these gates). If B concludes the cleanest fix *is* to move to VNDF, stop and hand
  to pkg124 rather than doing it here — keep pkg123 to the shape-consistency
  adjudication so the two packages stay separable.
- **Not the one-sided→two-sided MIS change.** That is **pkg120**; pkg123 only
  hardens the `bsdfPdf` that pkg120's weight consumes.
- **Not new BSDF lobes.** Sheen, clearcoat, subsurface chi² validation is the
  pkg121 Phase B campaign, not this package.
- **Not GPU.** CPU BSDF path only, matching pkg121's CPU-only scope. Any GPU chi²
  extension is a future package.
- **Not re-blessing reference images.** No image references move here (chi² is a
  sampler test, not a render gate).

---

## Provenance

Filed from the **pkg121 Disney BSDF chi² investigation FINAL STATE (2026-07-20)**
(`.astroray_plan/docs/pkg121-disney-pdf-finding.md`, "The residual finding for
pkg123"). pkg121 (PR #485, merged 75ba67a) proved the harness correct against
Lambertian, resolved two harness bugs and the failed-sample convention, and
isolated a **real, unexplained specular-lobe sample()/pdf() shape mismatch** that
its xfail(strict=False) gates document and defer here. The gate reasons in
`tests/statistical/test_chi2_bsdf.py:111-120, 175-180, 233` name pkg123 explicitly.
The production stake is the pkg120 one-sided integrator's dependence on a correct
`Material::pdf` for its NEE MIS weight.

---

## Progress

- [ ] A — per-cell residual maps; diagnostic anchor localized.
- [ ] B — engine sample/pdf vs pbrt-v4/Walter 2007 comparison; responsible side fixed with evidence.
- [ ] C — full-sphere domain; glass/transmission gates testable.
- [ ] D — near-delta roughness floor documented; grid-limited configs marked.
- [ ] E — Disney gates un-xfailed; full slow grid re-run and recorded.

---

## Lessons

*(Fill in after the package is done.)*
