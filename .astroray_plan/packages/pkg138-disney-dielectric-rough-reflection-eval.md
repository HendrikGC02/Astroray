# pkg138 — Disney dielectric rough reflection in eval() (fix the delta-vs-continuous sample/pdf type mismatch)

**Pillar:** 3 (BSDF correctness / MIS density consistency)
**Track:** A (CPU BSDF first, chi²-gated on CI; GPU mirror verified on RTX — the GPU dielectric lowers via the closure graph, so check both legs)
**Codex-paste-ready:** no (an `eval()` energy-shape change on the glass path — needs furnace + CPU/GPU parity validation and judgment about the delta-fallback boundary, not a mechanical patch)
**Status:** open — **blocked on pkg123 (PR #498) merging first** (this defect was found and adjudicated by the #498 Opus re-review; the xfail'd gate this package un-xfails lives on that branch, and all `disney.cpp` line anchors below are against `origin/pkg123-disney-chi2` — re-anchor after merge)
**Estimated effort:** M (the eval change is localized, but it changes measured glass energy shape: chi² re-pass + rough-glass furnace + CPU/GPU parity all must be re-validated together)
**Depends on:** **pkg123 (PR #498)** — land order: pkg123 → pkg138. **Coordinate with pkg124** (VNDF for the OPAQUE reflection lobe): disjoint lobes, but both edit `disney.cpp` sample/pdf regions — sequence the merges or rebase carefully; do not let either reopen the other's chi² gates.

---

## Context — found by the #498 Opus parity re-review (measured, mechanism confirmed)

The pkg123 adjudication round-2 review measured a **delta-vs-continuous sample/pdf
type mismatch** on the Disney dielectric (transmission=1, metallic=0):

- **chi² χ² = 143M** at `glass[0.3-45]` (roughness 0.3, 45° incidence) — not a
  tolerance issue, a structural mismatch.
- The sample/eval density ratio is a **constant 0.060** — the signature of a
  wrong event *class*, not a wrong formula constant.
- **Furnace-INVISIBLE:** the throughput/pdf ratio is correct along each sampled
  path, so energy conservation tests cannot see it — only the MIS *density shape*
  is wrong. This is why the defect survived every furnace gate to date.

## Root cause (mechanism, verified on `origin/pkg123-disney-chi2`)

The rough VNDF **reflection** candidate inside the transmission branch is
rejected in `sample()` and silently replaced by a smooth mirror **delta**, while
`pdf()` keeps reporting a **continuous** VNDF reflection density for the same
directions:

1. `sample()`'s transmission branch draws a VNDF microfacet and builds the rough
   reflection candidate, accepting it only if
   `s.pdf > 0 && s.f.length2() > 0` (`plugins/materials/disney.cpp:455`).
2. At metallic=0 the reflection lobe of `eval()` is ≈0 because
   `Cspec0 = specular_ * 0.08` collapses the reflection color
   (`disney.cpp:325`, `F0 = Cspec0*(1-metallic) + Cdlin*metallic` at `:326`) —
   so `s.f.length2() == 0` and the candidate is **rejected**.
3. Control falls through to the smooth mirror event
   (`disney.cpp:465-474`): `s.wi = reflect(wo, n)`, `pdf = fresnel*transmission_`
   (or `transmission_` for forced TIR), **isDelta** — a delta reflection.
4. `pdf()` meanwhile reports the **continuous** VNDF reflection term for the
   reflection hemisphere of the glass path (`disney.cpp:~543` region, the VNDF
   reflection term added by the #498 mixScale fix).

Net: sampled reflection events are deltas, reported density is continuous —
chi² explodes, and any MIS weight computed against `pdf()` for a
light-sampled reflection direction is wrong for rough glass.

---

## Canonical fix (from the review — cite, no inventions, CLAUDE.md §6)

**Make the dielectric reflection lobe rough in `eval()`**, so the VNDF reflection
candidate in `sample()` survives its own `s.f.length2() > 0` check and matches
`pdf()`'s continuous term. The dielectric reflection BRDF is the standard
microfacet form with **dielectric Fresnel**, not the Cspec0/F0 Schlick color:

```
f_r(wo, wi) = D(wm) · G(wo, wi) · F_dielectric(wo·wm, eta) / (4 · cosθo · cosθi)
```

**Cite:**
- *pbrt-v4* `src/pbrt/bxdfs.cpp` **`DielectricBxDF::f` / `DielectricBxDF::Sample_f`
  reflection branch** (Apache-2.0) — the production reference for the rough
  dielectric reflection lobe with `FrDielectric` Fresnel; already the in-tree
  source for `vndfPdf` (`disney.cpp:200-211` cites `DielectricBxDF::PDF`).
- *Walter et al. 2007, "Microfacet Models for Refraction through Rough Surfaces"
  (EGSR)* **§5.1 Eq. 20** — `f_r = D·G·F / (4·|cosθo|·|cosθi|)`; the in-tree
  `smithG1_GGX` already cites Walter 2007 Eq. 34.
- The in-tree rough-transmission twin `roughTransmissionEval` /
  `roughTransmissionPdf` (already used at `disney.cpp:450-451`) — mirror its
  structure for the reflection side; **do not add a second D/G/Fresnel
  implementation** (reuse `D_GTR2`, `smithG1_GGX`, and the existing dielectric
  Fresnel used by the transmission branch).

**Explicitly REJECTED alternative (do not do this):** suppressing the VNDF
reflection term in `pdf()` so it matches the delta sampling. The review rejected
it because it **breaks MIS** — light-sampled rough-glass reflection directions
would be under-counted (pdf()=0 or near-0 where real reflected energy exists).
The fix is to make `eval()` (and thus `sample()`'s accepted candidate) rough,
not to make `pdf()` blind.

**Boundary to preserve:** the smooth-mirror fallback at `disney.cpp:465-474`
remains the correct event for `cannotRefract` (TIR) and for the genuinely-smooth
regime (`roughness_ <= kDeltaTransmissionRoughness`, which routes around the
rough branch entirely). The fix targets the rough regime where the VNDF
candidate exists but is being vetoed by the collapsed reflection color.

---

## Acceptance criteria

- [ ] Dielectric reflection lobe is rough in `eval()` (Walter Eq. 20 with
      dielectric Fresnel); the `sample()` VNDF reflection candidate at
      `disney.cpp:455` (post-#498 anchor) is accepted in the rough regime; the
      smooth delta remains only for TIR / below the delta-roughness threshold.
- [ ] **Un-xfail `test_chi2_disney_glass[0.3-45]`** and the full slow-grid glass
      rows; they pass (the χ²=143M mismatch and the constant 0.060 density ratio
      are gone).
- [ ] **Rough-glass furnace stays green** — the eval change alters measured
      energy shape, so re-run the white-furnace / rough-glass energy gates
      (watch the eta²/albedo-LUT class of bug; memory:
      `rough-glass-residual-is-multiscatter`).
- [ ] **CPU/GPU parity** — the GPU dielectric shades via the closure graph
      (memory: `gpu-dielectric-lowers-to-closure-graph`); verify the GPU leg
      agrees with the fixed CPU eval (wavefront-diff / GPU parity gates at the
      1e-5 Monte-Carlo convention) and mirror the eval change if the GPU has its
      own copy of the collapsed-Cspec0 reflection.
- [ ] Line anchors re-verified against merged main (all anchors above are
      against `origin/pkg123-disney-chi2`).
- [ ] Research/citation note in `.astroray_plan/docs/` (pbrt-v4 file+function,
      Walter Eq. 20, before/after chi² numbers), citations in the code at the
      change site.

---

## Notes

- **Pre-existing CPU/GPU MIS-pdf asymmetry (OUT OF SCOPE — flag only, future GPU
  MIS pass):** the CPU opaque-specular `sample()` returns the **full mixture**
  `pdf()` (`disney.cpp:514`, `s.pdf = pdf(rec, wo, s.wi)`), while the GPU
  computes the **selected-lobe-only** pdf
  (`include/astroray/gpu_materials.h:849-857`, `D·NdotH/(4·HdotV) · specW/total`).
  These diverge for mixed diffuse+specular materials and the divergence is not
  chi²-covered (the chi² harness drives the CPU bindings). Do NOT fix it here —
  record it for a dedicated GPU MIS-consistency pass so the fix is measured on
  both legs at once.
- **Relationship to pkg124:** pkg124 swaps the **opaque** specular reflection
  lobe's sampler NDF→VNDF (sample+pdf, no eval change). pkg138 fixes the
  **dielectric** reflection lobe's eval so the existing VNDF sampling is not
  vetoed. Different lobes, same file — coordinate merges; each must leave the
  other's chi² gates green.

---

## Non-goals

- **Not the pdf-only suppression** (rejected by review — breaks MIS).
- **Not the opaque reflection lobe** (that is pkg124).
- **Not the transmission/refraction lobe** — `roughTransmissionEval/Pdf` are
  correct and untouched.
- **Not the CPU/GPU mixture-pdf asymmetry** (Notes above — future GPU MIS pass).
- **Not multiscatter energy compensation** (pkg129 territory).

---

## Provenance

Filed from the **#498 (pkg123) Opus parity re-review gate-failure adjudication
(2026-07-20)**: measured χ²=143M at `glass[0.3-45]`, constant sample/eval density
ratio 0.060, mechanism traced to the `disney.cpp:455` rejection →
`:465-474` delta fallback caused by the `:325` Cspec0 collapse at metallic=0,
while `pdf()` (`:~543`) reports a continuous VNDF reflection term. The canonical
fix (rough dielectric reflection in eval per pbrt-v4 `DielectricBxDF` + Walter
2007 §5.1 Eq. 20) and the rejection of pdf-only suppression are the reviewer's
adjudication, recorded here verbatim as the implementation contract.

---

## Progress

- [ ] Rough dielectric reflection lobe in `eval()` (pbrt-v4 mirror; reuse
      in-tree D/G/Fresnel helpers).
- [ ] `sample()` VNDF reflection candidate accepted in the rough regime;
      delta fallback boundary preserved (TIR / delta-roughness only).
- [ ] chi² glass rows un-xfailed + green; rough-glass furnace green;
      CPU/GPU parity green.
- [ ] Citation note + code citations.

---

## Lessons

*(Fill in after the package is done.)*
