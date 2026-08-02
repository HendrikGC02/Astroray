# pkg150 — Disney dielectric VNDF reflection candidate: same-hemisphere masking kills 100% of samples at grazing

**Pillar:** 3 (BSDF correctness / sampling coverage)
**Track:** A
**Codex-paste-ready:** no (a sampling-coverage fix with a documented furnace-regression trap — measurement-first, judgment at the gate)
**Status:** closed — resolved-by-pkg149 (2026-08-02, docs/test PR `test(pkg150): correct chi2 xfail attribution`). The charter defect ("100% of VNDF reflection candidates rejected at grazing, reflection never sampled") was measured on the pre-pkg149 azimuth-buggy sampler and was ALREADY fixed on main by the pkg149 sampler landing (#522): on current main, WITHOUT any pkg150 code change, reflection-candidate acceptance at glass[0.3-45] is **5.1%** with sample()/pdf() agreement median rel err **0.0000** (N=300k), and the residual same-hemisphere delta fallback is only **0.16%** of samples. The spec's fix-contract option-1 (pbrt-v4 dead-sample) was implemented, built, and measured — it removes that 0.16% fallback but **regresses the high-roughness furnace** (r=1.0 CPU 0.997→0.788), the #517 trap, and moves chi² only 2.4% because the chi² gate is ~90% an ires=4 quadrature artifact (see closeout below). No code fix ships; the reverted fix is captured at `.astroray_plan/docs/pkg150-deadsample-fix.patch` for the follow-up multi-scatter-compensation spec. **Superseded history (pre-2026-08-02):** open — dispatchable behind pkg151/#519, pkg154/#521, pkg149/#522 (all merged); fix-contract item 1 baselined on the current main sampler.
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

---

## Closeout (2026-08-02) — resolved-by-pkg149; option-1 fix measured and rejected

All measurements on current main `d02fe07` (pkg151/#519 + pkg154/#521 + pkg149/#522
all landed), LINEAR renders (`apply_gamma=False`), in worktree `pkg150`. The
implemented-and-reverted fix (pbrt-v4 `DielectricBxDF::Sample_f` dead-sample:
return `pdf=0` on a below-horizon VNDF reflection candidate instead of the
smooth-mirror-delta fallback, CPU `disney.cpp` + GPU `gpu_materials.h`) is
captured verbatim at `.astroray_plan/docs/pkg150-deadsample-fix.patch`.

### Finding 1 — charter already met on main by pkg149 (measure-first, fix-contract item 1)

The spec premise ("same-hemisphere masking kills 100% of samples at grazing") was
the pre-pkg149 azimuth-buggy sampler. On current main, WITHOUT any pkg150 change,
`debug_bsdf_sample_batch` (glass metallic=0/transmission=1/ior=1.5, N=300k):

| θ | reflection-candidate acceptance | sample/pdf match <10% (median rel err) | delta fallback (rejected-candidate) frac |
|---|---|---|---|
| 0  | 4.0% | 100% (0.0000) | 0.08% |
| 30 | 4.2% | 100% (0.0000) | 0.11% |
| 45 | 5.1% | 100% (0.0000) | 0.16% |
| 60 | 8.9% | 100% (0.0000) | 0.35% |
| 75 | 21.7% | 100% (0.0000) | 1.25% |

Reflection is sampled (was 0% on the buggy sampler → 5.1% at [0.3-45]) and
`sample()`/`pdf()` already describe the same reflection set. The charter defect is
resolved-by-pkg149.

### Finding 2 — option-1 dead-sample fix regresses the high-roughness furnace (#517 trap, still live)

White-furnace (depth 32), CPU / GPU, before → after applying the dead-sample fix:

| roughness | CPU before | CPU after | GPU before | GPU after |
|---|---|---|---|---|
| 0.0 | 1.0000 | 1.0000 | 0.9932 | 0.9932 |
| 0.03 | 1.0000 | 1.0000 | 0.9932 | 0.9932 |
| 0.1 | 0.9986 | 0.9986 | 0.9988 | 0.9987 |
| 0.3 | 0.9987 | 0.9982 | 0.9995 | 0.9991 |
| 0.6 | 0.9985 | 0.9766 | 1.0000 | 0.9999 |
| 1.0 | 0.9970 | **0.7882** | 1.0000 | **0.9180** |

Mechanism: below-horizon dead fraction scales with roughness (0.08%@r0.3-θ0 →
7.1%@r1.0-θ0) and compounds over the 32-bounce integral. The old delta fallback
was energy-load-bearing — ad-hoc compensation for genuinely-missing reflection-lobe
multi-scatter energy. r=1.0 CPU 0.788 fails the `[0.92,1.03]` gate → the fix must
NOT ship naked. This validates the spec's Constraint.

### Finding 3 — the chi² gate is ~90% an ires=4 quadrature artifact; prior root-cause attribution disproven

chi²[0.3-45] 34987.97 (before) → 34141.83 (after removing the delta fallback): only
a **2.4%** move, i.e. the delta fallback was NOT the dominant contributor. Raising
ONLY the harness quadrature `ires` on the identical sampler/config:

| ires | raw chi² | pdf integral |
|---|---|---|
| 4 (test default) | 35107 | 0.967 |
| 8 | 3942 | 0.999 |
| 16 | 3240 | 0.999 |

The coarse `ires=4` trapezoid under-integrates the peaked microfacet lobe near the
equator (same class the full-grid test documents as grid-limited). The true (ires=8)
residual ~3942 splits ~50/50 reflection(1981)/transmission(1961) across all cosθ
bands — a small symmetric effect in BOTH lobes, not a reflection-specific delta
spike. The prior xfail reason (residual "owned SOLELY by pkg150", caused by the
delta fallback) is corrected in `tests/statistical/test_chi2_bsdf.py`.

### Disposition

- Charter closed as resolved-by-pkg149; no code change ships.
- chi² gate stays xfail (still red at ires=4; not closeable by a sampler/coverage
  tweak). xfail reason corrected to document the quadrature dominance and remove
  the pkg150 attribution.
- Real prerequisite for pbrt-faithful masking (dead-sample without furnace
  regression) is reflection-lobe multi-scatter compensation (Kulla-Conty 2017 /
  Turquin 2019) — a separately-citable physics addition (CLAUDE.md §6), routed to
  its own spec by the architect. The reverted dead-sample diff
  (`pkg150-deadsample-fix.patch`) is the drop-in coverage half for that package.
