# pkg230 Phase 2 delivery evidence

Verified implementation, 2026-09-06; final independent sign-off and CI/merge pending.
Base: `31f30298c79dad151b270bef448184b598995137`.

## Architecture and scope

[The research note](pkg230-phase2-vector-semantics-research.md) pins Blender 5.1
Cycles sources and resolves the color/scalar-versus-coordinate fork. Phase 2
adds all 30 Vector Math operations, five Vector Rotate modes (center/invert),
and faithful modern Mix factor clamping. Coordinate chains visibly degrade;
pkg230b owns their later extension. Legacy raw Mix retains its default clamp.

Integration corrected real Blender socket/type handling, operand placement,
Cycles power/wrap edge cases, Euler inversion, implicit color/vector-to-scalar
conversion, and indexable `mathutils.Euler` defaults. Tests cover compiler output
through the native evaluator, beyond mocks. Independent Claude architecture and
source reviews accepted the math, scope, ABI and callers.

## Builds and runtime identity

- Hardware: RTX 5070 Ti, 16303 MiB, driver 616.56, Windows; CUDA 12.8,
  MSVC 14.44.35207, native sm_120, wavefront N3 ON.
- Fresh baseline: main `build_cuda/Release/astroray.cp313-win_amd64.pyd`,
  153047040 bytes; imported path/features and baseline VM canary confirmed.
  Baseline Phase 1 tests: **10 passed**. OpenMP ON.
- CPU-only addon: MinGW, CUDA OFF, OpenMP OFF; native tests **96 passed**;
  image programs **3 passed / 6 GPU-only skipped**. Final Blender CPU charts
  import this module from `build_blender_addon`, with its packaged thread DLL.
- Feature CUDA: first sccache attempt failed with connection reset 10054 in
  stage_advance; direct compiler retry passed with the same feature options.
  Initial native focused run: **118 passed**. OpenMP ON for the full-suite run.
- Final Blender CUDA addon: canonical backend flags, OpenMP OFF, build ID
  `31f3029+20260905T153751Z`, module 153293312 bytes, built 2026-09-05 16:03 UTC.
  Intended import path, matching package build ID, native sm_120, host ABI canary,
  and header stamp PASS. Canonical staging bundles OIDN/CUDA DLLs.
  Final focused pkg219/pkg230 run: **158 passed in 10.99 s**.
- Linked resources: **128 shade variants**; all **64 HasProgram=false** variants
  match every recorded baseline resource field. Fleet: REG 254 / STACK 3400 /
  CONSTANT[0] 1748 / LOCAL 0. These are measured resource identities, not a
  claim that complete machine-code byte streams were compared.

## Visual and numerical gates

Final charts use real Blender 5.1.0 (`adfe2921d5f3`), 128x128, 256 samples,
raw linear float32 arrays, no denoising or adaptive sampling. Fifteen legs PASS:
plain image, MULTIPLY_ADD, inverted Euler XYZ, clamped Mix and unclamped Mix,
each through CPU-only Astroray, RTX Astroray and Cycles. The carrier is textured
Principled with specular zero, perspective camera, Closest filtering; Astroray
reports its existing textured-Base-Color lambertian approximation explicitly.

- CPU/Cycles interior RGB mean ratios: **0.976648-1.018138**.
- GPU/Cycles interior RGB mean ratios: **0.976268-1.017924**.
- GPU/CPU interior RGB mean ratios: **0.999458-1.000073**.
- All lie inside the declared **[0.95,1.05]** gate. ROI is pixels `[24:104,24:104]`.
- Clamped Mix matches the plain control (maximum GPU difference 1.19e-7;
  CPU/Cycles exact). Unclamped Mix visibly extrapolates; mean control difference
  is 0.02685 CPU/GPU and 0.02793 Cycles.
- Astra qualitative PASS on `final_blender_cpu_gpu_cycles.png`: corresponding
  color patterns and transformations, CPU/GPU agreement, no new spatial defects,
  modest spectral color differences/noise relative to Cycles.
- Native program image tests also PASS: ratios 0.997252-1.000201 and program
  effects above 0.02 mean absolute difference on both backends. Astra inspected
  `native_cpu_gpu.png` and accepted the representative math/rotation/Mix effects.

Initial Diffuse-carrier and Linear-filter comparisons exposed existing consumer
and nearest-only filtering gaps. Their `_failed_diffuse` and `_linear_filter_gap`
artifacts are retained; pkg233 and pkg234 own these gaps. They are not counted as
pkg230 coverage. The final carrier and filtering restriction are intentional and
were independently reviewed.

## Full suite and investigated failures

The full split run recorded **1642 passed, 56 skipped, 9 xfailed** in the CPU
pass (342.08 s), then **684 passed, 16 skipped, 8 xfailed, 6 xpassed, 4 failed**
in the serial pass (239.70 s). This original full-suite run is not green.

Two failures are baseline renderer/test debt, with unchanged assertions:

| Gate | Fresh main | Feature | Existing bound |
| --- | --- | --- | --- |
| HDRI SSIM, original failure runs | 0.77432567 | 0.7690514 | >=0.97 |
| PostInit maximum ULP | 13 | 13 | <=4 |

Independent Claude gate-failure review accepts their baseline reproduction and
exclusion from new-VM reachability, conditional on extra measurements. Those
measurements are now recorded without changing or bypassing source assertions:
all snapshots were already captured before the failure, so the diagnostic driver
uses the failing frame's values and the original numerical helper functions.

| Stage | Main and feature measured identically | Result |
| --- | --- | --- |
| PostInit | origin ULP 0, direction 2, wavelength 13; p99.9 4.88660e-7 | ULP fails; p99.9 passes |
| PostIntersect | ULP 46; p99.9 3.82908e-6 | Pass |
| PostShade | 134 rows; p99.9 1.15045e-6 | Pass |
| PostLightSample | 95 rows; p99.9 8.10758e-7 | Pass |
| PostRR | No bounce-zero CPU rows | Inactive, not a measured pass |

The overshoot is in wavelengths, not camera direction. Its precise cause remains
pkg238 work. Captured HDRI images show noisier CPU output on both branches;
new scores are 0.769988 main / 0.768899 feature. All peaks are below 1, so the
`max(1, image.max())` normalization is inactive in these captures. No exact HDRI
cause is claimed; pkg237 retains that diagnosis. Astra inspected
`baseline_hdri_failure.png` as failure evidence, not a passing visual gate.

The other two failures were investigated and corrected for reruns:

- The non-hermetic dev-loop test attempted installation into the running Blender
  5.2 profile and hit a locked older module after partially removing support
  directories. Recovery restored the matching `1967cb5` Python/assets and
  unchanged runtime DLL bundle, preserving the original native module. Background
  registration PASS. The unmodified smoke test then **passed** with all Blender
  user-resource paths redirected to a verified worktree test directory. pkg236
  owns permanent isolation/rollback; this round did not install the new build
  into the live profile. Recovery evidence is in the root workspace's
  `test_results/pkg230-p2/installed-recovery/`.
- Backdrop initially failed DLL loading, then selected the CPU-only build while
  requesting GPU. Providing the byte-identical staged CUDA artifact at the
  canonical addon discovery path let the stock test reach its actual assertion.
  The faithful sample/denoising configuration exposed insufficient sampling:
  both main and feature score **0.8395174 at 64 spp**, **0.9141075 at 256 spp**.
  The test now requests 256 on both engines and retains its 0.90 threshold.
  **All 37 harness tests pass in 7.68 s.** Astra inspected the convergence sheet:
  noise decreases and baseline/feature structure agrees. A small bright patch on
  the green backdrop persists in both Astroray builds and is absent in Cycles;
  this local baseline discrepancy is a separate diagnostic follow-up, not a
  claim of perfect backdrop parity.

## Callers, hygiene and independent review

`svm_mix` adds a defaulted boolean; its sole production caller decodes the new
negative flag. `_resolve_vector_input` adds an optional warning callback, passed
by all three production callers and recursion. Old tests/mocks remain valid.
`compile_socket` keeps its public signature; its internal value helper leaves
recursive implicit conversions intact. The render configurator's optional
backend argument is passed by its CLI caller; the backdrop test is its real
harness consumer. No bindings, POD layouts, slot limits, specialization axes or
material layouts change. Final caller sweep is saved.

Differential Ruff/cppcheck/markdownlint/codespell/diff-check reports zero new
findings, no unavailable/error tools. clang-format is skipped because the repo
has no style configuration. Final harness/evidence edits will receive the same
scoped check before commit.

Two early cheap source-critic attempts timed out: incomplete, never counted as
PASS. Later bounded opencode call-path and settings traces completed; Astra
corrected their mistaken inferences before use. Claude architecture, source and
conditional failure reviews are retained. Final independent judgment and CI
remain release gates.

## Follow-ups and artifacts

Separately filed after independent Claude review and docs CI: pkg230b (#697),
pkg231 (#698), pkg232-235 (#699), pkg236-238 (#700). All new follow-ups remain OPEN
with implementation gates UNRUN, no queue promotion. Pillar 4 remains PAUSED.

`test_results/pkg230-p2/` retains builds, import proofs, raw resource dumps,
linear arrays, contact sheets, test logs, compiler/real-Blender probes, caller
sweep, and Claude transcripts. Key final files are `final-module-proof.json`,
`final-resource-comparison.json`, `final-blender-metrics.json`,
`final_blender_cpu_gpu_cycles.png`, `backdrop-convergence.json`,
`backdrop_convergence.png`, `baseline_hdri_failure.png`, and the
`main/feature-baseline-diagnostics.json` pair.
