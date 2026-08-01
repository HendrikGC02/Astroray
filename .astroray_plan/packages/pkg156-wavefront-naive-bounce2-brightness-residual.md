# pkg156 — Wavefront visible-naive ~1–1.5% deterministic brightness residual (bounce-2 onset; owns the 0.995 SSIM re-pin)

**Pillar:** 3 (GPU transport correctness)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (transport-diff diagnosis on the live wavefront; needs per-bounce instrumentation judgment)
**Status:** open — dispatchable (precondition MET 2026-07-25: PR #524/pkg55-C7 merged, wavefront is the sole GPU path); not urgent-tier, but it OWNS the `test_visible_band_cpu_gpu_ssim` re-pin (0.998→0.995) — that gate may only return to 0.998 through this package's fix, never by silent re-tightening on a lucky run.
**Estimated effort:** S–M (the dossier already localizes onset; the fix is likely one transport term)
**Depends on:** pkg55-C7/PR #524 merged. Cross-link: **pkg153** — the bounce-2 onset (= first albedo-upsample-dependent transport) is the same structural neighborhood as the R-drift; if pkg153's bisect convicts a spectral-eval arc commit, re-measure this residual at that commit before independent work.

**Origin:** pkg55-C7 finale sweep (2026-07-25, `.astroray_plan/docs/pkg55-c7-day-arc-2026-07-25.md` §5; architect adjudication V1 in the pkg55 spec).

---

## Defect (measured dossier, RTX 5070 Ti)

Wavefront naive-MW mode renders ~1–1.5% bright vs BOTH the CPU naive reference AND the pre-deletion megakernel (WF/MK [1.011, 1.006, 1.010] @depth2): onset exactly at the SECOND bounce (depth-1 ratio ~1.00), spp-independent, deterministic. Pre-existing wavefront transport difference — NOT introduced by the C7 deletion (the MK comparison proves it), surfaced when the repoint made the wavefront the measured leg. Full numbers in the `test_visible_band_cpu_gpu_ssim` docstring dossier.

## Contract

1. Per-bounce diff instrumentation (the pkg55 snapshot harness pattern): isolate which per-bounce term diverges at bounce 2 — throughput update, albedo upsample, RR weight, or env/emission accumulation. Depth-1-clean means the primary shade agrees; suspect the first RECURSIVE use of upsampled albedo.
2. Fix the convicted term with citation; CPU is the oracle.
3. Restore the SSIM gate to 0.998 (measured, in the fix PR) — that is this package's definition of done; if 0.998 is unreachable after the fix, escalate to the architect with the residual decomposition, do not re-pin again unilaterally.
4. Report whether the fix moves the pkg153 R-drift ratios (same scene family, shared-mechanism check) — evidence either way is bisect intel.

## Non-goals

- The pkg153 env-scene ratio gates themselves (quarantined, own bisect arc).
- Perf work (pkg155).

## Residual decomposition + BLOCKED-ON verdict (architect, 2026-08-02 — PR #537 round)

The investigation ran and split the residual in two; the implementer correctly
did NOT re-pin:

1. **A real pkg120 regression, fixed in PR #537:** #534's two-sided `w_B` leg
   ran unconditionally on the GPU wavefront, including in naive mode
   (`enableNEE=false`) where the CPU oracle has no such term. Recorded as a
   Lessons entry in the pkg120 spec ("mirror the CONDITION, not just the term").
2. **The remainder after the fix:** depth-4 GPU/CPU ratio [1.014, 1.007,
   1.014], SSIM 0.9955 vs the aspirational 0.998. Controls: black background
   renders identically black on both legs (zero transport from the light quad);
   neutral-grey background still shows the channel-asymmetric ratio. Verdict:
   the remaining ~1.4% is the **CPU-`RGBAlbedoSpectrum`/`RGBIlluminant`-vs-
   GPU-tables RGB→spectral upsampling parity gap** — the same mechanism family
   as pkg153's R-drift.

**BINDING: the 0.995 → 0.998 SSIM restoration is BLOCKED-ON pkg168**
(`pkg168-rgb-spectral-upsampling-parity.md`, filed 2026-08-02, owns the
upsampling-parity fix). Do NOT re-dispatch this package for the remainder, and
NO future run may re-tighten the gate on a lucky draw — the gate returns to
0.998 only in (or immediately after, with measurement) pkg168's fix PR. This
supersedes fix-contract item 3 above: the escalation it required has happened
and this is the architect's disposition.
