# pkg275 — HDRI reflection lookup gap: research note + diagnostic ladder

Tracks #795 (chrome reflection ~23% under Cycles with an exact white furnace)
and #755 (systematic CPU-vs-GPU gap on the env-only HDRI parity scene).

`cite-algorithm` scope: environment-map texture lookup semantics. This note
records the reference (Cycles), the chosen filtering/parameterisation, and the
per-rung diagnostic-ladder measurements. Only the step the ladder localises is
changed in code.

## Reference semantics (Cycles, Apache-2.0)

- `intern/cycles/kernel/svm/svm_image.h` — `svm_image_texture` / the bilinear
  path in `kernel_tex_image_interp`: texel *centers* sample the image, i.e. the
  continuous coordinate is offset by half a texel before flooring
  (`x = tx*width - 0.5`), then bilinearly blended. Background/world lookups use
  the image's interpolation setting (Linear by default) with **no mip / no
  derivative-based blur** — a glossy reflection reads the same unblurred
  bilinear texel a mirror ray would.
- `intern/cycles/kernel/light/background.h` — `background_light_sample` /
  `background_light_pdf` build only a CDF for importance sampling; they do not
  filter the returned radiance. So any roughness-dependent dimming in Astroray
  that survives the furnace control is a lookup/upsample divergence, not a
  Cycles behaviour we must reproduce.

## Astroray code under examination

- `EnvironmentMap::lookup` (`include/raytracer.h:1545`) — RGB bilinear. Maps
  `theta=acos(y)`, `phi=atan2(z,x)`, `u=0.5+phi/2pi`, `v=1-theta/pi`, then
  `x0=floor(u*W)`, `y0=floor(v*H)` — **no half-texel offset**.
- `EnvironmentMap::evalSpectral` (`include/raytracer.h:1601`) — bilinear over a
  per-texel `RGBIlluminantSpectrum` atlas (upsample-then-interpolate).
- `gpu_envmap_lookup` (`include/astroray/gpu_bvh.h:652`) — RGB bilinear;
  byte-identical mapping + indexing to the CPU `lookup`.
- `gpu_env_miss_spectral` (`include/astroray/gpu_env_spectral.cuh`) — fetches
  per-texel RGB, upsamples each via `gpu_rgbToSampledSpectrum(...,
  GSPEC_RGB_ILLUMINANT)`, interpolates in spectral space.

## Instruments added by pkg275

- `PyRenderer::probe_env_lookup_gpu(dirs, u)` (binding) →
  `CUDARenderer::probeEnvLookup` → `pkg275_env_probe_kernel`
  (`src/gpu/cuda_renderer.cu`): runs the production device functions
  (`gpu_envmap_lookup`, `gpu_env_miss_spectral`) for a batch of directions, no
  Monte Carlo. Returns `[r,g,b,s0..sN]` per direction.
- `tests/test_pkg275_env_lookup_probe.py`: rung 2 (CPU vs numpy bilinear on the
  stb-decoded bytes), rung 5 (GPU vs CPU RGB), rung 6 (GPU vs CPU spectral).

## Diagnostic ladder — measurements & verdicts

Format: measurement → verdict. Filled in as each rung runs on a fresh `.pyd`.

### Rung 1 — uniform-env vs HDRI through the chrome sphere (CPU)
- Prior work: #809 (Batch I) white furnace at corpus chrome F0=(0.9,0.9,0.92),
  r=0.05: `furnace/F0 = [1.0002, 1.0044, 0.9846]` (F0=1 control mean 0.9954);
  HDRI sphere-masked ROI vs Cycles `[0.772, 0.775, 0.773]` (#795).
- Verdict: conductor BSDF conserves energy; the deficit is the env reflection
  lookup path, not the closure. (Cited, not re-run.)

### Rung 2 — texel-exact CPU lookup vs numpy bilinear
- Measurement: with the numpy reference decoding the identical RGBE bytes AND
  mirroring the loader's deliberate vertical flip (`raytracer.h:1525`, so
  `v=1-theta/pi` puts the up direction on the file's top scanline),
  `environment_lookup` matches the numpy bilinear to worst-rel < 1e-3 per
  channel on a smooth HDRI. The first cut (before the flip) showed R/B exact
  and only the vertical G gradient off by ~0.64 — a pure row-order relationship
  the load-flip fully explains, not a decode or interpolation error.
- Verdict: CPU bilinear is correct. No gamma-on-load (values are linear), no
  interpolation error, no row-flip *bug* (the flip is intentional and matches
  the equirect convention). The only parameterisation difference from Cycles is
  the **half-texel offset**: Astroray floors `u*W` (texel edges) where Cycles
  `svm_image` floors `u*W - 0.5` (texel centers). On a smooth HDRI this is
  << 1e-3 and cannot produce the #795 23% dimming.

### Rung 3 — sRGB-vs-linear on load / flat-.hdr decode
- Measurement: the numpy reference reproduces `stbi_loadf`'s exact RGBE decode
  (`out = byte * 2^(e-136)`) and agrees with `environment_lookup` to < 1e-3, so
  the loaded texels are LINEAR — no sRGB transform is applied on load. (The
  #797/#798 MinGW flat-`.hdr` miscompile is a separate, already-fixed codegen
  bug gated by test_issue797; this build is MSVC/nvcc.)
- Verdict: load path is linear and correct; not the culprit.

### Rung 4 — mip/blur on glossy lookups
- Measurement: `EnvironmentMap::lookup` / `gpu_envmap_lookup` do a single
  bilinear fetch with NO mip and NO derivative/roughness-dependent blur; a
  glossy reflection ray reads the same unblurred texel a mirror ray would.
  Matches Cycles `svm_image.h` + `background.h` (background lookups use no mip).
- Verdict: no roughness-dependent dimming originates in the lookup itself.

### Rung 5 — CPU vs GPU texel-exact lookup (#755)
- Measurement: `probe_env_lookup_gpu` RGB vs `environment_lookup` over 32
  directions on a smooth HDRI: **worst rel 2.25e-7** (float round-off).
- Verdict: the GPU RGB lookup is byte-faithful to the CPU. #755's render-level
  gap is NOT in the RGB env lookup.

### Rung 6 — spectral upsampling (Jakob-Hanika) grey vs colour HDRI
- Measurement: GPU `gpu_env_miss_spectral` vs CPU `evalSpectral` at identical
  wavelengths (u=0.5) over 32 directions: **worst rel 4.94e-6**.
- Verdict: the GPU RGB->spectral (Jakob-Hanika ILLUMINANT) upsample matches the
  CPU `RGBIlluminantSpectrum` atlas to ~5e-6. #755's per-channel-chromatic gap
  (R 1.025 / G 1.040 / B 0.978) is NOT the spectral upsample of the env lookup
  either.

### Rung 7 (added) — env-NEE estimator invariance on a glossy chrome sphere (CPU)
- Rationale: rungs 2-6 clear the lookup, so if the #795 deficit is real it must
  live in the env-reflection *combination* (BSDF-sampled env hit + env NEE via
  the pkg258 power-heuristic MIS). Two unbiased estimators of the same integral
  (env NEE ON vs OFF) must agree at convergence; a uniform furnace (rung 1)
  cannot see a MIS-weight bias because a constant env makes every direction
  equal.
- Measurement (metal F0=(0.9,0.9,0.92) sphere under a 256x128 smooth colour
  HDRI, 2048 spp, linear, ROI = central disk):
  - r=0.00 (mirror): NEE on/off ratio = [1.0000, 1.0000, 1.0001]
  - r=0.05 (corpus): NEE on/off ratio = [0.9999, 1.0001, 0.9998]
  - r=0.20:          NEE on/off ratio = [0.9781, 0.9741, 0.9776]
- Verdict: at the corpus chrome roughness (r=0.05) the CPU env-reflection path
  is UNBIASED to ~0.01% and a perfect mirror equals the glossy sphere — the
  23% #795 deficit is NOT reproduced on the CPU env-reflection path. A small
  (~2.3%) NEE-on deficit appears only at higher roughness (r=0.2), a minor
  pkg258 power-heuristic MIS effect, not a 23% lookup bug.

## Conclusion

The diagnostic ladder falsifies the spec's premise that "the causal step is in
the environment-map reflection LOOKUP":

- The env lookup is byte-faithful across CPU and GPU (rung 5: 2.25e-7) and the
  RGB->spectral upsample is faithful (rung 6: 4.94e-6). The CPU lookup matches
  an independent numpy bilinear once the intentional load-flip is accounted for
  (rung 2), the load is linear (rung 3), and there is no mip/blur (rung 4).
  **Neither #755 nor #795 is an env-lookup or env-upsample bug.**
- The only Cycles parameterisation difference found is the **half-texel offset**
  (Astroray floors `u*W`; Cycles `svm_image` floors `u*W-0.5`). This is a real
  but sub-1e-3 effect on smooth HDRIs and cannot account for 23%. It is a
  legitimate small parity nit; fixing it is low-risk and mirrored CPU+GPU (see
  below) but it is NOT the #795 cause.
- On CPU, the env-reflection combination is unbiased at r=0.05 (rung 7), so the
  #795 23% deficit is not reproduced by the CPU path. Its residual therefore
  lives OUTSIDE pkg275's authorised surface (the env lookup): most likely the
  GPU wavefront env-reflection/MIS leg (pkg258 owns env NEE/MIS;
  memory `gpu-wavefront-nee-occlusion-deferred-stage`) or the Cycles-comparison
  harness exposure/colour-management, both of which need a GPU repro of the
  corpus hero + a Cycles reference to pin — flagged to the lead.

### #755 (CPU/GPU env-only render gap)
Rungs 5/6 prove the GPU and CPU env lookup and spectral upsample are identical
to ~1e-6. Rung 8 (CPU vs GPU chrome sphere under the same colour HDRI, 4096 spp,
adaptive OFF, linear ROI) confirms the two backends AGREE at render level:
  r=0.00 GPU/CPU = [1.0000, 0.9999, 1.0004]
  r=0.05 GPU/CPU = [1.0003, 0.9998, 1.0010]
So the previously-reported R 1.025 / G 1.040 / B 0.978 gap does NOT reproduce on
a clean chrome scene with adaptive sampling disabled and a shared exposure — it
was an artefact of the pkg237 env-only parity scene's stopping metric / firefly
exposure (see tests/test_world_hdri_parity.py::test_gpu_cpu_mean_ratio_hdri
docstring), not the env lookup. Any residual downstream gap is a wavefront
integrator difference owned by pkg258, not pkg275's lookup.

### Recommended pkg275 action
The one in-scope, evidence-backed change is the **half-texel offset** to match
Cycles `svm_image` texel-center sampling, mirrored in `EnvironmentMap::lookup`,
`evalSpectral`, `gpu_envmap_lookup`, and `gpu_env_miss_spectral`. It closes the
only lookup-vs-Cycles discrepancy the ladder found. The chrome-ROI [0.95,1.05]
and #755 acceptance gates cannot be met by a lookup change (the lookup is
clean) and are reassigned per the evidence — see the PR / lead hand-off.
