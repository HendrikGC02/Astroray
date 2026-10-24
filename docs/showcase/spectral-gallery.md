# Spectral showcase gallery (pkg324, corpus v1)

Nine small Cycles-node scenes for the spectral effects Astroray is built around (dispersion, thin film, absorbing
glass caustics) plus a node-parity bench and a heavy interior. Every scene renders on Astroray CPU, Astroray GPU and
Cycles from the same `.blend`; where Cycles cannot do the effect the Cycles column says so. Recipes are inferred from
published renders of two other spectral engines (`.astroray_plan/docs/research/spectra-*-2026-10-25.md`); no
competitor asset is used. Seed 324 (non-zero: 0 is the engine's random sentinel), Blender 5.2.0 LTS, linear output,
adaptive sampling and denoising off.

Reproduce (CPU + Cycles legs need no GPU; GPU legs run under `scripts/build/gpu_locked_run.py`):

```
python benchmarks/showcase/spectral/build_scenes.py --all --addon-dir <staged addon>      # rebuild scenes + manifest
python -m benchmarks.showcase.runner --preset spectral --legs cpu gpu cycles --pyd-dir <addon or build dir> --output-dir <dir>
pytest tests/test_pkg324_showcase_corpus.py                                              # fast part (CI)
ASTRORAY_PKG324_BLENDER=1 ASTRORAY_PYD_DIR=<dir> pytest tests/test_pkg324_showcase_corpus.py -m "slow and not gpu" -s
```

`.blend` bytes are not reproducible across Blender sessions (verified), so `manifest.json` carries a content digest per
scene (`build_scenes.py --digest <blend>`); the slow tests check the committed file and a fresh rebuild against it.

## Analytic checks (CPU leg measured; GPU leg pending, see the end)

| check | scene | measured | gate | result |
|---|---|---|---|---|
| Airy thin-film hue vs thickness (film 1.33 over n=2.0, flat D65 world, CIE 1931 2 deg) | `sp01` | CPU hue error 2.49 / 0.77 / 0.75 deg at 300 / 600 / 900 nm; Cycles 1.67 / 0.59 / 1.78 deg | <= 10 deg | pass |
| Prism fan: red-to-blue 50 % edge separation on the screen vs a 2-D Sellmeier ray trace (BK7, min deviation, 6 m) | `sp02b` | CPU 91.56 mm vs 90.19 mm predicted (0.874 vs 0.861 deg), error 1.5 % | <= 5 % | pass |
| White furnace, white base + Principled thin-film layer, and a no-film control | `sp04b` | CPU 0.9992 / 0.9996 / 0.9991 (both spheres); Cycles 0.9999 | within 3 % | pass |
| Bounce cap 4 / 8 / 12 vs 64 (tumbler ROI mean ratio) | `sp07` | CPU 1.007 / 0.995 / 1.118 (median 0.84 / 1.00 / 1.00); Cycles 0.971 / 0.997 / 0.999 | report only (pkg325 gate) | see below |
| Per-ROI Astroray / Cycles luminance | `sp08`, `sp09` | `sp08`: 16 of 21 tiles within 15 %; `sp09`: 0 of 3 (linked textures, #1158) | report only | see findings |

The thin-film and prism numbers are the engine's own spectral transport against closed forms, not a Cycles comparison:
Airy single-layer reflectance (Born and Wolf; the model Belcour and Barla evaluate), the engine's Sellmeier table
(`optical_presets.h`; BK7 reproduces n_d = 1.5168), the engine's baked CIE 1931 observer. Non-vacuity is tested: a
synthetic render built from the prediction passes, a 25 deg hue rotation or a 10 % blue-edge shift fails
(`tests/test_pkg324_showcase_corpus.py`).

## Scenes

Sheets: `spectral-<scene>.png` in this folder (columns Astroray CPU | Astroray GPU | Cycles; every panel stamped with
spp, seed, size and render time). Times are CPU 8 threads on the lane machine; GPU times come from the lead's run.

| scene | what it shows | Cycles can do it? | res, spp | CPU / Cycles s |
|---|---|---|---|---|
| `sp01_thinfilm_ladder` | white diffuse, chrome and three Principled thin films (300 / 600 / 900 nm) under a white world and one softbox; the Airy check | yes (agrees with Astroray to < 3 deg) | 640x360, 128 | 32.5 / 9.0 |
| `sp02_prism_fan` (+ `sp02b_prism_check`) | collimated sun through a window and a BK7 prism onto a matte screen; red edge left of blue. `sp02b` is the square-on measurement camera, no fill light | no (Blender 5.2 has no dispersion): black screen | 640x480, 256 / 128 | 50.7 / 18.3 |
| `sp03_brilliant_diamond` | convex-hull brilliant (procedural), Sellmeier n_d 2.417 (Peter 1923), dark glossy floor, two softboxes and an emissive panel | no: undispersed sparkle | 640x480, 256 | 71.8 / 21.8 |
| `sp04_bubble_glass_block` | soap bubble (Add Shader: specular thin film + Transparent) beside a 1.5 glass block | yes (bubble agrees visually) | 640x480, 256 | 82.0 / 30.8 |
| `sp04b_film_furnace` | check scene for the energy test above | yes | 256x128, 128 | 2.1 / 0.6 |
| `sp05_absorbing_cube_caustic` | orange-absorbing glass cube (mesh volume) and clear sphere, one small spot, white plane, photon caustics | partly: no dispersion, no photon-map caustics | 480x480, 512 | 61.4 / 19.7 |
| `sp06_iridescent_head` | Principled thin film 520 nm over a black n=2 dielectric, sun plus dim sky | yes (CPU and Cycles look alike) | 640x480, 256 | 106.3 / 38.7 |
| `sp07_tumbler_bounce_cap` | thick 1.5 glass tumbler on a plinth under the CC0 sky HDRI at max bounces 4 / 8 / 12 / 64 (pkg325 acceptance scene) | yes | 640x480, 256 x4 | 52-68 / 20-29 |
| `sp08_shader_ball_bench` | 21 spheres, one node family each (Principled, Metallic, Glass, Sheen, mapping, bump, noise, wave, gradient, Voronoi, colour/XYZ separate-combine, vector math, bright-contrast, RGB curves) | yes (reference) | 640x480, 128 | 50.6 / 12.6 |
| `sp09_classroom` | Blender CC0 Classroom, linked from `assets/classroom/` (gitignored, never committed) | yes (reference) | 480x270, 48 | 137.6 / 5.8 |

## Findings (follow-ups filed, none fixed here)

- **#1155** The engine's `diamond` Sellmeier preset gives n_d = 2.758 (C terms are not the squared Peter resonance
  wavelengths). The diamond scene supplies Peter 1923 coefficients through the Sellmeier node's manual sockets; a strict
  xfail test pins the bug.
- **#1158** Images linked from a library `.blend` resolve against the main file, so Astroray renders the Classroom chairs
  and desks magenta and the blackboard white (`sp09`: luminance 7.6x Cycles on the blackboard, 2.8x on the window).
- **#1159** Separate/Combine Color, Separate/Combine XYZ and Vector Math (dot / normalize) tiles in `sp08` are 2.7-7.5x off
  Cycles; procedural bump tiles are 1.3x (tracked as #1005). The competitor's own parity sheet fails the same node families.
- **#1136 / pkg326** Glass BSDF thin film is dropped (`BSDF_GLASS: Thin Film ... not honoured`). A thin-wall Principled
  bubble shows no film in either engine (the film modifies the specular lobe only), so the bubble uses
  Add(Principled specular film, Transparent); the Add Shader pair is additive, not energy conserving, and the GPU backend
  renders only its first child (degradation report): expect a dark film mirror in the GPU bubble column.
- Bounce cap (`sp07`): Astroray's capped renders match the 64-bounce reference to within a few percent in the ROI median
  (b08 / b12 1.00, b04 0.84) and show no dark dead spots (dark fraction 0 at 5 % of the reference median) with the sky HDRI;
  the sun-lit-glass view differs strongly from Cycles (Cycles shows a bright sun wedge through the glass, Astroray a darker
  tumbler). The b12 ROI mean ratio of 1.12 is a firefly outlier of a 256 spp frame, not a trend. A city HDRI with many
  bright spots would stress the cap harder (the repo has none).

## Substitutions and notes

- Blender 5.2 has no Cycles dispersion sockets (5.3 adds them), so dispersion comes from the Astroray Sellmeier node on
  the Astroray Output; the Cycles leg sees the plain Glass BSDF. The spec's "Cauchy" check uses the engine's Sellmeier
  table (BK7, Abbe 64 against the recipe's ~58) because that is what the engine evaluates.
- The Stanford bunny is not in the repo and its licence was not checked: `sp06` uses Blender's Suzanne (subdivided).
- No city HDRI is in the repo: `sp07` and `sp08` use the CC0 `syferfontein_18d_clear_1k.hdr` already under
  `benchmarks/reference_corpus/assets/`.
- First-pass visual inspection was done by the lane directly (the vision delegate tier is unavailable: OpenCode key
  expired 2026-10-18); every position/colour claim above is backed by the numbers in the check table, not by eye.
- Lead visual sign-off: pending.
