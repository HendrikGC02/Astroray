# pkg158 — GPU Disney metal remainder: reconcile the near-delta numbers, then fix or close (pkg152 split-out)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (measurement-reconciliation first; whether any code changes exist depends on Step 0's outcome)
**Status:** open — dispatchable (this is the split-out follow-up pkg152's fired split-clause requires; its Step 0 unblocks the "reconcile before filing" precondition recorded in pkg152's status)
**Estimated effort:** S (Step 0) + S–M only if a real residual survives
**Depends on:** pkg152/PR #523 merged (done). Reads: `.astroray_plan/docs/pkg141-gpu-metal-near-delta-research.md` (the 0.60–0.77 record), the #523 verifier evidence (~1.0 near-delta), pkg55 spec adjudication note (2026-07-25).

**Origin:** pkg152 closeout (2026-07-25). Two credible measurements of the near-delta Disney-metal GPU/CPU ratio disagree: the pkg141/#518 research-doc record (0.60–0.77, R<G<B, floor+sun scene family) vs the #523 verifier's post-merge reading (~1.0). Until reconciled, the project does not know whether a metal-dimness defect still exists — neither number is citable.

---

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
