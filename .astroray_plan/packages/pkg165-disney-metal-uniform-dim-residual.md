# pkg165 — uniform ~5–8% Disney-metal GPU-dim residual at every roughness: localize before fixing (pkg158 Step-0 out-of-scope finding)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (RTX-gated)
**Status:** verify-and-close (2026-08-08) — **the GPU-dim premise DOES NOT REPRODUCE on current main.** The pkg129 metal A/B (research doc `reflection-multiscatter-turquin-research.md` §5, lead HW lane, RTX 5070 Ti + Blender 5.1, Disney metallic=1) measures **GPU ≈ CPU with GPU marginally BRIGHTER (≤~1%), not dimmer**, at every roughness — the opposite sign of this package's "uniform ~5–8% GPU-dim" finding, which was measured on the old SHA `b036ac93`. Likely resolved by pkg170's opaque-Disney 2× gain fix (PR #542) + intervening work. **Disposition:** recommend verify-and-close — a focused confirm on pkg158's exact Step-0 scene at r ∈ {0.0, 0.3, 0.6, 0.9} would fully close it, but it is non-urgent, in-band, and below the Integration Milestone. Spec retained (not deleted) for the finding + disposition record. *(Superseded original status: open — dispatchable, diagnosis-first, NOT urgent-tier — every reading inside the `[0.90, 1.10]` band.)*
**Estimated effort:** S (diagnosis/localization) + S–M only if a material-side defect is convicted
**Depends on:** pkg158 closed (PR #535, Outcome A — reconciliation table is this package's baseline). pkg163 done (PR #533, `b036ac9` — the plain-metal per-λ spectral path; its gate numbers are the cross-datapoint below). Reads: pkg158 Step-0 reconciliation table, `.astroray_plan/docs/pkg141-gpu-metal-near-delta-research.md` (per-event instrumentation pattern).

**Origin:** pkg158 Step 0 (PR #535, 2026-08-02). The reconciliation itself closed as Outcome A (the 0.60–0.77 vs ~1.0 near-delta disagreement resolved; pkg158 is CLOSED and this package must NOT reopen it or pkg152). But the Step-0 sweep surfaced a finding outside pkg158's near-delta scope: a mild **uniform** GPU-dim on the Disney-metal parity scene at **every** roughness, filed here so it has an owner instead of living in a closed package's evidence.

---

## Finding (baseline — cite this, do not re-derive casually)

**Measured (pkg158 Step 0, SHA `b036ac93`, RTX 5070 Ti, linear output):** the
Disney-metal parity scene reads GPU/CPU per-channel mean ratios **0.92–0.98 at
every roughness 0.0 → 0.9** — a uniform ~5–8% GPU-dim, present in the near-delta
regime AND the rough regime alike, channel-ordered **R > G > B** (R dimmest).
The pkg158 Step-0 reconciliation table is the authoritative number set.

Three properties any hypothesis must explain:

1. **Uniform across roughness.** It is NOT compensation-regime-gated: r=0.0
   (where every compensation term is inert) dims the same as r=0.9. This
   already argues against the pkg160/pkg163 compensation seam as the mechanism
   — those defects grew with roughness and vanished near delta.
2. **Channel-ordered R > G > B, but mild.** A consistent chromatic ordering at
   ~5–8% magnitude. Implementer's (unverified) guess: residual
   multiscatter/spectral-upsampling behaviour in `gpu_disney_eval` /
   `gpu_material_*_spectral`. Treat as a hypothesis to test, not a conviction.
3. **Opposite sign on the plain-metal path.** Cross-datapoint from pkg163's
   gates the same night: plain metal (post-pkg163 per-λ `gpu_metal_eval_spectral`
   path) measured uniform **~1.5–2% GPU-BRIGHT** at r=0.9 (ratios ~1.015–1.020,
   achromatic) on pkg163's scene. Different material path (plain-metal closure
   vs Disney metal) AND different scene — the sign flip is confounded on two
   axes, which is exactly what Step 1 below un-confounds.

## Step 1 — localize (blocking; no fix work before this fork is resolved)

All on ONE recorded post-#533/#535 main SHA, linear output, `applyGamma` stated
explicitly for every leg (the gamma-vs-linear artifact is a stable ~1.8–2.4× on
dim scenes and has burned this exact material family before — pkg55 spec
Lessons, 2026-06-11; at 5–8% it is not the prime suspect, but state it anyway).

1. **Un-confound material vs scene.** Render the 2×2: {Disney metal, plain
   metal} × {pkg158 Step-0 scene, pkg163 gate scene}, CPU vs GPU, per-channel
   linear mean ratio. If the dim follows the Disney material across scenes, it
   is material-side → step 2. If it follows the scene, it is transport/scene
   (lighting, env sampling, background) → re-scope accordingly and do NOT touch
   Disney code.
2. **If material-side: per-event instrumentation** (the pkg141 pattern — dump
   `(f, pdf, throughput)` CPU-vs-GPU at a fixed config) at r=0.0 AND r=0.6.
   Because the dim is uniform across roughness, whatever term is convicted must
   be active at r=0.0 too — use that as a consistency check on any conviction
   (a compensation-only suspect fails it).
3. **Check the known seam first, cheaply.** Disney's CPU `evalSpectral` is an
   RGB-upsample fallback (`disney.cpp:689-695`) and pkg163's scope survey
   (2026-07-26) recorded Disney's CPU/GPU twins as CONSISTENT per-RGB at that
   time — if that survey's premise no longer holds on the current SHA (e.g. a
   spectral-path asymmetry introduced since), that is the shortest path to the
   mechanism. Verify, don't assume.

## Outcomes

- **Outcome A — scene/transport-side:** record the localization table, file or
  hand over to the owning transport package; close this package with the table,
  no Disney code change.
- **Outcome B — Disney-material-side defect convicted:** fix with citations
  (CLAUDE.md §6 — the Disney reference implementation and/or Cycles
  `bsdf_microfacet.h` as appropriate). Target on close: GPU/CPU per-channel mean
  ratio within **[0.95, 1.05]** on the pkg158 Step-0 scene at r ∈ {0.0, 0.3,
  0.6, 0.9}; pkg123 promoted rows stay green; furnace/energy suites green
  (linear, upper bound asserted — memory `gamma-furnace-cannot-detect-energy-gain`).

## Non-goals

- **Reopening pkg158 or pkg152.** Both are closed; their reconciliation stands.
  This package cites pkg158's table as a baseline, it does not re-litigate it.
- **Reopening pkg163.** The plain-metal ~1.5–2% bright reading is a
  cross-datapoint for Step 1's 2×2, not a pkg163 defect claim — it passed its
  gates in-band.
- **Any gate-band change without architect sign-off.** The current `[0.90,
  1.10]` band stays until an owner decision on project-wide tightening (open
  item since 2026-07-26); do not tighten it "while here."

## Disposition (2026-08-08) — premise not reproducing; verify-and-close

The pkg129-narrowed live-Cycles metal A/B ran this date on current main (lead HW
lane; verdict recorded in `.astroray_plan/docs/reflection-multiscatter-turquin-research.md`
§5). Disney metallic=1, r ∈ {0.3, 0.6, 0.9} × {chromatic, neutral}, CPU + GPU:
**GPU ≈ CPU, with GPU marginally BRIGHTER (≤~1%)** at every roughness (e.g. r=0.9
neutral CPU 0.936/0.939/0.923 vs GPU 0.946/0.948/0.930). This is the **opposite
sign** of this package's Step-0 finding — the "uniform ~5–8% GPU-dim, R>G>B" does
NOT reproduce on current main. It was measured on the old SHA `b036ac93`; the
most likely resolver is pkg170's opaque-Disney closure-recombination 2× gain fix
(PR #542, which reached the Disney closure path) plus intervening spectral work.

**Recommendation:** verify-and-close. Step 1's 2×2 localization is NOT needed —
the premise it would localize is gone. A single focused confirm on pkg158's exact
Step-0 scene (r ∈ {0.0, 0.3, 0.6, 0.9}, per-channel GPU/CPU linear ratio, `[0.95,
1.05]`) would fully close the package with a clean datapoint, but it is
non-urgent (in-band, no red gate) and sits below the Integration Milestone; run
it opportunistically the next time that scene is on the GPU lane. Do NOT reopen
Step 1's full fork or touch Disney code — there is no convicted defect.

## Provenance

Filed by the architect 2026-08-02 at team-lead request, from the pkg158 Step-0
out-of-scope finding (PR #535) plus pkg163's same-night opposite-sign gate
reading (PR #533). **Disposition update 2026-08-08:** premise not reproducing on
current main per the pkg129 metal A/B (research doc §5) → verify-and-close.
