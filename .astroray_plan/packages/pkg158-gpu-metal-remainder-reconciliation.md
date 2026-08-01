# pkg158 — GPU Disney metal remainder: reconcile the near-delta numbers, then fix or close (pkg152 split-out)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (measurement-reconciliation first; whether any code changes exist depends on Step 0's outcome)
**Status:** done (PR #TBD, 2026-08-02 — Outcome A: near-delta discrepancy reconciled & superseded. Re-measured on one build b036ac93 [post-#518/#523/pkg160/pkg163]: near-delta Disney-metal GPU/CPU = 0.924–0.949 linear / 0.960–0.971 gamma, no near-delta cliff, all rows within the [0.90,1.10] close band. The 0.60–0.77 research-doc record is SUPERSEDED (does not reproduce); the #523 verifier's ~1.0 reading is confirmed within band. A mild uniform ~5–8% GPU-dim persists across ALL roughness (0.92–0.98, channel-ordered R>G>B) — within band, NOT near-delta-specific, flagged for architect. No code. See Step 0 results below.)
**Estimated effort:** S (Step 0) + S–M only if a real residual survives
**Depends on:** pkg152/PR #523 merged (done). Reads: `.astroray_plan/docs/pkg141-gpu-metal-near-delta-research.md` (the 0.60–0.77 record), the #523 verifier evidence (~1.0 near-delta), pkg55 spec adjudication note (2026-07-25).

**Origin:** pkg152 closeout (2026-07-25). Two credible measurements of the near-delta Disney-metal GPU/CPU ratio disagree: the pkg141/#518 research-doc record (0.60–0.77, R<G<B, floor+sun scene family) vs the #523 verifier's post-merge reading (~1.0). Until reconciled, the project does not know whether a metal-dimness defect still exists — neither number is citable.

---

## Scope fence (2026-07-26) — this package is DISNEY metal (`gpu_disney_eval`) ONLY

A separate, larger, plain-`metal` defect was convicted 2026-07-26 and filed as
**pkg160** (`gpu_metal_eval` omits the CPU MetalPlugin multiscatter term; ~3.5×
mean / ~7× median GPU-dim, scene-controlled). That is a DIFFERENT GPU function
and a DIFFERENT CPU plugin — do NOT absorb it into this reconciliation or its
0.279 number will corrupt the Disney near-delta reconcile below. **Co-verify
efficiency:** run pkg160's plain-metal dump and this package's Disney-metal dump
in the SAME GPU-lock session with the shared pkg141/pkg152 per-event harness;
cross-referenced, neither absorbs the other.

## Post-pkg160 re-baseline (2026-07-26, architect — read before dispatching Step 0)

pkg160's fix is merged (owner-approved, with a documented r=0.9 band exception
now owned by **pkg163**). Two consequences for this package, one verdict:

1. **Every plain-metal comparator in this package's evidence base is STALE.**
   pkg160 moved plain-metal output by 0.46–0.67×, and the metal-vs-Disney MSE
   this package's origin-era evidence leaned on dropped **7×** (0.02474 →
   0.00353). Any Step-0 leg that used plain metal as a reference or "bright
   side" is void — Step 0 MUST run on a post-pkg160 main build (record the SHA)
   and use CPU as the only oracle, never plain-metal-vs-Disney cross-material
   comparisons.
2. **The core reconciliation question is UNAFFECTED by pkg160.** pkg160 changed
   only the ROUGH branch (roughness > 0.1) of `gpu_metal_eval`; the near-delta
   (≤ 0.1) mirror shortcut is byte-unchanged, and `gpu_disney_eval` was not
   touched. The 0.60–0.77 (pkg141 research doc) vs ~1.0 (#523 verifier)
   near-delta Disney disagreement stands exactly as filed.

**Verdict (architect): NARROWED, not closed.** The disagreement between two
credible Disney near-delta measurements is still unresolved and neither number
is citable until Step 0 reconciles them on one build — that rule survives. But
the prior has tipped further toward **Outcome A** (fixed by #523): the verifier
reproduced ~1.0 twice, and the 7× MSE collapse shows the cross-material "metal
anomaly" framing was substantially pkg160's defect wearing this package's
clothes. Expect Step 0 to close this package with a supersession table; budget
S, not S–M.

## Step 0 — reconcile (blocking, do first)

Re-measure BOTH setups on the SAME post-#523 main build, same session:

1. The pkg141 research-doc scene exactly (disney metal sphere + floor + sun family, its documented resolution/spp/seed), and
2. the #523 verifier's scene/config exactly,

each CPU vs GPU, per-channel mean ratio, with **`applyGamma` stated explicitly for both legs** — the gamma-vs-linear artifact (pkg55 spec Lessons, 2026-06-11: a stable ~1.8–2.4× on dim scenes; partially overlapping ratio bands are exactly how it hides) is a prime suspect for the discrepancy, alongside: the #523 clearcoat double-divide fix reaching further than scoped, the widened eta² spectral guard, or a genuine fix by the mirrored compensation tables.

**Outcome A — both read ~1.0:** the metal remainder is FIXED by #523. Close this package with the reconciliation table; update the pkg141 research doc and pkg152 with a supersession note; done, no code.

**Outcome B — a real residual survives in either setup:** the reconciliation table becomes the defect record; proceed to conviction with the pkg141 per-event instrumentation pattern (dump `(f, pdf, throughput)` CPU-vs-GPU at the residual's config) and fix with citations. Target band on close: GPU/CPU within [0.90, 1.10] at the failing configs, pkg123 promoted rows stay green, furnace/energy suites green.

## Non-goals

- Re-opening the #522 rough-transmission furnace work (verified 0.9987–1.0000 on-stack; separate lobe).
- pkg129's reflection-LUT scope (hand over if convicted, per pkg152's rule).
- Any gate-band changes without architect sign-off.

## Provenance

Filed by the architect during the PR #524 adjudication (2026-07-25) to give the pkg152 near-delta anomaly a concrete owner (pkg55 spec adjudication, "pkg152 near-delta anomaly" paragraph).

---

## Step 0 results — reconciliation measurement (2026-08-02)

**Build:** worktree at SHA `b036ac93029b147ad94957a8dfa52fe3ebc2601c` (current main
at dispatch = post-pkg141/#518, post-pkg152/#523, post-pkg160, **post-pkg163**),
clean CUDA Release build via `build_cuda_worktree.bat`. RTX 5070 Ti, driver as
installed, CUDA 12.8. GPU lock held for the full render batch, released before
this write-up.

**Scene:** `tests/test_pkg123_disney_metal_gpu_cpu_parity.py` unchanged — this
file **is** the pkg141 research-doc scene family (Disney `metallic=1.0` sphere,
baseColor `[0.9,0.6,0.4]`, lambertian floor + area light, 48×48, 128 spp,
max_depth 4, seed 90123), and it is also the exact scene/config the #523
verifier's "Claim 2" measured. **The two "credible measurements" the origin
cites were of the SAME test/scene** — so the reconciliation collapses to
re-running this one scene on one build, CPU vs GPU, per-channel mean ratio.

### Both legs on one SHA (b036ac93), CPU vs GPU per-channel mean ratio

| leg / setup | roughness | applyGamma | R | G | B |
|---|---|---|---|---|---|
| pkg141 scene = #523 scene | 0.00 | False (linear) | 0.9493 | 0.9278 | 0.9240 |
| pkg141 scene = #523 scene | 0.03 | False (linear) | 0.9493 | 0.9278 | 0.9240 |
| pkg141 scene = #523 scene | 0.05 | False (linear) | 0.9493 | 0.9278 | 0.9240 |
| pkg141 scene = #523 scene | 0.10 | False (linear) | 0.9467 | 0.9304 | 0.9234 |
| pkg141 scene = #523 scene | 0.30 | False (linear) | 0.9589 | 0.9566 | 0.9452 |
| pkg141 scene = #523 scene | 0.60 | False (linear) | 0.9743 | 0.9644 | 0.9517 |
| pkg141 scene = #523 scene | 0.90 | False (linear) | 0.9792 | 0.9638 | 0.9472 |
| gamma spot-check          | 0.00 | True (gamma)   | 0.9708 | 0.9612 | 0.9597 |
| gamma spot-check          | 0.90 | True (gamma)   | 0.9900 | 0.9813 | 0.9757 |

Near-delta rows 0.00/0.03/0.05 are byte-identical (shared `alpha` floor
`max(roughness²,0.0064)` → identical renders), so the ~5–8% dim is structural,
not MC noise.

### Historical numbers, reconciled

| record | SHA | applyGamma | near-delta (R/G/B) | status |
|---|---|---|---|---|
| pkg141/#518 research doc, carried into pkg152 Symptom-(a) table | post-#518 | linear | 0.6034 / 0.6892 / 0.7565 | **SUPERSEDED** — does not reproduce on any current build |
| #523 verifier "Claim 2" | 6dc83d4 | linear | 1.0112 / 0.9969 / 0.9969 | **confirmed** (within band; my b036ac93 reads 0.92–0.95, same regime) |
| this Step 0 | b036ac93 | linear | 0.9493 / 0.9278 / 0.9240 | current, within [0.90,1.10] |

**Why the two disagreed:** the pkg152 research doc's Symptom-(a) near-delta row
was NOT re-measured on the #523 build — it was carried forward from the pkg141
post-#518 measurement under the (theoretically sound at the alpha floor, where
`E→1`) assumption that pkg152's compensation mirror had "zero effect" on
near-delta, and labelled "(unchanged)". The #523 verifier independently *ran*
the test on 6dc83d4 and measured ~1.0. On the same commit both cannot hold; the
verifier's fresh measurement is the trustworthy one. The 0.60–0.77 figure was a
genuine **earlier code-state** number (pkg141 post-#518), moved to ~1.0 by the
fixes that landed between #518 and #523, and is superseded — it is not a
gamma artifact (gamma raises the ratio *toward* 1.0, as the spot-check shows, so
it can never explain a number *below* the linear reading).

**Gamma verdict:** ruled out as the source of the historical disagreement — both
credible records used the linear test path. Gamma does inflate the ratio toward
1.0 (dim-scene compression), exactly the known artifact, but both legs here were
measured with matched `applyGamma`, so the residual is a genuine CPU-vs-GPU
structural difference.

### Verdict: **Outcome A** — reconciled, superseded, no near-delta defect, no code

The 0.60–0.77 vs ~1.0 disagreement is resolved: 0.60–0.77 is superseded, ~1.0 is
confirmed within band, and current main reads a uniform 0.92–0.98 across the full
roughness sweep with **no near-delta cliff** — the near-delta over-/under-
brightness this package was chartered to reconcile no longer exists. All rows are
inside the spec's own close band `[0.90, 1.10]`.

**Residual flagged for architect (not a reopener):** a mild *uniform* ~5–8%
GPU-dim persists at every roughness (linear 0.924–0.979, channel-ordered R>G>B,
B dimmest). It is within band and is NOT near-delta-specific, so it is out of
scope for this reconciliation. If the project later wants GPU/CPU metal parity
tighter than ~5%, that is a fresh, uniform-dim investigation (likely residual
multiscatter/spectral-upsampling differences in `gpu_disney_eval` /
`gpu_material_*_spectral`, pkg163 territory), not a resurrection of the
near-delta defect.
