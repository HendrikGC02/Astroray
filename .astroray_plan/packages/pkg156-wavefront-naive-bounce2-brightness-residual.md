# pkg156 — Wavefront visible-naive ~1–1.5% deterministic brightness residual (bounce-2 onset; owns the 0.995 SSIM re-pin)

**Pillar:** 3 (GPU transport correctness)
**Track:** A (RTX-gated)
**Codex-paste-ready:** no (transport-diff diagnosis on the live wavefront; needs per-bounce instrumentation judgment)
**Status:** partial fix + escalation (PR #537, 2026-08-02) — pkg120's un-gated two-sided-MIS w_B leg was firing in naive mode (enableNEE=false), growing the residual to depth-2 [1.028,1.022,1.027]/SSIM 0.9953; pkg156 gates that leg on enableNEE, restoring depth-4 [1.014,1.007,1.014]/SSIM 0.9955 and matching the CPU oracle + pre-pkg120 wavefront. The REMAINING ~1.4% residual is an RGB→spectral upsampling parity gap (channel-asymmetric [1.013,1.007,1.014] even under a NEUTRAL grey background), i.e. pkg153's R-drift shared mechanism — NOT reachable here. **0.998 is unreachable; gate stays at 0.995**; the 0.998 restoration is BLOCKED-ON pkg168 (the RGB-to-spectral upsampling-parity fix; pkg153's R-drift is the shared mechanism, see-also). Escalated to the architect (contract point 3). Do NOT re-pin to 0.998 without pkg168's fix.
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
   BLOCKED-ON pkg168's upsampling-parity fix (pkg153 shared mechanism, see-also). Escalated to the architect.

## Non-goals

- The pkg153 env-scene ratio gates themselves (quarantined, own bisect arc).
- Perf work (pkg155).

## Hardware verification 2026-08-02 (PR #537, independent verifier)

**Hardware:** RTX 5070 Ti, driver 610.47, CUDA 12.8, OptiX 9.1.0, OIDN 2.4.1, Windows 11. Worktree HEAD pinned + verified == `155a76a445e638aadbdd9ee3a8e54998c3e7fa45` (contamination guard passed).

Clean foreground rebuild via `build_cuda_worktree.bat` succeeded (astroray + astroray_test_helpers targets); fresh `.pyd` confirmed (mtime after rebuild, loaded from `build_cuda/astroray.cp313-win_amd64.pyd`, not a repo-root shadow). No new Python-level binding was added by this PR (device-only `enableNEE` CUDA parameter); the existing `enable_nee` Python-facing kwarg on `render_multiwavelength`-style Renderer calls predates pkg156 (pkg82), so the smoke-check step reduces to confirming the fresh-build render path executes correctly, which it did.

| Gate | Result | Measured |
|---|---|---|
| `test_visible_band_cpu_gpu_ssim` (pkg156-owned) | PASS | SSIM 0.9954909682273865; per-channel GPU/CPU ratio [1.0143244, 1.0066499, 1.014184] (independently re-measured, matches implementer's claim exactly) |
| `test_two_sided_recovers_large_near_light` (pkg120) | PASS | — |
| `test_two_sided_matches_analytic_formfactor` (pkg120) | PASS | — |
| `test_no_regression_distant_compact_light` (pkg120) | PASS | — |
| `test_visible_band_no_regression` | PASS | — |
| `test_nir_band_cpu_gpu_ssim_with_profiles` | PASS | — |
| `test_uv_band_cpu_gpu_ssim_with_profiles` | PASS | — |
| `test_nir_band_cpu_gpu_no_profile_fallback` | PASS | — |
| `test_gpu_mw_kernel_runs_and_is_finite` | PASS | — |
| `test_cpu_wavefront_*_bit_identity` (6 material suites, wavefront_diff/) | PASS | all report `max diff = 0.0, diverging fields = 0` |
| `test_cpu_to_cpu_baseline_bit_identity` | PASS | exact bit-identity |
| `test_cpu_to_gpu_threshold_gate` | PASS | PostInit ULP=2 p99.9=1.435664e-07; PostIntersect ULP=32 p99.9=2.170602e-06; PostShade p99.9=2.165780e-06; PostLightSample p99.9=2.211559e-06; PostRR p99.9=0.0 |
| `test_post_nee_mis_gate` (C2 PostNEE_MIS) | PASS | Tier1 0 diverging fields; Tier1b max residual 6.932e-08/99 rows; Tier2 max residual 7.472e-08/97 rows (tol 1e-05) |
| `test_wavefront_dedicated_light_nee` (pkg89, 3 params) | PASS | WF/CPU ratios [0.9965,0.997,0.9967] / [0.9965,0.9972,0.9967] / [0.9973,0.9972,0.9971] |
| `test_wavefront_contact_sheet_ceiling` (perf) | PASS | 0.819s median-of-3 vs 1.0s ceiling |
| `test_capabilities_gpu_supported`, `test_gpu_routes_to_wavefront_pipeline`, `test_cpu_fallback_renders` | PASS | — |
| `test_gpu_wavefront_final_image_mean_ratio` (pkg153-quarantined) | FAIL (pre-existing, skip per dispatch) | ratio [1.3364056, 1.0782511, 1.104607], SSIM 0.8881 |
| `test_megakernel_open_env_scene_mean_ratio` (pkg153-quarantined) | FAIL (pre-existing, skip per dispatch) | ratio [1.336, 1.078, 1.105] |
| `test_megakernel_world_max_bounces_env_gate` (pkg153-quarantined) | FAIL (pre-existing, skip per dispatch) | ratio [1.283, 1.065, 1.07] |

The 3 failures are the known pkg153-quarantined env-scene gates (`pkg153-wavefront-diff-env-gates-disposition.md`), same magnitude class/R-channel-dominant pattern as that spec's live investigation history — unrelated to pkg156's `enableNEE` gating change, which only touches the light-quad direct-hit `w_B` term (zero under the black-bg control per the implementer's own decomposition).

**Visual inspection:** rendered a 128x128 naive-mode CPU/GPU pair at 2048 spp from the pkg156 scene (`scenes.multiwavelength_parity`) and saved to `test_results/pkg156_naive_cpu_reference.png` / `test_results/pkg156_naive_gpu_wavefront.png`. Both show the same green-sphere-on-dark-surface scene at matching brightness; no fireflies, no NaN pixels (confirmed `np.isnan` all-False on both legs), no banding, no over-bright emissive quad, no mode regression. Max abs diff 0.0420051, mean abs diff 0.0007852945 (128x128, 2048 spp) — consistent with the ~1.4% residual measured at the gate's own 8192 spp/48x48 config.

**Verdict: PASS**, bound to `155a76a445e638aadbdd9ee3a8e54998c3e7fa45`. All gates the dispatch scoped to pkg156's change pass; the 3 pkg153-quarantined failures are pre-existing and correctly excluded from this package's gate.
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

**BINDING: the 0.995 → 0.998 SSIM restoration is BLOCKED-ON pkg172**
(`pkg172-triangle-transport-bias.md`; pointer updated 2026-08-02 from pkg168
after PR #541's decomposition — pkg168 fixed a real chroma-dependent
upsample-shape divergence, sphere-isolated ratios now exactly 1.000, but the
pkg156 scene is dominated by a third, triangle-geometry mechanism: uniform
~0.6% GPU-bright on triangles, achromatic, single-bounce,
background-independent). Do NOT re-dispatch this package for the remainder,
and NO future run may re-tighten the gate on a lucky draw — the gate returns
to 0.998 only in (or immediately after, with measurement) pkg172's fix PR.
This supersedes fix-contract item 3 above: the escalation it required has
happened and this is the architect's disposition. Residual stack for the
record: (1) pkg120 unconditional two-sided term — fixed #537; (2)
upsample-argument shape divergence — fixed #541 (pkg168); (3) triangle
transport bias — pkg172, open.
