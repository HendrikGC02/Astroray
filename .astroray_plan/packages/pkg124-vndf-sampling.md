# pkg124 — Visible-NDF (VNDF) sampling for the Disney specular reflection lobe

**Pillar:** 3 (sampling efficiency / BSDF correctness)
**Track:** A (CPU BSDF path first, chi²-gated on CI; the change is shared math so the GPU spec lobe mirrors it — RTX-verify the GPU leg)
**Codex-paste-ready:** no (a sampler replacement whose sample() and pdf() must change **together** to stay chi²-consistent; needs the pkg123 adjudication as its correctness baseline and an equal-time noise measurement to justify)
**Status:** open — **blocked on pkg123** (the specular-lobe sample/pdf shape must be adjudicated and the gates un-xfailed *before* the sampler is swapped, so the swap is measured against a green baseline)
**Estimated effort:** M (swap the reflection lobe to VNDF sample + matching VNDF pdf — most machinery already exists in-tree; re-pass chi², measure dead-sample rate before/after, equal-time noise A/B)
**Depends on:** **pkg123** — the Disney spec-lobe chi² gates must be **passing (un-xfailed)** first. pkg124 changes the sampler and *must not reopen* the mismatch; that is only checkable against a green chi² grid. Land order: pkg123 → pkg124.

---

## Context — measured waste, not a theoretical improvement

pkg121 measured the Disney sampler's **live fraction** directly: at roughness 1 the
diffuse-Disney config has live fraction **0.7514** — i.e. the specular half of the
mixture throws away **≈25% of its draws** as below-horizon dead samples
(`.astroray_plan/docs/pkg121-disney-pdf-finding.md` §3: "~25% dead samples at high
roughness is real waste — VNDF sampling (Heitz 2018, JCGT) eliminates most of it").
The current reflection lobe samples the **full GGX NDF** and then reflects, so any
half-vector that produces a `wi` below the horizon is rejected (`disney.cpp:509`
`if (rec.normal.dot(s.wi) > 0)`). Visible-NDF sampling draws only from the
distribution of normals **visible from the outgoing direction**, which by
construction almost never yields a below-horizon reflection — turning most of those
wasted draws into useful samples and lowering variance at equal sample count.

This is not speculative: the same VNDF machinery is **already in the tree** and
already used on the Disney **transmission/glass** path (see Root cause). pkg124
extends it to the reflection lobe, which pkg121 flagged and which the current code
comment (`disney.cpp:496-500`) explicitly left as NDF sampling only because the
earlier attempt mis-paired VNDF-sample with the NDF pdf.

---

## Goal

**Before:** The Disney specular **reflection** lobe samples the standard GGX NDF and
reflects (`disney.cpp:496-513`), paired with the NDF reflection pdf
`D·NdotH/(4·HdotV)` (`disney.cpp:529-536`). At roughness 1 this discards ~25% of
specular draws below the horizon (pkg121). The comment at `disney.cpp:496-500`
records that VNDF sampling was tried here and reverted — **because it was left
paired against the NDF pdf**, a sample/pdf mismatch that darkened metal. So the tree
today has VNDF sampling available but deliberately unused on the reflection lobe.

**After:** The reflection lobe samples the **visible** GGX NDF (Heitz 2018) paired
with its **matching VNDF pdf**, both changed together so the estimator stays
chi²-consistent. Below-horizon dead samples on the reflection lobe drop from ~25%
(roughness 1) toward the VNDF near-zero floor, direct-specular variance falls at
equal sample count, and the Disney chi² gates (un-xfailed by pkg123) **still pass**.
The CPU and GPU specular lobes stay in lockstep (shared VNDF sample + pdf), so no
CPU↔GPU parity regression.

---

## Root cause — the machinery already exists; only the reflection lobe opts out

The in-tree VNDF pieces, all present and cited:

- **`sampleGgxVNDF(rec, wo, gen)`** — `disney.cpp:95-97`, cites *Heitz 2018,
  "Sampling the GGX Distribution of Visible Normals," JCGT 7(4)*. Already used on
  the transmission path (`disney.cpp:425-426`).
- **`vndfPdf(rec.normal, wo, wm)`** — `disney.cpp:200-211`, the VNDF density
  `D(wm)·G1(wo)·|wo·wm|/|wo·n|`, cites *PBRT-v4 `DielectricBxDF::PDF`*.
- **`smithG1_GGX`** — `disney.cpp:32`, the Smith Λ masking term, cites *Walter 2007
  Eq. 34*, used by both `vndfPdf` and the reflection-reflection Jacobian.

The transmission branch already composes them correctly: sample `wm` via VNDF,
reflect, and set `pdf = vndfPdf(...) / (4·|HdotO|) · R/(R+T)` (`disney.cpp:441-442`).
The **opaque** specular reflection lobe (metallic/dielectric, non-transmission) is
the only path still on NDF-sample-then-reflect. pkg124's core change is therefore
small and local: replace the `disney.cpp:496-513` NDF sampler with a VNDF sampler
whose reflected-direction pdf is `vndfPdf(n, wo, wm) / (4·|wo·wm|)`, and update
`pdf()` (`disney.cpp:529-536`) for the reflection lobe to report that **same** VNDF
density — the two must move as one edit.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### A. Replace the reflection-lobe sampler with VNDF

In `sample()`'s opaque-specular branch (`disney.cpp:496-513`): draw
`wm = sampleGgxVNDF(rec, wo, gen)`, reflect `wi = 2(wo·wm)wm − wo`, and set the pdf
to the VNDF reflected-direction density `vndfPdf(rec.normal, wo, wm) / (4·|wo·wm|)`
(mirroring exactly what the transmission-reflection sub-branch already does at
`disney.cpp:436-442`, minus the `R/(R+T)` Fresnel-split factor that is
transmission-specific). Reuse the existing `sampleGgxVNDF` / `vndfPdf` — **do not
add a second VNDF implementation**. Remove the now-obsolete `disney.cpp:496-500`
comment (its warning was about the *mismatch*, which this package resolves by
changing both sides).

**Cite:**
- *Heitz 2018, "Sampling the GGX Distribution of Visible Normals," JCGT 7(4)* —
  already cited at `disney.cpp:95`; the canonical VNDF sampling routine.
- **Cycles reference implementation:**
  `intern/cycles/kernel/closure/bsdf_microfacet.h` (Apache-2.0) —
  `bsdf_microfacet_ggx_sample` and its VNDF half-vector helper
  (`microfacet_ggx_sample_vndf` / `microfacet_sample_stretched`); this is the
  production mirror the task requires. Pin the commit SHA in the research note.
- *PBRT-v4 `src/pbrt/bxdfs.h` `ConductorBxDF`/`DielectricBxDF::Sample_f` +
  `TrowbridgeReitzDistribution::Sample_wm`* (Apache-2.0) — the reflected-direction
  Jacobian `1/(4·|wo·wm|)`; already the source for the in-tree `vndfPdf`.

### B. Update the reflection-lobe pdf to the matching VNDF density

In `pdf()` (`disney.cpp:529-536`): replace the NDF reflection term
`D·NdotH/(4·HdotV)` with `vndfPdf(rec.normal, wo, wm)/(4·|wo·wm|)` for the specular
reflection component, keeping the diffuse and (already-VNDF) transmission terms and
the mixture weighting `specWeight/total` unchanged. **A and B are one atomic change**
— sample and pdf must agree, which is precisely the invariant pkg123 adjudicates and
pkg124 must preserve.

### C. Keep CPU and GPU in lockstep

The GPU specular lobe is described as an NDF-spec lobe matching the CPU
(`disney.cpp:496-497` comment: "matches ... the GPU non-transmission spec lobe").
Mirror the VNDF sample + pdf into the GPU material sampler so CPU and GPU stay
term-for-term identical, and verify with the existing CPU↔GPU wavefront-diff parity
gate. If the GPU port is non-trivial, it may split into a follow-up **only if** the
CPU↔GPU parity gate is kept green in the interim (i.e. do not land a CPU-only VNDF
that desyncs the two); prefer landing both together.

### D. Verify: chi², dead-sample rate, equal-time noise

1. **chi² still passes.** Re-run the Disney gates pkg123 un-xfailed
   (`test_chi2_disney_metallic`, `_diffuse`, `_glass`, and the slow full grid). VNDF
   sample + VNDF pdf must be chi²-consistent; a failure here means A/B desynced.
2. **Dead-sample rate before/after.** Instrument the specular lobe's live fraction
   (the pkg121 metric) at roughness ∈ {0.4, 0.8, 1.0}; report the drop (target: the
   ~25%-waste roughness-1 case falls toward the VNDF near-zero floor).
3. **Equal-time noise A/B.** Render a specular-dominant scene (e.g. the metal test
   material) at **equal wall-clock time** NDF-sampling vs VNDF-sampling and report
   the variance/noise reduction (MSE vs a high-spp reference, or per-pixel
   variance). This is the justification the package exists for; record the number.

---

## Acceptance criteria

- [ ] Reflection lobe samples VNDF (`sampleGgxVNDF`) with matching VNDF pdf
      (`vndfPdf(...)/(4·|wo·wm|)`); sample and pdf changed as one atomic edit; the
      obsolete `disney.cpp:496-500` NDF-only comment removed. No second VNDF
      implementation added (reuse the existing helpers).
- [ ] Disney chi² gates (un-xfailed by pkg123) **still pass** — the swap does not
      reopen the sample/pdf mismatch.
- [ ] Dead-sample (live-fraction) rate measured before/after at roughness
      {0.4, 0.8, 1.0}; the ~25% roughness-1 waste demonstrably drops.
- [ ] Equal-time noise A/B (NDF vs VNDF) measured on a specular-dominant scene;
      variance reduction reported.
- [ ] CPU↔GPU parity: GPU spec lobe mirrors the VNDF sample+pdf; wavefront-diff
      parity gate stays green (CPU and GPU term-for-term identical).
- [ ] No energy/furnace regression: white-furnace + specular energy-conservation
      gates stay green (VNDF is a variance change, not an energy change).
- [ ] Research/citation note in `.astroray_plan/docs/`: Heitz 2018 + Cycles
      `bsdf_microfacet.h` (pinned SHA) + PBRT-v4 Jacobian, with the before/after
      dead-sample and equal-time-noise numbers.

---

## Non-goals

- **Not the sample/pdf shape adjudication.** That is **pkg123**, which must land
  first; pkg124 assumes a green chi² baseline and preserves it.
- **Not the transmission/glass lobe.** It already uses VNDF (`disney.cpp:425-448`);
  leave it unchanged except where pkg123's full-sphere domain work touches its gate.
- **Not multiple-scattering GGX.** Energy compensation for rough-conductor
  multiscatter (the `1 + Fms·((1−E)/E)` factor, `disney.cpp:384`) is a separate
  concern; VNDF is single-scatter importance sampling only.
- **Not a new microfacet distribution.** Same GGX/Trowbridge-Reitz `D_GTR2`; only
  the *sampling strategy* for that distribution changes.
- **Not diffuse/sheen/clearcoat samplers.** Only the specular reflection lobe.

---

## Provenance

Filed from the **pkg121 Disney BSDF chi² investigation FINAL STATE (2026-07-20)**
(`.astroray_plan/docs/pkg121-disney-pdf-finding.md` §3: the ~25%-dead-sample
measurement at roughness 1 and the explicit "VNDF sampling (Heitz 2018, JCGT)
eliminates most of it ... recorded as a follow-up candidate" note). The in-tree VNDF
helpers (`sampleGgxVNDF` `disney.cpp:97`, `vndfPdf` `disney.cpp:200`) already exist
and are used on the transmission path; the reflection lobe was deliberately left on
NDF sampling (`disney.cpp:496-500`) pending the sample/pdf adjudication now scoped as
pkg123. Depends on pkg123 landing first.

---

## Progress

- [ ] A — reflection-lobe VNDF sampler (reuse `sampleGgxVNDF`); obsolete comment removed.
- [ ] B — matching VNDF reflection pdf; A+B atomic.
- [ ] C — GPU spec lobe mirror; CPU↔GPU parity green.
- [ ] D — chi² re-pass + dead-sample before/after + equal-time noise A/B.

---

## Lessons

*(Fill in after the package is done.)*
