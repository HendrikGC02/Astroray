# pkg179 — Disney dielectric dead-sample fix, Part 2: diagnose the 3× dead-sample rate, then redistribute the masked energy into the TRANSMISSION lobe

**Pillar:** 2 (materials / BSDF energy correctness)
**Track:** A (CPU furnace gates on CI; GPU twin RTX-verified)
**Status:** open — dispatchable (Phase 1 diagnosis-first; Phase 2 gated on Phase 1's finding)
**Estimated effort:** M–L (Phase 1 is S diagnosis; Phase 2 is the hard part — a transmission-lobe redistribution mechanism or a combined-closure treatment, CPU+GPU, holding the furnace at all roughnesses WITH the dead-sample fix in)
**Depends on:** pkg167 Part 1 landed (PR #562, `b4f8376` era — Disney dielectric reflection-lobe multiscatter compensation CPU+GPU, furnace in-band 0.99/0.94/0.93 at r=0.3/0.6/1.0, pkg169 xfail retired). The pkg151→pkg154→pkg149 sampler chain is on main. **Composes with:** pkg149 (VNDF sampler — Phase 1 audits its below-horizon reflection accounting), pkg118 (`ggxGlassCompensationFactor`, rough-dielectric transmission multiscatter — the existing transmission-side term this package extends), pkg178 (native Principled port — see Relationship note; the combined-closure question this package answers directly informs Stage 1/3 there).

**Origin:** pkg167 Part 2 escalation (lead, 2026-08-08). pkg167 shipped Part 1
(reflection-lobe compensation) but **Part 2 — the pkg150 pbrt-v4 dead-sample
fix (below-horizon VNDF reflection → `pdf=0`, delete the smooth-mirror delta
fallback) — was applied, measured, REVERTED, and its guiding premise
FALSIFIED.** The bundled two-commit plan of pkg167 assumed reflection-lobe
compensation would let the dead-sample fix ship without furnace regression. It
does not. This package owns what the measurement proved is actually required.

---

## The falsified premise (cite this; full detail in memory `dielectric-dead-sample-needs-transmission-redistribution` and PR #562's body)

Measured 2026-08-08 (lead HW lane) with pkg167 Part 1's reflection compensation
IN and the dead-sample fix re-applied on top:

- **Reflection compensation cannot rescue the dead-sample fix.** With the delta
  fallback removed, reflection-lobe compensation recovers only **+0.009** at
  r=1.0 (furnace **0.476 → 0.485**, still ❌ vs the 0.92 floor). A dielectric's
  `Fss ≈ 0.09` makes the Kulla-Conty compensation factor **≈1.05** —
  near-identity — so a reflection-lobe multiply has almost no energy to give.
- **The masked energy belongs in the TRANSMISSION lobe.** For a low-Fresnel
  dielectric the ~23% below-horizon reflection energy physically re-enters the
  surface and mostly transmits. **Cycles redistributes it for free inside ONE
  combined closure**; Astroray's SPLIT reflection/transmission lobes + pbrt-v4
  dead-sample termination structurally cannot recover it via a reflection-lobe
  multiply. The fix needs a transmission-lobe energy-redistribution mechanism
  (or Cycles' combined-closure treatment), not more reflection compensation.
- **Red flag — the dead-sample rate is ~3× the documented figure.** Measured
  below-horizon dead fraction is **22.9% at r=1.0** vs pkg150's documented
  **7.1%** (spec table `pkg150`, Finding 2). That 3× discrepancy is unexplained
  and may be a residual VNDF sampler bug introduced or exposed since pkg150's
  measurement — NOT physics. Diagnose it FIRST; the excess dead samples might
  be the whole story, and no redistribution term should be built on top of a
  broken sampler.

## Phase 1 — diagnose the 3× dead-sample-rate discrepancy (blocking; no Phase-2 work before it resolves)

All on ONE recorded post-#562 main SHA, LINEAR (`apply_gamma=False`), the exact
config pkg150 used (`debug_bsdf_sample_batch`, glass metallic=0 / transmission=1
/ ior=1.5, N≥300k).

1. **Reproduce and localize the rate.** Re-run pkg150's dead-fraction histogram
   across the roughness × incidence grid on current main. Confirm 22.9% @
   r=1.0-θ0 vs pkg150's 7.1%; establish whether the gap is uniform or
   corner-specific.
2. **Bisect the cause.** Candidates, in order of cheapness: (a) a sampler
   regression between pkg150's SHA (`d02fe07`) and current main — `git log` the
   VNDF path (`sampleGgxVNDF`, the reflect/refract branch) and A/B the
   dead-fraction across that range; (b) a measurement-methodology difference
   (spp, seed, which candidate counts as "dead") between pkg150's harness and
   the pkg167 measurement; (c) a genuine VNDF azimuth/hemisphere-orientation
   bug in the below-horizon accounting (the pkg149 class of defect — Lerp arg
   order, oriented-normal vs geometric-normal for the enter/exit side; memory
   `photon-caustic-exit-refraction-oriented-normal`).
3. **Fork on the finding.** If a sampler bug is convicted → fix it (cite the
   reference form, CLAUDE.md §6), re-measure the dead-fraction, and re-test
   whether the dead-sample fix + pkg167 compensation now holds the furnace on
   its own. If it does, Phase 2 may not be needed — CLOSE with the diagnosis.
   If the rate is legitimate physics (~23% really is below-horizon at r=1.0),
   proceed to Phase 2.

## Phase 2 — transmission-lobe energy redistribution (only if Phase 1 shows the dead-sample rate is real)

The below-horizon reflection energy that the dead-sample fix correctly refuses
to emit as a spurious smooth-mirror delta must be re-routed to where it
physically goes: the transmission lobe. Two candidate constructions — pick one
with citations, do not invent a hybrid:

- **Combined-closure redistribution (Cycles' approach).** Treat the dielectric
  reflection+transmission as one closure whose lobe-selection and throughput
  bookkeeping conserve the below-horizon energy into transmission, matching how
  Cycles' `bsdf_microfacet` dielectric handles the shared microfacet. This is
  the structurally-correct answer and directly informs pkg178's port; it may be
  larger than a term.
- **Transmission-lobe multiscatter extension.** Extend the existing
  `ggxGlassCompensationFactor` (pkg118, from `fresnelDielectricFss(etap)`) so
  the transmission lobe absorbs the reflected-below-horizon energy budget the
  dead-sample fix releases. Document precisely how this composes with pkg167's
  reflection-lobe term so the two never double-compensate and never
  double-count the same photons.

**Cite — no inventions (CLAUDE.md §6; invoke `cite-algorithm` before coding):**

- **Cycles `bsdf_microfacet.h`** (BSD-3-Clause) — the combined dielectric
  closure's below-horizon / total-internal-reflection energy bookkeeping. This
  is the production cross-check and the "one combined closure" the escalation
  names.
- **pbrt-v4 `DielectricBxDF`** (`src/pbrt/bxdfs.cpp`, Apache-2.0) — the
  dead-sample `pdf=0` semantics being ported (the coverage half, preserved at
  `.astroray_plan/docs/pkg150-deadsample-fix.patch`), and how pbrt keeps
  reflection/transmission lobe selection energy-consistent under that
  termination.
- **Heitz 2018 VNDF** (JCGT 7:4) + **Kulla & Conty 2017** / **Turquin 2019**
  for the multiscatter-compensation family already in-repo
  (`energy_compensation.h`), if Phase 2 takes the transmission-extension route.
- **In-repo composition partners:** pkg118's `ggxGlassCompensationFactor`
  (`disney.cpp`) and pkg167's new reflection-lobe term — the research note MUST
  state the composition rule across all three.

**CPU/GPU mirrored in the same package.** The term/closure lands in `disney.cpp`
eval/sampleSpectral AND its exact GPU twin in the closure-graph path
(`gpu_materials.h` / wavefront shade), the pkg160→pkg163 discipline. A CPU-only
land repeats the four-week divergence; do not split.

## Acceptance criteria

- [ ] **Phase 1 diagnosis recorded** with the dead-fraction grid on current
      main, the bisect verdict (sampler bug / methodology / real physics), and
      — if a sampler bug — the fix with its reference citation, re-measured
      dead-fraction, and un-`--runxfail`-proven gates.
- [ ] **The dead-sample fix ships** (delta fallback removed, below-horizon VNDF
      reflection returns `pdf=0` per pbrt-v4) — this is the binding deliverable
      that pkg150/pkg167 could not land.
- [ ] **White furnace in-band at ALL of r ∈ {0.3, 0.6, 1.0}, CPU AND GPU, in
      LINEAR with floor+ceiling** (pkg166 rules: `apply_gamma=False` explicit,
      upper bound asserted — a gamma furnace cannot see this failure mode), WITH
      the dead-sample fix IN. Target band `[0.92, 1.03]` unless the architect
      signs off otherwise. This is the pass/fail pkg167 Part 2 failed at 0.485.
- [ ] The pkg167-inherited quarantine cell (CPU Disney transmission furnace,
      ior 1.5, R=1.0) returns to the standard band and any residual xfail marker
      is removed, proven under `--runxfail` (memory `xfail-gated-features-must-unxfail`).
- [ ] CPU and GPU are the same construction (spectral handling per pkg163's
      class rule); a plain GPU/CPU parity check on a rough dielectric sphere
      stays in the standard band.
- [ ] **chi² caveat encoded:** do NOT pin any gate on a raw `ires=4` chi²
      number — that reading is ~90% a quadrature artifact (pkg150 Finding 3).
      Re-run at higher `ires` before citing or gating any chi² result.
- [ ] Research note
      `.astroray_plan/docs/pkg179-dielectric-transmission-redistribution-research.md`
      with the citations above, the Phase-1 verdict, the combined-closure
      vs transmission-extension decision, and the three-way composition rule
      (reflection pkg167 / transmission-multiscatter pkg118 / this
      redistribution).

## Relationship note — pkg178 (native Principled port)

The "one combined closure vs split lobes" question this package answers is the
same structural fork pkg178 confronts: Cycles' Principled dielectric is a
combined closure by construction. If Phase 2 lands a combined-closure
redistribution for the Disney dielectric, record the design in the research note
so pkg178 Stage 1/3 can adopt (not re-derive) it — but do NOT expand this
package into the full Principled port. This is the Disney dielectric only.

## Non-goals

- Not the reflection lobe (pkg167 Part 1 shipped that; do not re-tune it —
  extend/compose with it).
- Not the metal lobes (pkg60/pkg160/pkg163 shipped; pkg129 owns unification).
- Not reopening pkg150/pkg149/pkg151/pkg154 as charters — this package consumes
  their sampler and the preserved dead-sample patch.
- No gate-band changes without architect sign-off; no LUT regeneration from
  scratch — borrow license-clean tables (CLAUDE.md §6).

## Provenance

Filed by the architect 2026-08-08 at lead request, from pkg167 Part 2's
escalation (PR #562): reflection-lobe compensation recovers only +0.009 at
r=1.0 (furnace 0.476→0.485), the masked ~23% below-horizon energy belongs in
transmission, and the measured dead-sample rate is ~3× pkg150's documented
figure (possible sampler bug). Fourth+ member of the dielectric energy-accounting
chain: pkg150 (coverage STOP) → pkg149 (sampler) → pkg167 (reflection comp) →
**pkg179 (sampler diagnosis + transmission redistribution)**.
