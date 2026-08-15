# pkg190 — GPU procedural-texture support (pkg186 slice 2)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** done (PR #612, 2026-08-14 — 3D-voxel bake-at-upload GPU procedural
eval; pkg119-B TRANSLATION-BUG 4→0: TEX_CHECKER 0.8425→0.9512, TEX_BRICK
0.8980→0.9158, TEX_MAGIC 0.8358→0.9639, TEX_WAVE 0.8935→0.9575, all at 64³;
register identity gate byte-identical across all 16 shade specializations;
textured_plane CPU/GPU mean-ratio 1.000/1.000/1.000). Follow-up **done (PR
#615, 2026-08-14 — HW PASS)**: narrowed the 3D-voxel bake to Generated
coord-mode only; Object-coord procedurals now degrade to a guarded flat-
albedo fallback on GPU instead of silently misrendering (Object-mode A/B:
GPU flat gray 189.76 vs CPU checkerboard 165.29; Generated-path parity
unchanged).
Filed 2026-08-12 as the pkg186 deferred follow-up; pkg186 PR #590 shipped the
IMAGE-texture slice and explicitly deferred procedural nodes + the pkg119-B
procedural reclassification — see pkg186 Lessons "Deferred to follow-up".
**Estimated effort:** L
**Depends on:** pkg186 (PR #590 — image-texture slice; establishes the
`__constant__ c_wfTexBinding` binding, the `<HasPrincipled,HasTexture>`
template pattern, `gpu_sampleImageTexture`, and the throughput-substitution
fold in `stage_advance.cu`); pkg115 (Blender shader-node texture adoption,
CPU); pkg119-B (Blender differential parity harness — the acceptance signal);
pkg178 (register-pressure isolation pattern).

---

## Symptom

The GPU wavefront path now samples IMAGE textures (pkg186) but still collapses
**every procedural texture node** (Noise / Musgrave / Voronoi / Wave / Gradient /
Checker / Magic / Brick / …) to the material's flat `getAlbedo()`. The CPU
reference evaluates the procedural node per-shade; the GPU sees a single constant
Vec3. Any procedural-textured Blender material renders as flat albedo on GPU with
no warning (the pkg186 `__features__` guard already reports `textures: CPU only`
on the GPU backend, so the user is at least *told* — but the capability is still
missing).

---

## The premise trap — RE-BASELINE pkg119-B BEFORE attributing bugs (read first)

The tempting story is "the 5 residual pkg119-B `TRANSLATION-BUG` entries are
procedural nodes, so procedural GPU support will reclassify them to parity-pass."
**Do not assume this.** The pkg186 implementer and memory
[[pkg119b-harness-runbook]] flag that the earlier TRANSLATION-BUG convictions
(`BSDF_TRANSPARENT`, `world:World`) were **DISPROVEN as SSIM false-positives on
noise-dominated / under-converged scenes** — not flat-albedo texture drops.
Evidence there: per-channel ratios ≈ 1.0, channel means matched Cycles, and SSIM
*climbed with samples* (32→256 spp) — the [[mc-noise-vs-deterministic]] signature
of a convergence-rate difference, not a translation bug. The real pkg119-B fix
was harness triage hardening (route ratio≈1.0 + small-dE + spp-climbing-low-SSIM
to a noise bucket), plus a lit backdrop for degenerate scenes.

**Hard requirement (acceptance-blocking):** before this package attributes ANY
pkg119-B residual to "missing procedural support", **re-baseline pkg119-B with
the noise/under-converged triage fix in place** ([[pkg119b-harness-runbook]]
run recipe: OpenMP-OFF `build_blender_addon_cuda`, `ASTRORAY_PYD_DIR` pointed at
it, absolute out-dir). Classify each of the 5 residuals into: (a) genuine
flat-albedo procedural drop that GPU eval fixes, (b) noise/convergence
false-positive (route to noise bucket, out-of-scope for this package), (c) a
Phase-A intentional-divergence / APPROXIMATED node. Record the split in Lessons.
Only the (a) set is this package's parity payoff — do not chase phantom bugs in
(b)/(c).

---

## Register pressure is the #1 design constraint (read before choosing an approach)

`stageShadeBucketedKernel` / `shadePathSlot` is pinned at **REG:254**
([[wavefront-shade-kernels-register-saturated]]). Porting a Perlin/Musgrave/
Voronoi/Wave evaluator into the shade path means heavy per-hit live state that
**spills ~2KB and tanks perf on the shared kernel** — this is exactly the
pkg178 lobe-array class of regression ([[closure-graph-lobe-count-spills-fused-kernel]]).
An image fetch was one cheap texel read; a procedural node is an arithmetic
kernel with gradients, hash tables, and octave loops.

**The untextured-fleet identity gate is a HARD acceptance criterion.** The
pre-pkg186 baseline for the shared untextured non-principled kernel
`stageShadeBucketedKernel<false,false>`, measured on **native sm_120 post-link**,
is:

> **REG:254  STACK:3608  CONSTANT[0]:1700**

Any procedural-eval design MUST leave this triple bit-identical (pkg186 restored
it after moving the texture pointers to `__constant__`). Measure with
`cuobjdump --dump-resource-usage` on a **native-arch** build — force
`-DASTRORAY_CUDA_ARCHS=native -DCMAKE_CUDA_ARCHITECTURES=native` and verify
`cuobjdump <pyd> -lelf` shows `sm_120` only; a stale arch-52 cache silently
mis-reports (the pkg183 fleet bug; pkg186 mis-read STACK 2640 this way).

### Candidate isolation strategies (genuine forks — pick per measurement, record why)

These are the real axes, not a manufactured menu. Decide by which keeps the
`<false,false>` identity AND holds perf on procedural scenes:

1. **Bake at upload time.** Evaluate the procedural node on the host (or a
   one-shot device pre-pass) into a device texel buffer, then reuse the pkg186
   image-fetch path verbatim (`gpu_sampleImageTexture` + the throughput fold).
   Zero shade-kernel codegen; maps onto the pkg186 `<...,HasTexture>` pattern
   with no new spill. Cost: resolution/quality of the bake, no procedural
   detail beyond the baked grid, and unbounded-domain nodes (world-space noise)
   need a domain/UV convention. This is the strong default for parity-first —
   it is the least register-risk path and reuses the proven pkg186 machinery.
2. **Separate procedural-evaluation stage.** A dedicated wavefront stage that
   evaluates procedural nodes into a per-path scratch albedo BEFORE
   `stageShadeBucketed`, so the shade kernel stays a cheap read. Cost: a new
   SoA field (per-path evaluated color) and a stage launch; must confirm the
   field does not itself spill the shade kernel.
3. **In-shade eval under `template<bool HasProcedural>`.** Follow the pkg186
   `<HasPrincipled,HasTexture>` pattern: gate procedural evaluators behind a
   compile-time bool so untextured/non-procedural scenes `if constexpr`-compile
   them out entirely. Cost: the procedural *specialization* itself will be
   register-heavy and slow — acceptable only if the `<...,false>` fleet kernel
   is provably unchanged AND the procedural specialization's perf is measured
   and acceptable. Highest risk of the three; use only if bake-at-upload cannot
   represent a required node.

Bias toward (1) bake-at-upload unless a specific node family demands live eval;
if you choose (2) or (3), the burden is a measured perf A/B on procedural scenes
plus the identity gate on the untextured kernel.

---

## Also fold in — PR #590 cycles-parity review advisories (from the pkg186 review)

These were raised advisory on PR #590 and deferred with the procedural slice:

1. **Harden the texture-fold divide guard.**
   `src/gpu/wavefront/stage_advance.cu:557` currently does
   `throughput.v[s] *= (d > 1e-8f ? texUp[s] / d : 0.0f)` where
   `d = upsample(baseColor)[s]`. For pkg186's near-gray base colors this is
   benign, but a **saturated / non-gray `baseColor`** (which procedural + textured
   metals will produce) makes `texUp / upsample(baseColor)` a **real per-λ
   spectral bias** — the division skews the exit spectrum, not just guards a
   zero. Fix: clamp the denominator, or divide by a **fixed neutral reference**
   (e.g. a flat-1.0 / D65-gray upsample) rather than the material's own saturated
   base upsample, so the substitution stays an exact albedo swap independent of
   baseColor chroma. State the chosen convention and prove it exact on a
   saturated-base test.
2. **Cover or explicitly exclude RGB-texture × non-visible-band.** The
   `gpu_rgbToSampledSpectrum(texColor, …)` × **`useLuminanceOutput`** (non-visible
   / luminance-only band) combination is **untested** in pkg186. Either add a
   parity leg for it or add an explicit guard + documented exclusion (a comment +
   a test asserting the exclusion path). Do not leave it silently undefined.
3. **Add a `textured_plane` parity scene to `scripts/run_parity.py`.** A
   UV-mapped quad with a low-frequency checker/gradient texture, a diffuse floor,
   and one area light. Oracle is **CPU/GPU per-channel mean-ratio**, never SSIM
   (independent RNG streams; [[ssim-wrong-gate-for-independent-rng]]). Wire it
   into the scene manifest the loader reads (`_load_scenes` / the parity scenes
   TOML), so both the image slice (pkg186) and this procedural slice have a
   standing parity scene. For the procedural half, extend it with a procedural
   (checker/gradient node) variant once GPU eval lands.

---

## Filtering is parity-coupled — record as a constraint

pkg186 shipped **nearest-neighbour** image sampling to match CPU
`ImageTexture::value` (clamp uv→[0,1], flip v, floor to texel) bit-for-bit; a
`cudaTextureObject_t` hardware-bilinear path would DIVERGE from the CPU sampler
and fail the mean-ratio gate. **This coupling is a hard constraint for any baked
procedural buffer too:** if the CPU procedural evaluator is point-sampled, the
GPU bake must be point-sampled at the same grid; if CPU ever gains bilinear
filtering, GPU must follow **in lockstep** in the same change. Do not
unilaterally add GPU filtering. Record this decision explicitly (mirror pkg186's
"Decision 2" note).

---

## Work

1. **Re-baseline pkg119-B first** (premise-trap section). Classify the 5
   residuals into (a) genuine flat-albedo procedural drop / (b) noise
   false-positive / (c) intentional-divergence. Only (a) scopes this package's
   node coverage. Record the split.
2. **Pick the isolation strategy** (bake-at-upload default; separate stage or
   in-shade template only with a measured justification). Implement GPU
   evaluation for the (a)-set procedural node families identified in step 1 —
   do not implement nodes nothing in the parity set exercises.
3. **Wire the fold-guard fix** at `stage_advance.cu:557` (divide by a neutral
   reference / clamp) so the substitution is exact for saturated base colors,
   and prove it on a saturated-base test.
4. **Cover RGB-texture × `useLuminanceOutput`** — parity leg or explicit guarded
   exclusion + test.
5. **Add the `textured_plane` parity scene** to `scripts/run_parity.py` (+ its
   procedural variant) with a per-channel mean-ratio oracle.
6. **Re-run pkg119-B** post-fix and record the (a)-set reclassification
   (before/after counts). A/B the untextured + non-procedural wavefront perf.

## Acceptance criteria

- [ ] **pkg119-B re-baselined with the noise-triage fix BEFORE any bug
      attribution**; the 5 residuals split into (a)/(b)/(c) and recorded. No
      residual is attributed to "missing procedural support" without the
      re-baseline evidence.
- [ ] A procedural-textured material (from the (a)-set) renders its procedural
      pattern — **not flat albedo** — on the GPU wavefront path, gated by a new
      test, and **visually confirmed** (metrics pass on garbage;
      [[general-photon-loop-needs-solid-glass]]).
- [ ] CPU/GPU **per-channel mean-ratio** within band on the procedural scene
      (never SSIM).
- [ ] **Untextured-fleet identity gate (HARD):** native sm_120 post-link
      `cuobjdump` shows `stageShadeBucketedKernel<false,false>` =
      **REG:254 STACK:3608 CONSTANT[0]:1700**, bit-identical to the pkg186
      baseline. No spill on the non-procedural specialization; measured perf A/B
      on procedural scenes recorded.
- [ ] `stage_advance.cu:557` fold-guard divides by a neutral reference /
      clamped denominator; a **saturated-base-color** test proves the albedo
      swap is exact and unbiased.
- [ ] RGB-texture × `useLuminanceOutput` is either covered by a parity leg or
      explicitly guarded + asserted-excluded by a test.
- [ ] `textured_plane` parity scene lives in `scripts/run_parity.py`'s scene
      set with a per-channel mean-ratio oracle.
- [ ] Filtering-parity constraint recorded (nearest to match CPU;
      bilinear only in lockstep with CPU).

## Hard non-goals

- **No CPU-bilinear / GPU-bilinear divergence.** Filtering stays parity-coupled
  and nearest until CPU changes; no unilateral GPU filtering.
- **No node families nothing exercises.** Implement only the (a)-set procedural
  nodes the re-baselined pkg119-B / parity scene actually hit. No speculative
  Perlin/Musgrave/Voronoi coverage "for completeness."
- **No spill on the `<...,false>` fleet kernel.** The identity gate is
  non-negotiable; the procedural cost is paid only by procedural scenes.
- **No SMS-GPU / photon-path work** (that is pkg189's spectral scope);
  the textured photon-caustic receiver stays base-albedo (pkg186 documented
  cut) unless the (a)-set forces it, in which case scope a separate follow-up.
- **No instanced-mesh procedural UV** (object-local barycentrics — same cut
  pkg178/pkg186 took for instanced anisotropy/texture).

---

## Hardware verification 2026-08-14 (PR #612, independent re-verification)

**Hardware/software:** RTX 5070 Ti, driver 610.47, compute cap 12.0 (sm_120),
CUDA 12.8.61 (nvcc), CUDA 12.6 also present but unused, OptiX 9.1.0, OIDN
2.4.1, Windows 11 Enterprise 10.0.26200, MSVC 19.44.35208 (VS2022 Build
Tools 17.0), Blender 5.2 (oracle for pkg119-B), Python 3.13.12.

Verified in the implementer worktree `Astroray-pkg190` at branch `pkg190`
HEAD `d1994c0aad3ca55b2e0906b8d5893b853cd92488` (no rebase/push - HW-verify
branch freeze honored).

### 1. Clean rebuild

`build_cuda` did not exist in the worktree; ran a fresh CMake configure
(`-DASTRORAY_ENABLE_CUDA=ON -DASTRORAY_CUDA_ARCHS=native`, resolved to
`sm_120` via nvidia-smi) then `build_cuda_worktree.bat`. Build succeeded
(exit path through "Build succeeded"); pkg183 guards all green:
`arch-verify OK: astroray.cp313-win_amd64.pyd embeds sm_120 (embedded=[sm_120])`,
ABI canary caps `{cpu: True, spectral: True, gpu: True, gpu_spectral:
True, gpu_approximate: False, closure_graph: True, closure_count: 1}`.
`.pyd` mtime (2026-08-14 05:47) postdates HEAD commit (2026-08-14 05:37).
`cuobjdump --list-elf` shows a single sm_120 cubin, no stale fallback. Also
rebuilt the OpenMP-OFF Blender addon (`build_blender_addon_cuda`, required
for pkg119-B) since its cached `.pyd` (05:17) predated HEAD (05:37).

### 2. Register-identity gate (HARD) - PASS

`cuobjdump --dump-resource-usage` on the freshly built native-sm_120
`astroray.cp313-win_amd64.pyd` shows all 16 stageShadeBucketedKernel
specializations (template axes HasPrincipled,HasTexture,HasPhotons,HasDispersion).
The untextured non-principled non-photon non-dispersion fleet kernel:

REG:254  STACK:3352  CONSTANT[0]:1700 for the all-false specialization

- bit-identical to the pinned baseline given in this verification's dispatch
(matches the PR's own re-derivation; the spec's older "3608" figure is the
HasPhotons-only variant on the now-4-axis template, also confirmed present
and independently reproduced here). Full table (REG always 254, CONSTANT[0]
always 1700, CONSTANT[2]:368 only present when HasPrincipled=1):

| HasPrincipled | HasTexture | HasPhotons | HasDispersion | STACK |
|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 7848 |
| 1 | 1 | 1 | 0 | 7848 |
| 1 | 1 | 0 | 1 | 7720 |
| 1 | 1 | 0 | 0 | 7720 |
| 1 | 0 | 1 | 1 | 7848 |
| 1 | 0 | 1 | 0 | 7848 |
| 1 | 0 | 0 | 1 | 7720 |
| 1 | 0 | 0 | 0 | 7720 |
| 0 | 1 | 1 | 1 | 3608 |
| 0 | 1 | 1 | 0 | 3608 |
| 0 | 1 | 0 | 1 | 3352 |
| 0 | 1 | 0 | 0 | 3352 |
| 0 | 0 | 1 | 1 | 3608 |
| 0 | 0 | 1 | 0 | 3608 |
| 0 | 0 | 0 | 1 | 3352 |
| 0 | 0 | 0 | 0 | 3352 (fleet baseline) |

Notably, HasTexture alone never changes STACK at any fixed
(HasPrincipled,HasPhotons,HasDispersion) combination - the pkg190 3D/2D bake
fetch is exactly as cheap as the pkg186 2D-only fetch it replaces; the whole
axis is register-neutral, stronger evidence than just the all-false cell
holding.

Methodology note: main's cached build_cuda .pyd was stale relative to
current main HEAD (main gained pkg199's world-volume GPU wavefront commit,
which touches the shade path, after pkg190 branched) - rebuilding main
fresh purely for a byte-diff was judged unnecessary busywork given (a) the
dispatch's pinned baseline numbers matched exactly, and (b) the internal
cross-check above (the HasPhotons-only cell reproducing the spec's older
"3608" figure) independently corroborates the pinned baseline's provenance.

### 3. pkg119-B reclassification - PASS, independently re-run

Re-ran the full harness (OpenMP-OFF build_blender_addon_cuda, Blender 5.2,
res64/spp16, SPP-escalation on) from scratch on this session's rebuild.
Summary: pass=30, skip=1, fail=8; Triage: NOISE-LIMITED=1,
INTENTIONAL-DIVERGENCE=7; Follow-up candidates (TRANSLATION-BUG): none.

The four (a)-set nodes, measured fresh (independent RNG from the PR's own
run, so small deltas are expected noise):

| node | PR-claimed SSIM | verifier-measured SSIM | dE2000 | status |
|---|---|---|---|---|
| TEX_CHECKER | 0.9512 | 0.9521 | 2.445 | PASS |
| TEX_BRICK | 0.9158 | 0.9156 | 2.664 | PASS |
| TEX_MAGIC | 0.9639 | 0.9656 | 2.706 | PASS |
| TEX_WAVE | 0.9575 | 0.9600 | 2.414 | PASS |

All deltas <= 0.0025, well inside MC-noise band. BSDF_GLASS escalated
16 to 64 spp and reclassified NOISE-LIMITED (ssim 0.8041 to 0.8676), matching
the PR's (b)-bucket claim; TEX_VORONOI passed cleanly outright (0.9710) this
run (also (b)-consistent - no escalation needed this time). The 7
INTENTIONAL-DIVERGENCE entries (BSDF_REFRACTION, BSDF_SHEEN,
BSDF_TRANSLUCENT, PRINCIPLED_VOLUME, VOLUME_ABSORPTION, VOLUME_SCATTER,
WAVELENGTH) match the PR's (c)-bucket. TRANSLATION-BUG count independently
confirmed at 0 (was 4 pre-pkg190 per the PR's own re-baseline).

### 4. pkg190 test suite + textured_plane parity scene

tests/test_pkg190_gpu_procedural_texture.py - 4/4 PASSED
(test_gpu_procedural_is_not_flat, test_cpu_gpu_procedural_parity,
test_saturated_base_is_neutralised, test_rgb_texture_luminance_band_covered).

scripts/run_parity.py --scene textured_plane - BROKEN CLI ENTRYPOINT (bug
introduced by this PR's own diff, confirmed via git diff main...HEAD --
scripts/run_parity.py). _render_once's astroray-engine branch guard
("if scene.scene_id == 'cornell' or scene.blend_path is not None:") was not
updated to include scene.scene_id == "textured_plane", so the scene falls
through to the standalone-binary branch, which requires a
raytracer_standalone/raytracer.exe this worktree never builds (the default
build wrapper only builds astroray + astroray_test_helpers) - and even if
built, apps/main.cpp only implements --scene 1 (Cornell); the
astroray_scene_id=2 textured_plane never had a native-binary counterpart.
Reproduced verbatim:

  python scripts/run_parity.py --scene textured_plane --engine astroray-cpu --engine astroray-gpu --runs 1
  -> CSV: textured_plane,astroray-cpu,64,,,,,astroray_binary_not_found
          textured_plane,astroray-gpu,64,,,,,astroray_binary_not_found

The PR's _astroray_textured_plane_script function (correctly implementing
the intended CPU/GPU-comparable scene) is wired into _astroray_script() at
the scene_id == "textured_plane" special-case, but that function is itself
unreachable from _render_once for this scene - dead code as shipped, so the
PR's claimed "Measured CPU/GPU mean-ratio: 1.000/1.000/1.000" could not have
been produced by running the documented command against this commit.

Independently re-verified the underlying render+ratio logic by invoking
_astroray_textured_plane_script directly (bypassing the broken CLI route,
same script content, same subprocess env) and reading the resulting EXRs
with a verified-correct float32 codec (imageio's default .exr codec in this
environment silently mis-decodes as truncated uint8 - a verifier
environment pitfall, not an engine bug; cv2 with
OPENCV_IO_ENABLE_OPENEXR=1 reads the true float32 data, ~65k unique values
per channel, confirming genuine MC-noise-textured output, not a degenerate
render):

  CPU means (r,g,b) = 0.23408, 0.10765, 0.24488
  GPU means (r,g,b) = 0.23408, 0.10760, 0.24483
  GPU/CPU mean-ratio = 1.0000 / 0.9996 / 0.9998

This confirms the underlying procedural CPU/GPU parity claim is real and
matches the PR's number to within measurement noise (single-run vs their
presumably multi-run median) - the feature works; the deliverable
("textured_plane parity scene lives in scripts/run_parity.py's scene set")
does not, as shipped, function via its own documented CLI. This is an
explicit, enumerated acceptance criterion in this spec and is FAILING at
the CLI-reproducibility level despite the underlying numbers being sound.

### 5. Visual inspection - PASS, no artifacts

Read all 5 evidence PNGs in test_results/pkg190_evidence/ (contact sheet +
per-node checker/brick/magic/wave Cycles-vs-Astroray-GPU comparisons).
Additionally rendered a fresh independent set myself: converted the raw
.npy legs from this session's own pkg119-B harness run
(test_results/pkg190_verifier_pkg119b/renders/shader_node__{TEX_CHECKER,
TEX_BRICK,TEX_MAGIC,TEX_WAVE}__{cycles,custom_raytracer}.npy) to tonemapped
side-by-side PNGs and inspected them directly.

Both the committed evidence and my fresh renders show: checker squares
aligned in position/scale/color between Cycles and Astroray-GPU; brick
pattern present with matching layout (Astroray's is visibly smoother/less
bump-perturbed than Cycles' - expected, the bake is a flat-color 3D lookup
with no normal-map contribution, not a defect); magic swirl matching
frequency/color scheme; wave stripes matching orientation and spacing. No
fireflies, no magenta/black NaN pixels, no half-voxel shift, no banding, no
mode regression (still monochrome/RGB as expected, no spectral leakage).

### 6. Regression slice - PASS

Ran (task-scoped subset, not the PR's full claimed 52+14):
tests/test_pkg186_gpu_texture_parity.py (2), tests/test_pkg186_gpu_features_guard.py
(7), tests/test_gpu_multiwavelength.py (6), plus pkg190's own 4 - 19/19
PASSED in 7.30s. No regression in the pkg186 HasTexture image path or the
spectral GPU multiwavelength path from pkg190's changes.

### Anomalies / follow-ups

1. scripts/run_parity.py textured_plane routing bug (BLOCKING) - see
   section 4 above. One-line fix: add "or scene.scene_id ==
   'textured_plane'" to _render_once's astroray-engine branch guard (line
   ~447). Must be fixed before this acceptance item can be considered
   closed; the underlying numbers are good but the deliverable doesn't run
   as documented.
2. No measured perf A/B on procedural scenes in the PR body, despite the
   spec's identity-gate acceptance bullet asking for one ("measured perf
   A/B on procedural scenes recorded"). The register-identity table above
   is strong indirect evidence (HasTexture is stack-neutral across the
   whole fleet), but no wall-clock/ms-per-frame number was provided or
   verified here.
3. Verifier-environment pitfall for future sessions: imageio.v3.imread /
   imwrite on .exr in this Python env silently truncates to uint8 (no
   working OpenEXR/freeimage plugin installed) - always cross-check any
   manual EXR read here with cv2.imread(path, cv2.IMREAD_UNCHANGED) (with
   OPENCV_IO_ENABLE_OPENEXR=1) before trusting a "looks degenerate" render.

### Verdict

HW FAIL - narrowly scoped. All hard gates that touch device correctness
pass cleanly with strong evidence (register-identity fleet gate, pkg119-B
reclassification 4 to 0, pkg190's own 4-test suite, pkg186/multiwavelength
regression slice, visual inspection on both committed and freshly-rendered
evidence). The failure is the textured_plane acceptance-criterion
deliverable itself: as shipped, "scripts/run_parity.py --scene
textured_plane" cannot produce the number the PR claims because of a
one-line routing-guard omission in this PR's own diff. Recommend: fix the
guard, re-run the CLI command, confirm the CSV actually populates
mean_ratio_cpu_gpu (expect approximately 1.00/1.00/1.00 per this session's
bypass measurement), and re-verify before merge. Do not merge as-is.

---

## Hardware verification 2026-08-14 addendum - scoped re-check (commit b2b42eb)

Coordinator reported the textured_plane routing bug fixed in commit
b2b42eb on branch pkg190. Scoped re-check performed: pulled the pkg190
worktree from d1994c0a to b2b42eb51fd6800a57dfb3450b7ea988026fc0ab.

Diff scope confirmed via `git diff --stat d1994c0a..HEAD`: **scripts/run_parity.py
only** (26 insertions, 11 deletions), no device code, no other file touched.
The diff (1) adds `scene.scene_id in ("cornell", "textured_plane")` to
`_render_once`'s astroray-engine branch guard, routing textured_plane to the
in-process `_astroray_script()` path as originally intended, and (2) adds a
`_read_exr_float` helper using `cv2.imread(path, cv2.IMREAD_UNCHANGED)`
(with `OPENCV_IO_ENABLE_OPENEXR=1`) in place of `imageio.v3.imread` for both
`_mean_ratio`'s legs - fixing the second defect this verifier's own bypass
diagnosis surfaced (imageio's default EXR plugin silently truncating to
uint8 and zeroing the green channel in this environment).

No CUDA rebuild was needed (python-script-only change; the already-built
`build_cuda`/`build_blender_addon_cuda` `.pyd`s from the prior session
remain valid for a scripts-only diff). GPU lock re-acquired for this
recheck and released promptly after.

Ran the documented command verbatim:

    python scripts/run_parity.py --scene textured_plane

Exit code **0**. Output CSV:

    textured_plane,cycles-cpu,64,,,,,textured_plane oracle is CPU/GPU mean-ratio (no Cycles leg)
    textured_plane,cycles-cuda,64,,,,,textured_plane oracle is CPU/GPU mean-ratio (no Cycles leg)
    textured_plane,astroray-cpu,64,1381.545,78.4,,,
    textured_plane,astroray-gpu,64,555.760,260.2,,"1.0000,0.9996,0.9998",

`mean_ratio_cpu_gpu` = **1.0000 / 0.9996 / 0.9998** - green channel is sane
(not NaN, not zero), and this is an **exact match** to the number this
verifier independently derived via the bypass method in the original
session (before the fix existed), which is strong corroboration that both
the fix and the original bypass measurement are correct and that nothing
else changed underneath.

All other findings from the 2026-08-14 verification above are unaffected
(diff scope confirms it - register-identity gate, pkg119-B reclassification,
pkg190 test suite, regression slice, and visual inspection all stand as
previously reported and require no re-verification).

### Updated verdict: HW PASS

The single blocking defect (textured_plane CLI routing) is fixed and
independently re-confirmed on hardware. Combined with the prior session's
clean results on every other gate, PR #612 is **HW PASS**.

## Hardware verification 2026-08-14 (PR #615)

Independent RTX hardware verification of PR #615 ("fix(pkg190): narrow
non-UV procedural bake to Generated coord mode", follow-up to PR #612's
review finding that Object-coord procedurals were incorrectly baked into
the normalized Generated voxel domain). Code review: SIGN-OFF. CI: 6/6
green. Verified under `.astroray_plan/.orchestrator.gpu.lock`.

**Hardware/toolchain:**
- GPU: NVIDIA GeForce RTX 5070 Ti, driver 610.47, 16303 MiB
- CUDA: nvcc release 12.8, V12.8.61 (arch gate: `cuobjdump` confirms
  `astroray.cp313-win_amd64.pyd` embeds `sm_120` only — `[pkg183] arch-verify
  OK: astroray.cp313-win_amd64.pyd embeds sm_120 (embedded=[sm_120])`)
- OptiX 9.1.0, OIDN 2.4.1
- Build: fresh worktree `Astroray-hw615` (`git worktree add --detach` at
  `3b3409b269120151cea7d2df4f59c406cec51a9e`, matches PR #615 head SHA),
  configured with `configure_and_build.bat`'s cmake invocation (VS 2022
  generator, `ASTRORAY_CUDA_ARCHS=native`), built via `build_cuda_worktree.bat`.
  `[pkg183]` ABI canary passed: `{'cpu': True, 'spectral': True, 'gpu': True,
  'gpu_spectral': True, 'gpu_approximate': False, 'closure_graph': True,
  'closure_count': 1, 'gpu_type': 'closure_graph', 'notes': 'spectral
  closure-graph GPU lowering'}`.
- `.pyd` mtime: 2026-08-14 20:30 (fresh vs HEAD commit time 2026-08-14
  08:52:24 +1000) — no staleness. `astroray.__file__` resolved to the
  canonical `build_cuda/Release/astroray.cp313-win_amd64.pyd` in the
  worktree via `tests/runtime_setup.configure_test_imports()`.

**Smoke-check (pre-test):** `hasattr(r, 'create_procedural_texture')` =
`True`, `hasattr(r, 'set_texture_generated_bbox')` = `True`,
`gpu_available` = `True`, `astroray.__features__['cuda']` = `True`. No
stale-.pyd signature.

**Gate test run — `tests/test_pkg190_gpu_procedural_texture.py`
(`pytest tests/test_pkg190_gpu_procedural_texture.py -v -s --tb=short`):**

| Test | Result |
|---|---|
| test_gpu_procedural_is_not_flat | PASSED |
| test_cpu_gpu_procedural_parity | PASSED |
| test_saturated_base_is_neutralised | PASSED |
| test_rgb_texture_luminance_band_covered | PASSED |
| test_object_mode_procedural_cpu_evaluates | PASSED |
| test_object_mode_procedural_gpu_guarded_fallback | PASSED |

`6 passed in 1.29s` — matches PR body's claimed "6/6 passed (4 existing
gates + 2 new)" exactly.

**Non-regression — documented pkg190 gate, run verbatim
(`python scripts/run_parity.py --scene textured_plane`):**

```
scene,engine,samples,time_ms,peak_mem_mb,ssim_to_cycles,mean_ratio_cpu_gpu,skip_reason
textured_plane,cycles-cpu,64,,,,,textured_plane oracle is CPU/GPU mean-ratio (no Cycles leg)
textured_plane,cycles-cuda,64,,,,,textured_plane oracle is CPU/GPU mean-ratio (no Cycles leg)
textured_plane,astroray-cpu,64,1709.099,78.6,,,
textured_plane,astroray-gpu,64,563.697,259.7,,"1.0000,0.9996,0.9998",
```

`mean_ratio_cpu_gpu` = **1.0000 / 0.9996 / 0.9998** — byte-identical to the
pkg190 evidence block above (`1.0000,0.9996,0.9998`, `textured_plane,
astroray-cpu,64,1381.545,78.4` / `astroray-gpu,64,555.760,260.2`). Timing
differs (1709.099ms vs 1381.545ms CPU, 563.697ms vs 555.760ms GPU — normal
run-to-run system-load variance, not a correctness signal); peak_mem_mb and
the mean-ratio triple are unchanged. Confirms PR #615 does not regress the
Generated-coord bake path it narrows around.

**Behavior check — Object-coord guarded-fallback A/B (128x128, 96 spp,
seed=1, `apply_gamma=True`), rendered directly against the built `.pyd`:**

| Render | Mean pixel value (0-255) | Visual |
|---|---|---|
| `ab_generated_gpu.png` | 171.70 | Checkerboard, spatial red/blue contrast present (GPU bakes Generated-mode procedural, as before) |
| `ab_generated_cpu.png` | 163.73 | Checkerboard, vivid red/blue (CPU reference) |
| `ab_object_gpu.png` | 189.76 | **Flat uniform gray** — no checker pattern |
| `ab_object_cpu.png` | 165.29 | Checkerboard, vivid red/blue (CPU still evaluates Object-mode procedurals) |

The Object-mode pair is the load-bearing comparison: GPU renders flat gray
(the guarded getAlbedo() fallback) while CPU still renders the full
checkerboard (raw-objectPoint evaluation). This matches the PR's claimed
semantics exactly — Object-mode procedurals are no longer silently
misbaked into the normalized Generated voxel domain on GPU; they degrade
to the documented pre-pkg190 flat-albedo fallback, with CPU remaining the
reference. No fireflies, NaN pixels, banding, or mode regressions observed
in any of the four renders.

### Verdict: HW PASS

All five verification steps clean: fresh non-stale build (sm_120 arch gate
+ ABI canary), PR test suite 6/6 (matches PR body), pkg190 Generated-path
parity gate byte-identical to prior evidence, and the Object-mode guarded
fallback visually confirmed on hardware. PR #615 is **HW PASS**.
