# pkg234 — Honor Blender Image Texture filtering

**Pillar:** 5
**Track:** A
**Status:** open — architect-reviewed 2026-11-01, implementation-ready; one owner confirmation pending (colour-space order, see Key design decisions)
**Estimated effort:** 2 sessions (~7 h): Phase 1 + 1b in one lane (~5 h incl. one CUDA build + register probe), closeout HW / corpus / probe (~2 h); Phase 2 only if the owner picks Cycles order (+~3 h)
**Depends on:** pkg230

---

## Goal

**Before:** every Image Texture is sampled nearest-neighbour on CPU and GPU. Linear (Cycles' default), Cubic and Smart all render as Closest, so magnified textures show texel blocks (#1215).
- In the probe `img_interp`, Cycles moves the render by d_ab 4.4e-2.
- Astroray's render does not change at all (d_ab 0).

**After:** every Image Texture node's Interpolation is honoured, per texture, on CPU and GPU.
- **Closest:** unchanged and byte-identical.
- **Linear:** Cycles `interp_linear`.
- **Cubic:** Cycles' uniform cubic B-spline.
- **Smart:** same as Cubic, as in Cycles SVM.
- All four extensions are honoured.
- The pkg328 DegradationReport line for interpolation goes away.

---

## Context

Row (e) high #1215 was rated high by both Sonnet raters (STATUS 2026-11-01). Linear is Blender's default, so almost every real textured scene diverges from Cycles today. That makes this a Pillar 5 (Blender/DCC fidelity) correctness gap with wide reach.

The extension half is already done:
- #1004 landed per-texture extension (REPEAT / EXTEND / CLIP / MIRROR) on both backends.
- #1004 also landed a Cycles-exact bilinear footprint, used only by the bump/normal reads.

This package generalises that sampler to the base path and adds the mode plumbing.

Routing:
- **Implementer:** one lane on Sonnet 5.5, effort `high`. This is multi-file CPU + CUDA + addon work on a register-saturated kernel, the profile where the DeepSeek delegate tier stalls (memory `delegate-tier-stalls-on-hard-packages`).
- **Grunt sub-steps** (numpy reference, mock updates): may go to DeepSeek V4.1 Flash.
- **Review:** Opus `cycles-parity-reviewer` plus `cpp-abi-guard` on the descriptor change. Codex is out of quota until 11-04.
- **Builds:** the lead runs them; lanes never poll builds.

---

## Evidence

- 2026-11-01: pkg328 probe `img_interp` (4x4 random 8-bit sRGB PNG on a UV sphere, CPU 64 spp, 80x80). Cycles d_ab = 4.4e-2; Astroray CPU d_ab = 0 (#1215).
- 2026-11-01, architect review. Cycles v5.2.0 semantics are pinned with file:line in `.astroray_plan/docs/pkg234-texture-filtering-research.md`:
  - Texel centres at `(i + 0.5) / w`.
  - Cubic = B-spline.
  - Smart = Cubic in SVM and for Blender images in OSL.
  - No mip filtering unless the opt-in Texture Cache is on.
  - 8-bit sRGB images are filtered **sRGB-encoded, then decoded**.
- 2026-11-01: numpy model of the probe texture. Filtering in Cycles' encoded order instead of linear space shifts the mean by **-0.032** (about -11 % of the 0.284 mean), every sample darker. For scale, Linear vs Closest in linear space is 0.096.
- 2026-09-06: filing review, SIGN-OFF TO FILE ONLY (`test_results/pkg232-235/claude-filing-review.txt`).

---

## Reference

- Research note (Cycles semantics, our code map, order-term numbers): `.astroray_plan/docs/pkg234-texture-filtering-research.md`.
- Cycles v5.2.0 (Apache-2.0):
  - `intern/cycles/kernel/device/cpu/image.h:21-323`: closest / linear / cubic and the wraps.
  - `kernel/device/gpu/image.h:21-157`: B-spline via bilinear; Smart.
  - `kernel/svm/image.h:22-38`: unassociate, then sRGB decode after interpolation.
  - `scene/shader_nodes.cpp:261-266, 441-455`: default Linear; flags.
  - `util/image_metadata.cpp:123-145, 489-497`: sRGB compression; alpha association.
- Prior art in this repo:
  - #1004 sampler and extension: `include/astroray/gpu_types.h:950-1041`, `include/advanced_features.h:457-534`, `.astroray_plan/docs/issue1004-1005-bump-research.md`.
  - pkg186 GPU texture binding: `gpu_types.h:753-762`.
- Register / perf precedent (memory):
  - `noinline-runtime-flag-avoids-shade-spill`.
  - `pointer-params-on-fused-shade-path-cost-4pct`.
  - `shade-axis-side-table-avoids-spill`.
  - `gpu-perf-ab-clock-drift`.

---

## Prerequisites

- [ ] Worktree from current origin/main. One-time cmake configure per memory `worktree-build-configure-and-sha`.
- [ ] Baseline `cuobjdump -res-usage` of the **live** main `.pyd`, saved before any edit (STATUS numbers drift). It must cover:
  - every `stageShadeBucketedKernel` specialisation,
  - `stageGraphEvalKernel`,
  - the program / `HasNormalPerturb` kernels.
- [ ] Owner answer on the colour-space order (below). Phase 1 does not wait for it.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg234_image_filtering.py` | CPU texel-exact tests against a numpy port of Cycles `interp_linear` / `interp_cubic`; CPU-vs-GPU render twins; Closest regression; addon plumbing (see acceptance) |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | `enum GImgInterp { G_IMG_CLOSEST=0, G_IMG_LINEAR=1, G_IMG_CUBIC=2 }`; `int interpolation = 0;` appended at the END of `GImageTexture`; today's nearest body renamed `gpu_sampleImageTextureClosest`; the Linear taps re-pointed to it; `gpu_imageCubicTaps` + `gpu_sampleImageTextureCubic` (Phase 1b); `gpu_sampleImageTexture` becomes the HD dispatcher |
| `include/advanced_features.h` | `ImageTexture`: `interpolation_` + setter/getter; `value()` dispatches; `valueLinear` / `valueCubic` tap through a private `valueClosest`; `sampleSpectral` non-Closest path |
| `src/gpu/wavefront/stage_advance_device.cuh` | device-only `__noinline__` wrapper `wf_sampleImageFiltered(int texId, float u, float v)`; the three nearest call sites (`:1354`, `:1469`, `:2816`) branch Closest-inline / wrapper |
| `src/gpu/wavefront/stage_graph_eval.cu` | `tex_coord` (`:77-82`) uses the same branch |
| `src/gpu/scene_upload.cu` | `desc.interpolation = img->getInterpolation();` beside `:991` |
| `module/blender_module.cpp` | `setTextureInterpolation(name, "Closest"/"Linear"/"Cubic"/"Smart")` (Smart → `G_IMG_CUBIC`, unknown → throw) beside `:373-384`; wrapper with `invalidateWavefrontMaterials()` beside `:701-704`; `.def("set_texture_interpolation", ...)` beside `:4242` |
| `blender_addon/__init__.py` | thread `interpolation` through `load_blender_image` / `_load_blender_image_resolved` (cache key, native call); drop `_report_image_interpolation` for honoured modes; Texture Cache report |
| `tests/pkg321_probe_blender.py` | add probes `img_interp_float` and `img_interp_cubic` beside `img_interp` (`:553-562`, table `:170`) |
| `tests/test_pkg321_dropped_row_probes.py` | `img_interp` row (`:97`) flips from inert to honoured; new rows |
| `tests/test_pkg328_b4_reported_drops.py` | `:122` classification, `:147-148`, `:209-215` re-pinned to honoured behaviour |
| `tests/test_issue981_gpu_scene_cache.py` | add a `_texture_interpolation` edit kind beside `_texture_extension` (`:161-162`) |
| `tests/test_blender_uv_plumbing.py` | mock renderer gains `set_texture_interpolation` (beside `:145`) if its assertions need it |
| `tests/test_pkg257_displacement_bump.py` | mock: same (`:199`) |
| `tests/test_pkg274_addon_gaps.py` | mock: same (`:187`) |
| `benchmarks/reference_corpus/scenes/manifest.json` | re-pinned bands for any production ROI this package moves (pbr_group), each with its attribution |

### Key design decisions

#### Cycles contract (pinned; do not re-derive)

- **Coordinates:** `x = u*w`, `y = v*h`, rows from the bottom. The existing V-flip in `gpu_imageWrapTexel` / the EXTEND path handles our top-first storage.
- **Linear:** footprint `x - 0.5` (`gpu_imageLinearTaps`, already Cycles-exact).
- **Cubic:** a 4x4 footprint at `x - 0.5` with the B-spline weights of `SET_CUBIC_SPLINE_WEIGHTS` (cpu/image.h:21-27). Use the CPU 16-tap form, not the GPU 4-bilinear trick: the two are equal in exact arithmetic, and the 16-tap form shares the extension handling.
- **Smart:** maps to Cubic at the binding.
- **Extension:** applied per tap by fetching each tap centre through `gpu_sampleImageTextureClosest`. This is the #1004 scheme, and it reproduces `wrap_periodic` / `wrap_clamp` / `wrap_mirror` / `read_clip` exactly.
- **Reference:** Cycles **CPU**. Cycles CUDA filters with 8-bit hardware weights.

#### Mode storage: on the texture descriptor, not a side table

- `GImageTexture` sits in global memory behind `c_wfTexBinding.textures` and is read only inside texture branches. An appended `int interpolation` therefore changes no kernel signature, `GMaterial` (640 B) or constant footprint. This is exactly how #1004 added `extension`.
- No `template<bool>` axis: the mode is per texture, not per material class, and a new axis would double the 128 shade specialisations for no gain.
- Untagged textures default to Closest. Every direct-API caller and existing test stays byte-identical. The addon tags every Image Texture node.

#### GPU register budget

The shade kernels are pinned at REG:254.
- **Shade sites:** each does `tdesc.interpolation == G_IMG_CLOSEST ? gpu_sampleImageTextureClosest(...) : wf_sampleImageFiltered(texId, uu, vv)`.
- **The wrapper** is `__device__ __noinline__ inline`. It takes scalars only and reads `c_wfTexBinding` itself (memory `noinline-runtime-flag-avoids-shade-spill`). It must NEVER take a pointer or reference to a caller local (memory `pointer-params-on-fused-shade-path-cost-4pct`: +4 % on scenes that never took the branch).
- **Host builds** (CPU wavefront / snapshot-parity) call the HD dispatcher `gpu_sampleImageTexture` directly.
- **Bump/normal reads** keep their explicit `gpu_sampleImageTextureLinear` and are unchanged.

#### Taps never re-enter the dispatcher

`valueLinear` today taps through `value()` (`advanced_features.h:510-511`). Once `value()` dispatches, that would filter twice. All tap helpers, CPU and GPU, must call the raw Closest fetch.

#### Spectral

- **GPU:** upsamples the filtered RGB (`stage_advance_device.cuh:2868-2869`).
- **CPU non-Closest:** `RGBAlbedoSpectrum(value(uv)).sample(lambdas)`, the same as the existing empty-cache branch (`advanced_features.h:516-519`). This keeps the twins equal by construction. Blending the four cached texel spectra instead would be a metameric, non-twin result.
- **CPU Closest:** keeps the per-texel cache.

#### One sampler family, two entry points

- Bump/normal and base colour share `gpu_imageLinearTaps` and the Closest fetch; there is no second implementation.
- Bump stays forced Linear with its existing report (`__init__.py:3539-3546`). Honouring Closest heights is out of scope; Cycles' footprint-based bump makes it a separate question.

#### Addon

- **Plumbing:**
  - Pass `getattr(node, 'interpolation', 'Linear')` at every TEX_IMAGE load: `:4653`, `:4879`, `:5026` (the graph-coord load, silent today), `:5030`.
  - Bump / normal loads (`:3475`, `:5114`, `:6404`) pass `'Linear'`.
  - The legacy base-colour fallback (`:6361`) passes the source node's value, or `'Linear'` when no node is found.
- **Cache key:** append `::interp=<mode>` when the mode is not Linear, the same pattern as `::ext=` (`:4162-4163`).
- **Native call:** `set_texture_interpolation` behind `hasattr`. An old module without it gets a visible DegradationReport entry, as for extension (`:4243-4246`).
- **Texture Cache:** when the scene enables Cycles' Texture Cache, report once that mip selection is not implemented. Read the RNA property name in Blender 5.2; do not hardcode it.

#### Colour-space order: owner fork; Phase 1 default = linear-space filtering

Cycles filters 8-bit sRGB images in encoded space and decodes afterwards (`svm/image.h:33-35`). This is a storage shortcut ("to save memory", `image_metadata.cpp:133-134`). Because the decode is convex, it lowers the mean of a magnified texture: -11 % on the probe texture.

**Phase 1 (linear-space filtering):**
- Keeps today's linear upload.
- Preserves the texel mean.
- Needs no storage change.
- Matches the owner rule "physics over Cycles look-parity" (2026-09-29).

**Phase 2 (Cycles order, only if the owner overrides):** a contained follow-up.
- Add `int srgbDecode` on the descriptor and in `ImageTexture`.
- The addon uploads encoded texels for non-Closest 8-bit sRGB images, skipping the decode at `__init__.py:4228-4229`.
- Decode after filtering in the dispatcher and in `valueLinear` / `gpu_sampleImageTextureLinear`.
- The spectral cache and `average()` decode first.
- Closest uploads stay decoded, so they remain byte-identical.

**Gate design (order-independent):**
- The kernel's parity gate is a **float scene-linear** probe (`img_interp_float`), where Cycles also filters linearly.
- The sRGB probe's Astroray-vs-Cycles residual must equal the numpy-predicted order term. That makes it a measured, documented divergence rather than an unexplained one.

#### Phases

1. **Phase 1, Linear (closes #1215):** CPU + GPU + binding + addon + tests + probes + corpus re-pin.
2. **Phase 1b, Cubic and Smart:** the same lane and PR. About 40 lines once the dispatcher exists, and the noinline wrapper absorbs the 16 taps. If Phase 1b alone breaks the register or perf gate:
   - ship Linear;
   - keep the Cubic/Smart DegradationReport line;
   - file the remainder.
3. **Phase 2, Cycles colour order:** conditional on the owner. Not needed otherwise.

No mip / footprint phase is needed: Cycles applies none without the opt-in Texture Cache. Phase 1 reports that case.

---

## Acceptance criteria

#### CPU contract (no GPU)

- [ ] `sample_named_texture` matches a numpy port of Cycles `interp_linear` / `interp_cubic` (cpu/image.h:170-311) within 1e-6 abs. Test texture: 5x3 random (non-square, non-power-of-two).
  - Covers all 4 extensions × {Linear, Cubic, Smart}.
  - UVs at texel centres (Linear reproduces the texel), texel edges, image borders, outside [0,1], negative, and ±1e4.
  - Closest-tagged and untagged textures match today's nearest fetch exactly.

#### CPU vs GPU twin

- [ ] The #1004 `_quad_render` pattern: a magnified 2x2 texture under Mapping scale 2, 64x64, same seed. For each extension × {Closest, Linear, Cubic}, the CPU-vs-GPU mean abs difference stays within the band the #1004 twin uses.
- [ ] Linear renders differ from Closest on both backends: the feature is not inert.
- [ ] Program-input, graph `tex_coord` and sphere-emitter sites each have one twin case.

#### Cycles-referenced probes (CPU leg and GPU leg)

- [ ] `img_interp_float`: the same 4x4 texels as `img_interp`, pre-decoded into a `float_buffer` scene-linear image; A Linear, B Closest. Required:
  - Astroray d_ab / Cycles d_ab in [0.85, 1.15].
  - Per variant, Astroray-vs-Cycles mean abs on the `.npy` renders ≤ the Closest variant's own Astroray-vs-Cycles value + 2·d_aa.
- [ ] `img_interp_cubic`: float image; A Cubic, B Closest. Same two bounds (Phase 1b).
- [ ] `img_interp` (sRGB 8-bit): Astroray now moves (d_ab > 3·d_aa).
  - Phase 1: the Linear-variant Astroray-vs-Cycles signed mean difference is within ±25 % of the numpy order term, computed in-test on the same texels and on the probe's UV mapping. Record it as a documented divergence.
  - Phase 2: this probe meets the float-probe bounds instead.

#### Regression

- [ ] Closest witnesses are byte-identical before and after on CPU, and within 1e-6 on GPU:
  - the corpus `image_card` (`benchmarks/reference_corpus/build_corpus.py:646`),
  - `VectorChart` (`benchmarks/blender_parity/scene_library.py:453`).
- [ ] Spectral consistency: textured CPU spectral vs GPU renders stay within the existing pkg186 twin band.

#### Corpus, GPU cache and tests

- [ ] Re-measure, and re-pin in this PR with attribution, every scene with a non-Closest Image Texture:
  - row (g) **pbr_group**: four Linear images, base sRGB, at `build_corpus.py:1413-1417`;
  - blender_parity **material_zoo** (`scene_library.py:887`);
  - blender_parity **textures_mapping** (`:1869`, `:1911`, `:2020`, `:2041`; all default Linear 16x16 float).

  Any ROI that leaves its band needs its cause measured before it is pinned. For a Cycles-only A/B, rebuild pbr_group with PbrBase as a float linear image.
- [ ] #981 cache test: an interpolation edit MISSes and re-renders. The OptiX and software traversal legs both pass.
- [ ] Addon tests:
  - the same image as Closest and Linear makes two cache entries;
  - `set_texture_interpolation` receives the node value at all seven load sites;
  - an old module without the binding gives a visible report;
  - no `#1215` report remains for honoured modes;
  - Texture Cache on gives a report.

#### Register and performance (GPU; hold `gpu.lock`)

- [ ] `cuobjdump -res-usage`, name-keyed against the saved main baseline:
  - every `HasTexture=false` shade specialisation is byte-identical (REG/STACK/CONSTANT);
  - `HasTexture=true`, program and graph kernels: REG ≤ 254, STACK delta ≤ +64 B per kernel, no new ptxas spill stores.

  No canonical script exists (`project_index.py script` found none on 2026-11-01). A reusable one goes into `scripts/README.md` (CLAUDE.md §5b).
- [ ] Interleaved main/branch timing: warm-up, then min-of-4, interleaved twice (memory `gpu-perf-ab-clock-drift`).
  - Untextured Principled scene: within 1 %.
  - Closest-textured scene: within 1 %.
  - Linear-textured scene: report Linear vs Closest cost on GPU and CPU; no gate.

#### Process

- [ ] Fresh build with the `.pyd` mtime newer than HEAD, and `astroray.__file__` loads the canonical build.
- [ ] Caller sweep covers every renamed / changed signature (`gpu_sampleImageTexture`, `ImageTexture::value`/`valueLinear`, `load_blender_image`, `_load_blender_image_resolved`), including mocks.
- [ ] Full local suite, without `-x`.
- [ ] RTX closeout sweep.
- [ ] Probe renders (Linear / Closest / Cubic, both engines) saved as small PNGs. The lead reviews them visually, alongside the numbers.
- [ ] Reviews: `cycles-parity-reviewer` and `cpp-abi-guard` (Opus) both clear.

---

## Non-goals

- No change to bump / normal-map sampling: forced Linear stays, and so does its report.
- No mip-mapping, ray differentials or Texture Cache emulation.
- No Environment Texture node interpolation (env lookups stay bilinear).
- No Box / Sphere / Tube projection.
- No UDIM.
- No alpha. Cycles' Color output is premultiplied for 8-bit images whose Alpha output is unlinked (`util/image_metadata.cpp:489-497`, `svm/image.h:28-31`), but the addon drops alpha (`__init__.py:4215`). This affects Closest too. The lead files it as its own issue.
- No hardware `cudaTextureObject_t` filtering. CPU/GPU twin parity needs the shared software sampler (pkg186 decision).
- No op-VM opcode or transport changes.
- No new UI.
- Pillar 4 stays paused.
- At most one implementation worktree.

---

## Progress

- [x] 2026-11-01: architect review. Contract pinned and the research note filed. Spec made implementation-ready.
- [ ] Phase 1: Linear on CPU + GPU + addon, with tests, probes and corpus re-pin.
- [ ] Phase 1b: Cubic / Smart.
- [ ] Phase 2: Cycles colour order (only on owner request).

---

## Lessons

- (none yet)
