# pkg230b — affine coordinate delivery evidence

Status: implemented and locally verified with two reproduced baseline failures;
**REVIEW APPROVED; delivery and CI pending**. Independent Claude architecture review passed.
On 2026-09-06 the owner approved commit/merge and explicitly authorized Terra or
DeepSeek independent review while Claude is unavailable. Terra final review
returned SIGN-OFF after source/caller/binding and visual inspection.
Full-suite results remain recorded below; the full suite is NOT green.

## Implementation and architectural limits

One bounded addon resolver carries coordinate provenance and the affine matrix
together. It supports ADD/SUBTRACT/MULTIPLY/SCALE with at most one varying vector,
all five constant-control Rotate modes, centered inverse rotations, Mapping order,
zero/mirrored scales, linked constants, stable RNA node identity and finite native
matrix values. Unlinked Mapping Vector sockets use Blender's constant semantics.

Image cache identities preserve small edits and named UV layers. Image programs
receive isolated identity child samplers for each parent mapping; unsupported
per-input program coordinate differences warn. Procedural transformed-p behavior
remains under pkg242, normal/bump provenance under pkg245, and image filtering /
extension behavior under pkg234. No C++/CUDA, ABI/layout, transport, spectral or
scientific-output code changed. Pillar4 remains PAUSED.

## Focused and real Blender evidence

- 45 new coordinate tests; 101 focused mock tests passed, one native-binding skip.
- Six real Blender 5.1 RNA chains, three point probes each, matched independent
  `mathutils`/arithmetic expectations within absolute/relative 1e-6. Maximum
  absolute error 1.074934e-7; UV provenance retained; no fallback warnings.
- Final 21 render legs: seven cases across CPU-only Astroray, RTX5070Ti CUDA
  Astroray and Cycles, 128x128, 256 spp, seed7, linear float32, denoise/adaptive
  off. Closest + Extend are explicit common supported settings. The arithmetic
  and mirror charts stay within the image domain so the nonuniform pattern
  demonstrates placement rather than mostly sampling one clamped texel.
- ROI [16:112,16:112]; per-channel mean ratio gate [0.95,1.05], transformed/control
  mean absolute difference gate >0.01. Every final case passes. Maximum deviation
  from Cycles is 3.486%; maximum GPU/CPU deviation 0.120%; minimum nonidentity
  effect MAD 0.05593. These are bounded chart gates, not universal Cycles parity.

| Case | Max RGB deviation vs Cycles | Max GPU/CPU deviation | Min effect MAD |
| --- | --- | --- | --- |
| plain | 1.940% | 0.120% | 0.00000 |
| arithmetic | 3.486% | 0.080% | 0.11370 |
| euler | 1.873% | 0.099% | 0.05593 |
| axis | 1.754% | 0.095% | 0.05760 |
| mirror | 1.828% | 0.050% | 0.08651 |
| program | 1.759% | 0.098% | 0.07430 |
| shared_programs | 1.373% | 0.082% | 0.07078 |

Astra qualitative review: PASS for transform placement, centered rotation, mirror
orientation and independently mapped materials sharing one image. Minor spectral
color differences remain. Claude final visual review is **PENDING**.

![Representative CPU/GPU/Cycles comparison](../../test_results/pkg230b/representative-comparison.png)

Full sheet: `test_results/pkg230b/cpu-gpu-cycles-comparison.png`.
Metrics and raw float arrays are retained beside it.

## Failed references were investigated, not discarded

The first fixtures used Cycles Repeat while native image samplers clamp. The
large spatial/mean differences remain saved in `initial-repeat-extension/`.
Matching Extend fixed the extension mismatch; two strongly clamped fixtures still
failed the 5% red-channel gate (arithmetic 7.94%, mirror 13.04%). Those cases and
comparisons remain in `clamped-extend-baseline/`.

The untouched prior addon (4035a00) with equivalent ordinary Mapping nodes
reproduces them: mirror is pixel-identical; arithmetic image MAD is 3.096e-8
(max pixel difference 0.001174). Thus this behavior predates pkg230b. A separate
non-render numerical reconstruction using existing spectral LUT/CIE1964/D65 data
predicted red ratios 1.07562 / 1.12618, close to the rendered 1.079 / 1.130.
That is corroboration of shared spectral round-trip bias, not proof of its full
underlying cause. Spectral/color-contract investigation is drafted as pkg246,
pending independent filing review and not dispatch eligible;
no ad-hoc compensation or tolerance relaxation was added here.

The final in-domain charts improve visual sensitivity to mirroring and arithmetic.
All affected CPU/GPU/Cycles legs were rerun; unchanged rotation/plain/program legs
retain their matching Extend outputs. This does not turn the saved out-of-domain
failures into passing cases or waive their remaining limitations.

## Native build and packaging identity

Native cache: `.claude/worktrees/pkg230-p2` at 4035a00. Native sources are identical
to primary base305caf5 and this addon-only diff. Layout-header hash matches both
worktrees and the existing cache stamp. Both stale modules were rebuilt before
GPU verification, with explicit intended import paths:

- CPU: build ID `4035a00+20260905T173933Z`, CUDA/OpenMP false, ABI canary PASS.
- CUDA: build ID `4035a00+20260905T173857Z`, CUDA/wavefront true, OpenMP false,
  Release; ABI canary PASS; cuobjdump proves embedded sm_120 only.
- Native build files, module identities and timestamps are captured under
  `test_results/pkg230b/fresh-*-*.{json,log}` in the root workspace. CUDA work is
  serialized under the project GPU lock. No post-commit rebuild is claimed.

An initial CUDA reconfigure failed after a case-only compiler-path change reset
Release/native/OpenMP settings. The corrected rebuild restored the intended flags;
the failed log remains evidence for pkg244, not a successful build claim.

Canonical staging produced CPU/CUDA zip archives with the current addon hash
`450a64f87743967c77fd970bd8608df6b2d34ba70a53a6dc97538ed250238d8e`.
Its pre-staging probe emitted missing-DLL warnings; these probes did not pass.
Successful native import/canary and real-Blender legs used the full dependency
setup. Both actual staged packages passed isolated Blender smoke verification:

- CPU archive extracted under this worktree: canonical pkg175 smoke PASS,
  finite 96x96 RGB, mean luminance 0.117186, nonblack fraction 1.0.
- CUDA staging installed only into the isolated test profile: canonical
  `test_dev_loop_smoke_local_host` PASS (8.640 s); installed addon hash and native
  build ID match the records above.

Evidence: `cpu-package-smoke.log`, `isolated-install-identity.json`,
`staged-artifacts.json`, and serial JUnit XML. Nothing was installed into the
live profile. All five Blender user-path variables were redirected for tests.

## Full tests, callers, lint and delivery

Canonical split-suite results against the explicitly selected fresh CUDA native
artifact (CPU tests use its CPU rendering path):

- CPU lane: **1687 passed, 56 skipped, 9 xfailed**, 815.68 s.
- Serial lane: **683 passed, 2 failed, 19 skipped, 9 xfailed, 5 xpassed**,
  1749 deselected, 638.81 s. The deselected tests belong to the other lane.
- Combined: **2370 passed, 2 failed**. The full suite is **NOT green**. Skips
  include missing local standalone/harness artifact discovery and optional
  dependencies; the 21 explicit Blender comparison legs and package smokes above
  supply their own evidence, not blanket coverage of skipped tests.

Both failures were replayed against untouched addon/native source `4035a00`
with the SAME fresh native artifact and reproduced in 6.54 s:

| Test | pkg230b result | Untouched baseline | Gate |
| --- | --- | --- | --- |
| `test_gpu_cpu_ssim_hdri` (pkg237) | 0.7642104 | 0.7654136 | SSIM >= 0.97 |
| `test_cpu_to_gpu_threshold_gate` (pkg238) | 13 | 13 | PostInit ULP <= 4 |

These native-only scene/init paths do not consume the addon coordinate resolver.
This establishes baseline reproduction, not a waiver or independent final
adjudication. Logs/XML: `full-cpu`, `full-serial`, and root-workspace
`current-baseline-failures`; machine-readable summary: `full-suite-summary.json`.

Existing callable signatures remain compatible. Parent integration inspected
image/program/procedural callers and native matrix bindings; the normal/bump
routing loss was filed separately as pkg245. Differential whole-diff lint passed
with zero new findings across all four applicable tools; public signatures remain
unchanged. Final documentation lint is retained with the same evidence.

Owner-authorized independent Terra final review returned SIGN-OFF. It found the
two native-only baseline failures do not block this addon package under the
owner's accepted-risk directive. Neither failure is waived or closed, and the
full suite remains NOT green. The reviewer inspected both saved comparison
sheets and confirmed correct placement, rotations, mirroring and distinct shared
program mappings. Review: root `test_results/pkg230b/final-terra-review.txt`.
All five source/test manifest hashes remain exact; documentation hashes were
refreshed after recording approval. CI and final merge are recorded at closeout.
