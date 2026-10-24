# Spectral showcase gallery (pkg324, corpus v1)

Nine small Cycles-node scenes for the spectral effects Astroray is built around (dispersion, thin film, absorbing
glass caustics) plus a node-parity bench and a heavy interior. Every scene renders on Astroray CPU, Astroray GPU,
Cycles CPU and Cycles OptiX from the same `.blend`; where Cycles cannot do the effect the Cycles column says so. Recipes
are inferred from published renders of two other spectral engines (`.astroray_plan/docs/research/spectra-*-2026-10-25.md`);
no competitor asset is used. Seed 324 (non-zero: 0 is the engine's random sentinel), Blender 5.2.0 LTS, linear output,
adaptive sampling and denoising off.

Reproduce (CPU + Cycles legs need no GPU; GPU legs run under `scripts/build/gpu_locked_run.py`):

```
python benchmarks/showcase/spectral/build_scenes.py --all --addon-dir <staged addon>      # rebuild scenes + manifest
python -m benchmarks.showcase.runner --preset spectral --legs cpu gpu cycles cycles_gpu --pyd-dir <addon or build dir> --output-dir <dir>
pytest tests/test_pkg324_showcase_corpus.py                                              # fast part (CI)
ASTRORAY_PKG324_BLENDER=1 ASTRORAY_PYD_DIR=<dir> pytest tests/test_pkg324_showcase_corpus.py -m "slow and not gpu" -s
ASTRORAY_PKG324_BLENDER=1 ASTRORAY_PKG324_GPU=1 ASTRORAY_PYD_DIR=<dir> pytest tests/test_pkg324_showcase_corpus.py -m gpu -s   # under the GPU lock
```

`.blend` bytes are not reproducible across Blender sessions (verified), so `manifest.json` carries a content digest per
scene (`build_scenes.py --digest <blend>`); the slow tests check the committed file and a fresh rebuild against it.

## Analytic checks

| check | scene | CPU | GPU | Cycles | gate |
|---|---|---|---|---|---|
| Airy thin-film hue vs thickness (film 1.33 over n=2.0, flat D65 world, CIE 1931 2 deg), max error over 300 / 600 / 900 nm | `sp01` | 2.49 deg (2.49 / 0.77 / 0.75) | 2.57 deg | 1.78 deg | <= 10 deg |
| Prism fan: red-to-blue 50 % edge separation on the screen vs a 2-D Sellmeier ray trace (BK7, min deviation, 6 m) | `sp02b` | 91.56 vs 90.19 mm, 1.5 % | 90.28 mm, 0.1 % | n/a (no dispersion) | <= 5 % |
| White furnace, white base + Principled thin-film layer / no-film control | `sp04b` | 0.9992 / 0.9992 | 0.9992 / 0.9993 | 0.9999 / 0.9997 | within 3 % |
| Bounce cap 4 / 8 / 12, tumbler ROI mean ratio vs 64 (dark-pixel fraction at 5 % of the reference median) | `sp07` | 1.007 / 0.995 / 1.118 (0 / 0 / 0) | 0.827 / 1.000 / 1.000 (3e-4 / 1e-4 / 1e-4) | 0.971 / 0.997 / 0.999 (0) | report only |
| Per-ROI Astroray / Cycles luminance | `sp08`, `sp09` | `sp08` 16 of 21 tiles within 15 %; `sp09` 0 of 3 | identical failing tiles | reference | report only |

The thin-film and prism numbers are the engine's own spectral transport against closed forms, not a Cycles comparison:
Airy single-layer reflectance (Born and Wolf; the model Belcour and Barla evaluate), the engine's Sellmeier table
(`optical_presets.h`; BK7 reproduces n_d = 1.5168), the engine's baked CIE 1931 observer. Non-vacuity is tested: a
synthetic render built from the prediction passes, a 25 deg hue rotation or a 10 % blue-edge shift fails
(`tests/test_pkg324_showcase_corpus.py`). The GPU analytic tests (`-m gpu`) pass: 3 of 3.

## Scenes and lead sign-off

Sheets: `spectral-<scene>.png` in this folder, columns Astroray CPU | Astroray GPU | Cycles CPU | Cycles OptiX, every
panel stamped with spp, seed, size and render time. Times (s): CPU 8 threads / GPU RTX 5070 Ti / Cycles CPU / Cycles OptiX.
Sign-off is the lead's visual review (2026-10-25) with 4x4-cell means; first-pass vision-tier critiques are in the lead's
evidence folder (`%LOCALAPPDATA%\astroray-evidence\2026-10-24\pkg324\run1\vision\ALL_critiques.md`); its one position /
brightness claim about the sp02 GPU card was refuted numerically (all 4x4 cells within 0.8-1.25 of the CPU card).

| scene | what it shows | res, spp | CPU / GPU / Cycles / OptiX s | verdict |
|---|---|---|---|---|
| `sp01_thinfilm_ladder` | white diffuse, chrome and three Principled thin films (300 / 600 / 900 nm), white world, one softbox; the Airy check | 640x360, 128 | 32.5 / 2.3 / 9.0 / 1.3 | **showcase-ready**; hues match Cycles |
| `sp02_prism_fan` (+ `sp02b_prism_check`) | collimated sun through a window and a BK7 prism onto a matte screen; `sp02b` is the square-on measurement camera without fill. Cycles 5.2 has no dispersion | 640x480, 256 (`sp02b` 128) | 50.7 / 20.0 / 18.3 / 7.0 | check passes, **visual weak**: white core with narrow orange/blue edges; a longer throw or narrower slit would spread the spectrum (scene change, deferred) |
| `sp03_brilliant_diamond` | convex-hull brilliant (procedural), Sellmeier n_d 2.417 (Peter 1923), dark glossy floor, two softboxes and an emissive panel | 640x480, 256 | 71.8 / 17.1 / 21.8 / 1.2 | **showcase-ready, strongest**: dispersion fire and coloured floor caustics against Cycles' white |
| `sp04_bubble_glass_block` | soap bubble (Add Shader: specular thin film + Transparent) beside a 1.5 glass block | 640x480, 256 | 82.0 / 3.8 / 30.8 / 1.2 | CPU column showcase-ready; **GPU column is a known gap**: the GPU renders only the first Add Shader child (#955; closure composition is in progress, #995), so the bubble is opaque black |
| `sp04b_film_furnace` | check scene for the energy test | 256x128, 128 | 2.1 / 1.4 / 0.6 / 0.6 | check only |
| `sp05_absorbing_cube_caustic` | orange-absorbing glass cube (mesh volume) and clear sphere, one small spot, white plane, photon caustics | 480x480, 512 | 61.4 / 26.2 / 19.7 / 1.5 | ok; Astroray light pool 1.33x Cycles in one 4x4 cell; no GPU cube artefact confirmed |
| `sp06_iridescent_head` | Principled thin film 520 nm over a black n=2 dielectric, sun plus dim sky (Suzanne stands in for the bunny) | 640x480, 256 | 106.3 / 5.5 / 38.7 / 1.3 | **showcase-ready, best match**: all four columns agree |
| `sp07_tumbler_bounce_cap` | thick 1.5 glass tumbler on a plinth under the CC0 sky HDRI at max bounces 4 / 8 / 12 / 64 | 640x480, 256 x4 | 52-68 / ~4.0 / 20-29 / ~1.2 each cap | **parity probe, not showcase** (below) |
| `sp08_shader_ball_bench` | 21 spheres, one node family each | 640x480, 128 | 50.6 / 3.5 / 12.6 / 1.0 | **parity probe** (below) |
| `sp09_classroom` | Blender CC0 Classroom, linked from `assets/classroom/` (gitignored, never committed) | 480x270, 48 | 137.6 / 49.9 / 5.8 / 1.1 | **parity probe, not showcase** (below) |

- **sp07.** CPU and GPU disagree inside the glass (4x4 cells (1,1) 1.69x, (1,2) 0.61x; #1160) and Cycles differs further
  (no caustics through its transparent-shadow glass). The dark-pixel fraction is 0 on every backend at cap 4 (GPU 3e-4), so
  the scene does **not** demonstrate the bounce-cap dead-spot premise. pkg325 needs a revised scene (thicker nested glass,
  caps 1 / 2 / 4); until then `sp07` is only a CPU/GPU/Cycles probe. The CPU b12 ROI mean ratio of 1.12 is a firefly outlier
  of one 256 spp frame (median ratio 1.00), not a trend.
- **sp08.** Five tiles fail identically on CPU and GPU: `separate_combine_color` (2.7x, the blue ball in Cycles renders
  near-white), `separate_combine_xyz` (7.5x, the red/green ball renders near-white), `vector_math_dot_normalize` (4.7x), and
  the two procedural-bump tiles `bump_checker` / `bump_noise_strength_1p6` (1.3x, #1005). The first three are #1159.
- **sp09.** Linked-library images render magenta and the blackboard white (#1158): frame mean 0.500 vs Cycles 0.228 (2.2x),
  blackboard 7.6x. Re-measure after #1158.

## Findings (follow-ups filed, none fixed here)

- **#1155** The engine's `diamond` Sellmeier preset gives n_d = 2.758 (C terms are not the squared Peter resonance
  wavelengths). The diamond scene supplies Peter 1923 coefficients through the Sellmeier node's manual sockets; a strict
  xfail test pins the bug.
- **#1158** Images linked from a library `.blend` resolve against the main file (Classroom, `sp09`).
- **#1159** Separate/Combine Color, Separate/Combine XYZ and Vector Math (dot / normalize) tiles in `sp08`; the
  competitor's own parity sheet fails the same node families.
- **#1160** CPU vs GPU disagreement inside the `sp07` tumbler glass.
- **#1136 / pkg326** Glass BSDF thin film is dropped (`BSDF_GLASS: Thin Film ... not honoured`). A thin-wall Principled
  bubble shows no film in either engine (the film modifies the specular lobe only), so the bubble uses
  Add(Principled specular film, Transparent); the Add Shader pair is additive, not energy conserving.

## Substitutions and notes

- Blender 5.2 has no Cycles dispersion sockets (5.3 adds them), so dispersion comes from the Astroray Sellmeier node on
  the Astroray Output; the Cycles legs see the plain Glass BSDF. The spec's "Cauchy" check uses the engine's Sellmeier
  table (BK7, Abbe 64 against the recipe's ~58) because that is what the engine evaluates.
- The Stanford bunny is not in the repo and its licence was not checked: `sp06` uses Blender's Suzanne (subdivided).
- No city HDRI is in the repo: `sp07` and `sp08` use the CC0 `syferfontein_18d_clear_1k.hdr` already under
  `benchmarks/reference_corpus/assets/`.
- The lane's own first look was by eye backed by the numbers above; the vision-tier critiques and the lead's cell-mean
  review (the sign-off column) supersede it.
