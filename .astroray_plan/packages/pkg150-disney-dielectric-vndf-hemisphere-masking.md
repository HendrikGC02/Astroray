# pkg150 — Disney dielectric VNDF reflection candidate: same-hemisphere masking kills 100% of samples at grazing

**Pillar:** 3 (BSDF correctness / sampling coverage)
**Track:** A
**Codex-paste-ready:** no (a sampling-coverage fix with a documented furnace-regression trap — measurement-first, judgment at the gate)
**Status:** open — dispatchable (serialize behind PR #517 and behind/with pkg149; same `disney.cpp` sample() region). **2026-07-24 overnight: Lane A slot 3, CONDITIONAL** — start only after the pkg151→pkg149 chain has merged AND its HW verification passed, with ≥2 h of run budget left; first action is the re-baseline (measure the rejected-candidate fraction on the stacked main per the BASELINE UPDATE below). If the chain stalls, this package does not start (its baseline doesn't exist without the chain).
**Estimated effort:** S–M (localized, but the naive fix is a proven trap — see Constraint)
**Depends on:** pkg138/PR #517 merged. Secondary contributor to the glass[0.3-45] chi² gate **owned by pkg149** — this package may not close the gate alone, and neither package closes while it is xfail (memory `xfail-gated-features-must-unxfail`).

**Origin:** pkg138/PR #517 adjudication (2026-07-23). Measured there: at
glass[0.3-45], **100% of `sample()`'s VNDF reflection candidates are rejected by
the same-hemisphere check** (N≥100k) — the reflection lobe that pkg138 just made
correct in `eval()`/`pdf()` is **never sampled** at grazing configs, so MIS
weights and the chi² statistic still see a sampler that cannot produce
reflection directions the pdf assigns density to.

> **BASELINE UPDATE (2026-07-24, pkg149 root-cause session):** the pkg149
> `sampleGgxVNDF` azimuth fix (pbrt-v4 `Lerp` args were transposed; worktree
> `Astroray-pkg149`, local commit `670e583`, HELD — ships stacked on pkg151)
> improves this package's masking from **100% rejected → ~5–22% acceptance**
> without touching pkg150 scope: most of the "masking" was the swapped-azimuth
> half-vectors reflecting below the horizon. **Re-measure the rejected-candidate
> fraction on the corrected sampler (post pkg151+pkg149 landing) before doing
> anything here** — the residual ~78–95% rejection at grazing is this package's
> real target, and it may shrink the fix from a coverage redesign to a
> pdf-side truncation of a small set. Fix-contract item 1 (measure first) now
> explicitly means: baseline on the stacked pkg151+pkg149 main, not on the
> pre-670e583 sampler.

---

## Defect

The VNDF-drawn microfacet normal at grazing incidence + roughness 0.3 yields
reflection directions `wi = reflect(wo, wm)` that land below the geometric
hemisphere, and the candidate is discarded (same-hemisphere check) with the
sample falling through to other lobes. `pdf()` still reports continuous
reflection density there → sampled-set/pdf mismatch (the same *class* as the
pkg138 delta-vs-continuous defect, mechanism = coverage hole, not event type).

## ⚠️ Constraint — the furnace-regression trap (measured, PR #517)

A pbrt-faithful "return dead sample" fix (emit the rejected candidate as a
zero/terminate event so the sampled distribution matches the pdf) **regressed
the rough-glass furnace 0.9 → 0.0 and was reverted**. Root-cause that
interaction BEFORE re-attempting any fix: the working hypothesis must explain
why dead-sample semantics zeroed throughput that the current fall-through
routing preserves (suspect: the fall-through re-routes the sample's full weight
to transmission, so "dead" samples deleted energy the lobe-selection weights
assumed was re-routed). Any fix must keep lobe-selection probabilities and
`f/pdf` consistent — do not ship a coverage fix that un-conserves energy.

## Canonical references (cite in code; CLAUDE.md §6)

- **Heitz 2018, "Sampling the GGX Distribution of Visible Normals," JCGT
  vol. 7 no. 4** — VNDF sampling guarantees `wo`-visible microfacet normals but
  NOT that `reflect(wo, wm)` stays in the upper hemisphere; handling of the
  below-horizon reflection set is an explicit implementation decision.
- **pbrt-v4 `DielectricBxDF::Sample_f`** (`src/pbrt/bxdfs.cpp`, Apache-2.0) —
  returns an invalid/zero sample on `SameHemisphere` failure **and** its `PDF()`
  is consistent with that (the pdf integrates over the same accepted set). The
  correct port must keep BOTH sides consistent — the #517 revert shows porting
  only the sampler side breaks energy accounting in our lobe-selection scheme.
- **Cycles `bsdf_microfacet.h`** (BSD-3-Clause — license corrected in pkg124/#501)
  — compare how `bsdf_microfacet_ggx_sample` treats below-horizon reflections
  (clamp/reject + weight bookkeeping) for a production-engine alternative.

## Fix contract

1. Measure first: histogram the rejected-candidate fraction across the chi² grid
   (roughness × incidence) so the fix's coverage claim is quantified, not
   asserted.
2. Make `sample()`'s accepted reflection set and `pdf()`'s reflection density
   describe the **same set** — either dead-sample semantics with pdf-side
   consistency AND corrected lobe-weight bookkeeping (the #517 trap), or
   pdf-side truncation to the accepted set (renormalize per the reference
   chosen). Cite whichever reference form is ported; do not invent a hybrid.
3. Keep diffs disjoint from pkg149's transmission construction so chi²
   contributions stay attributable.

## Gates

- Reflection-candidate acceptance at glass[0.3-45] > 0 (from 0%), with the
  sampled reflection histogram matching `pdf()`'s reflection term (N≥100k).
- **Furnace/rough-glass furnace unchanged** — the 0.9→0.0 trap is the explicit
  regression gate; run it before and after, show both.
- chi² glass[0.3-45]: quantified improvement of the reflection contribution;
  the gate un-xfail itself is owned by pkg149 (joint flip allowed — state which
  PR flips it, verified with `--runxfail`).
- CPU==GPU parity (closure-graph path) on RTX; build evidence per CLAUDE.md.

## Non-goals

- Transmission-lobe sample/pdf re-derivation (pkg149).
- VNDF for the opaque specular reflection lobe (pkg124).
