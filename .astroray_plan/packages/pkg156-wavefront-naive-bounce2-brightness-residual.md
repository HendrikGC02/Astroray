# pkg156 — Wavefront visible-naive ~1–1.5% deterministic brightness residual (bounce-2 onset; owns the 0.995 SSIM re-pin)

**Pillar:** 3 (GPU transport correctness)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (transport-diff diagnosis on the live wavefront; needs per-bounce instrumentation judgment)
**Status:** partial fix + escalation (PR #537, 2026-08-02) — pkg120's un-gated two-sided-MIS w_B leg was firing in naive mode (enableNEE=false), growing the residual to depth-2 [1.028,1.022,1.027]/SSIM 0.9953; pkg156 gates that leg on enableNEE, restoring depth-4 [1.014,1.007,1.014]/SSIM 0.9955 and matching the CPU oracle + pre-pkg120 wavefront. The REMAINING ~1.4% residual is an RGB→spectral upsampling parity gap (channel-asymmetric [1.013,1.007,1.014] even under a NEUTRAL grey background), i.e. pkg153's R-drift shared mechanism — NOT reachable here. **0.998 is unreachable; gate stays at 0.995** and the residual decomposition is escalated to the architect (see contract point 3). Do NOT re-pin to 0.998 without the pkg153 upsampling-parity fix.
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

## Outcome (2026-08-02, RTX 5070 Ti)

1. **Convicted term:** pkg120's two-sided-MIS BSDF-hits-emitter `w_B` leg in
   `intersectPathSlot` (stage_advance.cu) was applied unconditionally, including
   the naive route (`multiwavelength_path_tracer` => `enableNEE=false`). The
   `w_B` leg is only valid as the complement of the NEE light-sampling leg; with
   no NEE it diverges the GPU bright from the CPU oracle
   (`MultiwavelengthPathTracer::pathTrace`, which takes emission only on
   `bounce==0||wasSpecular`). Fix: gate the `else` branch on `enableNEE`
   (threaded through intersectPathSlot / stageIntersectQueuedKernel /
   launchStageIntersectQueued and the dense/restir/snapshot callers). NEE path
   (`path_tracer`, enableNEE=true) is byte-unchanged — pkg120 gates stay green.
   Cite: Veach 1997 §9.2 (the w_B/w_L partition presupposes both legs exist).
2. **Measured:** depth-4 GPU/CPU mean-ratio [1.028,1.020,1.018]→[1.014,1.007,1.014];
   SSIM(8192) 0.9953→0.9955. Back to the pre-pkg120 dossier baseline.
3. **Remaining residual is NOT transport.** Black background ⇒ whole image black
   on both legs (the camera never sees the down-facing quad; all light is ambient
   env-miss). Neutral grey background ⇒ channel-asymmetric ratio
   [1.013,1.007,1.014] from a neutral input color ⇒ RGB→spectral upsampling
   parity gap (CPU RGBAlbedoSpectrum/RGBIlluminantSpectrum vs GPU tables) on the
   first post-bounce use.
4. **pkg153 shared-mechanism check (contract pt 4):** this fix does NOT move the
   pkg153 R-drift — it only removes the light-quad `w_B` term (zero under the
   black-bg control), leaving the env-miss/albedo upsampling path (the R-drift
   carrier) untouched. The remaining residual IS the pkg153 mechanism; 0.998 is
   gated on pkg153's upsampling-parity fix. Escalated to the architect.

## Non-goals

- The pkg153 env-scene ratio gates themselves (quarantined, own bisect arc).
- Perf work (pkg155).
