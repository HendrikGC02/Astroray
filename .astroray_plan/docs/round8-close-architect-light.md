# Round 8 Close — Architect Light Pass

**Date:** 2026-05-14
**Mode:** Light pass (every-round `/close-round` trigger). Not a full
strategy review. One focus question, accept "no changes needed" as a
complete answer.
**Branch:** `docs/round8-close-architect-light`
**Inputs read:**
- `.astroray_plan/docs/STATUS.md` (head; lines 1-200) — Round 8 mid-cycle snapshot
- `.astroray_plan/docs/NEXT_STAGE_REPORT.md` (full)
- `test_results/session_close_2026-05-14b/REPORT.md`
- Spot-checked diagnostic PNGs at `test_results/session_close_2026-05-14b/`:
  caustics (glass + prism), contact sheet (material_contact_sheet,
  disney_glass_r35, subsurface), convergence (cornell 128/1024 spp +
  strip), AOV (beauty, normal)

Note: STATUS.md / NEXT_STAGE_REPORT.md are being rewritten by docs-updater
in PR-flight on branch `docs/round8-mid-cycle-sync-2026-05-14b`. The
state above is the pre-update version; if docs-updater's PR has merged
before this is reviewed, prefer the updated version for queue ordering —
nothing in §1 below should contradict it materially.

---

## §1 — Round 8 outcome

Round 8's planned implementation scope was four medium tracks (pkg55-B
Phase B' restart, pkg43, pkg44, pkg85 follow-up) plus three doc/spec
items (pkg86 Light Tree, pkg87 Cryptomatte, and the three carries pkg82
/ pkg83 / pkg84). The actual landed work was **doc/spec/research-heavy**:
strategy pass, pkg55 Phase B' amendment (8 decisions), pkg86/87 specs,
pkg88/89 research + DRAFT specs, pkg85 partial fix (PR #268), pkg85-B/-C
audit completion, pkg85-D HDRI parity filing, pkg88/89 promotion, pkg38
light-source-spectra amendment, pkg64-gpu follow-up spec, issue #276
chronic clearcoat flake filed, and pkg55-B Phase B' Session 2a foundation
(out of a planned 6+ sessions). pkg43, pkg44, and pkg85-B full audit did
not land in Round 8. The session-close verifier reports **910/911 tests
pass** with all gates cleared (build, GPU rendering, wavefront parity,
viewport, AOV).

Honest framing: the round delivered the **architectural runway** Round 9
needs (Phase B' restart spec authoritative, pkg86 unblocked-pending-pkg89,
Cryptomatte spec ready to pick up, motion blur + dedicated lights specs
DRAFT, CUDA stability audit closed via pkg85-A/-B/-C). It did not deliver
the **emission-model breadth** Round 8 planned (pkg43/pkg44 slipped). The
"CPU-first" decision on pkg55-B looks defensible on the limited Session 2a
evidence — the worst-case for that decision was that re-establishing the
CPU reference would feel wasteful relative to debugging Phase B in place,
and Session 2a's foundation work didn't surface that signal. The added
in-round scope (pkg88/89, pkg85-D, #276, pkg38 amendment) was real
finding-driven follow-up rather than scope creep, but it did dilute the
implementation wave — three implementer-shaped packages (pkg43, pkg44,
pkg85-B audit) slipped largely because architect/doc-updater cycles
absorbed the bandwidth that would otherwise have gone to dispatching them.

## §2 — Visual-quality assessment

Spot-check across the diagnostic renders:

- **AOV passes (`aov/beauty.png`, `aov/normal.png`)** — clean. Beauty
  shows three colored balls (green/mauve/blue) on a light blue
  background with expected per-pixel noise floor and correct shading;
  normal pass has the canonical RGB encoding without artifacts.
- **Caustics (`caustics/glass_caustic_caustic_path_tracer.png`,
  `prism_to_screen_caustic_path_tracer.png`)** — glass caustic shows
  correct hotspot pattern, no fireflies. Prism is a near-black silhouette
  by design (no rainbow without the multiwavelength integrator); the
  verifier note already calls this out, so this is expected, not a
  regression.
- **Material contact sheet (`contact_sheet/material_contact_sheet.png`)**
  — **mild concern**. Subsurface, emissive, blackbody, line emitters,
  metal_smooth, and disney_metal look right. But `lambertian`, `ruby`,
  `emerald`, `glass_flat`, `glass_bk7`, `mirror`, `thin_glass_clear`,
  `disney_plastic`, and several Disney glass variants all read as
  near-black. That can be correct (no lighting environment, dark
  spheres), but the sheet is the primary "is the engine producing
  recognizable materials" reference and at a glance the answer is
  "many materials are indistinguishable from black." Worth confirming
  this is the intended lighting setup, not a silent regression in
  envmap/sky contribution.
- **Convergence (`convergence/cornell_1024spp.png`,
  `convergence_strip.png`)** — Cornell at 1024 spp denoises cleanly
  (PSNR 23.52 dB at 64 spp per the verifier report, slope on the
  MC curve looks right), but the **overall scene exposure reads
  underlit** — the sphere is nearly black, red/green walls are dim.
  Compare with a canonical Cornell box reference: ours looks roughly
  1-2 stops dark. Could be a deliberate tonemap choice, could be
  silent regression in light contribution since the harness was last
  baselined. Either way, "production-quality system" is not the
  word I'd use looking at this image cold.

Overall: numerics are healthy (gates green, parity bit-identical, tests
pass), but **two of the headline diagnostic renders read as visually
underexposed**. This is the kind of drift that a quantitative pipeline
won't catch (SSIM-vs-self is fine, PSNR-floor-delta is fine) but a
qualitative review notices immediately.

## §3 — Focus question for Round 9

> **Round 9 priority — finish what Round 8 started, or close the
> visual-quality gap surfaced by §2?**
>
> Option-shaped framing (not multiple choice — answer in your own
> words): Round 8 left pkg43 / pkg44 / pkg85-B / pkg55-B' Sessions 2-N
> in-flight or unstarted, and the natural Round 9 default is "land
> those, plus pkg86/87/89 Phase A." But §2 suggests the diagnostic
> renders may have drifted to underexposed-by-default, and if the
> Cornell baseline is genuinely dim relative to a canonical reference,
> that's a fidelity claim the project makes on every PR's session-close
> verifier output. Should Round 9 add a "diagnostic-render visual
> baseline" track (probably a small package — recalibrate Cornell
> exposure target, regenerate contact-sheet lighting if needed, add
> a per-render visual-diff gate against a pinned reference) before
> committing all bandwidth to the inherited backlog?

## §4 — Architectural concerns

Two flags worth surfacing, both small:

1. **Doc-cycle absorption of implementation bandwidth.** Round 8 added 6+
   architect/doc passes during the round itself. Each is individually
   load-bearing (pkg85-B/-C/-D, pkg88, pkg89, pkg38 amendment, #276,
   pkg64-gpu follow-up), but in aggregate they explain why pkg43/pkg44
   slipped. If Round 9 wants to land emission-model breadth, the dispatch
   loop should treat "spec promotion" as competing with implementer
   dispatch rather than a free side action. Not a blocker — just worth
   naming.

2. **Visual-quality silent-drift risk.** The §2 observation about the
   contact sheet and Cornell underexposure isn't proven to be a
   regression — it could be the intended baseline. But the project has
   no qualitative visual-diff gate; every test we run is either
   self-similarity (SSIM vs prior Astroray output) or numerics (PSNR,
   MSE, parity counts). If the engine ever silently drifts on
   tonemap/exposure/envmap contribution, our gates won't catch it. This
   may want a tiny "visual sanity" gate against an external reference
   render (Cycles, or a frozen Astroray reference at a known-good
   commit), at least for the convergence and contact-sheet harnesses.

Otherwise: no architectural concerns from this pass. The Phase B'
restart spec and pkg86/87/89 spec wave have set up Round 9 with a
genuinely clear pickup queue, and the CUDA stability work (pkg85
through pkg85-D) has closed the test-harness instability that was
draining cycles in Rounds 6-7.
