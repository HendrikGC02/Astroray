# pkg180 — systemic ~12–20% Astroray-vs-Cycles dim: is it a comparison-methodology artifact or a real engine energy offset? (diagnosis-first, do NOT fix until localized)

**Pillar:** 3 (GPU/CPU + Cycles parity) / Integration Milestone verification layer
**Track:** A (RTX + headless-Blender/Cycles; render legs serialize on the GPU lane per repo rule)
**Status:** open — dispatchable (DIAGNOSIS-FIRST; no fix work until the offset is localized to a mechanism)
**Estimated effort:** S–M (Phase 1 is a cheap methodology check; a real-engine conviction only then sizes into further work with architect sign-off)
**Depends on:** pkg119-B differential harness landed + HW-validated (PR #550 — the passing-cell ratio cluster is this package's primary evidence), pkg129-narrowed metal A/B (research doc §5, run 2026-08-08 — the metal cross-datapoint), pkg104 reference bank + pkg71 cycles-parity benches (oracle blessing + metrics). Reads: memory `pkg119b-harness-runbook`, `ssim-wrong-gate-for-independent-rng`, `gamma-vs-linear-comparison-artifact`, `mc-noise-vs-deterministic`.

**Origin:** lead cross-harness measurement, 2026-08-08. The pkg119-B differential
harness and the pkg129 metal A/B, run independently on current main, BOTH show
Astroray rendering **systemically dimmer than Cycles at equal settings** on
diffuse/metal scenes. This is filed so the offset has an owner and a
diagnosis-first charter instead of living as scattered "INTENTIONAL-DIVERGENCE"
triage lines across two harnesses.

---

## Finding (baseline — cite this, do not re-derive casually)

Across three independent measurements on current main (RTX 5070 Ti + Blender
5.1, linear ratio statistic):

1. **pkg119-B differential harness:** passing cells cluster at Astroray/Cycles
   ratio **~0.88** (the harness correctly routes this to a parity-band /
   INTENTIONAL-DIVERGENCE signal rather than a per-feature bug — PR #550).
2. **pkg129 metal A/B** (research doc §5, 2026-08-08): neutral-albedo Disney
   metal reads ~1.00 at r=0.3 falling to ~**0.93** at r=0.9 vs Cycles — a mild
   roughness-dependent dim on top of a baseline offset.
3. **Plain solid-diffuse backdrop probe:** ratio **~0.79–0.82** — the largest
   reading, on the simplest possible scene.

The signature: a **UNIFORM, chromatically-uniform energy-scale offset** of
**~12–20%** — NOT a per-feature bug, NOT channel-ordered, NOT
roughness-gated (the roughness term in (2) rides on top of it). A uniform
achromatic scale factor across unrelated materials and scenes is the fingerprint
of a **comparison-methodology or global-exposure** difference far more than an
engine transport defect — which is exactly what Phase 1 checks, cheaply, first.

**Why it matters:** it is directly relevant to pkg178's Principled-BSDF
true-parity goal and the owner's standing parity ambitions. A ~15% global dim
would swamp every per-lobe parity delta pkg178 tries to measure; this offset
must be characterized (and, if real, owned) before "true Cycles parity" is a
measurable claim.

## Phase 1 — is it a comparison-methodology artifact? (blocking; cheapest check first)

A uniform achromatic scale is most likely NOT in the engine. Rule the
methodology out before touching any transport code. All on ONE recorded main
SHA, every leg's `apply_gamma` / color-management state stated explicitly.

1. **View transform / color management.** Cycles applies a view transform
   (Filmic / AgX in Blender 5.x) and display color management by default;
   Astroray outputs linear. If the harness compares Cycles' **view-transformed**
   output against Astroray's **linear** output, a systemic offset is guaranteed
   and is an artifact, not a defect. Confirm each harness reads Cycles in the
   **same** transform space as Astroray (Standard/Raw view transform, or both
   compared in scene-linear before any display transform). This is the prime
   suspect — the gamma-vs-linear comparison artifact has burned this project
   before (memory `gamma-vs-linear-comparison-artifact`,
   `mc-noise-vs-deterministic`).
2. **Exposure / film settings.** Check Cycles `Film > Exposure`, the scene
   `View Layer` exposure, and any tonemap the harness applies to one leg but not
   the other. A stray exposure≠0 or an implicit filmic curve reproduces a
   uniform scale exactly.
3. **Sample/normalization convention.** Confirm both engines normalize
   accumulated radiance identically (per-sample average vs sum), and that the
   background/world contribution is present and identical in both legs (a missing
   or half-strength world uniformly dims the whole frame — cf. pkg119-B's
   `world:World` SSIM 0.62 finding).

**Phase 1 exit:** if the offset collapses into band once the comparison is put
in a common linear space with matched exposure/world → it is a
**methodology artifact**. Record the corrected comparison protocol (feed it back
to the pkg119-B harness and pkg129 A/B so their ratio bands are honest), close
this package with no engine change, and note whatever residual remains for
pkg178's baseline.

## Phase 2 — only if a REAL engine offset survives Phase 1

If the offset persists with the comparison provably in a common linear space,
matched exposure, and matched world — THEN it is an engine energy difference.
Localize before proposing any fix:

1. Bisect by scene minimalism: single diffuse surface + single known-radiance
   light, no world, delta-ish — compute the expected radiance analytically and
   see which engine is off the analytic truth (Cycles is the oracle for
   *parity*, but an analytic scene tells you WHICH engine is wrong).
2. Decompose direct vs indirect: does the dim appear at max_depth=1 (a
   direct-lighting / light-normalization / solid-angle factor) or only with
   bounces (an indirect-throughput / russian-roulette / clamp difference)?
3. Report the localized mechanism to the architect. **Do NOT ship a global
   brightness multiply** — a uniform fudge factor is a CLAUDE.md §6 violation and
   would mask whatever the real cause is. A fix, if any, sizes into its own spec
   with architect sign-off.

## Acceptance criteria

- [ ] **Phase 1 verdict recorded:** the comparison protocol audited leg-by-leg
      (view transform, exposure, normalization, world), with a same-linear-space
      re-measurement of the ~0.88 / ~0.93 / ~0.79–0.82 readings. Verdict:
      artifact (→ close with corrected protocol) or real (→ Phase 2).
- [ ] If artifact: the corrected comparison protocol is documented and the
      pkg119-B harness + pkg129 A/B ratio bands are updated/annotated to reflect
      it (so future runs don't re-file this).
- [ ] If real: a localization table (which engine, direct vs indirect, analytic
      vs oracle) and an architect hand-off — NOT a fix in this package.
- [ ] Research note
      `.astroray_plan/docs/pkg180-systemic-cycles-dim-diagnosis.md` with the
      measurements, the Phase-1 methodology audit, and the disposition.

## Non-goals

- **No fix until localized.** This is diagnosis-first; a uniform brightness
  multiply is explicitly forbidden (CLAUDE.md §6).
- **Not a per-feature parity bug.** The pkg119-B TRANSLATION-BUG cells
  (`BSDF_TRANSPARENT`, `world:World`) are their own follow-ups; this package
  owns the UNIFORM offset underneath them, not the per-feature divergences.
- **Not reopening pkg129, pkg163, or pkg165.** Their metal-specific readings are
  cross-datapoints for the uniform offset, not defect claims here.
- **No parity-band change without architect sign-off.** The `[0.90,1.10]`
  history stays; this package explains the offset, it does not widen the band to
  hide it.

## Provenance

Filed by the architect 2026-08-08 at lead request, from the cross-harness
measurement this run: pkg119-B passing cells ~0.88, pkg129 metal neutral r0.9
~0.93, plain solid-diffuse backdrop ~0.79–0.82 — a uniform chromatically-uniform
~12–20% Astroray-vs-Cycles dim. Diagnosis-first; prime suspect is a Cycles
view-transform-vs-Astroray-linear comparison artifact (check cheaply, first)
rather than an engine energy bug. Directly relevant to pkg178's true-parity goal.
