# pkg138 — Disney dielectric rough reflection in eval() (fix the delta-vs-continuous sample/pdf type mismatch)

**Pillar:** 3 (BSDF correctness / MIS density consistency)
**Track:** A (CPU BSDF first, chi²-gated on CI; GPU mirror verified on RTX — the GPU dielectric lowers via the closure graph, so check both legs)
**Codex-paste-ready:** no (an `eval()` energy-shape change on the glass path — needs furnace + CPU/GPU parity validation and judgment about the delta-fallback boundary, not a mechanical patch)
**Status:** in review (PR #517) — **ADJUDICATED 2026-07-23: MERGEABLE as a partial-scope correctness improvement** (architect verdict, design authority for the overnight run; see block below; HW non-regression check in parallel; final merge via pr-merger checklist).

> **✅ ADJUDICATION (2026-07-23, architect) — PR #517 ships; the chi² glass[0.3-45] gate transfers to pkg149/pkg150.**
>
> **Verdict: MERGEABLE.** Reasoning:
> 1. **The in-scope fix is real, cited, and verified by its own direct evidence.** The diagnosed defect (eval() reflection-lobe Cspec0 collapse) is fixed per the spec's canonical form (Walter 2007 EGSR §5.1 / pbrt-v4 `DielectricBxDF::f` reflection branch), with the GPU twin mirrored, and **eval/pdf now agree <0.3%** — that agreement, not the aggregate chi² statistic, is the direct measurement of this package's defect.
> 2. **The unchanged chi² number (bit-identical 143,140,779) is honestly explained and re-attributed, not hidden.** Two newly-measured defects outside this spec's scope dominate the statistic: (a) at glass[0.3-45] the VNDF reflection candidate is **100% masked by the same-hemisphere check** (N≥100k) — so the fixed eval() shape is never exercised by sampling at that config; (b) the rough **transmission** lobe (an explicit Non-goal here) carries **~92–96% of sampled weight** with a ~16–18° sample/pdf peak mismatch. A gate whose statistic is >92% out-of-scope lobe was **mis-assigned at spec time**; keeping #517 hostage to it would gate this fix on work the spec explicitly excluded.
> 3. **The xfail discipline is respected, not violated.** The memory rule (`xfail-gated-features-must-unxfail`) forbids accepting XFAIL as evidence *for the gated feature*; here the re-xfail carries documented reasons naming the two out-of-scope defects, and the gate obligation **transfers explicitly**: un-xfail of glass[0.3-45] is owned by **pkg149** (transmission re-derivation — the dominant term) with **pkg150** (reflection-candidate masking) as the secondary contributor. Neither may close while the gate is xfail.
> 4. **Non-regression:** the attempted pbrt-faithful dead-sample fix that regressed furnace 0.9→0.0 was correctly **reverted** rather than shipped; the furnace-trap constraint is recorded in pkg150. HW verifier is confirming render-level non-regression in parallel — a MERGE condition, per the checklist.
>
> **Merge conditions:** (i) HW non-regression PASS; (ii) the chi² xfail reason strings in the test name pkg149/pkg150; (iii) the research note (`pkg138-disney-dielectric-rough-reflection-research.md`) and the spec lessons land with the PR.

*(Pre-#517 status for the record: open — dispatchable, UNBLOCKED 2026-07-23 after pkg123/#498 merged as `587b554`; serialized behind pkg145.)*

*(Implementer's own PARTIAL-status write-up, 2026-07-23, superseded by the
architect adjudication above but kept for detail: the spec's diagnosed
defect — Cspec0 collapse in `eval()`'s dielectric reflection lobe — is fixed
and verified (rough dielectric reflection lobe, Walter 2007 EGSR §5.1 Eq. 20
/ pbrt-v4 `DielectricBxDF::f`, mirrored CPU + GPU). The acceptance gate
[`test_chi2_disney_glass[0.3-45]`] is still xfail — chi²=143,140,779,
bit-identical before/after this fix, because the config is dominated by two
FURTHER, newly-measured defects out of this spec's stated scope: (2) at this
specific (roughness, theta), `sample()`'s VNDF reflection candidate is masked
(same-hemisphere check fails) 100% of the time regardless of the eval() fix —
a PBRT-v4-faithful "dead sample" correction was tried and reverted after it
regressed white-furnace energy conservation to ~0.0; (3) the rough
TRANSMISSION lobe (`roughTransmissionEval`/`Pdf`, this spec's explicit
Non-goal) has its own ~16-18° sample/pdf peak-location mismatch, independently
measured, and dominates this test's chi² given transmission carries ~92-96%
of the sampled weight. Full measurements: `.astroray_plan/docs/pkg138-disney-
dielectric-rough-reflection-research.md`. Follow-up specs filed: **pkg149**
(transmission sample/pdf re-derivation, owns the un-xfail) and **pkg150**
(VNDF hemisphere masking).)*
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

- [x] Dielectric reflection lobe is rough in `eval()` (Walter Eq. 20 with
      dielectric Fresnel) — `roughReflectionEval`/`gpu_disney_roughReflectionEval`,
      blended into `spec` by the same `(1-transmission_)`/`transmission_`
      mixture weights `pdf()` already uses. Verified directly: `eval()` now
      returns physically correct nonzero values (matching `pdf()` to <0.3%)
      at plausible reflection directions, instead of the Cspec0-collapsed
      near-zero. **NOT achieved:** "the `sample()` VNDF reflection candidate
      ... is accepted in the rough regime" — at `glass[0.3-45]` specifically,
      the candidate is STILL rejected 100% of the time, but now by the
      same-hemisphere masking check (root cause #2), not by `eval()`
      collapsing to zero. See research note.
- [ ] **Un-xfail `test_chi2_disney_glass[0.3-45]`** — **NOT ACHIEVED**. chi²
      is bit-identical (143,140,779) before/after this fix; re-xfailed with
      an updated reason documenting root causes #2 and #3 (both newly
      measured, both outside this spec's stated scope). "The full slow-grid
      glass rows" — no such parametrized row set exists in
      `test_chi2_bsdf.py` today (only the single `[0.3-45]` config); not
      added (would be scope creation beyond what was asked).
- [x] **Rough-glass furnace stays green** — verified unchanged (CPU/GPU both
      pass `test_disney_rough_glass_furnace_energy_{cpu,gpu}`,
      `test_dielectric_glass_furnace_{cpu,gpu}`, `test_disney_energy_conservation.py`).
      A candidate companion fix for root cause #2 (return a dead sample
      instead of the smooth-delta fallback, matching pbrt-v4's own
      convention) was tried and REVERTED after it collapsed furnace values
      to ~0.0 — see research note.
- [x] **CPU/GPU parity** — the GPU dielectric-transmission closure
      (roughness>0.03) lowers to `GMAT_DISNEY` via `gpu_closure_as_material`
      (confirmed by reading `scene_upload.cu`/`gpu_materials.h`), so it does
      have its own copy of the collapsed-Cspec0 bug; mirrored the identical
      fix (`gpu_disney_roughReflectionEval`, same blend in `gpu_disney_eval`).
      GPU furnace/energy-conservation tests pass unchanged (see above). Full
      GPU hardware chi²/render sweep is the orchestrator's dedicated
      verifier's job (HW gate pending, not run here per dispatch instructions).
- [x] Line anchors re-verified against merged `main` (HEAD `1af7eca`, includes
      pkg123 `587b554` and pkg145 `531f512`).
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

- [x] Rough dielectric reflection lobe in `eval()` (pbrt-v4 mirror; reuse
      in-tree D/G/Fresnel helpers). Shipped, verified, CPU+GPU.
- [ ] `sample()` VNDF reflection candidate accepted in the rough regime —
      NOT achieved at `glass[0.3-45]` (masked 100% of the time by a
      same-hemisphere check, independent of the eval() fix; see root cause
      #2 in the research note). Delta fallback boundary UNCHANGED (kept as
      the pre-existing behavior after a PBRT-faithful alternative regressed
      furnace energy to ~0.0).
- [ ] chi² glass rows un-xfailed + green — NOT achieved (bit-identical
      chi²=143,140,779 before/after); rough-glass furnace green (achieved,
      unchanged); CPU/GPU parity green (achieved for the shipped fix; full
      HW sweep is the orchestrator's job).
- [x] Citation note + code citations
      (`.astroray_plan/docs/pkg138-disney-dielectric-rough-reflection-research.md`,
      inline comments in `disney.cpp`/`gpu_materials.h`).

---

## Lessons

1. **A xfail's diagnosed root cause can be real but non-dominant.** The
   pkg123 review's diagnosis (Cspec0 collapse rejecting the VNDF candidate)
   was correct and the fix is real — but at the exact acceptance-criterion
   config (`glass[0.3-45]`), a *different* rejection mechanism (same-
   hemisphere masking, selected-for by the Fresnel roulette) already vetoes
   every candidate before `eval()`'s value ever matters. Fixing the diagnosed
   cause moved the chi² statistic by exactly 0.00% at this config. Always
   re-measure the SPECIFIC failing config after a "fix", not just the
   general mechanism — a real, cited fix can still be inert for the config
   the gate actually tests.
2. **A pbrt-v4-faithful change is not automatically safe to port piecewise.**
   `DielectricBxDF::Sample_f`'s "return no sample on SameHemisphere/Refract
   failure" convention is correct *in pbrt*, where it's paired with pbrt's
   own (presumably masking-aware) pdf and — per Kulla&Conty/Turquin-style
   engines — often a multiscatter compensation layer. Porting just the
   "discard" half without its energy-accounting half is not a partial win;
   it's a silent, severe energy-conservation regression (measured: furnace
   ~0.0). Any port of a masking-shadowing discard rule needs to also verify
   the DOWNSTREAM density accounts for the discarded mass, not just check
   chi² for the sampling side.
3. **The transmission lobe was never checked for POSITIONAL sample/pdf
   agreement**, only magnitude/energy (furnace tests). A ~16-18° peak-
   location mismatch between `roughTransmissionPdf`'s analytic peak and
   `sample()`'s actual VNDF-then-refract output survived every prior
   furnace/energy pass because the *total* integrated energy can still look
   conserved even when the *shape* is wrong — chi² is the only gate that
   catches this, and nobody had run a full-sphere (not hemisphere-only) chi²
   sweep against the transmission lobe specifically until this
   investigation.
