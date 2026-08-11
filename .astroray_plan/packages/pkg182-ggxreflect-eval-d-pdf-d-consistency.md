# pkg182 — Principled/Disney `ggxReflect` eval-D vs pdf-D consistency: low-roughness metal/specular near-black fix

**Pillar:** 2 (materials / BSDF energy correctness)
**Track:** A (CPU+GPU byte-mirrored, RTX-verified)
**Status:** done (PR #582, 2026-08-10 — grey-furnace centre luminance: metallic
r=0.02/0.05/0.10 0.067→**0.604** (matches the `metal` reference), r=0.30
0.567→0.603; dielectric-specular r=0.02/0.05/0.10 0.025→**0.231**, r=0.30
0.217→0.230. Register-neutral: `<false>` STACK 3608 B / `<true>` STACK
6592 B unchanged. 14 new/extended tests + 73-test regression green, RTX
5070 Ti hardware-verified.)
**Estimated effort:** S (eval-only fix, sampler/pdf untouched)
**Depends on:** `disney.cpp` / `gpu_materials.h` GGX reflect evaluators
(metallic + specular + anisotropic lobes); discovered as a blocker for
**pkg178** Stage 4 PR-4 (thin-wall) — the same regularizer mismatch made
thin-glass render black before this fix.

## Origin

Surfaced during pkg178 Stage 4 PR-4 (thin wall / thin glass, 2026-08-10):
the thin-glass reflect lobe rendered black at low roughness. Root-caused to
a pre-existing defect in the (much older) Principled/Disney metallic and
specular reflect evaluators, not the new thin-glass code — filed and fixed
as its own package since it affects every existing low-roughness
metal/specular render, not just thin-glass.

## The defect

Reflect **eval** used a regularized GGX D: `a2 / (π·denom² + 1e-4)`. Reflect
**sample**'s pdf used the unregularized `D_GTR2` (no epsilon). At the
specular peak (`denom→0`) the `+1e-4` collapses eval-D up to **~19000× at
r=0.02** relative to pdf-D, driving `f/pdf → 0` and the surface toward
black. The anisotropic path carried the twin defect (`ggxAnisoD` eval
regularizer `1e-4` vs pdf regularizer `1e-12`).

## Fix

Make eval-D **equal** pdf-D: unregularized `D_GTR2` for the isotropic
metallic/specular/anisotropic reflect evaluators (aniso regularizer
tightened `1e-4 → 1e-12` to match the sampler), CPU + GPU byte-mirrored.
**Eval-only** — the sampler and pdf are untouched (they were already
`D_GTR2`). Same discipline as the existing Transmission lobe and the
pkg178 Stage-4 thin-glass lobe. Cites Heitz 2014 (GGX D term).

## Acceptance criteria

- [x] Grey-furnace centre luminance in-band at low roughness for metallic
      and dielectric-specular (`test_principled_reflection_not_black`).
- [x] GPU furnace + CPU/GPU parity green.
- [x] Register-neutral (`<false>`/`<true>` STACK unchanged).
- [x] chi² invariant (eval-only change; sampler/pdf untouched).
- [x] Full regression suite green (73 tests), RTX 5070 Ti hardware-verified.

## Non-goals

- Not the sampler or pdf (already correct — `D_GTR2` unregularized).
- Not the transmission lobe (already used the correct unregularized form).
- Not a general regularizer-policy change across every closure — scoped to
  the three reflect evaluators that carried the mismatch.

## Provenance

Filed by the lead 2026-08-10, discovered during pkg178 Stage 4 PR-4 review
(thin-glass black-render blocker); fixed and merged the same day as PR #582.

## Hardware verification 2026-08-12 (PR #586 — per-λ-native conductor thin-film follow-up)

**Scope note:** PR #586 is the pkg182 follow-up leg (per-λ-native Principled
metallic/conductor F82 thin-film, superseding the PR-2/PR-3 RGB-upsample
approximation). Its own gate list lives in the PR body, not restated as
spec acceptance criteria here — this section records the independent
hardware re-measurement.

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, compute capability
12.0. CUDA 12.8 (`nvcc` V12.8.61, `CMAKE_CUDA_COMPILER` =
`CUDA/v12.8/bin/nvcc.exe`; `ASTRORAY_CUDA_ARCHS=native` local-dev build).
Windows 11 Enterprise 10.0.26200. Worktree
`.claude/worktrees/awesome-morse-c232d1`, HEAD
`3425afeb9256a850779ea367e60a2c13cb71997e`, clean rebuild
(`build_cuda_worktree.bat`), `.pyd` mtime 2026-08-12 09:17 (post-HEAD-commit,
non-stale), `astroray.__file__` confirmed pointing at the worktree's own
`build_cuda/astroray.cp313-win_amd64.pyd`.

| Gate | Claimed | Measured | Result |
|---|---|---|---|
| cuobjdump `stageShadeBucketedKernel<false>` | STACK 3608 / REG 254, unchanged | STACK 3608 / REG 254 (identical to current-main baseline: STACK 3608/REG 254) | PASS |
| cuobjdump `stageShadeBucketedKernel<true>` | STACK 6592 / REG 254, unchanged, only CONSTANT[2] +40 B | STACK 6592 / REG 254; CONSTANT[2] 208→248 B (main baseline 208, branch 248 = +40 B exactly) | PASS |
| Thickness-0 bit-equality (CPU, metallic) | PASS | `test_metallic_thin_film_thickness0_bit_equality` PASSED (np.array_equal true for both absent-vs-0.0 and 0.05nm-sub-cutoff) | PASS |
| Thickness-0 bit-equality (CPU+GPU ×3, pkg178 harness) | PASS | `test_thinfilm_zero_thickness_bit_identity[dielectric_spec\|metallic\|glass]` — 3/3 PASSED | PASS |
| CPU/GPU conductor thin-film spectral parity | 12/12, metallic within 0.7% | 12/12 PASSED (`test_thinfilm_gpu_cpu_parity` × 9 cases + `test_thinfilm_zero_thickness_bit_identity` × 3); metallic cases max deviation: mean-ratio ≤1.0016 (0.16%), median-ratio up to 1.0071 (metallic_r0.3_d550, R channel, 0.71%) — consistent with the claimed "within 0.7%" | PASS |
| Furnace no-energy-gain (LINEAR, `apply_gamma=False`) | PASS | `test_metallic_thin_film_furnace_no_energy_gain` PASSED — 15-case thickness×film-IOR sweep held within `[off_mean×0.90-0.02, off_mean×1.06+0.02]`; render call confirmed `apply_gamma=False` at the call site (line 46 of `tests/test_thin_film_pr2.py`) | PASS |
| Full gate suite (`test_thin_film_pr2` + `test_pkg182_conductor_spectral_native` + `test_pkg178_thinfilm_gpu_cpu_parity`) | 17/17 | 17/17 PASSED (`10.70s`) — first attempt showed 1 failure (`UnicodeEncodeError` on `λ` glyph under the shell's cp1252 console codepage inside a `print()`, not a logic failure); re-ran with `PYTHONIOENCODING=utf-8`, all 17 green | PASS |
| Saturation washout guard (`test_conductor_spectral_stays_chromatic`) | mean 0.0488→0.0499, max 0.1842→0.2045 | mean_sat=0.0499, max_sat=0.2045 (exact match to claimed) | PASS |
| Hue trajectory moves with thickness | — | `test_conductor_spectral_hue_moves_with_thickness` PASSED | PASS |

**Visual inspection:** rendered a 384×384 metallic Principled sphere
(thickness 500 nm, film IOR 1.5, base_color 0.9/0.9/0.9, white background,
256 spp, GPU path) on this branch and on a freshly-rebuilt current-`main`
(24106ca) baseline for the same scene/seed. Both show the same iridescent
banding pattern (yellow rim → magenta band → cyan/green core, growing
toward grazing angle) at comparable noise level (mean|on−off| = 0.00898
branch vs 0.00955 main). A saturation-boosted (×6 chroma) crop and a ×10
absolute-difference heatmap confirm: no fireflies/single-pixel spikes, no
banding/quantization artifacts, no NaN pixels (magenta/black), no mode
regression (thin-film-off renders a clean uniform-white sphere on both
builds). The branch-vs-main diff is smooth and ring-shaped (concentrated at
the grazing rim, consistent with the physics), not noisy or structurally
different — matches the PR's own "not the visible saturation jump the
ticket implied" finding. No visual regression found.

**Anomalies worth watching:** none blocking. Both this worktree's and
current-main's `build_cuda/CMakeCache.txt` still carry a stale cached
`CMAKE_CUDA_ARCHITECTURES:STRING=52` alongside `ASTRORAY_CUDA_ARCHS=native`;
confirmed this is shadowed at configure time by the CMakeLists.txt
unconditional `set(CMAKE_CUDA_ARCHITECTURES "${ASTRORAY_CUDA_ARCHS}")` (a
non-cache variable), and the actually-compiled kernels correctly target
this machine's `native` SM (RTX 5070 Ti, CC 12.0) — not a live bug, but the
cache entry should eventually be cleaned so it stops looking like drift on
every worktree-cache audit. Main's `.pyd` was found stale (older than its
own HEAD commit) at verification start and was rebuilt as the comparison
baseline; this was pre-existing main-branch build-cache staleness, unrelated
to PR #586's own gate results.

**Overall verdict:** mergeable-on-HW-evidence: yes. All 17/17 gate tests
pass, the cuobjdump structural claims measure exactly as stated including
the precise +40 B CONSTANT[2] delta, and visual inspection found no
regression. This is a numbers report, not a merge authorization — gate/merge
decisions remain with the architect dialogue.
