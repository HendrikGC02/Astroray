# pkg158 — GPU Disney metal remainder: reconcile the near-delta numbers, then fix or close (pkg152 split-out)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (measurement-reconciliation first; whether any code changes exist depends on Step 0's outcome)
**Status:** open — dispatchable (this is the split-out follow-up pkg152's fired split-clause requires; its Step 0 unblocks the "reconcile before filing" precondition recorded in pkg152's status)
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
