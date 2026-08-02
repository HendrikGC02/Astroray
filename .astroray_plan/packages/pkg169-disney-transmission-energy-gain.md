# pkg169 — Disney Principled TRANSMISSION lobe CREATES energy in the white furnace (CPU at all roughness incl. delta; GPU rough-only, up to 2.3×)

**Pillar:** 2 (BSDF energy conservation — correctness wins over both fidelity and perf)
**Track:** A (RTX-gated for the GPU leg; CPU leg CI-runnable in linear)
**Status:** in review (PR #540, 2026-08-02) — both convictions fixed CPU+GPU. Conviction A: delta glass dropped the Fresnel common factor R/T (PBRT-v4 §9.5) + rough transmission missing the incident cosine |N·wi| (Heitz-2018 VNDF). Conviction B: GPU closure-graph reflection-pdf used sign(normal·wo) not rec.frontFace for the exit-side Fresnel → internal-reflection pdf up to ~20× too small (fixed both legs). Furnace after fix (ior 1.5): CPU 0.990/0.990/0.993/0.980/0.926/0.902, GPU 0.992/0.992/0.992/0.986/0.970/0.930; ior 1.33 both legs 0.98–0.99. pkg166's 3 xfails removed. One residual cell (CPU ior1.5 R=1.0 ≈0.90, multiscatter) quarantined to pkg167 per architect verdict. GPU opaque-Disney 2× filed as pkg170.
**Estimated effort:** M (two independent convictions + mirrored fix + un-xfail)
**Depends on:** nothing open. pkg166 (linear furnace conversion, in flight) discovered it and quarantines the affected cases as `xfail(strict=False)` citing **pkg169** — this package MUST remove those markers in its fix PR (memory `xfail-gated-features-must-unxfail`; verify with `--runxfail`).

**Origin:** pkg166 implementation (2026-08-02). Converting the furnace suites
to linear rendering (the gamma clamp maps 1.78 → 1.000, the exact
`gamma-furnace-cannot-detect-energy-gain` failure mode) immediately exposed a
real energy gain in the Disney Principled transmission lobe. The old gamma
bands `[0.92, 1.03]` were green throughout.

---

## Baseline measurements (cite these; SHA `cf67a92`, RTX 5070 Ti, linear, albedo=1, ior=1.5, white env, deterministic across 32→512 spp)

Disney Principled, transmission lobe, white-furnace linear ratio (1.0 = conserving):

| roughness | CPU | GPU |
|---|---|---|
| 0 / 0.03 (delta) | **1.784** | 0.993 (conserves) |
| 0.1 | 1.099 | 1.098 |
| ... rising monotonically ... | → | → |
| 1.0 | **1.260** | **2.296** |

Controls (same rig, conserving — the defect is Disney-transmission-specific):
plain dielectric 0.994, opaque Disney 0.958.

Determinism across 32→512 spp = structural weight error, not MC noise
(memory `mc-noise-vs-deterministic`).

## The asymmetry that defines the diagnosis structure (two seams, two convictions)

- **CPU gains at ALL roughness INCLUDING delta (1.784 at R=0).** The delta
  path has no microfacet pdf/Jacobian — the only candidates are the
  delta-transmission weight itself: an eta² radiance-scaling factor applied
  where it shouldn't be, a missing 1/eta² counterpart, or a double-application
  across the sample/eval/upsample chain.
- **GPU delta CONSERVES (0.993) but rough gains up to 2.296.** The GPU delta
  leg is healthy, so the GPU defect lives in the rough-transmission microfacet
  weight — at 2.3× this smells like a pdf/Jacobian factor (the Walter 2007
  transmission Jacobian `|wi·m| eta² / (denominator²)` family), not a Fresnel
  or albedo term.
- These are **plausibly two DIFFERENT bugs on two different code paths** (CPU
  Disney transmission vs GPU closure-graph lowering — memory
  `gpu-dielectric-lowers-to-closure-graph`) that must be convicted SEPARATELY.
  Do not assume one mechanism; do not fix one side by mirroring the other
  until each is convicted against the citation.

**Priors — this is the eta²-family, OPPOSITE direction:** PR #404 (GPU delta
refraction eta² albedo-clamped → energy DEFICIT), PR #423 (CPU eta²
albedo-LUT clamp → deficit; memory `rough-glass-residual-is-multiscatter`),
memory `refraction-frontface-bug`. Every prior member was a LOSS because a
clamp ate a legitimate >1 factor; a GAIN suggests the factor applied twice, or
applied without its reciprocal-direction counterpart. Audit every eta²
application point on both legs as step one of each conviction.

## Diagnosis-first contract (blocking order)

1. **Conviction A — CPU delta-transmission weight.** Instrument the delta
   branch (per-event `(f, pdf, throughput)` dump, pkg141 pattern) on the
   furnace scene at R=0. Trace every eta²/1-over-eta² application from
   `sample()`/`sampleSpectral()` through the spectral upsample (PR #423's
   factor-out-the-magnitude path) to the integrator's radiance-transport
   convention (PBRT-v4 §9.5.2 radiance scaling under refraction — whether
   eta² belongs at all depends on the transport-quantity convention; state
   the repo's convention explicitly in the finding). Convict the exact line.
2. **Conviction B — GPU rough-transmission weight.** Same instrumentation on
   the GPU closure-graph rough-transmission branch at R=0.6/1.0. Compare
   term-by-term against Walter et al. 2007 (EGSR), "Microfacet Models for
   Refraction through Rough Surfaces" — eq. 17 (BTDF) + eq. 38 (half-vector
   Jacobian) — and the CPU twin (which gains only ~1.26×, so the two legs
   differ by an additional ~1.8× factor on GPU; find THAT factor first, it is
   the sharpest lead).
3. **Fix with citations** (CLAUDE.md §6 — invoke `cite-algorithm` before any
   weight-formula change; canonical refs: Walter 2007 for microfacet
   transmission, PBRT-v4 §9.5.2 / pbrt `DielectricBxDF` for refraction
   radiance scaling; PR #404/#423 in-repo history for where eta² handling
   lives). CPU and GPU mirrored; the same-hemisphere/frontFace handling
   re-checked against memory `refraction-frontface-bug` while in there.
4. **Un-xfail:** remove pkg166's `xfail(strict=False)` quarantine markers on
   the affected furnace cases in the fix PR; prove with `--runxfail` that the
   cases genuinely pass.

## Acceptance (all linear, floor+ceiling — pkg166 rules; a gamma gate is not evidence here)

- [ ] Disney transmission white furnace at R ∈ {0, 0.03, 0.1, 0.3, 0.6, 1.0},
      ior 1.5, albedo=1: CPU AND GPU within `[0.92, 1.03]` linear (band
      changes only with architect sign-off).
- [ ] Controls unchanged: plain dielectric and opaque Disney stay conserving
      (regression guard that the fix didn't leak into healthy paths).
- [ ] A second ior point (e.g. 1.33) at delta + one rough value, both legs —
      an eta²-family fix that only works at ior 1.5 is not a conviction.
- [ ] pkg166's quarantine xfails removed and passing under `--runxfail`.
- [ ] Finding doc `.astroray_plan/docs/pkg169-transmission-energy-gain-findings.md`
      with both conviction traces, the repo's radiance-transport convention
      statement, and the citation-to-line mapping.

## Non-goals

- Not the multiscatter/compensation family (pkg167 dielectric reflection,
  pkg129 metal) — this is a single-scatter weight defect, orders louder.
- Not re-touching PR #423's albedo-LUT factor-out (verified shipped) unless
  Conviction A lands exactly there — in which case cite it, don't re-derive.
- No gate-band widening ever; the fix moves the renderer to the band, not the
  band to the renderer.

## Provenance

Filed URGENT by the architect 2026-08-02 at team-lead request, mid-pkg166
implementation, so impl-pkg166 can cite the number in its quarantine xfails.
Discovery is itself the pkg166 thesis validated: a gamma furnace structurally
cannot see energy gain; the first linear run found a shipped lobe creating up
to 2.3× energy.
