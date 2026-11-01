# pkg234 research: Cycles Image Texture interpolation and extension (Blender v5.2.0)

Architect review, 2026-11-01. Sources were fetched from `github.com/blender/blender` tag `v5.2.0`, Apache-2.0
(compatible). Paths are relative to `intern/cycles/`. Our line numbers are on origin/main `000cd943`.

## Cycles semantics

**Texel convention.** `kernel_image_interp` scales uv to pixels, `xy = uv * (width, height)`
(`kernel/device/cpu/image.h:363-365`). Rows count from the bottom.
- Closest: `ix = floor(x)`, `iy = floor(y)` (`cpu/image.h:135-168`).
- Linear: taps around `x - 0.5`, `frac(x - 0.5f, &ix)` (`cpu/image.h:170-222`), so texel centres sit at `(i + 0.5) / w`.
- Cubic: same `-0.5` centring with a 4x4 footprint (`cpu/image.h:224-311`).

**Extension.**
- REPEAT: `wrap_periodic`.
- EXTEND: `wrap_clamp`.
- MIRROR: `wrap_mirror`, symmetric, with texel -1 mapping to 0.
- CLIP: `read_clip` returns zero outside the image. Edge taps therefore blend toward 0, which darkens the outer half-texel.

All four apply per tap, on integer indices (`cpu/image.h:110-131, 182-216, 238-289`).

**Cubic kernel.** Uniform cubic **B-spline**, not Catmull-Rom.
- CPU weights: `SET_CUBIC_SPLINE_WEIGHTS` (`cpu/image.h:21-27`).
- GPU uses the same basis, `cubic_w0..w3`, evaluated as four hardware-bilinear lookups (`kernel/device/gpu/image.h:21-86`).
- The B-spline approximates: it smooths, and a texel centre does not reproduce the texel value.

**Smart.**
- SVM: identical to Cubic. On CPU, `interp()` sends every non-Closest, non-Linear mode to `interp_cubic` (`cpu/image.h:313-323`). On GPU, `CUBIC || SMART` selects bicubic (`gpu/image.h:136, 148`).
- OSL: Blender images go through `kernel_image_interp_with_udim` (`kernel/osl/services_shared.h:721, 847`), so OIIO's `smartcubic` string is not consulted for them.

**Default.** `SOCKET_ENUM(interpolation, ..., INTERPOLATION_LINEAR)` (`scene/shader_nodes.cpp:266`). The Blender sync reads `b_node.interpolation`, which falls back to Linear when invalid (`blender/shader.cpp:93-98`), and sets it per node (`blender/shader.cpp:903`). Extension is read the same way (`blender/shader.cpp:100-104, 904`).

**Colour-space order.**
- 8-bit sRGB images are stored sRGB-encoded "to save memory and/or loading time" (`util/image_metadata.cpp:132-135`, `is_compressible_as_srgb`).
- The kernel filters the encoded values, then decodes: `svm_image_texture` calls interp, then unassociates, then applies `color_srgb_to_linear_v4` when `NODE_IMAGE_COMPRESS_AS_SRGB` is set (`kernel/svm/image.h:22-38`; flag set at `scene/shader_nodes.cpp:441-447`).
- Blender-side byte images arrive as BYTE4 with the image's colour space (`blender/image.cpp:84-90`).
- Float images are already scene-linear (`blender/image.cpp:72-83`) and are filtered linear.
- Other OCIO spaces are converted to half linear at load (`util/image_metadata.cpp:137-145`), so they are filtered linear too.

**Alpha.**
- Blender byte images are flagged unassociated (`blender/image.cpp:62`) and premultiplied at load (`util/image_metadata.cpp:489-497`).
- The kernel unassociates only when the node's Alpha output is linked (`scene/shader_nodes.cpp:448-455`, `svm/image.h:28-31`).
- So with Alpha unlinked, Color is premultiplied.

**Mip / texture cache.**
- The tiled, mipmapped path (`kernel/util/image_2d.h:75-190`) runs only when `use_texture_cache` is set (`blender/sync.cpp:1020-1021`; `scene/image.cpp:493`) and the image has tiles and mipmaps.
- It is opt-in under Render > Performance > Texture Cache (Blender 5.2 LTS).
- Without it, Cycles samples the full image with no footprint filtering (`cpu/image.h:357-366`).

**GPU precision.** Cycles CUDA Closest/Linear use texture objects with hardware filtering, so the weights are 8-bit fixed point. Cycles **CPU** is the bit-level reference.

## Astroray today (origin/main 000cd943)

**CPU sampler.**
- `ImageTexture::value` is nearest only (`include/advanced_features.h:488-501`).
- The extension is honoured since #1004 (`:461, 483-487, 490-495`).
- `valueLinear` is the bump/normal-only bilinear sampler (`:503-513`). It taps through `value()`.
- `sampleSpectral` reads a per-texel `RGBAlbedoSpectrum` cache built in `setData` (`:465-475, 514-534`).

**Shared HD helpers** (`include/astroray/gpu_types.h`).
- `GImageTexture` (`:702-751`) already carries `extension` (`:731-733`). It sits in global memory behind `c_wfTexBinding.textures` (`:760-762`), so a new int field adds no kernel parameter.
- `GImgExt` (`:950`).
- `gpu_imageWrapTexel` (`:969-984`).
- `gpu_sampleImageTexture`, nearest (`:989-1005`).
- `gpu_imageLinearTaps` (`:1012-1024`), the Cycles `interp_linear` footprint.
- `gpu_sampleImageTextureLinear` (`:1033-1041`), whose taps go through the nearest sampler so extension wrapping is shared.
- Checked by hand against `wrap_*`: the tap-through-nearest scheme reproduces Cycles for all four extensions, including CLIP's zero taps and MIRROR's `-1 -> 0`.

**GPU nearest call sites.**
- `stage_advance_device.cuh:2816`: base colour in the `HasTexture` shade block (`:2734`), on the REG:254 fused path.
- `:1354`: `gpu_progInputTexel`, the program / graph inputs.
- `:1469`: sphere emitter.
- `stage_graph_eval.cu:80`: `tex_coord`.
- The bump/normal Linear reads at `stage_advance_device.cuh:2466, 2544-2546` are explicit.

**Spectral on GPU.** The GPU upsamples the sampled RGB per lambda: `gpu_rgbToSampledSpectrum(texColor, ...)` (`stage_advance_device.cuh:2868-2869`).

**Upload.**
- Texels are linear float RGB (`Vec3` / `GVec3`), copied verbatim to the device buffer (`src/gpu/scene_upload.cu:978-988`). `desc.extension` is set at `:991`.
- The addon decodes 8-bit sRGB to linear before upload (`blender_addon/__init__.py:4228-4229`) and drops alpha (`:4215`).

**Addon.**
- The extension is read and set through `set_texture_extension` (`:4240-4246`; binding `module/blender_module.cpp:373-384, 701-704, 4242`), and is part of the cache key (`:4162-4163`).
- Interpolation is only reported:
  - `_report_image_interpolation` (`:3530-3537`) is called at `:4652, 4878, 5029`.
  - The graph-coord load (`:5023-5027`) does not report at all.
  - Bump/normal reads are forced Linear and report non-Linear (`:3539-3546`).

## The colour-space order on the probe texture

The `img_interp` probe image is a 4x4 `uniform(0.05, 0.95)` 8-bit sRGB PNG (`tests/pkg321_probe_blender.py:553-562`). A numpy model, dense uv, REPEAT, 8-bit quantised, gives:
- Mean value: 0.284.
- |Linear - Closest|: 0.096 in linear space, 0.095 in Cycles order.
- |Cycles order - linear order|: **0.032**, with a signed mean of **-0.032**.

So Cycles' order is darker everywhere, by about 11 % of the mean on this adversarial texture. Decoding is convex, so filtering encoded values lowers the mean (Jensen). Linear-space filtering preserves the texel mean. The term grows with the contrast between neighbouring texels and with magnification. Photographic textures at normal magnification show much less.
